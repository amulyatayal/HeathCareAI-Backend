"""
Intent Extraction Agent
Classifies user queries into one of 18 intent categories.

Spec Reference: ProjectSpec.md v1.2, Section 6
"""

import logging
from typing import Optional

from services.agents.base_agent import BaseAgent, AgentError
from models.schemas import PipelineContext, IntentResult
from config.pipeline_config import (
    IntentCategory,
    ModelType,
    IntentThresholds,
    INTENT_CATEGORIES
)

logger = logging.getLogger(__name__)


# ================================
# Intent Classification Prompt
# ================================

INTENT_SYSTEM_PROMPT = """You are an intent classification specialist for a breast cancer patient education system.

Your task is to analyze a patient's message and classify it into exactly ONE of the following intent categories:

INTENT CATEGORIES:
1. symptoms - Questions about physical symptoms, what they're experiencing
2. surgery_procedures - Questions about surgical procedures (mastectomy, lumpectomy, reconstruction, lymph node removal)
3. drains_wound_care - Questions about post-surgical drains, wound care, scar management
4. cancer_treatment - Questions about chemotherapy, radiation, hormone therapy, targeted therapy, immunotherapy
5. medication_info - Questions about specific medications, dosing, how to take them
6. side_effects - Questions about treatment side effects and managing them
7. pre_surgery_prehab - Questions about preparing for surgery, prehabilitation exercises
8. post_surgery_recovery - Questions about recovery after surgery, what to expect, mobility
9. follow_up_care - Questions about ongoing monitoring, follow-up appointments after treatment
10. nutrition - Questions about diet, food, recipes, eating during/after treatment
11. exercise - Questions about physical activity, exercise, staying active
12. clothing - Questions about comfortable clothing, bras, prosthetics, adaptive wear
13. emotional_support - Expressions of fear, anxiety, sadness, or need for emotional support
14. diagnosis_testing - Questions about diagnostic tests, biopsies, imaging, blood tests, results
15. admin_logistics - Questions about appointments, insurance, hospital processes, paperwork
16. safety_red_flags - Questions about warning signs, when to seek emergency care
17. statistics - Questions about survival rates, prognosis, research data, statistics
18. unknown - Cannot determine intent or doesn't fit any category

CLASSIFICATION RULES:
- Choose the SINGLE most specific category that matches the primary intent
- If a question touches multiple topics, choose the one that represents the main concern
- "emotional_support" should be chosen when the emotional component is the PRIMARY focus
- "safety_red_flags" should be chosen when asking about urgent/emergency symptoms
- Use "unknown" only when the message is truly ambiguous or off-topic

Respond with a JSON object containing:
{
    "intent": "<category_name>",
    "confidence": <0.0-1.0>,
    "reasoning": "<brief explanation of why this intent was chosen>",
    "clarification_needed": <true/false>,
    "suggested_clarification": "<question to ask if clarification needed, or null>"
}"""


INTENT_USER_TEMPLATE = """Classify the intent of this patient message:

"{message}"

Previous conversation context (if any):
{context}

Respond with JSON only."""


class IntentAgent(BaseAgent):
    """
    Agent that classifies user messages into intent categories.
    
    Uses a fast model (Haiku) for quick classification.
    Returns IntentResult with category, confidence, and optional clarification.
    """
    
    def __init__(self):
        super().__init__(
            name="intent_agent",
            model_type=ModelType.FAST,  # Use Haiku for speed
            timeout_ms=10000  # 10 second timeout
        )
    
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Classify the user's intent.
        
        Args:
            context: Pipeline context with user_message
            
        Returns:
            Updated context with intent_result populated
        """
        logger.info(f"IntentAgent processing: {context.user_message[:100]}...")
        
        # Build context string from conversation history
        history_context = self._build_history_context(context.conversation_history)
        
        # Format the user prompt
        user_prompt = INTENT_USER_TEMPLATE.format(
            message=context.user_message,
            context=history_context if history_context else "No previous context"
        )
        
        try:
            # Call LLM for classification
            result = await self.invoke_llm_with_json(
                system_prompt=INTENT_SYSTEM_PROMPT,
                user_message=user_prompt,
                temperature=0.1,  # Low temperature for consistent classification
                max_tokens=300
            )
            
            # Parse and validate the result
            intent_result = self._parse_result(result)
            
            # Apply confidence-based logic
            intent_result = self._apply_confidence_rules(intent_result)
            
            # Store in context
            context.intent_result = intent_result
            
            logger.info(
                f"Intent classified: {intent_result.intent} "
                f"(confidence: {intent_result.confidence:.2f})"
            )
            
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            # Fallback to unknown with low confidence
            context.intent_result = IntentResult(
                intent=IntentCategory.UNKNOWN,
                confidence=0.0,
                reasoning="Classification failed - using fallback",
                clarification_needed=True,
                suggested_clarification="Could you please rephrase your question?"
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
    
    def _parse_result(self, result: dict) -> IntentResult:
        """Parse LLM response into IntentResult."""
        # Get intent, defaulting to unknown
        intent_str = result.get("intent", "unknown").lower()
        
        # Validate intent is in our list
        try:
            intent = IntentCategory(intent_str)
        except ValueError:
            logger.warning(f"Invalid intent returned: {intent_str}, using unknown")
            intent = IntentCategory.UNKNOWN
        
        # Get confidence, clamping to valid range
        confidence = float(result.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
        
        return IntentResult(
            intent=intent,
            confidence=confidence,
            reasoning=result.get("reasoning"),
            clarification_needed=result.get("clarification_needed", False),
            suggested_clarification=result.get("suggested_clarification")
        )
    
    def _apply_confidence_rules(self, result: IntentResult) -> IntentResult:
        """Apply confidence threshold rules from spec."""
        
        # Below clarification threshold → always ask for clarification
        if result.confidence < IntentThresholds.CLARIFICATION_REQUIRED:
            result.clarification_needed = True
            if not result.suggested_clarification:
                result.suggested_clarification = (
                    "I want to make sure I understand your question correctly. "
                    "Could you tell me a bit more about what you'd like to know?"
                )
        
        # For unknown intent, always suggest clarification
        if result.intent == IntentCategory.UNKNOWN:
            result.clarification_needed = True
            if not result.suggested_clarification:
                result.suggested_clarification = (
                    "I'm not sure I understood your question. "
                    "Are you asking about symptoms, treatment, nutrition, or something else?"
                )
        
        return result
    
    def _get_output_summary(self, context: PipelineContext) -> Optional[str]:
        """Generate output summary for logging."""
        if context.intent_result:
            return f"intent={context.intent_result.intent}, conf={context.intent_result.confidence:.2f}"
        return None

