import datetime
import json
import logging
import pathlib
from typing import Optional

from openai import OpenAI

from app.config import (
    ALLERGEN_DISH_NAMES,
    PRODUCT_FEATURES,
    PRODUCT_KEYWORDS,
    GROK_API_KEY,
    GROK_MODEL,
)

logger = logging.getLogger(__name__)

GENERATED_RECIPES_PATH = pathlib.Path("app/data/generated_recipes.json")

_MEAL_SLOT_RU = {
    "BREAKFAST": "завтрак",
    "LUNCH":     "обед",
    "DINNER":    "ужин",
}

_CALORIE_SPLIT = {
    "BREAKFAST": 0.25,
    "LUNCH":     0.40,
    "DINNER":    0.35,
}

_CUISINE_FEATURE_TO_RU = {
    "asian":    "азиатская",
    "european": "европейская",
    "eastern":  "восточная",
    "slavic":   "славянская",
    "american": "американская",
    "mexican":  "мексиканская",
}

_ALL_MEAL_TYPES = ["BREAKFAST", "LUNCH", "DINNER"]

# Keywords to detect protein source from an ingredients list
_PROTEIN_KEYWORDS: dict[str, list[str]] = {
    "курица":       ["куриц", "курин", "бройлер", "цыплён"],
    "говядина":     ["говядин", "говяж", "телятин", "стейк"],
    "свинина":      ["свинин", "свиной", "окорок", "бекон"],
    "индейка":      ["индейк", "индюш"],
    "рыба":         ["рыб", "лосос", "сёмг", "форел", "треск", "тунец", "хек"],
    "морепродукты": ["креветк", "кальмар", "мидий", "краб", "гребешок"],
    "яйца":         ["яйц", "яйко"],
    "бобовые":      ["чечевиц", "нут", "фасол", "горох", "соя"],
    "творог":       ["творог"],
    "тофу":         ["тофу"],
    "грибы":        ["гриб", "шампиньон", "вешенк"],
}

_CATEGORY_BY_MEAL = {
    "BREAKFAST": "Завтраки",
    "LUNCH":     "Первые блюда",
    "DINNER":    "Вторые блюда",
}


def to_backend_payload(recipe: dict) -> dict:
    """
    Convert an internal recipe record (the dict shape returned by RecipeGenerator)
    into a payload accepted by POST /api/v1/dishes on meal-service.

    `id` is intentionally None so the backend allocates a unique negative id
    on its side (id space below zero is reserved for AI-generated dishes).
    `aiGenerated` is always True; `verified` is always False — only admins
    flip verified=true after a manual review.
    """
    ingredients = recipe.get("ingredients") or []
    if isinstance(ingredients, list):
        ingredients_str = [str(i) for i in ingredients]
    else:
        ingredients_str = []

    return {
        "id":           None,
        "url":          None,
        "title":        recipe["title"],
        "description":  recipe.get("description"),
        "dishImage":    recipe.get("dish_image"),
        "calories":     recipe.get("calories"),
        "protein":      recipe.get("protein"),
        "fat":          recipe.get("fat"),
        "carbs":        recipe.get("carbs"),
        "readyIn":      recipe.get("ready_in"),
        "kitchenTime":  recipe.get("kitchen_time"),
        "cuisine":      recipe.get("cuisine"),
        "categoryPath": recipe.get("category_path"),
        "recipe":       recipe.get("recipe"),
        "mealType":     recipe.get("mealType", "DINNER"),
        "allergens":    list(recipe.get("common_allergens") or []),
        "ingredients":  ingredients_str,
        "aiGenerated":  True,
        "verified":     False,
    }


def _minutes_to_ru(minutes: int) -> str:
    """Convert integer minutes to a Russian time string."""
    if minutes <= 0 or minutes >= 9999:
        return ""
    h, m = divmod(minutes, 60)
    parts = []
    if h:
        parts.append(f"{h} {'час' if h == 1 else 'часа' if 2 <= h <= 4 else 'часов'}")
    if m:
        parts.append(f"{m} {'минута' if m == 1 else 'минуты' if 2 <= m <= 4 else 'минут'}")
    return " ".join(parts)


