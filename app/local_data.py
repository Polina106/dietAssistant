"""
Reads users and recipes from local JSON files instead of external microservices.

Expected files:
  app/data/recipes.json  – list of recipe dicts in notebook format
  app/data/users.json    – list of user dicts in notebook format

recipes.json columns that matter:
  id, title, calories (kcal/100g), protein, fat, carbs
  ready_in (str) / ready_in_minutes (int)
  kitchen_time (str) / kitchen_time_in_minutes (int)
  cuisine, common_allergens (list), ingredients (list)
  mealType (BREAKFAST | LUNCH | DINNER) – added manually or derived here
  binary product flags: рыба, морепродукты, свинина, …
  binary cuisine flags: asian, european, eastern, slavic, america, mexica

users.json columns that matter:
  user_id (int), target_calories, активное_время_готовки_мин, пассивное_время_мин
  cuisine prefs (1–10): asian, european, eastern, slavic, america, mexica
  product prefs (1–10): рыба, морепродукты, …
  allergen flags (0/1 with Russian names): Белок коровьего молока, …
"""

import json
import logging
import pathlib
from typing import Optional

import pandas as pd

from app.config import ALLERGEN_DISH_NAMES, PRODUCT_FEATURES

logger = logging.getLogger(__name__)

# Accept both .json (array) and .jsonl (one record per line)
RECIPES_PATH = pathlib.Path("app/data/recipes.json")
RECIPES_PATH_JSONL = pathlib.Path("app/data/recipes.jsonl")
USERS_PATH = pathlib.Path("app/data/users.json")
USERS_PATH_JSONL = pathlib.Path("app/data/users.jsonl")
GENERATED_RECIPES_PATH = pathlib.Path("app/data/generated_recipes.json")

# Local file cuisine keys → planner feature names (CUISINE_FEATURES in config)
_CUISINE_MAP = {
    "asian":    "asian",
    "european": "european",
    "eastern":  "eastern",
    "slavic":   "slavic",
    "america":  "american",
    "mexica":   "mexican",
}

# Deterministic mealType fallback when the field is missing
_MEAL_TYPE_BY_MOD = {0: "BREAKFAST", 1: "LUNCH", 2: "DINNER"}


# ------------------------------------------------------------------
# Availability checks
# ------------------------------------------------------------------

def _resolve_path(json_path: pathlib.Path, jsonl_path: pathlib.Path) -> Optional[pathlib.Path]:
    """Return whichever of the two paths exists (json preferred)."""
    if json_path.exists():
        return json_path
    if jsonl_path.exists():
        return jsonl_path
    return None


