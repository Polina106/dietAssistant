import json
import logging
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import service_client, local_data
from app.config import GROK_API_KEY, ALLERGEN_DISH_NAMES
from app.data_loader import load_recipes
from app.local_data import GENERATED_RECIPES_PATH
from app.planner import MealPlanner
from app.recipe_generator import RecipeGenerator, to_backend_payload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

_planner: MealPlanner | None = None
_generator: RecipeGenerator | None = None
_lock = threading.Lock()


# ------------------------------------------------------------------
# Lazy singletons
# ------------------------------------------------------------------

def _get_planner() -> MealPlanner:
    global _planner
    with _lock:
        if _planner is None:
            if local_data.recipes_available():
                logger.info("Loading recipes from local file %s", local_data.RECIPES_PATH)
                df = local_data.load_recipes_df()
            else:
                logger.info("Loading recipes from meal-service…")
                dishes = service_client.get_all_dishes()
                df = load_recipes(dishes)
            _planner = MealPlanner(df)
            logger.info("Planner ready with %d recipes", len(df))
        return _planner


def _invalidate_planner() -> None:
    global _planner
    with _lock:
        _planner = None


def _get_generator() -> RecipeGenerator | None:
    global _generator
    with _lock:
        if _generator is None:
            if not GROK_API_KEY:
                logger.warning("GROK_API_KEY not set — recipe generation disabled")
                return None
            try:
                _generator = RecipeGenerator()
                logger.info("RecipeGenerator ready (model=%s)", _generator.model)
            except Exception:
                logger.exception("Failed to init RecipeGenerator")
        return _generator


def _resolve_user_dict(user_id: str) -> dict:
    if local_data.users_available():
        user = local_data.load_user(user_id)
        if user is None:
            raise ValueError(f"Пользователь {user_id} не найден в users.json")
        return local_data.build_user_dict(user)

    profile = service_client.get_user_meal_profile(user_id)
    return _build_user_dict_from_profile(profile)


def _build_user_dict_from_profile(profile: dict) -> dict:
    from app.config import ALLERGEN_KEY_TO_DISH_NAME, INGREDIENT_KEY_TO_FEATURE
    user: dict = {
        "пассивное_время_мин":        profile.get("passiveCookingTimeMin") or 9999,
        "активное_время_готовки_мин": profile.get("activeCookingTimeMin") or 9999,
        "target_calories":            float(profile.get("targetCalories") or 2000),
    }
    allergens_data: dict = profile.get("allergens") or {}
    for user_key, dish_name in ALLERGEN_KEY_TO_DISH_NAME.items():
        user[dish_name] = 1 if allergens_data.get(user_key) else 0

    cuisines: dict = profile.get("cuisinePreferences") or {}
    for key in ["asian", "european", "eastern", "slavic", "american", "mexican"]:
        user[key] = float(cuisines.get(key) or 5) / 10.0

    ingredients: dict = profile.get("ingredientPreferences") or {}
    for user_key, feature_name in INGREDIENT_KEY_TO_FEATURE.items():
        user[feature_name] = float(ingredients.get(user_key) or 5) / 10.0

    return user


def _user_allergen_names(user_dict: dict) -> list[str]:
    return [name for name in ALLERGEN_DISH_NAMES if user_dict.get(name, 0) == 1]


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class ReplaceRequest(BaseModel):
    userId:        str
    mealPlanId:    str
    mealSlot:      str
    currentDishId: int


class IngredientChatRequest(BaseModel):
    """
    Chat-style request: the user types what they have on hand and the assistant
    proposes a single recipe. userId is optional — if supplied, allergens from
    the user's profile are honoured automatically.
    """
    ingredients:  list[str]                  = Field(..., min_length=1, description="Что есть у пользователя")
    mealType:     str                        = "DINNER"
    userId:       str | None                 = None
    extraAllergens: list[str]                = Field(default_factory=list, description="Доп. аллергены сверх профиля")
    persistToCatalog: bool                   = True


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------
# NOTE: meal-plan generation has been moved back to the Kafka consumer
# (app/consumer.py) — the orchestrator publishes commands to Kafka and
# the consumer processes them asynchronously. This file only exposes
# interactive scenarios that genuinely need an HTTP response in real time.

