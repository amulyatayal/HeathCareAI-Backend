"""
Recipe Service
Single owner of recipe data for every consumer.

Two callers sit above this service and want different output shapes:

* ``api/recipe_routes.py``       — structured records for the dashboard recipe flow
* ``services/agents/recipe_agent.py`` — the same records rendered as prose for chat

Neither owns the data. This service does: catalogue loading, the OpenSearch
``recipe_catalog`` query and its offline fallback, diet/allergen filtering, id
resolution, and the per-(diet, allergies) batch cache that keeps "Show more"
paging stable.

Source of truth
---------------
``recipes_full.json`` is the recipe catalogue (the parsed UK Diet & Supplementary
recipe book). ``meals.json`` is read for its ``diet_options`` / ``common_allergies``
config blocks only — its eight legacy recipes use a disjoint id space
("paneer-bowl" vs "recipe-001") and are deliberately ignored. Reading recipes
from both files is what previously made a listed recipe unfetchable.

The service never invents recipes. Anything it returns came from the catalogue.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "recipe"
CATALOGUE_FILE = DATA_DIR / "recipes_full.json"
CONFIG_FILE = DATA_DIR / "meals.json"
IMAGES_DIR = DATA_DIR / "images"

ALLOWED_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

# OpenSearch index holding the ingested catalogue (== KnowledgeBase.RECIPE).
# Imported lazily in _query_opensearch to keep config off the import path.
RECIPE_INDEX = "recipe_catalog"

# Upper bound on the batch generated per (diet, allergies) pair. The route pages
# through this batch, so it also caps how far "Show more" can go.
MAX_SUGGESTIONS = 9

# Distinct (diet, allergies) batches held at once. Allergies include free text
# typed by the user, so the key space is unbounded without a cap.
MAX_CACHED_BATCHES = 128

# The UI offers allergy labels ("Eggs") whose casing and plurality differ from
# the book's canonical lowercase singular tags ("egg"). Normalise both sides so
# filtering works regardless of which vocabulary the caller speaks.
_ALLERGEN_ALIASES = {
    "eggs": "egg",
    "tree nuts": "nuts",
    "peanuts": "nuts",
    "milk": "dairy",
    "shell fish": "shellfish",
}

CacheKey = Tuple[str, Tuple[str, ...]]


def _normalise_allergen(value: str) -> str:
    value = (value or "").strip().lower()
    return _ALLERGEN_ALIASES.get(value, value)


class RecipeService:
    """Loads, filters and resolves recipes. No LLM calls, no HTTP concerns."""

    def __init__(self) -> None:
        self._catalogue: Optional[List[Dict[str, Any]]] = None
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self._config: Optional[Dict[str, Any]] = None
        self._batches: Dict[CacheKey, List[Dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Record helpers — tolerate unified and legacy field names in one place
    # ------------------------------------------------------------------
    @staticmethod
    def _pick(record: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        for key in keys:
            value = record.get(key)
            if value not in (None, "", []):
                return value
        return default

    @classmethod
    def recipe_id(cls, record: Dict[str, Any]) -> str:
        return cls._pick(record, "recipe_id", "id", default="")

    @classmethod
    def diet_tags(cls, record: Dict[str, Any]) -> List[str]:
        return cls._pick(record, "dietary_tags", "diets", default=[])

    # ------------------------------------------------------------------
    # Catalogue
    # ------------------------------------------------------------------
    def all_recipes(self) -> List[Dict[str, Any]]:
        """Every recipe in the catalogue, loaded once per process."""
        if self._catalogue is None:
            self._catalogue = self._load_catalogue()
            self._by_id = {
                self.recipe_id(r): r for r in self._catalogue if self.recipe_id(r)
            }
        return self._catalogue

    def _load_catalogue(self) -> List[Dict[str, Any]]:
        try:
            with CATALOGUE_FILE.open(encoding="utf-8") as f:
                recipes = json.load(f).get("recipes") or []
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.error("Recipe catalogue unavailable (%s): %s", CATALOGUE_FILE, exc)
            return []

        if not recipes:
            logger.error("Recipe catalogue %s contains no recipes", CATALOGUE_FILE)
        return recipes

    def get_config(self) -> Dict[str, Any]:
        """Diet options and common allergies offered by the recipe flow."""
        if self._config is None:
            try:
                with CONFIG_FILE.open(encoding="utf-8") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError) as exc:
                logger.error("Recipe config unavailable (%s): %s", CONFIG_FILE, exc)
                data = {}
            self._config = {
                "diet_options": data.get("diet_options", []),
                "common_allergies": data.get("common_allergies", []),
            }
        return self._config

    def get_recipe(self, recipe_id: str) -> Optional[Dict[str, Any]]:
        """Resolve a recipe by id.

        Checks the catalogue first, so an id stays resolvable across restarts and
        across uvicorn workers. Falls back to cached batches only for records that
        exist in OpenSearch but not yet in the local file.
        """
        self.all_recipes()  # ensure the id index is built
        if recipe_id in self._by_id:
            return self._by_id[recipe_id]
        for batch in self._batches.values():
            for record in batch:
                if self.recipe_id(record) == recipe_id:
                    return record
        return None

    # ------------------------------------------------------------------
    # Suggestions
    # ------------------------------------------------------------------
    def suggest(
        self,
        diet: str,
        allergies: Optional[List[str]] = None,
        count: int = MAX_SUGGESTIONS,
    ) -> List[Dict[str, Any]]:
        """Up to `count` recipes matching `diet` and avoiding every allergen.

        The batch is cached per (diet, allergies) so the route's `offset` paging
        stays stable across "Show more" calls.
        """
        diet = (diet or "").strip()
        allergies = [a.strip() for a in (allergies or []) if a.strip()]
        key = self._cache_key(diet, allergies)

        if key not in self._batches:
            self._batches[key] = self._build_batch(diet, allergies, count)
            self._evict_if_needed()
        return self._batches[key]

    @staticmethod
    def _cache_key(diet: str, allergies: List[str]) -> CacheKey:
        """Order- and casing-insensitive: ["Dairy","Nuts"] == ["nuts","dairy"]."""
        return (
            diet.lower(),
            tuple(sorted(_normalise_allergen(a) for a in allergies)),
        )

    def _evict_if_needed(self) -> None:
        """Bound the cache. Dicts preserve insertion order, so this drops the
        oldest batches first."""
        while len(self._batches) > MAX_CACHED_BATCHES:
            self._batches.pop(next(iter(self._batches)))

    def _build_batch(
        self, diet: str, allergies: List[str], count: int
    ) -> List[Dict[str, Any]]:
        if self._opensearch_enabled():
            recipes = self._query_opensearch(diet, allergies, count)
            if recipes:
                return recipes
            logger.info("recipe_catalog empty or unreachable — using local catalogue")
        return self._filter_locally(diet, allergies, count)

    def _filter_locally(
        self, diet: str, allergies: List[str], count: int
    ) -> List[Dict[str, Any]]:
        wanted_diet = diet.lower()
        excluded = {_normalise_allergen(a) for a in allergies}
        matches = [
            r
            for r in self.all_recipes()
            if wanted_diet in [t.lower() for t in self.diet_tags(r)]
            and not (excluded & {_normalise_allergen(a) for a in r.get("allergens", [])})
        ]
        return matches[:count]

    # ------------------------------------------------------------------
    # OpenSearch
    # ------------------------------------------------------------------
    @staticmethod
    def _opensearch_enabled() -> bool:
        """True only when a real endpoint is configured. Unset or still the
        env.example placeholder means serve locally — no network attempt, no
        error logs."""
        try:
            from config.settings import settings

            endpoint = (settings.opensearch_endpoint or "").strip().lower()
        except Exception:  # noqa: BLE001 — missing config is a local-only signal
            return False
        return bool(endpoint) and "your-opensearch-endpoint" not in endpoint

    def _query_opensearch(
        self, diet: str, allergies: List[str], limit: int
    ) -> List[Dict[str, Any]]:
        """Diet must match; excluded allergens must not. Any failure returns []
        so the caller falls back to the local catalogue."""
        wanted_diet = (diet or "").lower()
        excluded = [_normalise_allergen(a) for a in allergies]
        try:
            from config.aws import opensearch  # lazy: keep config off import path

            must: List[Dict[str, Any]] = []
            if wanted_diet:
                must.append({"term": {"dietary_tags": wanted_diet}})
            query: Dict[str, Any] = {"bool": {"must": must or [{"match_all": {}}]}}
            if excluded:
                query["bool"]["must_not"] = [{"terms": {"allergens": excluded}}]

            response = opensearch().search(
                index=RECIPE_INDEX, body={"size": limit, "query": query}
            )
            hits = response.get("hits", {}).get("hits", [])
            return [self._hit_to_recipe(h.get("_source", {})) for h in hits]
        except Exception as exc:  # noqa: BLE001 — fall back to local on any error
            logger.warning("recipe_catalog query failed (%s)", exc)
            return []

    @staticmethod
    def _hit_to_recipe(source: Dict[str, Any]) -> Dict[str, Any]:
        """Map an OpenSearch _source doc onto the catalogue record shape.

        Ingestion writes document_id = recipe_id (scripts/opensearch/ingest_recipes.py),
        so ids stay comparable with the local catalogue.
        """
        record = dict(source)
        record["recipe_id"] = (
            source.get("document_id") or source.get("recipe_id") or source.get("id")
        )
        record.pop("embedding", None)
        return record

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------
    def image_file(self, filename: str) -> Optional[Path]:
        """Resolve a recipe photo to a real file under data/recipe/images/.

        Returns None for path traversal, missing files, and non-image suffixes,
        so the caller has one thing to check rather than three.
        """
        images_root = IMAGES_DIR.resolve()
        path = (IMAGES_DIR / filename).resolve()
        if images_root not in path.parents or not path.is_file():
            return None
        if path.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
            return None
        return path

    @staticmethod
    def image_api_path(record: Dict[str, Any]) -> Optional[str]:
        """Stored as "images/recipe-001.png"; exposed as the path the frontend
        fetches: /recipes/images/recipe-001.png."""
        raw = record.get("image")
        return f"/recipes/{raw.lstrip('/')}" if raw else None

    # ------------------------------------------------------------------
    # Test / ops hook
    # ------------------------------------------------------------------
    def clear_caches(self) -> None:
        """Drop cached catalogue, config and batches. Used by tests to simulate
        a cold process; also lets an operator pick up edited JSON without a
        restart."""
        self._catalogue = None
        self._by_id = {}
        self._config = None
        self._batches = {}


# ================================
# Singleton accessor
# ================================
_recipe_service: Optional[RecipeService] = None


def get_recipe_service() -> RecipeService:
    """Return the shared RecipeService instance."""
    global _recipe_service
    if _recipe_service is None:
        _recipe_service = RecipeService()
    return _recipe_service
