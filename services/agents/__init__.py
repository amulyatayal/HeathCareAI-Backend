"""
Multi-Agent Pipeline - Agents Package
Contains all agent implementations for the patient education system.
"""

from services.agents.base_agent import BaseAgent, AgentError
from services.agents.intent_agent import IntentAgent
from services.patient_stage_service import get_stage_guidelines  # Moved to PatientStageService
from services.agents.retrieval_agent import (
    RetrievalAgent,
    format_chunks_for_prompt,
    get_citations_from_chunks
)
from services.agents.reasoning_agent import (
    ReasoningAgent,
    ReasoningAgentFactory,
    get_reasoning_agent
)
from services.agents.orchestrator import (
    PipelineOrchestrator,
    process_message
)
from services.agents.validator_agent import (
    ValidatorAgent,
    quick_safety_check,
    sanitize_response
)

__all__ = [
    "BaseAgent",
    "AgentError",
    "IntentAgent",
    # StageAgent removed - stage comes from profile
    "get_stage_guidelines",
    "RetrievalAgent",
    "format_chunks_for_prompt",
    "get_citations_from_chunks",
    "ReasoningAgent",
    "ReasoningAgentFactory",
    "get_reasoning_agent",
    "PipelineOrchestrator",
    "process_message",
    "ValidatorAgent",
    "quick_safety_check",
    "sanitize_response",
]

