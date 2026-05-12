import numpy as np
import pandas as pd

from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import MinMaxScaler
from ortools.linear_solver import pywraplp
from IPython.display import display


class MealPlanner:

    def __init__(self, recipes_df: pd.DataFrame, allergens: list,
                 cont_features: list, product_features: list):

        self.recipes_df = recipes_df
        self.allergens = allergens
        self.cont_features = cont_features
        self.product_features = product_features

    # 1. Фильтрация
    def filter_recipes(self, user_row):

        recipes_df = self.recipes_df.copy()

        allergen_mask = np.ones(len(recipes_df), dtype=bool)

        for allergen in self.allergens:
            if user_row.get(allergen, 0) == 1:
                allergen_mask &= (recipes_df[allergen] == 0)

        time_mask = (
            recipes_df['ready_in_minutes']
            <= user_row['пассивное_время_мин'] * 1.25
        )

        time_mask_kitchen = (
            recipes_df['kitchen_time_in_minutes']
            <= user_row['активное_время_готовки_мин'] * 1.25
        )

        return recipes_df[allergen_mask & time_mask & time_mask_kitchen]


    # 2. Считаем косинусное сходство
    def rank_recipes(self, user_row, filtered_recipes):

        scaler = MinMaxScaler()

        recipes_cont_scaled = scaler.fit_transform(
            filtered_recipes[self.cont_features]
        )

        user_cont_vector = scaler.transform(
            user_row[self.cont_features].values.reshape(1, -1)
        )

        recipes_prod = filtered_recipes[self.product_features].astype(float).values
        user_prod_vector = (
            user_row[self.product_features].values / 10
        ).reshape(1, -1)

        recipes_vectors = np.hstack([recipes_cont_scaled, recipes_prod])
        user_vector = np.hstack([user_cont_vector, user_prod_vector])

        cos_sim = cosine_similarity(user_vector, recipes_vectors)[0]

        ranked = filtered_recipes.copy()
        ranked['cos_sim'] = cos_sim

        ranked['calories'] = ranked['calories'] * 3

        display(ranked.sort_values('cos_sim', ascending=False)[:10])

        return ranked.sort_values('cos_sim', ascending=False)


    # 3. Оптимизатор
    def optimize_meals(self, filtered_recipes_df, target_calories, tolerance=0.1):
        """
        Выбирает оптимальный набор блюд (завтрак, обед, ужин, десерт).
        """
        solver = pywraplp.Solver.CreateSolver('CBC')
        if not solver:
            print('Solver не найден.')
            return None

        recipes = filtered_recipes_df.to_dict('records')
        n = len(recipes)

        x = [solver.IntVar(0, 1, f'recipe_{i}') for i in range(n)]

        # --- Правильное распределение категорий по приемам пищи ---
        breakfast_indices = [
            i for i in range(n)
            if recipes[i]['category_lvl1'] in ['Закуски', 'Вторые блюда']
        ]

        lunch_indices = [
            i for i in range(n)
            if recipes[i]['category_lvl1'] in ['Первые блюда', 'Вторые блюда', 'Салаты', 'Рецепты с любимыми продуктами']
        ]

        dinner_indices = [
            i for i in range(n)
            if recipes[i]['category_lvl1'] in ['Вторые блюда', 'Салаты', 'Закуски', 'Рецепты с любимыми продуктами', 'Гарниры']
        ]

        dessert_indices = [
            i for i in range(n)
            if recipes[i]['category_lvl1'] in ['Десерты', 'Выпечка']
        ]


        # 1. Калорийность
        calories_expr = solver.Sum([recipes[i]['calories'] * x[i] for i in range(n)])
        solver.Add(calories_expr >= target_calories * (1 - tolerance))
        solver.Add(calories_expr <= target_calories * (1 + tolerance))

        # 2. Ровно по одному блюду на каждый прием пищи
        # Проверяем, что для каждого типа есть хотя бы один рецепт
        meal_types = {
            'завтрак': breakfast_indices,
            'обед': lunch_indices,
            'ужин': dinner_indices,
            'десерт': dessert_indices
        }

        for meal_name, indices in meal_types.items():
            if not indices:
                print(f"Предупреждение: Нет рецептов для '{meal_name}' в доступном списке!")
                continue
            solver.Add(solver.Sum([x[i] for i in indices]) == 1)

        # 3. Дополнительное ограничение: всего должно быть выбрано ровно 4 блюда
        # (на случай, если какой-то тип отсутствует)
        solver.Add(solver.Sum(x) == 4)

        objective = solver.Objective()
        for i in range(n):
            objective.SetCoefficient(x[i], recipes[i]['cos_sim'])
        objective.SetMaximization()

        status = solver.Solve()

        if status == pywraplp.Solver.OPTIMAL or status == pywraplp.Solver.FEASIBLE:
            print('Решение найдено!')
            print(f'Целевая калорийность: {target_calories} ± {tolerance*100}%')

            selected_ids = []
            total_calories = 0
            total_score = 0
            meal_count = {'завтрак': 0, 'обед': 0, 'ужин': 0, 'десерт': 0}

            print("\nОптимальное меню на день:")
            print("-" * 50)

            for i in range(n):
                if x[i].solution_value() > 0.5:
                    recipe = recipes[i]
                    selected_ids.append(recipe['id'])
                    total_calories += recipe['calories']
                    total_score += recipe['cos_sim']

                    # Определяем, к какому приему пищи относится блюдо
                    if i in breakfast_indices:
                        meal_type = "ЗАВТРАК"
                        meal_count['завтрак'] += 1
                    elif i in lunch_indices:
                        meal_type = "ОБЕД"
                        meal_count['обед'] += 1
                    elif i in dinner_indices:
                        meal_type = "УЖИН"
                        meal_count['ужин'] += 1
                    elif i in dessert_indices:
                        meal_type = "ДЕСЕРТ"
                        meal_count['десерт'] += 1
                    else:
                        meal_type = "ДРУГОЕ"

                    print(f"{meal_type:8}: {recipe.get('title', f'ID:{recipe['id']}')}")
                    print(f"          id: {recipe['id']}")
                    print(f"          Категория: {recipe['category_lvl1']}")
                    print(f"          Калории: {recipe['calories']} ккал")
                    print(f"          Релевантность: {recipe['cos_sim']:.3f}")
                    print()

            print("-" * 50)
            print(f" ИТОГО:")
            print(f"   Калории: {total_calories} ккал (цель: {target_calories} ккал)")
            print(f"   Отклонение: {((total_calories/target_calories)-1)*100:.1f}%")
            print(f"   Суммарная релевантность: {total_score:.3f}")
            print(f"   Состав меню: {meal_count}")

            return filtered_recipes_df[filtered_recipes_df['id'].isin(selected_ids)]

        else:
            print('Не удалось найти оптимальное решение.')
            print('\nВозможные причины:')
            print('1. Слишком жесткие ограничения по калорийности')
            print('2. Нет подходящих рецептов для какого-то приема пищи')

            # Диагностика
            print('\n Доступные рецепты по категориям:')
            print(filtered_recipes_df['category_lvl1'].value_counts())

            return None


    # Собираем pipeline
    def plan_day(self, user_dict, exclude_recipe_ids=None):

        user_row = pd.Series(user_dict)

        filtered = self.filter_recipes(user_row)

        if filtered.empty:
            return []

        ranked = self.rank_recipes(user_row, filtered)

        if exclude_recipe_ids:
            exclude_set = set(exclude_recipe_ids)
            ranked = ranked[~ranked["id"].isin(exclude_set)]
        if ranked.empty:
            return []

        tolerances = [0.05, 0.07, 0.1, 0.2, 0.3, 0.5, 0.7]

        for tol in tolerances:
            result = self.optimize_meals(
                ranked,
                target_calories=user_row["target_calories"],
                tolerance=tol,
            )

            if result is not None:
                return result.to_dict(orient="records")

        return []
