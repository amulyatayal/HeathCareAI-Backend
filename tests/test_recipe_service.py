"""Unit tests for RecipeService and the recipe routes that sit on top of it.

The regression these guard against: recipe ids must resolve from the catalogue
itself, not from cache state left behind by an earlier /suggestions call. That
state does not survive a restart or a second uvicorn worker.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app
from services.recipe_service import get_recipe_service


@pytest.fixture(autouse=True)
def cold_service():
    """Simulate a freshly started process: no cached suggestion batches."""
    service = get_recipe_service()
    service.clear_caches()
    yield service
    service.clear_caches()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Catalogue + id resolution
# ---------------------------------------------------------------------------
def test_catalogue_loads_the_full_recipe_book(cold_service):
    recipes = cold_service.all_recipes()
    assert len(recipes) > 100, "expected recipes_full.json, not the 8-recipe legacy file"
    assert all(cold_service.recipe_id(r) for r in recipes), "every recipe needs an id"


def test_recipe_resolves_without_a_prior_suggestion_call(cold_service):
    """Regression: this is the restart/second-worker 404.

    Previously /recipes/{id} searched meals.json (ids like 'paneer-bowl') while
    suggestions came from recipes_full.json (ids like 'recipe-001'), so the only
    thing making the detail endpoint work was an in-process dict populated as a
    side effect of /suggestions.
    """
    known_id = cold_service.recipe_id(cold_service.all_recipes()[0])
    assert cold_service.get_recipe(known_id) is not None


def test_unknown_recipe_id_returns_none(cold_service):
    assert cold_service.get_recipe("no-such-recipe") is None


def test_most_of_the_catalogue_has_no_ingredients_or_method(cold_service):
    """Documents a known data gap, not desired behaviour.

    Only the recipes flagged has_full_recipe carry ingredients and instructions;
    the rest are index entries from the book. suggest() does not currently
    distinguish them, so a suggested recipe can open to an empty detail page.
    Pinned here so a change in the ratio is a deliberate decision.
    """
    recipes = cold_service.all_recipes()
    complete = [r for r in recipes if r.get("ingredients") and r.get("instructions")]
    assert len(complete) == 36, "recipe completeness changed — revisit suggest() ranking"
    assert len(recipes) == 310


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def test_suggestions_match_the_requested_diet(cold_service):
    meals = cold_service.suggest("Vegan", [])
    assert meals
    for m in meals:
        assert "vegan" in [t.lower() for t in cold_service.diet_tags(m)]


def test_non_vegetarian_diet_is_matched_despite_ui_casing(cold_service):
    """The UI sends 'Non-Vegetarian'; the book tags 'non-vegetarian'."""
    assert cold_service.suggest("Non-Vegetarian", [])


def test_suggestions_exclude_the_requested_allergens(cold_service):
    meals = cold_service.suggest("Vegetarian", ["Dairy"])
    assert meals
    for m in meals:
        assert "dairy" not in [a.lower() for a in m.get("allergens", [])]


def test_allergen_aliases_are_normalised(cold_service):
    """UI offers 'Eggs'; the book tags 'egg'. Without aliasing this filters nothing."""
    meals = cold_service.suggest("Vegetarian", ["Eggs"])
    assert meals
    for m in meals:
        assert "egg" not in [a.lower() for a in m.get("allergens", [])]


def test_impossible_filter_combination_returns_empty_not_error(cold_service):
    meals = cold_service.suggest("Vegan", ["Dairy", "Nuts", "Gluten", "Soy", "Fish"])
    assert isinstance(meals, list)


# ---------------------------------------------------------------------------
# Pagination stability
# ---------------------------------------------------------------------------
def test_repeated_suggest_calls_return_a_stable_batch(cold_service):
    """'Show more' pages into a fixed batch; the ordering must not shift."""
    first = cold_service.suggest("Vegetarian", [])
    second = cold_service.suggest("Vegetarian", [])
    assert [cold_service.recipe_id(m) for m in first] == [
        cold_service.recipe_id(m) for m in second
    ]


def test_allergy_order_and_casing_hit_the_same_cache_entry(cold_service):
    a = cold_service.suggest("Vegetarian", ["Dairy", "Nuts"])
    b = cold_service.suggest("Vegetarian", ["nuts", "dairy"])
    assert [cold_service.recipe_id(m) for m in a] == [
        cold_service.recipe_id(m) for m in b
    ]


# ---------------------------------------------------------------------------
# Image path safety
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "filename",
    ["../meals.json", "../../config/settings.py", "nope.png", "notanimage.txt"],
)
def test_unsafe_or_missing_image_paths_are_rejected(cold_service, filename):
    assert cold_service.image_file(filename) is None


# ---------------------------------------------------------------------------
# HTTP contract (the frontend depends on these exact shapes)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_config_endpoint_returns_diets_and_allergies(client):
    res = await client.get("/api/v2/recipes/config")
    assert res.status_code == 200
    body = res.json()
    assert body["diet_options"] and body["common_allergies"]
    assert {"value", "emoji", "desc"} <= set(body["diet_options"][0])


@pytest.mark.asyncio
async def test_suggestions_then_detail_round_trip(client):
    """End-to-end version of the regression: every id the list hands out must
    be fetchable, with the full recipe fields the detail view renders."""
    listing = await client.get("/api/v2/recipes/suggestions?diet=Vegetarian&offset=0")
    assert listing.status_code == 200
    meals = listing.json()["meals"]
    assert meals

    for meal in meals:
        detail = await client.get(f"/api/v2/recipes/{meal['id']}")
        assert detail.status_code == 200, f"{meal['id']} was listed but not fetchable"
        body = detail.json()
        assert isinstance(body["ingredients"], list)
        assert isinstance(body["steps"], list)


@pytest.mark.asyncio
async def test_detail_survives_a_cold_cache(client, cold_service):
    """The list and the detail call are separated by a process restart."""
    listing = await client.get("/api/v2/recipes/suggestions?diet=Vegan&offset=0")
    meal_id = listing.json()["meals"][0]["id"]

    cold_service.clear_caches()  # restart / different worker

    detail = await client.get(f"/api/v2/recipes/{meal_id}")
    assert detail.status_code == 200


@pytest.mark.asyncio
async def test_paging_advances_and_reports_has_more(client):
    first = await client.get("/api/v2/recipes/suggestions?diet=Vegan&offset=0&limit=3")
    body = first.json()
    assert len(body["meals"]) == 3
    assert body["has_more"] is True

    second = await client.get("/api/v2/recipes/suggestions?diet=Vegan&offset=3&limit=3")
    assert {m["id"] for m in second.json()["meals"]}.isdisjoint(
        {m["id"] for m in body["meals"]}
    )


@pytest.mark.asyncio
async def test_unknown_recipe_id_404s(client):
    res = await client.get("/api/v2/recipes/no-such-recipe")
    assert res.status_code == 404
