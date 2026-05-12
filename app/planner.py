import logging

import numpy as np
import pandas as pd
from ortools.linear_solver import pywraplp
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import MinMaxScaler

from app.config import CUISINE_FEATURES, PRODUCT_FEATURES, ALLERGEN_DISH_NAMES

logger = logging.getLogger(__name__)


class MealPlanner:

    def __init__(self, recipes_df: pd.DataFrame):
        self.recipes_df = recipes_df
        self.allergens = ALLERGEN_DISH_NAMES
        self.cont_features = CUISINE_FEATURES
        self.product_features = PRODUCT_FEATURES

    def filter_recipes(self, user_row: pd.Series) -> pd.DataFrame:
        df = self.recipes_df.copy()

        allergen_mask = np.ones(len(df), dtype=bool)
        for allergen in self.allergens:
            if user_row.get(allergen, 0) == 1 and allergen in df.columns:
                allergen_mask &= (df[allergen] == 0)

        passive_limit = user_row.get("пассивное_время_мин", 9999) * 1.25
        active_limit = user_row.get("активное_время_готовки_мин", 9999) * 1.25

        time_mask = df["ready_in_minutes"] <= passive_limit
        kitchen_mask = df["kitchen_time_minutes"] <= active_limit

        return df[allergen_mask & time_mask & kitchen_mask]

    def rank_recipes(self, user_row: pd.Series, filtered: pd.DataFrame) -> pd.DataFrame:
        if filtered.empty:
            return filtered

        scaler = MinMaxScaler()

        recipes_cont = filtered[self.cont_features].fillna(0).values
        if recipes_cont.max() == recipes_cont.min():
            recipes_cont_scaled = recipes_cont
            user_cont_scaled = np.array([[user_row.get(f, 0) for f in self.cont_features]])
        else:
            recipes_cont_scaled = scaler.fit_transform(recipes_cont)
            user_cont_scaled = scaler.transform(
                np.array([[user_row.get(f, 0) for f in self.cont_features]])
            )

        recipes_prod = filtered[self.product_features].fillna(0).astype(float).values
        user_prod = np.array([[user_row.get(f, 0.5) for f in self.product_features]])

        recipes_vec = np.hstack([recipes_cont_scaled, recipes_prod])
        user_vec = np.hstack([user_cont_scaled, user_prod])

        cos_sim = cosine_similarity(user_vec, recipes_vec)[0]

        ranked = filtered.copy()
        ranked["cos_sim"] = cos_sim
        ranked = ranked.sort_values("cos_sim", ascending=False)

        logger.debug("Top-5 by cosine similarity:\n%s",
                     ranked[["id", "title", "cos_sim"]].head(5).to_string())
        return ranked

    def optimize_meals(self, ranked: pd.DataFrame, target_calories: float, tolerance: float = 0.1):
        solver = pywraplp.Solver.CreateSolver("CBC")
        if not solver:
            logger.error("OR-Tools solver not found")
            return None

        recipes = ranked.to_dict("records")
        n = len(recipes)

        x = [solver.IntVar(0, 1, f"r_{i}") for i in range(n)]

        breakfast = [i for i in range(n) if recipes[i]["mealType"] == "BREAKFAST"]
        lunch = [i for i in range(n) if recipes[i]["mealType"] == "LUNCH"]
        dinner = [i for i in range(n) if recipes[i]["mealType"] == "DINNER"]

        meal_slots = {"BREAKFAST": breakfast, "LUNCH": lunch, "DINNER": dinner}
        available_slots = {k: v for k, v in meal_slots.items() if v}

        if not available_slots:
            logger.warning("No recipes available for any meal slot")
            return None

        cal_expr = solver.Sum([recipes[i]["calories"] * x[i] for i in range(n)])
        solver.Add(cal_expr >= target_calories * (1 - tolerance))
        solver.Add(cal_expr <= target_calories * (1 + tolerance))

        for slot_name, indices in available_slots.items():
            solver.Add(solver.Sum([x[i] for i in indices]) == 1)

        solver.Add(solver.Sum(x) == len(available_slots))

        obj = solver.Objective()
        for i in range(n):
            obj.SetCoefficient(x[i], recipes[i]["cos_sim"])
        obj.SetMaximization()

        status = solver.Solve()

        if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
            logger.info(
                "No solution found (tolerance=%.0f%%). Category distribution: %s",
                tolerance * 100,
                ranked["mealType"].value_counts().to_dict(),
            )
            return None

        selected_ids = [
            recipes[i]["id"] for i in range(n) if x[i].solution_value() > 0.5
        ]
        total_cal = sum(recipes[i]["calories"] for i in range(n) if x[i].solution_value() > 0.5)
        logger.info(
            "Plan found: %d dishes, %.0f kcal (target %.0f, deviation %.1f%%)",
            len(selected_ids), total_cal, target_calories,
            (total_cal / target_calories - 1) * 100 if target_calories else 0,
        )
        return ranked[ranked["id"].isin(selected_ids)]

    def plan_day(self, user_dict: dict, exclude_recipe_ids: list[int] | None = None) -> list[dict]:
        user_row = pd.Series(user_dict)

        filtered = self.filter_recipes(user_row)
        if filtered.empty:
            logger.warning("No recipes passed filters")
            return []

        ranked = self.rank_recipes(user_row, filtered)

        if exclude_recipe_ids:
            ranked = ranked[~ranked["id"].isin(set(exclude_recipe_ids))]
        if ranked.empty:
            logger.warning("No recipes left after exclusions")
            return []

        for tol in [0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.7]:
            result = self.optimize_meals(ranked, target_calories=user_dict["target_calories"], tolerance=tol)
            if result is not None:
                return result.to_dict(orient="records")

        logger.warning("Optimizer failed for all tolerances")
        return []

    def find_replacement(
        self,
        user_dict: dict,
        meal_type: str,
        exclude_ids: list[int],
    ) -> dict | None:
        user_row = pd.Series(user_dict)
        filtered = self.filter_recipes(user_row)
        filtered = filtered[filtered["mealType"] == meal_type]
        filtered = filtered[~filtered["id"].isin(set(exclude_ids))]

        if filtered.empty:
            return None

        ranked = self.rank_recipes(user_row, filtered)
        if ranked.empty:
            return None

        return ranked.iloc[0].to_dict()