def _detect_proteins(ingredients: list[str]) -> list[str]:
    """Detect protein sources present in an ingredient list."""
    joined = " ".join(ingredients).lower()
    return [name for name, kws in _PROTEIN_KEYWORDS.items() if any(kw in joined for kw in kws)]


def _product_flags(ingredients: list[str]) -> dict:
    """Binary product presence flags from ingredient list, matching local data format."""
    joined = " ".join(ingredients).lower()
    return {
        product: int(any(kw in joined for kw in keywords))
        for product, keywords in PRODUCT_KEYWORDS.items()
    }


def _allergen_flags(common_allergens: list[str]) -> dict:
    """Binary allergen flags matching local data format."""
    allergen_set = set(common_allergens)
    return {name: int(name in allergen_set) for name in ALLERGEN_DISH_NAMES}


class RecipeGenerator:
    """Generates recipes via the Grok (xAI) API as a fallback when the optimizer fails."""

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=GROK_API_KEY,
            base_url="https://api.mistral.ai/v1",
        )
        self.model = GROK_MODEL
        self._ensure_storage()

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    def _ensure_storage(self) -> None:
        GENERATED_RECIPES_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not GENERATED_RECIPES_PATH.exists():
            GENERATED_RECIPES_PATH.write_text("[]", encoding="utf-8")
            logger.info("Created generated recipes file: %s", GENERATED_RECIPES_PATH)

    def _load_generated(self) -> list[dict]:
        try:
            text = GENERATED_RECIPES_PATH.read_text(encoding="utf-8").strip()
            return json.loads(text) if text else []
        except Exception:
            return []

    def _next_id(self) -> int:
        recipes = self._load_generated()
        neg_ids = [r["id"] for r in recipes if isinstance(r.get("id"), int) and r["id"] < 0]
        return (min(neg_ids) - 1) if neg_ids else -1

    def _save_recipe(self, record: dict) -> None:
        """Append a recipe record (in local recipes.json format) to generated_recipes.json."""
        recipes = self._load_generated()
        recipes.append(record)
        GENERATED_RECIPES_PATH.write_text(
            json.dumps(recipes, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved generated recipe '%s' (id=%d)", record.get("title"), record.get("id"))

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    @staticmethod
    def _system_prompt() -> str:
        return (
            "Ты — нутрициолог и шеф-повар с фокусом на здоровое современное питание. "
            "Твои рецепты вдохновлены актуальными трендами: боулы, суперфуды, ферментированные продукты, "
            "цельнозерновые крупы, растительные белки. "
            "Каждое блюдо сбалансировано по макронутриентам: "
            "цельные углеводы (крупы, батат, бобовые), качественный белок, клетчатка из овощей. "
            "Названия и описания звучат аппетитно и современно — так, чтобы блюдо хотелось приготовить. "
            "Отвечаешь строго в формате JSON без markdown-обёртки и без пояснений. "
            "Все тексты исключительно на русском языке."
        )

    @staticmethod
    def _user_prompt(
        meal_type: str,
        target_calories: float,
        user_allergens: list[str],
        liked_ingredients: list[str],
        disliked_ingredients: list[str],
        preferred_cuisines: list[str],
        protein_ratings: dict[str, float] | None = None,
    ) -> str:
        meal_ru       = _MEAL_SLOT_RU[meal_type]
        allergens_str = ", ".join(user_allergens)       if user_allergens       else "нет"
        liked_str     = ", ".join(liked_ingredients)    if liked_ingredients    else "без особых предпочтений"
        disliked_str  = ", ".join(disliked_ingredients) if disliked_ingredients else "нет"
        cuisines_str  = ", ".join(preferred_cuisines)   if preferred_cuisines   else "любая"
        all_allergens = ", ".join(ALLERGEN_DISH_NAMES)

        # Format protein preference table, sorted from most to least liked
        protein_block = ""
        if protein_ratings:
            lines = []
            for name, score in sorted(protein_ratings.items(), key=lambda x: -x[1]):
                if score >= 0.7:
                    verdict = "нравится"
                elif score <= 0.3:
                    verdict = "не нравится / избегать"
                else:
                    verdict = "нейтрально"
                lines.append(f"  - {name}: {verdict} ({score:.0%})")
            protein_block = (
                "\nОтношение клиента к источникам белка (учитывай при выборе):\n"
                + "\n".join(lines)
                + "\n  Важно: не используй белок с оценкой «не нравится»."
                + "\n  Среди нейтральных и понравившихся — выбирай разнообразно, не зацикливайся на одном."
            )

        return f"""Создай рецепт на {meal_ru}.

Требования к рецепту:
- Тип приёма пищи: {meal_ru}
- Целевые калории порции (300 г): {target_calories:.0f} ккал (±5%)
- Аллергены пользователя (ЗАПРЕЩЕНО использовать в ингредиентах): {allergens_str}
- Пользователь хорошо относится к этим продуктам — можно использовать, но не обязательно: {liked_str}
- Пользователь не любит эти продукты — лучше не включать: {disliked_str}
- Предпочтения по кухне: {cuisines_str}
{protein_block}
Нутрициологический баланс (обязательно):
- Цельные углеводы: крупы (киноа, булгур, зелёная гречка, перловка, овсянка), батат, бобовые
- Белок: на выбор из рейтинга выше или растительный (нут, чечевица, тофу, эдамаме)
- Клетчатка и микронутриенты: свежие или запечённые овощи, зелень, листовые салаты
- Жиры: авокадо, оливковое масло, орехи, семена (чиа, кунжут, тыквенные) — в умеренном количестве

Тренды и суперфуды — используй уместно, не перегружай блюдо:
- Форматы: боул, скрэмбл, тост на цельнозерновом, ризотто из перловки, тёплый салат, карри
- Ингредиенты: рикотта, батат, авокадо, зелёная гречка, чиа, эдамаме, мисо, кокосовое молоко,
  шпинат, руккола, кейл, нут, чечевица, кабачок, брокколи, цветная капуста, свёкла
- Специи и соусы: тахини, лимонная заправка, терияки без сахара, зира, куркума, имбирь

Подача и название:
- Название должно звучать аппетитно и современно (можно добавить прилагательные: золотистый, кремовый, хрустящий)
- Описание — 1–2 предложения, которые хочется прочитать в меню ресторана
- Шаги рецепта — чёткие и конкретные, без воды

Полный список возможных аллергенов: {all_allergens}

Верни ТОЛЬКО валидный JSON в точно таком формате:
{{
  "title": "Название блюда",
  "description": "Краткое аппетитное описание блюда (1–2 предложения).",
  "cuisine": "одно из: азиатская|европейская|восточная|славянская|американская|мексиканская",
  "ingredients": ["200 г куриной грудки", "100 г риса", "2 зубчика чеснока"],
  "steps": [
    "Шаг 1: нарезать куриную грудку кубиками.",
    "Шаг 2: отварить рис до готовности.",
    "Шаг 3: обжарить курицу с чесноком 10 минут."
  ],
  "nutrition": {{
    "calories": {target_calories / 3:.1f},
    "protein": {target_calories / 3 * 0.15 / 4:.1f},
    "fat":     {target_calories / 3 * 0.30 / 9:.1f},
    "carbs":   {target_calories / 3 * 0.55 / 4:.1f}
  }},
  "active_cooking_time_min": 20,
  "passive_cooking_time_min": 10,
  "common_allergens": ["аллергены из стандартного перечня, которые реально присутствуют в блюде"]
}}

Обрати внимание: nutrition — значения на 100 г продукта, calories = ккал/100 г."""

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    # Protein features that have meaningful user ratings
    _PROTEIN_FEATURES = [
        "рыба", "морепродукты", "свинина", "говядина", "курица", "печень",
    ]

    def _extract_user_preferences(
        self, user_dict: dict
    ) -> tuple[list[str], list[str], list[str], list[str], dict[str, float]]:
        user_allergens = [name for name in ALLERGEN_DISH_NAMES if user_dict.get(name, 0) == 1]
        liked      = [f for f in PRODUCT_FEATURES if user_dict.get(f, 0.5) >= 0.7]
        disliked   = [f for f in PRODUCT_FEATURES if user_dict.get(f, 0.5) <= 0.3]
        cuisines   = [ru for feat, ru in _CUISINE_FEATURE_TO_RU.items()
                      if user_dict.get(feat, 0.5) >= 0.7]
        protein_ratings = {
            feat: user_dict.get(feat, 0.5)
            for feat in self._PROTEIN_FEATURES
        }
        return user_allergens, liked, disliked, cuisines, protein_ratings

    def _call_api(self, system: str, user: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0.7,
            max_tokens=2048,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _parse_json(content: str) -> dict:
        content = content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(content)

    def _generate_one(
        self,
        meal_type: str,
        target_calories: float,
        user_allergens: list[str],
        liked_ingredients: list[str],
        disliked_ingredients: list[str],
        preferred_cuisines: list[str],
        protein_ratings: dict[str, float] | None = None,
    ) -> dict:
        system = self._system_prompt()
        prompt = self._user_prompt(
            meal_type, target_calories,
            user_allergens, liked_ingredients, disliked_ingredients, preferred_cuisines,
            protein_ratings,
        )
        logger.info("Generating recipe for slot=%s, target=%.0f kcal", meal_type, target_calories)

        raw  = self._call_api(system, prompt)
        data = self._parse_json(raw)

        nutrition        = data.get("nutrition", {})
        cal_per_100g     = float(nutrition.get("calories", target_calories / 3))
        protein_per_100g = float(nutrition.get("protein",  0))
        fat_per_100g     = float(nutrition.get("fat",      0))
        carbs_per_100g   = float(nutrition.get("carbs",    0))

        active_min  = int(data.get("active_cooking_time_min",  0))
        passive_min = int(data.get("passive_cooking_time_min", 0))
        total_min   = active_min + passive_min

        ingredients      = data.get("ingredients", [])
        steps            = data.get("steps", [])
        common_allergens = data.get("common_allergens", [])

        # Warn if generated dish contains user allergens
        conflicts = set(user_allergens) & set(common_allergens)
        if conflicts:
            logger.warning(
                "Generated recipe '%s' contains user allergens %s",
                data.get("title"), conflicts,
            )

        # ------ Build record in local recipes.json format ------
        category = _CATEGORY_BY_MEAL[meal_type]
        record = {
            # Core identifiers
            "id":           self._next_id(),
            "title":        data["title"],
            "description":  data.get("description", ""),
            "dish_image":   None,

            # KBJU per 100 g (matching notebook format)
            "kbju": {
                "calories": round(cal_per_100g, 2),
                "protein":  round(protein_per_100g, 2),
                "fat":      round(fat_per_100g, 2),
                "carbs":    round(carbs_per_100g, 2),
            },

            # Time strings (Russian)
            "ready_in":    _minutes_to_ru(total_min),
            "kitchen_time": _minutes_to_ru(active_min),

            "cuisine":          data.get("cuisine", "европейская"),
            "breadcrumbs":      ["Рецепты", category],
            "category_path":    f"Рецепты > {category}",
            "category_lvl1":    category,
            "common_allergens": common_allergens,
            "ingredients":      ingredients,

            # Recipe as markdown steps (matches notebook's "recipe" column)
            "recipe": "\n\n".join(
                f"### Шаг {i + 1}\n{step}" for i, step in enumerate(steps)
            ),

            # Flat KBJU columns (per 100 g) — present in notebook DataFrame
            "calories": round(cal_per_100g, 2),
            "protein":  round(protein_per_100g, 2),
            "fat":      round(fat_per_100g, 2),
            "carbs":    round(carbs_per_100g, 2),

            # Time in minutes
            "ready_in_minutes":          total_min,
            "kitchen_time_in_minutes":   active_min,

            # Binary product flags (for planner)
            **_product_flags(ingredients),

            # Binary allergen flags (for planner)
            **_allergen_flags(common_allergens),

            # Meal type & meta
            "mealType":      meal_type,
            "is_generated":  True,
            "generated_at":  datetime.datetime.utcnow().isoformat(),
            "user_allergens": user_allergens,
        }

        self._save_recipe(record)

        # Return planner-compatible dict (calories = per portion = per_100g × 3)
        return {**record, "calories": round(cal_per_100g * 3, 2)}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_for_database(
        self,
        meal_type: str,
        target_calories: float,
        exclude_allergens: list[str] | None = None,
        preferred_cuisines: list[str] | None = None,
        liked_ingredients: list[str] | None = None,
        disliked_ingredients: list[str] | None = None,
        count: int = 1,
    ) -> list[dict]:
        """
        Generate `count` recipes for a given meal slot and save them to generated_recipes.json.
        Returns planner-compatible dicts (calories = per portion).
        Raises the last exception if no recipes were generated at all.
        """
        results: list[dict] = []
        last_error: Exception | None = None
        for i in range(count):
            try:
                recipe = self._generate_one(
                    meal_type=meal_type,
                    target_calories=target_calories,
                    user_allergens=exclude_allergens or [],
                    liked_ingredients=liked_ingredients or [],
                    disliked_ingredients=disliked_ingredients or [],
                    preferred_cuisines=preferred_cuisines or [],
                )
                results.append(recipe)
            except Exception as e:
                last_error = e
                logger.exception("Failed to generate recipe %d/%d for slot %s", i + 1, count, meal_type)
        if not results and last_error is not None:
            raise last_error
        return results

    # ------------------------------------------------------------------
    # Ingredient-based generation (chat scenario)
    # ------------------------------------------------------------------

    @staticmethod
    def _ingredient_prompt(
        available_ingredients: list[str],
        meal_type: str,
        user_allergens: list[str],
    ) -> str:
        meal_ru = _MEAL_SLOT_RU.get(meal_type, "блюдо")
        ingredients_str = ", ".join(available_ingredients)
        allergens_str = ", ".join(user_allergens) if user_allergens else "нет"
        all_allergens = ", ".join(ALLERGEN_DISH_NAMES)

        return f"""Пользователь хочет приготовить {meal_ru} ИЗ ТЕХ ПРОДУКТОВ, ЧТО У НЕГО ЕСТЬ.

Имеющиеся ингредиенты у пользователя: {ingredients_str}
Аллергены пользователя (ЗАПРЕЩЕНО использовать): {allergens_str}

Правила:
- Используй ПРЕИМУЩЕСТВЕННО ингредиенты из списка пользователя.
- Допустимо добавить базовые продукты, которые есть на кухне почти у всех (соль, перец, масло, вода, лук, чеснок) — но без экзотики.
- Если из имеющихся ингредиентов невозможно собрать осмысленное блюдо — верни {{"error": "..."}} с пояснением.
- НИКОГДА не используй заявленные аллергены.

Полный список возможных аллергенов: {all_allergens}

Верни ТОЛЬКО валидный JSON в точно таком формате:
{{
  "title": "Название блюда",
  "description": "Краткое аппетитное описание (1–2 предложения).",
  "cuisine": "одно из: азиатская|европейская|восточная|славянская|американская|мексиканская",
  "ingredients": ["200 г куриной грудки", "1 луковица", "2 ст. л. оливкового масла"],
  "steps": [
    "Шаг 1: ...",
    "Шаг 2: ..."
  ],
  "nutrition": {{
    "calories": 180.0,
    "protein": 18.0,
    "fat": 8.0,
    "carbs": 6.0
  }},
  "active_cooking_time_min": 20,
  "passive_cooking_time_min": 10,
  "common_allergens": ["аллергены из стандартного перечня, которые реально присутствуют в блюде"]
}}

Обрати внимание: nutrition — значения на 100 г продукта."""

    def generate_from_ingredients(
        self,
        available_ingredients: list[str],
        user_allergens: Optional[list[str]] = None,
        meal_type: str = "DINNER",
    ) -> dict:
        """
        Generate a recipe constrained to a user-supplied list of ingredients.
        Used by the interactive chat scenario where the user types what they have on hand.
        Returns the same record shape as _generate_one (planner-compatible dict).
        Raises ValueError if the LLM cannot compose a valid recipe.
        """
        if not available_ingredients:
            raise ValueError("Список ингредиентов пуст")

        system = self._system_prompt()
        prompt = self._ingredient_prompt(
            available_ingredients=available_ingredients,
            meal_type=meal_type,
            user_allergens=user_allergens or [],
        )
        logger.info("Generating recipe from ingredients: %s (slot=%s)",
                    available_ingredients, meal_type)

        raw = self._call_api(system, prompt)
        data = self._parse_json(raw)

        if isinstance(data, dict) and data.get("error"):
            raise ValueError(data["error"])

        # Reuse the same record-building path used by _generate_one, but inlined
        # because we already have parsed data and don't want to re-call the API.
        nutrition        = data.get("nutrition", {})
        cal_per_100g     = float(nutrition.get("calories", 200))
        protein_per_100g = float(nutrition.get("protein",  0))
        fat_per_100g     = float(nutrition.get("fat",      0))
        carbs_per_100g   = float(nutrition.get("carbs",    0))

        active_min  = int(data.get("active_cooking_time_min",  0))
        passive_min = int(data.get("passive_cooking_time_min", 0))
        total_min   = active_min + passive_min

        ingredients      = data.get("ingredients", [])
        steps            = data.get("steps", [])
        common_allergens = data.get("common_allergens", [])

        conflicts = set(user_allergens or []) & set(common_allergens)
        if conflicts:
            logger.warning("Generated recipe contains user allergens %s", conflicts)

        category = _CATEGORY_BY_MEAL.get(meal_type, "Вторые блюда")
        record = {
            "id":           self._next_id(),
            "title":        data["title"],
            "description":  data.get("description", ""),
            "dish_image":   None,
            "kbju": {
                "calories": round(cal_per_100g, 2),
                "protein":  round(protein_per_100g, 2),
                "fat":      round(fat_per_100g, 2),
                "carbs":    round(carbs_per_100g, 2),
            },
            "ready_in":    _minutes_to_ru(total_min),
            "kitchen_time": _minutes_to_ru(active_min),
            "cuisine":          data.get("cuisine", "европейская"),
            "breadcrumbs":      ["Рецепты", category],
            "category_path":    f"Рецепты > {category}",
            "category_lvl1":    category,
            "common_allergens": common_allergens,
            "ingredients":      ingredients,
            "recipe": "\n\n".join(
                f"### Шаг {i + 1}\n{step}" for i, step in enumerate(steps)
            ),
            "calories": round(cal_per_100g, 2),
            "protein":  round(protein_per_100g, 2),
            "fat":      round(fat_per_100g, 2),
            "carbs":    round(carbs_per_100g, 2),
            "ready_in_minutes":          total_min,
            "kitchen_time_in_minutes":   active_min,
            **_product_flags(ingredients),
            **_allergen_flags(common_allergens),
            "mealType":      meal_type,
            "is_generated":  True,
            "generated_at":  datetime.datetime.utcnow().isoformat(),
            "user_allergens": user_allergens or [],
            "source":        "ingredient_chat",
        }
        self._save_recipe(record)
        return {**record, "calories": round(cal_per_100g * 3, 2)}

    def generate_meals(
        self,
        user_dict: dict,
        target_calories: float,
        meal_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Generate one recipe per meal slot.
        Calories are split proportionally: BREAKFAST 25%, LUNCH 40%, DINNER 35%.
        Returns planner-compatible dicts; failed slots are skipped.
        """
        if meal_types is None:
            meal_types = _ALL_MEAL_TYPES

        user_allergens, liked, disliked, cuisines, protein_ratings = self._extract_user_preferences(user_dict)

        results: list[dict] = []
        for meal_type in meal_types:
            slot_cal = target_calories * _CALORIE_SPLIT.get(meal_type, 1 / len(meal_types))
            try:
                recipe = self._generate_one(
                    meal_type=meal_type,
                    target_calories=slot_cal,
                    user_allergens=user_allergens,
                    liked_ingredients=liked,
                    disliked_ingredients=disliked,
                    preferred_cuisines=cuisines,
                    protein_ratings=protein_ratings,
                )
                results.append(recipe)
                logger.info(
                    "Generated: slot=%s title='%s' calories=%.0f kcal/portion",
                    meal_type, recipe["title"], recipe["calories"],
                )
            except Exception:
                logger.exception("Failed to generate recipe for slot %s", meal_type)

        return results
