"""
Validator Agent
Applies safety guardrails and ensures response compliance.

Spec Reference: ProjectSpec.md v1.2, Section 9
"""

import re
import logging
from typing import Optional, List, Dict, Any

from services.agents.base_agent import BaseAgent
from models.schemas_pipeline import (
    PipelineContext,
    ValidationResult,
    ValidationFlag
)
from config.pipeline_config import (
    IntentCategory,
    ModelType,
    MEDICAL_DISCLAIMER,
    SAFE_FALLBACK_RESPONSE
)
from config.agent_routing import is_medical_intent

logger = logging.getLogger(__name__)


# ================================
# Validation Rules
# ================================

class ValidationRules:
    """
    Safety and compliance rules for response validation.
    
    Categories:
    - CRITICAL: Must block response entirely
    - HIGH: Must modify response
    - MEDIUM: Should add warning/disclaimer
    - LOW: Informational flag only
    """
    
    # Patterns that indicate potentially dangerous medical advice
    CRITICAL_PATTERNS = [
        # Specific dosage recommendations (but allow general food amounts)
        (r'\b(take|use|inject|apply)\s+\d+\s*(mg|ml|cc|gram|mcg|iu)\b', 
         "specific_dosage", "Response contains specific medication dosage"),
        
        # Telling patient to stop treatment (must be direct advice)
        (r'\b(you\s+should\s+)?(stop|discontinue|quit|cease)\s+(taking\s+)?(your\s+)?(medication|treatment|chemo|chemotherapy|radiation)',
         "stop_treatment", "Response advises stopping medical treatment"),
        
        # Claiming to diagnose (explicit diagnosis statements)
        (r'\b(you\s+have\s+cancer|you\s+definitely\s+have|i\s+can\s+confirm\s+you\s+have|i\s+diagnose)',
         "diagnosis_claim", "Response makes diagnostic claims"),
        
        # Promising cures
        (r'\b(will\s+cure\s+your|guaranteed\s+to\s+cure|100%\s+effective|miracle\s+cure)',
         "cure_promise", "Response promises cures or guaranteed outcomes"),
    ]
    
    # Patterns that need modification/warning
    HIGH_PATTERNS = [
        # Alternative medicine as replacement
        (r'\b(instead\s+of|replace|substitute).{0,30}(chemo|radiation|surgery|treatment)',
         "alt_med_replacement", "Suggests replacing standard treatment with alternatives"),
        
        # Minimizing symptoms that could be serious
        (r'\b(don\'t\s+worry|nothing\s+to\s+worry|probably\s+fine|ignore)',
         "symptom_minimization", "May minimize potentially serious symptoms"),
        
        # Unsupported supplement claims
        (r'\b(supplement|vitamin|herb).{0,30}(cure|treat|fight\s+cancer)',
         "supplement_claim", "Makes unsupported supplement treatment claims"),
    ]
    
    # Patterns that should trigger disclaimer
    MEDIUM_PATTERNS = [
        # Statistics without context
        (r'\b\d+%\s+(survival|chance|probability|risk)',
         "statistics_without_context", "Contains statistics that may need context"),
        
        # Time-based predictions
        (r'\b(will\s+take|expect|within)\s+\d+\s*(days|weeks|months|years)',
         "time_prediction", "Contains specific time predictions"),
    ]
    
    # Required content for certain intents
    REQUIRED_DISCLAIMERS = {
        IntentCategory.MEDICATION_INFO: "Always follow your prescriber's instructions",
        IntentCategory.SIDE_EFFECTS: "Report any concerning symptoms to your care team",
        IntentCategory.SAFETY_RED_FLAGS: "If symptoms are severe, seek immediate medical attention",
        IntentCategory.STATISTICS: "Statistics represent population averages, not individual outcomes",
    }
    
    # Phrases that should be avoided
    BANNED_PHRASES = [
        "i am a doctor",
        "i am a medical professional",
        "i can diagnose",
        "this is medical advice",
        "you should definitely",
        "you must",
        "guaranteed",
        "100% safe",
        "no side effects",
    ]


# ================================
# Validation Prompt for LLM
# ================================

