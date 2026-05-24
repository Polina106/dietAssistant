import json
import logging
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import service_client, local_data
from app.config import GROK_API_KEY, ALLERGEN_DISH_NAMES
from app.data_loader import load_recipes
from app.planner import MealPlanner
from app.recipe_generator import RecipeGenerator
from app.local_data import GENERATED_RECIPES_PATH

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
    """
    Load user profile and convert to planner format.
    If local users.json exists — uses only it (no external calls).
    Falls back to user-service only when the local file is absent.
    """
    if local_data.users_available():
        user = local_data.load_user(user_id)
        if user is None:
            raise ValueError(f"Пользователь {user_id} не найден в users.json")
        return local_data.build_user_dict(user)

    # No local file — use external service
    profile = service_client.get_user_meal_profile(user_id)
    return _build_user_dict_from_profile(profile)


def _build_user_dict_from_profile(profile: dict) -> dict:
    """Convert API profile dict to planner format (used when no local users.json)."""
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


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class GenerateRequest(BaseModel):
    userId: str
    date: str


class ReplaceRequest(BaseModel):
    userId: str
    mealPlanId: str
    mealSlot: str
    currentDishId: int


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/meal-plan/generate")
def generate_meal_plan(req: GenerateRequest):
    """
    Generate a daily meal plan for the user.
    Falls back to AI-generated recipes if the optimizer finds no solution.
    """
    try:
        user_dict = _resolve_user_dict(req.userId)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Пользователь не найден: {e}")

    excluded_ids: list[int] = []
    if not local_data.users_available():
        try:
            excluded_ids = service_client.get_user_dish_ids(req.userId)
        except Exception:
            pass

    result = _get_planner().plan_day(user_dict, exclude_recipe_ids=excluded_ids)
    is_generated = False

    if not result:
        logger.info("Optimizer found no plan for user %s — trying generation", req.userId)
        gen = _get_generator()
        if gen is None:
            raise HTTPException(status_code=404,
                                detail="Не удалось подобрать план питания по заданным параметрам")
        result = gen.generate_meals(user_dict, user_dict["target_calories"])
        if not result:
            raise HTTPException(status_code=404,
                                detail="Не удалось сгенерировать план питания")
        is_generated = True

    items = [
        {
            "mealSlot":    dish["mealType"],
            "dishId":      int(dish["id"]),
            "dishName":    dish["title"],
            "calories":    round(float(dish["calories"]), 2),
            "isGenerated": is_generated,
        }
        for dish in result
    ]

    if not local_data.users_available():
        try:
            service_client.create_meal_plan(req.userId, req.date, items)
        except Exception as e:
            if not is_generated:
                raise HTTPException(status_code=502, detail=f"Не удалось сохранить план: {e}")
            logger.warning("Backend rejected generated meal plan: %s", e)

    total_cal  = sum(d["calories"] for d in items)
    target_cal = user_dict["target_calories"]
    deviation  = round((total_cal / target_cal - 1) * 100, 1) if target_cal else 0

    return {
        "date":          req.date,
        "meals":         items,
        "isGenerated":   is_generated,
        "totalCalories": round(total_cal, 1),
        "targetCalories": target_cal,
        "deviationPct":  deviation,
    }


@router.post("/meal-plan/replace")
def replace_meal(req: ReplaceRequest):
    """Replace a single dish in an existing meal plan."""
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


@router.get("/users")
def list_users(limit: int = 20, offset: int = 0):
    """List users from local users.json."""
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
    """Get a single user's profile from local users.json."""
    if not local_data.users_available():
        raise HTTPException(status_code=404, detail="Локальный файл users.json не найден")
    user = local_data.load_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"Пользователь {user_id} не найден")
    return user


@router.get("/generated-recipes")
def list_generated_recipes():
    """Return all recipes that were generated by AI."""
    if not GENERATED_RECIPES_PATH.exists():
        return {"total": 0, "recipes": []}
    recipes = json.loads(GENERATED_RECIPES_PATH.read_text(encoding="utf-8"))
    return {"total": len(recipes), "recipes": recipes}


class DatabaseRecipeRequest(BaseModel):
    mealType: str = "DINNER"
    targetCalories: float = 500.0
    count: int = 1
    excludeAllergens: list[str] = []
    preferredCuisines: list[str] = []
    likedIngredients: list[str] = []
    dislikedIngredients: list[str] = []


@router.post("/recipes/generate")
def generate_recipe_for_database(req: DatabaseRecipeRequest):
    """
    Generate recipes and add them to the recipe database (generated_recipes.json).
    The planner cache is refreshed automatically so new recipes are immediately usable.

    mealType: BREAKFAST | LUNCH | DINNER
    targetCalories: kcal for a 300 g portion
    count: number of recipes to generate (1–5)
    excludeAllergens: Russian allergen names to forbid (see GET /allergens)
    preferredCuisines: Russian cuisine names (азиатская, европейская, …)
    likedIngredients: product names to prefer
    dislikedIngredients: product names to avoid
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

    # Invalidate planner so generated recipes are picked up on next request
    global _planner
    with _lock:
        _planner = None

    return {
        "generated": len(recipes),
        "recipes": recipes,
    }


@router.get("/allergens")
def list_allergens():
    """Return the list of allergen names accepted by the API."""
    return {"allergens": ALLERGEN_DISH_NAMES}


@router.post("/dishes/reload", status_code=200)
def reload_dishes():
    """Force reload of the recipe cache (picks up new generated_recipes.json entries)."""
    global _planner
    with _lock:
        _planner = None
    _get_planner()
    return {"status": "reloaded"}
