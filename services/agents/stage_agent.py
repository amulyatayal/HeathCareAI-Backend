"""
Patient Stage Identification Agent
Infers the patient's current stage in their medical journey.

Spec Reference: ProjectSpec.md v1.2, Section 7
"""

import logging
from typing import Optional, List

from services.agents.base_agent import BaseAgent, AgentError
from models.schemas import PipelineContext, StageResult
from config.pipeline_config import (
    PatientStage,
    CertaintyLevel,
    ModelType,
    StageThresholds,
    PATIENT_STAGES
)

logger = logging.getLogger(__name__)


# ================================
# Stage Identification Prompt
# ================================

STAGE_SYSTEM_PROMPT = """You are a patient stage identification specialist for a breast cancer education system.

Your task is to infer what stage of their medical journey the patient appears to be in, based on their message and conversation context.

PATIENT STAGES:
1. pre_diagnosis - Hasn't been diagnosed yet, may have concerns or symptoms
2. awaiting_results - Has had tests, waiting for results
3. newly_diagnosed - Recently received diagnosis, processing the news
4. active_treatment - Currently undergoing treatment (surgery, chemo, radiation, etc.)
5. post_treatment - Completed primary treatment, in early recovery
6. surveillance - Long-term follow-up, monitoring for recurrence
7. palliative_support - Focus on comfort and quality of life
8. unknown - Cannot determine stage from available information

SIGNALS TO LOOK FOR:

pre_diagnosis signals:
- "I found a lump", "I'm worried about...", "Should I get checked?"
- No mention of diagnosis or treatment

awaiting_results signals:
- "I had a biopsy", "waiting for results", "the doctor ordered tests"
- Anxiety about upcoming results

newly_diagnosed signals:
- "I was just diagnosed", "I just found out", "the doctor told me I have..."
- Processing shock, asking "what does this mean?"

active_treatment signals:
- "I'm on chemo", "I had surgery last week", "starting radiation"
- Questions about current treatment side effects
- References to ongoing appointments

post_treatment signals:
- "I finished treatment", "my last chemo was...", "recovering from surgery"
- Questions about recovery, returning to normal

surveillance signals:
- "It's been X years since treatment", "my annual checkup"
- Questions about long-term effects, monitoring

palliative_support signals:
- "Managing symptoms", "quality of life", "comfort care"
- Focus on symptom management over cure

CERTAINTY GUIDELINES:
- HIGH (0.9+): Clear, explicit statements about their stage
- MEDIUM (0.75-0.9): Strong contextual clues but not explicit
- LOW (0.5-0.75): Some hints but ambiguous
- If certainty would be below 0.5, use "unknown" stage

Respond with a JSON object containing:
{
    "stage": "<stage_name>",
    "certainty": "<high/medium/low>",
    "certainty_score": <0.0-1.0>,
    "signals": ["<signal 1>", "<signal 2>", ...]
}"""


STAGE_USER_TEMPLATE = """Identify the patient's likely stage based on this message:

"{message}"

Previous conversation context (if any):
{context}

Respond with JSON only."""