VALIDATOR_SYSTEM_PROMPT = """You are a medical content safety validator for a breast cancer patient education system.

Your task is to review an AI-generated response and check for safety issues.

CHECK FOR THESE ISSUES:

1. CRITICAL (must block):
   - Specific medication dosages or administration instructions
   - Advice to stop prescribed treatments
   - Diagnostic claims ("you have cancer", "this is definitely...")
   - Promises of cures or guaranteed outcomes
   - Recommendations that could cause physical harm

2. HIGH SEVERITY (must modify):
   - Suggesting alternatives INSTEAD OF standard medical care
   - Minimizing symptoms that could be serious
   - Unsubstantiated health claims about supplements/herbs
   - Advice that contradicts standard oncology practice

3. MEDIUM SEVERITY (add context):
   - Statistics without appropriate caveats
   - Time predictions without acknowledging individual variation
   - Emotional content that may need grounding

4. ALSO CHECK:
   - Is there a medical disclaimer if discussing treatments?
   - Are sources cited appropriately?
   - Is the tone empathetic and supportive?
   - Does it encourage consulting healthcare providers?

Respond with JSON:
{
    "is_safe": true/false,
    "critical_issues": ["issue1", ...] or [],
    "high_issues": ["issue1", ...] or [],
    "medium_issues": ["issue1", ...] or [],
    "missing_disclaimer": true/false,
    "suggested_modifications": "Description of needed changes" or null,
    "overall_assessment": "Brief summary"
}"""

VALIDATOR_USER_TEMPLATE = """Review this response for a breast cancer patient:

PATIENT QUESTION: {question}

INTENT CATEGORY: {intent}

AI RESPONSE:
{response}

Validate this response for safety and compliance."""


