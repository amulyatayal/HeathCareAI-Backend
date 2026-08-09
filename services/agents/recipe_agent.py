"""
Recipe Agent
The chat-pipeline face of the recipe catalogue.

Recipe *data* belongs to RecipeService (services/recipe_service.py); this agent
turns those records into prose for a conversational answer. The dashboard recipe
flow does not go through here — api/recipe_routes.py calls the service directly,
because it wants structured records rather than text.

The agent never invents meals: every recipe it mentions came from the catalogue.

Routing identity (agent type, KB, system prompt) is registered in
``config/agent_routing.py`` under IntentCategory.MEAL_PLANNING.

Note: MEAL_PLANNING is not currently emitted by IntentAgent, so the orchestrator
has no live path to this agent yet. Wiring it up is a routing change, not a
change here. Responses returned through the pipeline are validated by the
orchestrator's ValidatorAgent like any other agent's.
"""

import logging
from typing import Any, Dict, List, Optional

from services.agents.base_agent import BaseAgent
from services.recipe_service import get_recipe_service
from models.schemas import PipelineContext, ReasoningResult
from config.pipeline_config import ModelType
from config.agent_routing import ReasoningAgentType

logger = logging.getLogger(__name__)

# Conversational answers stay short; the dashboard flow is where a patient
# browses a longer list.
CHAT_SUGGESTION_COUNT = 3

DEFAULT_DIET = "vegetarian"


class RecipeAgent(BaseAgent):
    """Renders catalogue recipes as a chat answer."""

    def __init__(self) -> None:
        super().__init__(
            name="recipe_agent",
            model_type=ModelType.FAST,
            timeout_ms=12000,
        )
        self._recipes = get_recipe_service()

    async def execute(self, context: PipelineContext) -> PipelineContext:
        """Read diet/allergies from metadata, write prose into reasoning_result
        so the orchestrator and validator handle it like any reasoning agent."""
        metadata = context.metadata or {}
        diet = metadata.get("recipe_diet") or DEFAULT_DIET
        allergies = metadata.get("recipe_allergies") or []

        recipes = self._recipes.suggest(diet, allergies, count=CHAT_SUGGESTION_COUNT)
        context.reasoning_result = ReasoningResult(
            response_text=self._render(recipes, diet),
            citations=[],
            abstained=not recipes,
            confidence=0.8 if recipes else 0.0,
            agent_type=ReasoningAgentType.RECIPE.value,
        )
        return context

    @staticmethod
    def _render(recipes: List[Dict[str, Any]], diet: str) -> str:
        """Flatten catalogue records into a readable answer."""
        if not recipes:
            return "No suitable meals were found for these preferences."

        parts = [f"Here are some {diet} meal ideas:"]
        for record in recipes:
            title = record.get("title") or record.get("name", "")
            desc = record.get("description") or record.get("desc", "")
            steps = record.get("instructions") or record.get("steps", [])
            parts.append(
                f"\n**{title}** — {desc}\n"
                f"Ingredients: {', '.join(record.get('ingredients', []))}\n"
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
