import json
import logging
import threading

from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import NoBrokersAvailable

from app import service_client
from app.config import (
    KAFKA_BOOTSTRAP,
    TOPIC_GENERATE_COMMAND, TOPIC_REPLACE_COMMAND, TOPIC_JOB_UPDATED,
    ALLERGEN_KEY_TO_DISH_NAME, INGREDIENT_KEY_TO_FEATURE,
)
from app.data_loader import load_recipes
from app.planner import MealPlanner

logger = logging.getLogger(__name__)

# Dishes are loaded once at startup and cached
_dishes_cache: list[dict] = []
_planner: MealPlanner | None = None
_cache_lock = threading.Lock()


def _get_planner() -> MealPlanner:
    global _dishes_cache, _planner
    with _cache_lock:
        if _planner is None:
            logger.info("Loading dishes from meal-service")
            _dishes_cache = service_client.get_all_dishes()
            df = load_recipes(_dishes_cache)
            _planner = MealPlanner(df)
            logger.info("Planner initialised with %d dishes", len(_dishes_cache))
        return _planner


def _build_user_dict(profile: dict) -> dict:
    user: dict = {}

    user["пассивное_время_мин"] = profile.get("passiveCookingTimeMin") or 9999
    user["активное_время_готовки_мин"] = profile.get("activeCookingTimeMin") or 9999
    user["target_calories"] = float(profile.get("targetCalories") or 2000)

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


def _publish_job_updated(producer: KafkaProducer, job_id: str, status: str, message: str) -> None:
    payload = {"jobId": job_id, "status": status, "message": message}
    producer.send(TOPIC_JOB_UPDATED, value=payload)
    producer.flush()
    logger.info("Published job update: jobId=%s status=%s", job_id, status)


def _handle_generate(cmd: dict, producer: KafkaProducer) -> None:
    job_id = cmd["jobId"]
    user_id = cmd["userId"]
    date = cmd["date"]
    logger.info("Handling generate command: jobId=%s userId=%s date=%s", job_id, user_id, date)

    try:
        profile = service_client.get_user_meal_profile(user_id)
        user_dict = _build_user_dict(profile)

        excluded_ids = service_client.get_user_dish_ids(user_id)

        planner = _get_planner()
        result = planner.plan_day(user_dict, exclude_recipe_ids=excluded_ids)

        if not result:
            _publish_job_updated(producer, job_id, "FAILED",
                                 "Не удалось подобрать план питания по заданным параметрам")
            return

        items = [
            {
                "mealSlot": dish["mealType"],
                "dishId": int(dish["id"]),
                "dishName": dish["title"],
                "calories": round(float(dish["calories"]), 2),
            }
            for dish in result
        ]

        service_client.create_meal_plan(user_id, date, items)

        total_cal = sum(float(d["calories"]) for d in result)
        target_cal = user_dict["target_calories"]
        deviation = round((total_cal / target_cal - 1) * 100, 1) if target_cal else 0
        msg = (f"План на {date} создан: {len(result)} блюда, "
               f"{int(total_cal)} ккал (цель {int(target_cal)}, откл. {deviation:+.1f}%)")
        _publish_job_updated(producer, job_id, "COMPLETED", msg)

    except Exception as e:
        logger.exception("Generate failed for job %s", job_id)
        _publish_job_updated(producer, job_id, "FAILED", str(e))


def _handle_replace(cmd: dict, producer: KafkaProducer) -> None:
    job_id = cmd["jobId"]
    user_id = cmd["userId"]
    meal_plan_id = cmd["mealPlanId"]
    meal_slot = cmd["mealSlot"]
    current_dish_id = int(cmd["currentDishId"])
    logger.info("Handling replace command: jobId=%s slot=%s currentDish=%s",
                job_id, meal_slot, current_dish_id)

    try:
        profile = service_client.get_user_meal_profile(user_id)
        user_dict = _build_user_dict(profile)

        exclude_ids = service_client.get_user_dish_ids(user_id)
        if current_dish_id not in exclude_ids:
            exclude_ids.append(current_dish_id)

        # meal_slot matches mealType (BREAKFAST/LUNCH/DINNER)
        planner = _get_planner()
        replacement = planner.find_replacement(user_dict, meal_slot, exclude_ids)

        if replacement is None:
            _publish_job_updated(producer, job_id, "FAILED",
                                 f"Не найдена замена для слота {meal_slot}")
            return

        service_client.replace_meal_plan_item(
            meal_plan_id=meal_plan_id,
            slot=meal_slot,
            dish_id=int(replacement["id"]),
            dish_name=replacement["title"],
            calories=round(float(replacement["calories"]), 2),
        )

        msg = f"Заменено блюдо в слоте {meal_slot}: {replacement['title']}"
        _publish_job_updated(producer, job_id, "COMPLETED", msg)

    except Exception as e:
        logger.exception("Replace failed for job %s", job_id)
        _publish_job_updated(producer, job_id, "FAILED", str(e))


def start_consumer() -> None:
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
    )

    consumer = KafkaConsumer(
        TOPIC_GENERATE_COMMAND,
        TOPIC_REPLACE_COMMAND,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        group_id="diet-assistant",
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )

    logger.info("Kafka consumer started, listening on topics: %s, %s",
                TOPIC_GENERATE_COMMAND, TOPIC_REPLACE_COMMAND)

    for message in consumer:
        try:
            if message.topic == TOPIC_GENERATE_COMMAND:
                _handle_generate(message.value, producer)
            elif message.topic == TOPIC_REPLACE_COMMAND:
                _handle_replace(message.value, producer)
        except Exception:
            logger.exception("Unexpected error processing message from topic %s", message.topic)
