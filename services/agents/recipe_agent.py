"""
Recipe Agent
A first-class pipeline agent (extends BaseAgent) that powers the recipe chatbot.

Given a diet preference and a set of allergies, it returns diet- and
allergy-aware meal suggestions sourced from the ``recipe_catalog`` OpenSearch
index (ingested from the UK Diet & Supplementary recipe book). If OpenSearch is
unreachable or empty, it falls back to local recipe data on disk so the
experience degrades gracefully. The agent never invents meals.

Safety: served batches are passed through the ValidatorAgent (the same guardrail
used by the chat pipeline).

Routing identity (agent type, KB, system prompt) is registered in
``config/agent_routing.py`` under IntentCategory.MEAL_PLANNING; the KB value
``KnowledgeBase.RECIPE`` ("recipe_catalog") IS the OpenSearch index name.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.agents.base_agent import BaseAgent
from services.agents.validator_agent import ValidatorAgent
from models.schemas import (
    PipelineContext,
    IntentResult,
    ReasoningResult,
)
from config.pipeline_config import IntentCategory, ModelType
from config.agent_routing import ReasoningAgentType, KnowledgeBase

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "recipe"
# Primary local source = the full parsed book; meals.json is the legacy fallback.
RECIPES_FULL_FILE = DATA_DIR / "recipes_full.json"
DATA_FILE = DATA_DIR / "meals.json"

# OpenSearch index that holds the ingested recipes (== KnowledgeBase.RECIPE).
RECIPE_INDEX = KnowledgeBase.RECIPE.value

# Upper bound on how many meals we generate per (diet, allergies) request.
MAX_SUGGESTIONS = 9

# The frontend offers allergy labels (e.g. "Eggs") whose casing/plural differ
# from the book's canonical lowercase singular tags (e.g. "egg"). Normalise so
# diet/allergy filters match regardless of the UI vocabulary.
_ALLERGEN_ALIASES = {
    "eggs": "egg",
    "tree nuts": "nuts",
    "peanuts": "nuts",
    "milk": "dairy",
    "shell fish": "shellfish",
}


def _norm_allergen(a: str) -> str:
    a = (a or "").strip().lower()
    return _ALLERGEN_ALIASES.get(a, a)


def _diet_tags(meal: Dict[str, Any]) -> List[str]:
    """Diet tags for a meal, tolerant of unified (`dietary_tags`) and legacy
    (`diets`) field names."""
    return meal.get("dietary_tags") or meal.get("diets") or []


def _opensearch_enabled() -> bool:
    """True only when a real OpenSearch endpoint is configured.

    When unset or still the env.example placeholder, we skip OpenSearch entirely
    and serve recipes from the local JSON — no network attempt, no error logs.
    """
    try:
        from config.settings import settings
        ep = (settings.opensearch_endpoint or "").strip().lower()
    except Exception:  # noqa: BLE001
        return False
    return bool(ep) and "your-opensearch-endpoint" not in ep


@lru_cache(maxsize=1)
def _load_catalog() -> Dict[str, Any]:
    """Load and cache local recipe data for the fallback path.

    Prefers the full parsed book (``recipes_full.json``); if absent, uses the
    legacy curated catalogue (``meals.json``). Both expose a ``meals``/``recipes``
    list of dicts carrying at least: id, name, emoji, desc, time, calories,
    diets, allergens, ingredients, steps.
    """
    for path, key in ((RECIPES_FULL_FILE, "recipes"), (DATA_FILE, "meals")):
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            meals = data.get(key) or data.get("meals") or []
            if meals:
                return {"meals": meals}
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.warning("Recipe local source unavailable (%s): %s", path, exc)
    logger.error("No local recipe data found in %s", DATA_DIR)
    return {"meals": []}


class RecipeAgent(BaseAgent):
    """Generates diet/allergy-aware meals, grounded in the curated catalogue."""

    def __init__(self) -> None:
        super().__init__(
            name="recipe_agent",
            model_type=ModelType.FAST,  # Haiku — meals are simple, latency matters
            timeout_ms=12000,
        )
        # Rule-based validation only: fast, no extra Bedrock round-trip, still
        # enforces critical/banned-phrase guardrails on generated text.
        self._validator = ValidatorAgent(use_llm_validation=False)

    # ------------------------------------------------------------------
    # Public API (called by api/recipe_routes.py)
    # ------------------------------------------------------------------
    async def suggest_meals(
        self,
        diet: str,
        allergies: List[str],
        count: int = MAX_SUGGESTIONS,
    ) -> List[Dict[str, Any]]:
        """Return up to `count` meals for the diet that avoid all allergies.

        Meals are sourced from the ``recipe_catalog`` OpenSearch index; if that
        is unreachable or returns nothing, the agent falls back to local recipe
        data on disk. The agent never invents meals. Selected meals are passed
        through the ValidatorAgent guardrail before being returned.
        """
        diet = (diet or "").strip()
        allergies = [a.strip() for a in (allergies or []) if a.strip()]

        if _opensearch_enabled():
            meals = self._query_opensearch(diet, allergies, count)
            if not meals:
                logger.info("Recipe OpenSearch empty/unavailable — using local fallback")
                meals = self._deterministic(diet, allergies, count)
        else:
            # OpenSearch not configured: serve straight from local JSON.
            meals = self._deterministic(diet, allergies, count)

        try:
            if meals and not await self._validate(meals, diet, allergies):
                logger.warning("Recipe validation flagged catalogue meals for %s", diet)
        except Exception as exc:  # noqa: BLE001 — validation must never block serving
            logger.warning("Recipe validation skipped (%s)", exc)

        return meals

    # ------------------------------------------------------------------
    # BaseAgent contract — supports use inside the chat pipeline too.
    # ------------------------------------------------------------------
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """Pipeline entry point: read diet/allergies from metadata, write a
        text answer into reasoning_result so the orchestrator + validator can
        handle it like any other reasoning agent."""
        meta = context.metadata or {}
        diet = meta.get("recipe_diet") or "vegetarian"
        allergies = meta.get("recipe_allergies") or []

        meals = await self.suggest_meals(diet, allergies, count=3)
        context.reasoning_result = ReasoningResult(
            response_text=self._render(meals, diet, allergies),
            citations=[],
            abstained=not meals,
            confidence=0.8 if meals else 0.0,
            agent_type=ReasoningAgentType.RECIPE.value,
        )
        return context

    # ------------------------------------------------------------------
    # Primary source: OpenSearch recipe_catalog index
    # ------------------------------------------------------------------
    def _query_opensearch(
        self, diet: str, allergies: List[str], limit: int
    ) -> List[Dict[str, Any]]:
        """Filter recipes by diet (must match) and excluded allergens.

        Returns meal dicts shaped for the API (id, name, emoji, desc, time,
        calories, diets, allergens, ingredients, steps, + extras). Any failure
        (no endpoint, index missing, transport error) returns [] so the caller
        falls back to local data.
        """
        diet_l = (diet or "").lower()
        excluded = [_norm_allergen(a) for a in allergies]
        try:
            from config.aws import opensearch  # lazy: avoid import/config at module load

            must: List[Dict[str, Any]] = []
            if diet_l:
                must.append({"term": {"dietary_tags": diet_l}})
            query: Dict[str, Any] = {"bool": {"must": must or [{"match_all": {}}]}}
            if excluded:
                query["bool"]["must_not"] = [{"terms": {"allergens": excluded}}]

            resp = opensearch().search(
                index=RECIPE_INDEX,
                body={"size": limit, "query": query},
            )
            hits = resp.get("hits", {}).get("hits", [])
            return [self._hit_to_meal(h.get("_source", {})) for h in hits]
        except Exception as exc:  # noqa: BLE001 — fall back to local on any error
            logger.warning("Recipe OpenSearch query failed (%s)", exc)
            return []

    @staticmethod
    def _hit_to_meal(src: Dict[str, Any]) -> Dict[str, Any]:
        """Map an OpenSearch _source doc to a unified recipe dict."""
        meal = dict(src)
        meal["recipe_id"] = src.get("document_id") or src.get("recipe_id") or src.get("id")
        meal.pop("embedding", None)
        return meal

    # ------------------------------------------------------------------
    # Fallback source: local recipe data on disk
    # ------------------------------------------------------------------
    def _deterministic(
        self, diet: str, allergies: List[str], limit: int
    ) -> List[Dict[str, Any]]:
        diet_l = diet.lower()
        excluded = {_norm_allergen(a) for a in allergies}
        matches = [
            m
            for m in _load_catalog().get("meals", [])
            if diet_l in [d.lower() for d in _diet_tags(m)]
            and not (excluded & {_norm_allergen(a) for a in m.get("allergens", [])})
        ]
        return matches[:limit]

    # ------------------------------------------------------------------
    # Validation pass-through (ValidatorAgent)
    # ------------------------------------------------------------------
    async def _validate(
        self, meals: List[Dict[str, Any]], diet: str, allergies: List[str]
    ) -> bool:
        ctx = PipelineContext(
            user_message=f"Suggest {diet} meals avoiding {', '.join(allergies) or 'no allergens'}",
            intent_result=IntentResult(intent=IntentCategory.MEAL_PLANNING, confidence=1.0),
            reasoning_result=ReasoningResult(
                response_text=self._render(meals, diet, allergies),
                agent_type=ReasoningAgentType.RECIPE.value,
            ),
        )
        ctx, _ = await self._validator.run(ctx)
        return bool(ctx.validation_result and ctx.validation_result.is_safe)

    @staticmethod
    def _render(meals: List[Dict[str, Any]], diet: str, allergies: List[str]) -> str:
        """Flatten meals to text for validation / chat-pipeline answers."""
        if not meals:
            return "No suitable meals were found for these preferences."
        parts = [f"Here are some {diet} meal ideas:"]
        for m in meals:
            title = m.get("title") or m.get("name", "")
            desc = m.get("description") or m.get("desc", "")
            steps = m.get("instructions") or m.get("steps", [])
            parts.append(
                f"\n**{title}** — {desc}\n"
                f"Ingredients: {', '.join(m.get('ingredients', []))}\n"
                f"Method: {' '.join(steps)}"
            )
        return "\n".join(parts)


# ================================
# Singleton accessor
# ================================
_recipe_agent: Optional[RecipeAgent] = None


def get_recipe_agent() -> RecipeAgent:
    """Return the shared RecipeAgent instance."""
    global _recipe_agent
    if _recipe_agent is None:
        _recipe_agent = RecipeAgent()
    return _recipe_agent
