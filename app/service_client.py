import logging
import threading
import time
from typing import Optional

import requests

from app.config import (
    AUTH_URL, USER_URL, MEAL_URL, MEAL_PLAN_URL, SERVICE_API_KEY,
)

logger = logging.getLogger(__name__)

_token: Optional[str] = None
_token_lock = threading.Lock()
_token_expires_at: float = 0.0
_TOKEN_TTL_SECONDS = 800  # refresh before 15-min expiry


def _fetch_token() -> str:
    resp = requests.post(
        f"{AUTH_URL}/api/v1/auth/service/token",
        json={"apiKey": SERVICE_API_KEY},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["accessToken"]


def get_service_token() -> str:
    global _token, _token_expires_at
    with _token_lock:
        if _token is None or time.time() >= _token_expires_at:
            logger.info("Fetching new service token")
            _token = _fetch_token()
            _token_expires_at = time.time() + _TOKEN_TTL_SECONDS
        return _token


def _auth_header() -> dict:
    return {"Authorization": f"Bearer {get_service_token()}"}


def get_user_meal_profile(user_id: str) -> dict:
    resp = requests.get(
        f"{USER_URL}/api/v1/internal/users/{user_id}/meal-profile",
        headers=_auth_header(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_all_dishes(page_size: int = 500) -> list[dict]:
    dishes = []
    page = 0
    while True:
        resp = requests.get(
            f"{MEAL_URL}/api/v1/dishes",
            params={"page": page, "size": page_size},
            headers=_auth_header(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", [])
        dishes.extend(content)
        if data.get("last", True):
            break
        page += 1
    logger.info("Fetched %d dishes from meal-service", len(dishes))
    return dishes


def get_user_dish_ids(user_id: str) -> list[int]:
    resp = requests.get(
        f"{MEAL_PLAN_URL}/api/v1/internal/meal-plans/by-user/{user_id}/dish-ids",
        headers=_auth_header(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def create_meal_plan(user_id: str, date: str, items: list[dict]) -> dict:
    resp = requests.post(
        f"{MEAL_PLAN_URL}/api/v1/meal-plans",
        json={"userId": user_id, "date": date, "items": items},
        headers=_auth_header(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def replace_meal_plan_item(meal_plan_id: str, slot: str, dish_id: int, dish_name: str, calories: float) -> dict:
    resp = requests.patch(
        f"{MEAL_PLAN_URL}/api/v1/internal/meal-plans/{meal_plan_id}/items/{slot}",
        json={"dishId": dish_id, "dishName": dish_name, "calories": calories},
        headers=_auth_header(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def create_dish(payload: dict) -> dict:
    """
    POST a new dish into the meal-service catalog under the service token.
    Used to persist LLM-generated recipes so they receive a stable DB-side id
    (the backend allocates a unique negative id when payload['id'] is null)
    and become available to other services through the normal /api/v1/dishes API.

    The caller is responsible for providing payload fields that match
    CreateDishRequest: title, mealType, calories, ingredients, allergens, recipe etc.
    """
    resp = requests.post(
        f"{MEAL_URL}/api/v1/dishes",
        json=payload,
        headers=_auth_header(),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()
