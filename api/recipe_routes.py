"""
Recipe Routes
Serves the dashboard recipe flow: diet/allergy config, allergy-filtered meal
suggestions, full recipes, and recipe photos.

All recipe data comes from RecipeService (services/recipe_service.py). This
module owns only the HTTP contract: request validation, paging, and the Pydantic
response models the frontend depends on.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from services.recipe_service import get_recipe_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recipes", tags=["Recipes"])


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
    image: Optional[str] = None  # API path, e.g. /recipes/images/recipe-001.png


class Meal(MealSummary):
    diets: List[str]
    allergens: List[str]
    symptom_support: List[str] = []
    ingredients: List[str]
    steps: List[str]


class SuggestionsResponse(BaseModel):
    meals: List[MealSummary]
    has_more: bool


# ---------------------------------------------------------------------------
# Record -> response mapping (the HTTP contract; kept out of the service)
# ---------------------------------------------------------------------------
def _to_summary(record: dict) -> MealSummary:
    service = get_recipe_service()
    nutrition = record.get("nutrition") or {}
    calories = record.get("calories") or nutrition.get("calories_per_serving") or 0
    return MealSummary(
        id=service.recipe_id(record),
        name=record.get("title") or record.get("name") or "",
        emoji=record.get("emoji") or "🍽️",
        desc=record.get("description") or record.get("desc") or "",
        time=record.get("time") or "",
        calories=int(calories),
        image=service.image_api_path(record),
    )


def _to_meal(record: dict) -> Meal:
    service = get_recipe_service()
    return Meal(
        **_to_summary(record).model_dump(),
        diets=service.diet_tags(record),
        allergens=record.get("allergens") or [],
        symptom_support=(
            record.get("symptom_support") or record.get("side_effect_support") or []
        ),
        ingredients=record.get("ingredients") or [],
        steps=record.get("instructions") or record.get("steps") or [],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/config", response_model=RecipeConfig)
async def get_recipe_config():
    """Diet options and common allergies the recipe flow offers the user."""
    config = get_recipe_service().get_config()
    if not config["diet_options"]:
        raise HTTPException(status_code=500, detail="Recipe data unavailable")
    return RecipeConfig(**config)


@router.get("/suggestions", response_model=SuggestionsResponse)
async def get_suggestions(
    diet: str = Query(..., description="Selected diet preference"),
    allergies: Optional[str] = Query(
        None, description="Comma-separated allergies to exclude"
    ),
    offset: int = Query(0, ge=0, description="How many matches to skip (paging)"),
    limit: int = Query(3, ge=1, le=10),
):
    """A page of `limit` recipes for the diet that avoid every listed allergen.

    The service caches the batch per (diet, allergies), so `offset` stays stable
    across "Show more" calls.
    """
    allergy_list = [a.strip() for a in (allergies or "").split(",") if a.strip()]
    matches = get_recipe_service().suggest(diet, allergy_list)

    page = matches[offset : offset + limit]
    return SuggestionsResponse(
        meals=[_to_summary(record) for record in page],
        has_more=offset + limit < len(matches),
    )


@router.get("/images/{filename}")
async def get_recipe_image(filename: str):
    """Serve a recipe photo from data/recipe/images/ (path-traversal safe)."""
    path = get_recipe_service().image_file(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path)


@router.get("/{meal_id}", response_model=Meal)
async def get_recipe(meal_id: str):
    """Full recipe (ingredients + method) for a chosen meal."""
    record = get_recipe_service().get_recipe(meal_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return _to_meal(record)
