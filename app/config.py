import os

AUTH_URL = os.environ.get("AUTH_URL", "http://auth-service:8080")
USER_URL = os.environ.get("USER_URL", "http://user-service:8080")
MEAL_URL = os.environ.get("MEAL_URL", "http://meal-service:8080")
MEAL_PLAN_URL = os.environ.get("MEAL_PLAN_URL", "http://meal-plan-service:8080")

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")
SERVICE_API_KEY = os.environ.get("SERVICE_API_KEY", "default-service-secret-key")

TOPIC_GENERATE_COMMAND = "generate.mealplan.command"
TOPIC_REPLACE_COMMAND = "replace.mealplan.command"
TOPIC_JOB_UPDATED = "job.updated.event"

ALLERGEN_KEY_TO_DISH_NAME: dict[str, str] = {
    "dairy":        "Белок коровьего молока",
    "gluten":       "Злаки, содержащие глютен",
    "egg":          "Яйцо",
    "fish":         "Рыба",
    "celery":       "Сельдерей",
    "soy":          "Соя",
    "foodAdditives":"Пищевые добавки",
    "mustard":      "Горчица",
    "nuts":         "Орехи",
    "strawberry":   "Клубника",
    "sesame":       "Кунжут",
    "peanut":       "Арахис",
    "crustaceans":  "Ракообразные",
    "molluscs":     "Моллюски",
}

ALLERGEN_DISH_NAMES = list(ALLERGEN_KEY_TO_DISH_NAME.values())

CUISINE_TO_FEATURE: dict[str, str] = {
    "азиатская":    "asian",
    "европейская":  "european",
    "восточная":    "eastern",
    "славянская":   "slavic",
    "американская": "american",
    "мексиканская": "mexican",
}

CUISINE_FEATURES = ["asian", "european", "eastern", "slavic", "american", "mexican"]

PRODUCT_FEATURES = [
    "рыба", "морепродукты", "свинина", "говядина", "курица",
    "сыр", "картофель", "лук", "чеснок", "помидоры",
    "печень", "молоко", "творог", "оливки", "сельдерей",
    "кинза", "тыква", "баклажан", "орехи",
]

# User preference key → product feature name mapping
INGREDIENT_KEY_TO_FEATURE: dict[str, str] = {
    "fish":          "рыба",
    "seafood":       "морепродукты",
    "pork":          "свинина",
    "beef":          "говядина",
    "chicken":       "курица",
    "cheese":        "сыр",
    "potato":        "картофель",
    "onion":         "лук",
    "garlic":        "чеснок",
    "tomatoes":      "помидоры",
    "liver":         "печень",
    "milk":          "молоко",
    "cottageCheese": "творог",
    "olives":        "оливки",
    "celery":        "сельдерей",
    "cilantro":      "кинза",
    "pumpkin":       "тыква",
    "eggplant":      "баклажан",
    "nuts":          "орехи",
}

# Keywords to detect each product in an ingredient string
PRODUCT_KEYWORDS: dict[str, list[str]] = {
    "рыба":         ["рыб", "форел", "сёмг", "семг", "лосос", "окун", "хек", "треск", "судак", "карп", "тунец", "палтус"],
    "морепродукты": ["краб", "крев", "кальмар", "осьминог", "мидий", "устриц", "морепродукт", "гребешок"],
    "свинина":      ["свин", "окорок", "карбонад", "ветчин", "сало", "бекон", "рёбра"],
    "говядина":     ["говядин", "телятин", "говяж", "стейк"],
    "курица":       ["куриц", "курин", "бройлер", "цыплен"],
    "сыр":          ["сыр", "пармезан", "моцарелл", "рикотт", "фет", "маскарпон", "грюйер", "чеддер"],
    "картофель":    ["картофел", "картошк"],
    "лук":          ["репчат", "лук реп", "лук зел", "шалот", "лук-шалот", " лук "],
    "чеснок":       ["чеснок"],
    "помидоры":     ["томат", "помидор"],
    "печень":       ["печен"],
    "молоко":       ["молок", "сливк", "кефир", "сметан"],
    "творог":       ["творог"],
    "оливки":       ["оливк", "маслин"],
    "сельдерей":    ["сельдерей"],
    "кинза":        ["кинза"],
    "тыква":        ["тыкв"],
    "баклажан":     ["баклажан"],
    "орехи":        ["орех", "грецк", "миндал", "кешью", "фундук", "фисташк", "пекан"],
}
