import re
import logging
from typing import Optional

import pandas as pd

from app.config import (
    CUISINE_TO_FEATURE, CUISINE_FEATURES,
    PRODUCT_FEATURES, PRODUCT_KEYWORDS,
    ALLERGEN_DISH_NAMES,
)

logger = logging.getLogger(__name__)


def _parse_minutes(time_str: Optional[str]) -> int:
    if not time_str:
        return 9999
    s = time_str.lower()
    hours = 0
    minutes = 0
    h = re.search(r'(\d+)\s*(?:час|ч\b)', s)
    m = re.search(r'(\d+)\s*(?:минут|мин\b)', s)
    if h:
        hours = int(h.group(1))
    if m:
        minutes = int(m.group(1))
    if hours == 0 and minutes == 0:
        num = re.search(r'(\d+)', s)
        if num:
            minutes = int(num.group(1))
    total = hours * 60 + minutes
    return total if total > 0 else 9999


def _cuisine_scores(cuisine: Optional[str]) -> dict:
    scores = {f: 0 for f in CUISINE_FEATURES}
    if cuisine:
        feature = CUISINE_TO_FEATURE.get(cuisine.lower().strip())
        if feature:
            scores[feature] = 1
    return scores


def _product_flags(ingredients: list[str]) -> dict:
    joined = " ".join(ingredients).lower()
    return {
        product: int(any(kw in joined for kw in keywords))
        for product, keywords in PRODUCT_KEYWORDS.items()
    }


def _allergen_flags(allergens: list[str]) -> dict:
    allergen_set = set(allergens)
    return {name: int(name in allergen_set) for name in ALLERGEN_DISH_NAMES}


def build_dataframe(dishes: list[dict]) -> pd.DataFrame:
    rows = []
    for dish in dishes:
        allergens = dish.get("allergens") or []
        ingredients = dish.get("ingredients") or []

        row = {
            "id":                    dish["id"],
            "title":                 dish.get("title", ""),
            "calories":              float(dish.get("calories") or 0),
            "mealType":              dish.get("mealType", ""),
            "cuisine":               dish.get("cuisine", ""),
            "ready_in_minutes":      _parse_minutes(dish.get("readyIn")),
            "kitchen_time_minutes":  _parse_minutes(dish.get("kitchenTime")),
        }
        row.update(_cuisine_scores(dish.get("cuisine")))
        row.update(_product_flags(ingredients))
        row.update(_allergen_flags(allergens))
        rows.append(row)

    df = pd.DataFrame(rows)
    logger.info("Built DataFrame: %d dishes", len(df))
    return df


def load_recipes(dishes: list[dict]) -> pd.DataFrame:
    return build_dataframe(dishes)
