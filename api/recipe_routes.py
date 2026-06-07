"""
Recipe Routes
Serves the recipe chatbot flow: diet/allergy config, allergy-filtered meal
suggestions, and full recipes. Meal data is sourced from
``data/recipe/meals.json`` so it can be edited without code changes.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.agents.recipe_agent import get_recipe_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recipes", tags=["Recipes"])

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "recipe" / "meals.json"

# Per-(diet, allergies) cache of the full generated batch. Keeps pagination
# stable across "Show more" calls and lets GET /recipes/{id} resolve generated
# meals (which are not in the static catalogue).
_SUGGESTION_CACHE: Dict[Tuple[str, Tuple[str, ...]], List[dict]] = {}
_RECIPE_CACHE: Dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class DietOption(BaseModel):
    value: str
    emoji: str
    desc: str


class RecipeConfig(BaseModel):
    diet_options: List[DietOption]
    common_allergies: List[str]


class MealSummary(BaseModel):
    id: str
    name: str
    emoji: str
    desc: str
    time: str
    calories: int


class Meal(MealSummary):
    diets: List[str]
    allergens: List[str]
    ingredients: List[str]
    steps: List[str]


class SuggestionsResponse(BaseModel):
    meals: List[MealSummary]
    has_more: bool


# ---------------------------------------------------------------------------
# Data loading (cached; the JSON is static at runtime)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _load_data() -> dict:
    try:
        with DATA_FILE.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Recipe data file not found at %s", DATA_FILE)
        raise HTTPException(status_code=500, detail="Recipe data unavailable")
    except json.JSONDecodeError as exc:
        logger.error("Recipe data file is malformed: %s", exc)
        raise HTTPException(status_code=500, detail="Recipe data unavailable")


def _all_meals() -> List[dict]:
    return _load_data().get("meals", [])


# ---------------------------------------------------------------------------
# Mapping: unified recipe record (recipes_full.json / OpenSearch) -> API models.
# Readers stay tolerant of both unified field names and the legacy meals.json
# names, so the frontend contract (MealSummary/Meal) never changes.
# ---------------------------------------------------------------------------
def _pick(m: dict, *keys, default=None):
    for k in keys:
        v = m.get(k)
        if v not in (None, "", []):
            return v
    return default


def _meal_id(m: dict) -> str:
    return _pick(m, "recipe_id", "id", default="")


def _meal_summary(m: dict) -> MealSummary:
    nutrition = m.get("nutrition") or {}
    calories = _pick(m, "calories") or nutrition.get("calories_per_serving") or 0
    return MealSummary(
        id=_meal_id(m),
        name=_pick(m, "title", "name", default=""),
        emoji=_pick(m, "emoji", default="🍽️"),
        desc=_pick(m, "description", "desc", default=""),
        time=_pick(m, "time", default=""),
        calories=int(calories),
    )


def _meal_full(m: dict) -> Meal:
    summary = _meal_summary(m)
    return Meal(
        **summary.model_dump(),
        diets=_pick(m, "dietary_tags", "diets", default=[]),
        allergens=_pick(m, "allergens", default=[]),
        ingredients=_pick(m, "ingredients", default=[]),
        steps=_pick(m, "instructions", "steps", default=[]),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/config", response_model=RecipeConfig)
async def get_recipe_config():
    """Diet options and common allergies the chatbot offers the user."""
    data = _load_data()
    return RecipeConfig(
        diet_options=data.get("diet_options", []),
        common_allergies=data.get("common_allergies", []),
    )


@router.get("/suggestions", response_model=SuggestionsResponse)
async def get_suggestions(
    diet: str = Query(..., description="Selected diet preference"),
    allergies: Optional[str] = Query(
        None, description="Comma-separated allergies to exclude"
    ),
    offset: int = Query(0, ge=0, description="How many matches to skip (paging)"),
    limit: int = Query(3, ge=1, le=10),
):
    """A page of `limit` meals for the diet that avoid every listed allergen.

    The RecipeAgent generates the batch (grounded in the catalogue, validated
    for safety) on first request for a given (diet, allergies) pair; subsequent
    pages are served from the cached batch so `offset` stays stable.
    """
    allergy_list = [a.strip() for a in (allergies or "").split(",") if a.strip()]
    key = (diet.strip().lower(), tuple(sorted(a.lower() for a in allergy_list)))

    meals = _SUGGESTION_CACHE.get(key)
    if meals is None:
        meals = await get_recipe_agent().suggest_meals(diet.strip(), allergy_list)
        _SUGGESTION_CACHE[key] = meals
        for m in meals:
            _RECIPE_CACHE[_meal_id(m)] = m

    page = meals[offset : offset + limit]
    return SuggestionsResponse(
        meals=[_meal_summary(m) for m in page],
        has_more=offset + limit < len(meals),
    )


@router.get("/{meal_id}", response_model=Meal)
async def get_recipe(meal_id: str):
    """Full recipe (ingredients + method) for a chosen meal.

    Resolves from the static catalogue first, then from agent-generated meals
    cached during /suggestions.
    """
    for m in _all_meals():
        if _meal_id(m) == meal_id:
            return _meal_full(m)
    if meal_id in _RECIPE_CACHE:
        return _meal_full(_RECIPE_CACHE[meal_id])
    raise HTTPException(status_code=404, detail="Recipe not found")
