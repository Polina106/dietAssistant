import json
import pandas as pd
from IPython.display import display
from app.planner import MealPlanner


# 1. Загружаем рецепты
recipes_df = pd.read_json(path_or_buf='app/data/recipes.jsonl', lines=True)

print(pd.DataFrame(recipes_df)[:5])

recipes_df = pd.DataFrame(recipes_df)


# 2. Загружаем пользователей
users_data = pd.read_json(path_or_buf='app/data/users.jsonl', lines=True)

print(pd.DataFrame(users_data)[:5])

first_user = users_data.iloc[0]


# 3. Создаём planner
planner = MealPlanner(
    recipes_df=recipes_df,
    allergens=[
        'Белок коровьего молока', 'Злаки, содержащие глютен', 'Яйцо',
        'Рыба', 'Сельдерей', 'Соя', 'Пищевые добавки', 'Горчица',
        'Орехи', 'Клубника', 'Кунжут', 'Арахис', 'Ракообразные', 'Моллюски'
    ],
    cont_features=[
        'asian','european','eastern',
        'slavic','america','mexica'
    ],
    product_features=[
       'рыба','морепродукты','свинина','говядина','курица','сыр',
        'картофель','лук','чеснок','помидоры','печень','молоко','творог',
        'оливки','сельдерей','кинза','тыква','баклажан','орехи'
    ]
)


# 4. Запускаем pipeline
result = planner.plan_day(first_user)

print("Результат:")
display(result)