class ValidatorAgent(BaseAgent):
    """
    Agent that validates responses for safety and compliance.
    
    Applies both rule-based checks and LLM-based review.
    Can modify responses to add disclaimers or flag issues.
    """
    
    def __init__(self, use_llm_validation: bool = True):
        super().__init__(
            name="validator_agent",
            model_type=ModelType.FAST,  # Use Haiku for speed
            timeout_ms=10000  # 10 second timeout
        )
        self.use_llm_validation = use_llm_validation
    
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Validate the reasoning agent's response.
        
        Args:
            context: Pipeline context with reasoning_result
            
        Returns:
            Updated context with validation_result
        """
        logger.info("ValidatorAgent checking response...")
        
        # Skip validation if no response to validate
        if not context.reasoning_result or not context.reasoning_result.response_text:
            context.validation_result = ValidationResult(
                is_safe=True,
                flags=[],
                modified_response=None,
                disclaimer_added=False
            )
            return context
        
        response_text = context.reasoning_result.response_text
        intent = context.intent_result.intent if context.intent_result else IntentCategory.UNKNOWN
        
        # Step 1: Rule-based validation (fast)
        rule_flags = self._apply_rule_checks(response_text, intent)
        
        # Step 2: LLM-based validation (if enabled and no critical rule flags)
        llm_flags = []
        has_critical = any(f.severity == "critical" for f in rule_flags)
        
        if self.use_llm_validation and not has_critical:
            llm_flags = await self._apply_llm_validation(context)
        
        # Combine flags
        all_flags = rule_flags + llm_flags
        
        # Determine if safe
        critical_flags = [f for f in all_flags if f.severity == "critical"]
        high_flags = [f for f in all_flags if f.severity == "high"]
        
        is_safe = len(critical_flags) == 0
        
        # Apply modifications if needed
        modified_response = None
        disclaimer_added = False
        
        if critical_flags:
            # Block response entirely
            modified_response = SAFE_FALLBACK_RESPONSE
            logger.warning(f"Response blocked due to critical issues: {[f.rule_id for f in critical_flags]}")
        
        elif high_flags or self._needs_disclaimer(response_text, intent):
            # Add disclaimer if missing
            modified_response, disclaimer_added = self._add_disclaimer_if_needed(
                response_text, intent
            )
        
        context.validation_result = ValidationResult(
            is_safe=is_safe,
            flags=all_flags,
            modified_response=modified_response,
            disclaimer_added=disclaimer_added
        )
        
        logger.info(
            f"Validation complete: safe={is_safe}, "
            f"flags={len(all_flags)}, modified={modified_response is not None}"
        )
        
        # Update reasoning result if modified
        if modified_response:
            context.reasoning_result.response_text = modified_response
        
        return context
    
    def _apply_rule_checks(
        self,
        response: str,
        intent: IntentCategory
    ) -> List[ValidationFlag]:
        """Apply rule-based pattern matching."""
        flags = []
        response_lower = response.lower()
        
        # Check critical patterns
        for pattern, rule_id, message in ValidationRules.CRITICAL_PATTERNS:
            if re.search(pattern, response_lower):
                flags.append(ValidationFlag(
                    rule_id=rule_id,
                    severity="critical",
                    message=message,
                    suggested_fix="Remove or rephrase this content"
                ))
        
        # Check high severity patterns
        for pattern, rule_id, message in ValidationRules.HIGH_PATTERNS:
            if re.search(pattern, response_lower):
                flags.append(ValidationFlag(
                    rule_id=rule_id,
                    severity="high",
                    message=message,
                    suggested_fix="Add appropriate caveats or remove"
                ))
        
        # Check medium severity patterns
        for pattern, rule_id, message in ValidationRules.MEDIUM_PATTERNS:
            if re.search(pattern, response_lower):
                flags.append(ValidationFlag(
                    rule_id=rule_id,
                    severity="medium",
                    message=message,
                    suggested_fix="Add context or disclaimer"
                ))
        
        # Check banned phrases
        for phrase in ValidationRules.BANNED_PHRASES:
            if phrase in response_lower:
                flags.append(ValidationFlag(
                    rule_id="banned_phrase",
                    severity="high",
                    message=f"Contains banned phrase: '{phrase}'",
                    suggested_fix="Remove this phrase"
                ))
        
        return flags
    
    async def _apply_llm_validation(
        self,
        context: PipelineContext
    ) -> List[ValidationFlag]:
        """Use LLM for deeper content validation."""
        flags = []
        
        try:
            user_prompt = VALIDATOR_USER_TEMPLATE.format(
                question=context.user_message,
                intent=context.intent_result.intent if context.intent_result else "unknown",
                response=context.reasoning_result.response_text
            )
            
            result = await self.invoke_llm_with_json(
                system_prompt=VALIDATOR_SYSTEM_PROMPT,
                user_message=user_prompt,
                temperature=0.1,
                max_tokens=500
            )
            
            # Parse LLM response into flags
            for issue in result.get("critical_issues", []):
                flags.append(ValidationFlag(
                    rule_id="llm_critical",
                    severity="critical",
                    message=issue,
                    suggested_fix=result.get("suggested_modifications")
                ))
            
            for issue in result.get("high_issues", []):
                flags.append(ValidationFlag(
                    rule_id="llm_high",
                    severity="high",
                    message=issue,
                    suggested_fix=result.get("suggested_modifications")
                ))
            
            for issue in result.get("medium_issues", []):
                flags.append(ValidationFlag(
                    rule_id="llm_medium",
                    severity="medium",
                    message=issue
                ))
            
            if result.get("missing_disclaimer"):
                flags.append(ValidationFlag(
                    rule_id="missing_disclaimer",
                    severity="medium",
                    message="Response missing medical disclaimer",
                    suggested_fix="Add standard medical disclaimer"
                ))
                
        except Exception as e:
            logger.warning(f"LLM validation failed: {e}")
            # Continue without LLM validation
        
        return flags
    
    def _needs_disclaimer(self, response: str, intent: IntentCategory) -> bool:
        """Check if response needs a disclaimer added."""
        # Medical intents always need disclaimers
        if is_medical_intent(intent):
            # Check if disclaimer already present
            disclaimer_keywords = [
                "consult", "healthcare", "care team", "doctor",
                "medical advice", "professional", "provider"
            ]
            response_lower = response.lower()
            return not any(kw in response_lower for kw in disclaimer_keywords)
        
        return False
    
    def _add_disclaimer_if_needed(
        self,
        response: str,
        intent: IntentCategory
    ) -> tuple[str, bool]:
        """Add appropriate disclaimer to response if needed."""
        if not self._needs_disclaimer(response, intent):
            return response, False
        
        # Get intent-specific disclaimer if available
        specific_disclaimer = ValidationRules.REQUIRED_DISCLAIMERS.get(intent)
        
        # Build disclaimer
        disclaimer = f"\n\n---\n{MEDICAL_DISCLAIMER}"
        if specific_disclaimer:
            disclaimer = f"\n\n---\n{specific_disclaimer}. {MEDICAL_DISCLAIMER}"
        
        return response + disclaimer, True
    
    def _get_output_summary(self, context: PipelineContext) -> Optional[str]:
        """Generate output summary for logging."""
        if context.validation_result:
            v = context.validation_result
            return (
                f"safe={v.is_safe}, "
                f"flags={len(v.flags)}, "
                f"modified={v.modified_response is not None}"
            )
        return None


# ================================
# Quick Validation Functions
# ================================

def quick_safety_check(response: str) -> bool:
    """
    Perform a quick safety check without LLM.
    Returns True if response passes basic safety checks.
    """
    response_lower = response.lower()
    
    # Check critical patterns
    for pattern, _, _ in ValidationRules.CRITICAL_PATTERNS:
        if re.search(pattern, response_lower):
            return False
    
    # Check banned phrases
    for phrase in ValidationRules.BANNED_PHRASES:
        if phrase in response_lower:
            return False
    
    return True


def sanitize_response(response: str) -> str:
    """
    Apply basic sanitization to a response.
    Removes or replaces potentially problematic content.
    """
    # Remove any HTML tags
    response = re.sub(r'<[^>]+>', '', response)
    
    # Remove potential injection attempts
    response = re.sub(r'\{\{.*?\}\}', '', response)
    response = re.sub(r'\[\[.*?\]\]', '', response)
    
    return response.strip()