def _read_records(path: pathlib.Path) -> list[dict]:
    """
    Read a data file into a list of dicts.
    Handles four formats:
      - JSON array:                  [{"col": val}, ...]
      - JSONL (one object per line): {"col": val}\n{"col": val}
      - pandas orient='records':     same as JSON array
      - pandas orient='columns':     {"col": {"0": val, "1": val}, ...}  ← default to_json()
    """
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    # JSONL: suffix is .jsonl OR first char is not [ or {
    if path.suffix == ".jsonl" or text[0] not in ("[", "{"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    data = json.loads(text)

    if isinstance(data, list):
        return data  # already records format

    if isinstance(data, dict):
        first_val = next(iter(data.values()), None)
        if isinstance(first_val, dict):
            # pandas orient='columns': {"col": {"0": v0, "1": v1, ...}, ...}
            # Convert to records via pandas (already a dependency)
            return pd.DataFrame(data).to_dict(orient="records")
        # Single record wrapped in a dict
        return [data]

    return []


def recipes_available() -> bool:
    return _resolve_path(RECIPES_PATH, RECIPES_PATH_JSONL) is not None


def users_available() -> bool:
    return _resolve_path(USERS_PATH, USERS_PATH_JSONL) is not None


# ------------------------------------------------------------------
# Recipes
# ------------------------------------------------------------------

def load_recipes_df() -> pd.DataFrame:
    """Load recipes.json / recipes.jsonl and return a DataFrame ready for MealPlanner."""
    path = _resolve_path(RECIPES_PATH, RECIPES_PATH_JSONL)
    if path is None:
        raise FileNotFoundError(f"Neither {RECIPES_PATH} nor {RECIPES_PATH_JSONL} found")
    records = _read_records(path)
    rows = []
    for r in records:
        rid = r.get("id", 0)
        meal_type = r.get("mealType") or _MEAL_TYPE_BY_MOD[abs(int(rid)) % 3]

        # Local data stores kcal/100 g; the planner multiplies by 3 (300 g portion)
        calories_per_100g = float(r.get("calories") or 0)

        row = {
            "id":                   rid,
            "title":                r.get("title", ""),
            "calories":             calories_per_100g * 3,
            "mealType":             meal_type,
            "cuisine":              r.get("cuisine", ""),
            "ready_in_minutes":     int(r.get("ready_in_minutes") or 9999),
            "kitchen_time_minutes": int(
                r.get("kitchen_time_in_minutes")
                or r.get("kitchen_time_minutes")
                or 9999
            ),
        }

        # Cuisine binary features
        for local_key, feat_key in _CUISINE_MAP.items():
            row[feat_key] = int(r.get(local_key) or 0)

        # Product binary features (same names in both formats)
        for feat in PRODUCT_FEATURES:
            row[feat] = int(r.get(feat) or 0)

        # Allergen binary features – derive from common_allergens list
        allergen_set = set(r.get("common_allergens") or [])
        for allergen in ALLERGEN_DISH_NAMES:
            row[allergen] = int(allergen in allergen_set)

        rows.append(row)

    df = pd.DataFrame(rows)
    logger.info("Loaded %d recipes from %s", len(df), path)

    # Merge generated recipes so they are immediately available to the planner
    if GENERATED_RECIPES_PATH.exists():
        gen_records = json.loads(GENERATED_RECIPES_PATH.read_text(encoding="utf-8"))
        if gen_records:
            gen_rows = []
            for r in gen_records:
                meal_type = r.get("mealType") or _MEAL_TYPE_BY_MOD[abs(int(r.get("id", 0))) % 3]
                # Generated recipes store calories per 100g; multiply to get 300g portion
                cal_per_100g = float(r.get("calories") or 0)
                row = {
                    "id":                   r["id"],
                    "title":                r.get("title", ""),
                    "calories":             cal_per_100g * 3,
                    "mealType":             meal_type,
                    "cuisine":              r.get("cuisine", ""),
                    "ready_in_minutes":     int(r.get("ready_in_minutes") or 9999),
                    "kitchen_time_minutes": int(r.get("kitchen_time_in_minutes") or r.get("kitchen_time_minutes") or 9999),
                }
                for local_key, feat_key in _CUISINE_MAP.items():
                    row[feat_key] = int(r.get(local_key) or 0)
                for feat in PRODUCT_FEATURES:
                    row[feat] = int(r.get(feat) or 0)
                allergen_set = set(r.get("common_allergens") or [])
                for allergen in ALLERGEN_DISH_NAMES:
                    row[allergen] = int(allergen in allergen_set)
                gen_rows.append(row)
            gen_df = pd.DataFrame(gen_rows)
            df = pd.concat([df, gen_df], ignore_index=True)
            logger.info("Added %d generated recipes to planner", len(gen_rows))

    return df


# ------------------------------------------------------------------
# Users
# ------------------------------------------------------------------

def load_user(user_id: str | int) -> Optional[dict]:
    """Return the user dict for a given id, or None if not found."""
    path = _resolve_path(USERS_PATH, USERS_PATH_JSONL)
    if path is None:
        return None
    users = _read_records(path)
    try:
        uid: int | str = int(user_id)
    except (ValueError, TypeError):
        uid = user_id
    return next((u for u in users if u.get("user_id") == uid), None)


def load_all_users() -> list[dict]:
    path = _resolve_path(USERS_PATH, USERS_PATH_JSONL)
    return _read_records(path) if path else []


def build_user_dict(user: dict) -> dict:
    """Convert a local users.json record to the planner's user_dict format."""
    result: dict = {
        "пассивное_время_мин":          user.get("пассивное_время_мин") or 9999,
        "активное_время_готовки_мин":   user.get("активное_время_готовки_мин") or 9999,
        "target_calories":              float(user.get("target_calories") or 2000),
    }

    # Allergen binary flags – already correct column names
    for allergen in ALLERGEN_DISH_NAMES:
        result[allergen] = int(user.get(allergen) or 0)

    # Cuisine preferences: local 1–10 → planner 0–1
    for local_key, feat_key in _CUISINE_MAP.items():
        result[feat_key] = float(user.get(local_key) or 5) / 10.0

    # Product preferences: local 1–10 → planner 0–1
    for feat in PRODUCT_FEATURES:
        result[feat] = float(user.get(feat) or 5) / 10.0

    return result