@router.post("/meal-plan/replace")
def replace_meal(req: ReplaceRequest):
    """
    Replace a single dish in an existing meal plan. Kept on HTTP for now because
    the mobile UX expects a synchronous answer; can later move to Kafka if needed.
    """
    try:
        user_dict = _resolve_user_dict(req.userId)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Пользователь не найден: {e}")

    exclude_ids: list[int] = []
    if not local_data.users_available():
        try:
            exclude_ids = service_client.get_user_dish_ids(req.userId)
        except Exception:
            pass
    if req.currentDishId not in exclude_ids:
        exclude_ids.append(req.currentDishId)

    replacement = _get_planner().find_replacement(user_dict, req.mealSlot, exclude_ids)
    if replacement is None:
        raise HTTPException(status_code=404,
                            detail=f"Не найдена замена для слота {req.mealSlot}")

    if not local_data.users_available():
        try:
            service_client.replace_meal_plan_item(
                meal_plan_id=req.mealPlanId,
                slot=req.mealSlot,
                dish_id=int(replacement["id"]),
                dish_name=replacement["title"],
                calories=round(float(replacement["calories"]), 2),
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Не удалось обновить план: {e}")

    return {
        "mealSlot": req.mealSlot,
        "dishId":   int(replacement["id"]),
        "dishName": replacement["title"],
        "calories": round(float(replacement["calories"]), 2),
    }


@router.post("/recipes/from-ingredients")
def generate_from_ingredients(req: IngredientChatRequest):
    """
    Chat scenario: user lists what they have, LLM proposes one recipe using
    those ingredients (plus pantry basics), honouring their allergens.

    If persistToCatalog=True (default), the resulting dish is also POSTed to
    meal-service so it gets a stable backend id and shows up in /api/v1/dishes
    for future planner runs.
    """
    if req.mealType not in ("BREAKFAST", "LUNCH", "DINNER"):
        raise HTTPException(status_code=422, detail="mealType must be BREAKFAST, LUNCH or DINNER")

    gen = _get_generator()
    if gen is None:
        raise HTTPException(status_code=503,
                            detail="Генерация недоступна: GROK_API_KEY не задан")

    # Resolve allergens: union(profile, extraAllergens)
    user_allergens: list[str] = list(req.extraAllergens or [])
    if req.userId:
        try:
            user_dict = _resolve_user_dict(req.userId)
            user_allergens = sorted(set(user_allergens) | set(_user_allergen_names(user_dict)))
        except Exception:
            logger.warning("Failed to load profile for %s — proceeding with extraAllergens only",
                           req.userId)

    try:
        recipe = gen.generate_from_ingredients(
            available_ingredients=req.ingredients,
            user_allergens=user_allergens,
            meal_type=req.mealType,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Ingredient-based generation failed")
        raise HTTPException(status_code=500, detail=f"Ошибка генерации: {e}")

    persisted_id: int | None = None
    if req.persistToCatalog:
        try:
            created = service_client.create_dish(to_backend_payload(recipe))
            persisted_id = int(created["id"]) if created.get("id") is not None else None
            if persisted_id is not None:
                recipe = {**recipe, "id": persisted_id}
                _invalidate_planner()
                logger.info("Persisted chat-generated dish '%s' with backend id %s",
                            recipe["title"], persisted_id)
        except Exception:
            logger.exception("Failed to persist chat-generated dish to meal-service")

    return {
        "dishId":       recipe.get("id"),
        "persistedId":  persisted_id,
        "title":        recipe["title"],
        "description":  recipe.get("description"),
        "cuisine":      recipe.get("cuisine"),
        "mealType":     recipe.get("mealType"),
        "calories":     recipe.get("calories"),
        "ingredients":  recipe.get("ingredients", []),
        "steps":        [s for s in (recipe.get("recipe") or "").split("\n\n") if s.strip()],
        "allergens":    recipe.get("common_allergens", []),
        "activeCookingTimeMin":  recipe.get("kitchen_time_in_minutes"),
        "passiveCookingTimeMin": (recipe.get("ready_in_minutes") or 0)
                                  - (recipe.get("kitchen_time_in_minutes") or 0),
        "aiGenerated":  True,
        "verified":     False,
    }


@router.get("/users")
def list_users(limit: int = 20, offset: int = 0):
    if not local_data.users_available():
        raise HTTPException(status_code=404, detail="Локальный файл users.json не найден")
    users = local_data.load_all_users()
    page = users[offset: offset + limit]
    return {
        "total":  len(users),
        "offset": offset,
        "limit":  limit,
        "users":  [
            {
                "userId":         str(u["user_id"]),
                "gender":         u.get("пол"),
                "age":            u.get("возраст"),
                "strategy":       u.get("стратегия"),
                "targetCalories": round(float(u.get("target_calories") or 0), 0),
            }
            for u in page
        ],
    }


@router.get("/users/{user_id}")
def get_user(user_id: str):
    if not local_data.users_available():
        raise HTTPException(status_code=404, detail="Локальный файл users.json не найден")
    user = local_data.load_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"Пользователь {user_id} не найден")
    return user


@router.get("/generated-recipes")
def list_generated_recipes():
    """Local on-disk log of all recipes ever generated by the LLM (audit trail)."""
    if not GENERATED_RECIPES_PATH.exists():
        return {"total": 0, "recipes": []}
    recipes = json.loads(GENERATED_RECIPES_PATH.read_text(encoding="utf-8"))
    return {"total": len(recipes), "recipes": recipes}


class DatabaseRecipeRequest(BaseModel):
    mealType:            str       = "DINNER"
    targetCalories:      float     = 500.0
    count:               int       = 1
    excludeAllergens:    list[str] = []
    preferredCuisines:   list[str] = []
    likedIngredients:    list[str] = []
    dislikedIngredients: list[str] = []
    persistToCatalog:    bool      = True


@router.post("/recipes/generate")
def generate_recipe_for_database(req: DatabaseRecipeRequest):
    """
    Bulk-generate recipes for the catalog (admin scenario).
    With persistToCatalog=True each recipe is POSTed to meal-service and gets
    a backend-allocated id; the planner cache is invalidated so the new dishes
    are picked up on the next request.
    """
    if req.mealType not in ("BREAKFAST", "LUNCH", "DINNER"):
        raise HTTPException(status_code=422,
                            detail="mealType must be BREAKFAST, LUNCH, or DINNER")
    if not (1 <= req.count <= 5):
        raise HTTPException(status_code=422, detail="count must be between 1 and 5")
    if req.targetCalories <= 0:
        raise HTTPException(status_code=422, detail="targetCalories must be positive")

    gen = _get_generator()
    if gen is None:
        raise HTTPException(status_code=503,
                            detail="Генерация недоступна: задайте переменную окружения GROK_API_KEY")

    try:
        recipes = gen.generate_for_database(
            meal_type=req.mealType,
            target_calories=req.targetCalories,
            exclude_allergens=req.excludeAllergens,
            preferred_cuisines=req.preferredCuisines,
            liked_ingredients=req.likedIngredients,
            disliked_ingredients=req.dislikedIngredients,
            count=req.count,
        )
    except Exception as e:
        logger.exception("Recipe generation failed")
        raise HTTPException(status_code=500, detail=f"Ошибка генерации: {e}")

    if not recipes:
        raise HTTPException(status_code=500, detail="Не удалось сгенерировать ни одного рецепта")

    if req.persistToCatalog:
        for r in recipes:
            try:
                created = service_client.create_dish(to_backend_payload(r))
                backend_id = created.get("id")
                if backend_id is not None:
                    r["id"] = int(backend_id)
            except Exception:
                logger.exception("Failed to persist generated recipe '%s'", r.get("title"))
        _invalidate_planner()

    return {
        "generated": len(recipes),
        "recipes": recipes,
    }


@router.get("/allergens")
def list_allergens():
    return {"allergens": ALLERGEN_DISH_NAMES}


@router.post("/dishes/reload", status_code=200)
def reload_dishes():
    _invalidate_planner()
    _get_planner()
    return {"status": "reloaded"}
