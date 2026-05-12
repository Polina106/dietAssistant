from pathlib import Path
from typing import Dict, List, Literal, Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.planner import MealPlanner
from app.data_loader import load_recipes


app = FastAPI(title="Meal Planner")

_APP_DIR = Path(__file__).resolve().parent
_RECIPES_PATH = _APP_DIR / "data" / "recipes.jsonl"

recipes_df = load_recipes(str(_RECIPES_PATH))

planner = MealPlanner(
    recipes_df=recipes_df,
    allergens=[
        "Белок коровьего молока",
        "Злаки, содержащие глютен",
        "Яйцо",
        "Рыба",
        "Сельдерей",
        "Соя",
        "Пищевые добавки",
        "Горчица",
        "Орехи",
        "Клубника",
        "Кунжут",
        "Арахис",
        "Ракообразные",
        "Моллюски",
    ],
    cont_features=[
        "asian",
        "european",
        "eastern",
        "slavic",
        "america",
        "mexica",
    ],
    product_features=[
        "рыба",
        "морепродукты",
        "свинина",
        "говядина",
        "курица",
        "сыр",
        "картофель",
        "лук",
        "чеснок",
        "помидоры",
        "печень",
        "молоко",
        "творог",
        "оливки",
        "сельдерей",
        "кинза",
        "тыква",
        "баклажан",
        "орехи",
    ],
)


class Questionnaire(BaseModel):
    height_cm: float = Field(..., ge=100, le=250, description="Рост, см")
    weight_kg: float = Field(..., ge=30, le=300, description="Вес, кг")
    sex: Literal["female", "male"] = Field(..., description="Пол")
    activity_level: Literal["low", "moderate", "high"] = Field(
        ..., description="Уровень активности"
    )
    passive_cook_minutes: int = Field(
        ..., ge=0, le=300, description="Пассивное время готовки, минут"
    )
    active_cook_minutes: int = Field(
        ..., ge=0, le=300, description="Активное время готовки, минут"
    )
    allergens: Dict[str, int] = Field(
        default_factory=dict,
        description="Аллергены (0/1) с ключами как в датасете рецептов",
    )
    cuisines: Dict[str, int] = Field(
        default_factory=dict,
        description="Предпочтения по кухням (0/1) для asian/european/... и т.п.",
    )
    exclude_recipe_ids: Optional[List[int]] = Field(
        default=None,
        description="ID рецептов, которые уже показывали — исключить из оптимизатора.",
    )


def calculate_target_calories(
    height_cm: float,
    weight_kg: float,
    sex: Literal["female", "male"],
    activity_level: Literal["low", "moderate", "high"],
) -> int:
    # Упрощённая формула: базовый обмен 24 * вес * коэффициент активности
    activity_multipliers = {
        "low": 1.2,
        "moderate": 1.4,
        "high": 1.6,
    }
    base = 24.0 * weight_kg
    multiplier = activity_multipliers[activity_level]
    return int(base * multiplier)


@app.post("/plan-day/")
def plan_day(user: dict):
    return planner.plan_day(user)


@app.post("/plan-day-from-form/")
def plan_day_from_form(form: Questionnaire):
    user_dict: Dict[str, float] = {}

    user_dict["пассивное_время_мин"] = form.passive_cook_minutes
    user_dict["активное_время_готовки_мин"] = form.active_cook_minutes

    for allergen in planner.allergens:
        user_dict[allergen] = int(form.allergens.get(allergen, 0))

    for feature in planner.cont_features:
        user_dict[feature] = float(form.cuisines.get(feature, 0))

    for feature in planner.product_features:
        user_dict[feature] = 0.0

    target_calories = calculate_target_calories(
        height_cm=form.height_cm,
        weight_kg=form.weight_kg,
        sex=form.sex,
        activity_level=form.activity_level,
    )
    user_dict["target_calories"] = target_calories

    recipes = planner.plan_day(user_dict, exclude_recipe_ids=form.exclude_recipe_ids)
    if recipes:
        total_calories = sum(r.get("calories", 0) for r in recipes)
        deviation_percent = round(
            (total_calories / target_calories - 1) * 100, 1
        )
        return {
            "recipes": recipes,
            "target_calories": target_calories,
            "total_calories": int(total_calories),
            "deviation_percent": deviation_percent,
        }
    return {
        "recipes": [],
        "target_calories": target_calories,
        "total_calories": None,
        "deviation_percent": None,
    }


static_dir = Path(__file__).parent / "static"

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir), html=True), name="static")


@app.get("/")
def read_index():
    index_path = static_dir / "index.html"
    return FileResponse(index_path)


@app.get("/plan")
def read_plan():
    index_path = static_dir / "plan.html"
    return FileResponse(index_path)


@app.get("/viewed")
def read_viewed():
    index_path = static_dir / "viewed.html"
    return FileResponse(index_path)


@app.get("/favorites")
def read_favorites():
    index_path = static_dir / "favorites.html"
    return FileResponse(index_path)