class StageAgent(BaseAgent):
    """
    Agent that infers the patient's current treatment stage.
    
    Uses a fast model (Haiku) for quick inference.
    Returns StageResult with stage, certainty level, and supporting signals.
    """
    
    def __init__(self):
        super().__init__(
            name="stage_agent",
            model_type=ModelType.FAST,  # Use Haiku for speed
            timeout_ms=10000  # 10 second timeout
        )
    
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Infer the patient's treatment stage.
        
        Args:
            context: Pipeline context with user_message
            
        Returns:
            Updated context with stage_result populated
        """
        logger.info(f"StageAgent processing: {context.user_message[:100]}...")
        
        # Build context string from conversation history
        history_context = self._build_history_context(context.conversation_history)
        
        # Format the user prompt
        user_prompt = STAGE_USER_TEMPLATE.format(
            message=context.user_message,
            context=history_context if history_context else "No previous context"
        )
        
        try:
            # Call LLM for stage inference
            result = await self.invoke_llm_with_json(
                system_prompt=STAGE_SYSTEM_PROMPT,
                user_message=user_prompt,
                temperature=0.1,  # Low temperature for consistent inference
                max_tokens=300
            )
            
            # Parse and validate the result
            stage_result = self._parse_result(result)
            
            # Apply certainty threshold rules
            stage_result = self._apply_certainty_rules(stage_result)
            
            # Store in context
            context.stage_result = stage_result
            
            logger.info(
                f"Stage inferred: {stage_result.stage} "
                f"(certainty: {stage_result.certainty}, score: {stage_result.certainty_score:.2f})"
            )
            
        except Exception as e:
            logger.error(f"Stage inference failed: {e}")
            # Fallback to unknown with low certainty
            context.stage_result = StageResult(
                stage=PatientStage.UNKNOWN,
                certainty=CertaintyLevel.LOW,
                certainty_score=0.0,
                signals=["Stage inference failed - using fallback"]
            )
        
        return context
    
    def _build_history_context(self, history: list) -> str:
        """Build a summary of recent conversation history."""
        if not history:
            return ""
        
        # Take last 3 exchanges max
        recent = history[-6:] if len(history) > 6 else history
        
        lines = []
        for msg in recent:
            role = msg.get("role", "user")
            content = msg.get("content", "")[:200]  # Truncate long messages
            lines.append(f"{role}: {content}")
        
        return "\n".join(lines)
    
    def _parse_result(self, result: dict) -> StageResult:
        """Parse LLM response into StageResult."""
        # Get stage, defaulting to unknown
        stage_str = result.get("stage", "unknown").lower()
        
        # Validate stage is in our list
        try:
            stage = PatientStage(stage_str)
        except ValueError:
            logger.warning(f"Invalid stage returned: {stage_str}, using unknown")
            stage = PatientStage.UNKNOWN
        
        # Get certainty level
        certainty_str = result.get("certainty", "low").lower()
        try:
            certainty = CertaintyLevel(certainty_str)
        except ValueError:
            certainty = CertaintyLevel.LOW
        
        # Get certainty score, clamping to valid range
        certainty_score = float(result.get("certainty_score", 0.5))
        certainty_score = max(0.0, min(1.0, certainty_score))
        
        # Get signals
        signals = result.get("signals", [])
        if not isinstance(signals, list):
            signals = [str(signals)] if signals else []
        
        return StageResult(
            stage=stage,
            certainty=certainty,
            certainty_score=certainty_score,
            signals=signals
        )
    
    def _apply_certainty_rules(self, result: StageResult) -> StageResult:
        """Apply certainty threshold rules from spec."""
        
        # Very low certainty → force unknown stage
        if result.certainty_score < StageThresholds.LOW:
            result.stage = PatientStage.UNKNOWN
            result.certainty = CertaintyLevel.LOW
            if not result.signals:
                result.signals = ["Insufficient signals to determine stage"]
        
        # Align certainty level with score
        if result.certainty_score >= StageThresholds.HIGH:
            result.certainty = CertaintyLevel.HIGH
        elif result.certainty_score >= StageThresholds.MEDIUM:
            result.certainty = CertaintyLevel.MEDIUM
        else:
            result.certainty = CertaintyLevel.LOW
        
        return result
    
    def _get_output_summary(self, context: PipelineContext) -> Optional[str]:
        """Generate output summary for logging."""
        if context.stage_result:
            return (
                f"stage={context.stage_result.stage}, "
                f"certainty={context.stage_result.certainty}"
            )
        return None


# ================================
# Stage-Aware Response Modifiers
# ================================

STAGE_RESPONSE_GUIDELINES = {
    PatientStage.PRE_DIAGNOSIS: {
        "tone": "reassuring but not dismissive",
        "emphasis": "importance of getting checked, not jumping to conclusions",
        "avoid": "assuming they have cancer, detailed treatment info"
    },
    PatientStage.AWAITING_RESULTS: {
        "tone": "calm and supportive",
        "emphasis": "managing anxiety, what to expect from results",
        "avoid": "speculation about diagnosis, worst-case scenarios"
    },
    PatientStage.NEWLY_DIAGNOSED: {
        "tone": "gentle and empathetic",
        "emphasis": "it's okay to feel overwhelmed, take time to process",
        "avoid": "information overload, statistics without context"
    },
    PatientStage.ACTIVE_TREATMENT: {
        "tone": "practical and encouraging",
        "emphasis": "managing side effects, day-to-day coping",
        "avoid": "minimizing challenges, unrealistic expectations"
    },
    PatientStage.POST_TREATMENT: {
        "tone": "celebratory but realistic",
        "emphasis": "recovery milestones, adjusting to 'new normal'",
        "avoid": "dismissing ongoing concerns, 'you should be grateful'"
    },
    PatientStage.SURVEILLANCE: {
        "tone": "reassuring and informative",
        "emphasis": "importance of follow-ups, living well long-term",
        "avoid": "excessive focus on recurrence anxiety"
    },
    PatientStage.PALLIATIVE_SUPPORT: {
        "tone": "compassionate and dignified",
        "emphasis": "comfort, quality of life, support resources",
        "avoid": "false hope, dismissing their experience"
    },
    PatientStage.UNKNOWN: {
        "tone": "warm and open",
        "emphasis": "general support, asking clarifying questions",
        "avoid": "making assumptions about their situation"
    }
}


def get_stage_guidelines(stage: PatientStage) -> dict:
    """Get response guidelines for a specific patient stage."""
    return STAGE_RESPONSE_GUIDELINES.get(
        stage,
        STAGE_RESPONSE_GUIDELINES[PatientStage.UNKNOWN]
    )

