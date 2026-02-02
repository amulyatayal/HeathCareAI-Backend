"""
V2.1 Orchestrator Integration Extensions
Safety pre-check and verification question injection for orchestrator.

Import these functions and call them at the appropriate points in the orchestrator pipeline.
"""

from typing import Dict, Any, Optional, Tuple
import logging

from services.patient_stage_service import get_patient_stage_service
from services.stage_service_v2_1 import check_for_safety_triggers
from models.patient_profile import PatientProfile
from models.schemas import PipelineContext

logger = logging.getLogger(__name__)


def run_phase_0_safety_check(
    message: str,
    profile: Optional[PatientProfile],
    ctx: PipelineContext
) -> Dict[str, Any]:
    """
    PHASE 0: Safety Pre-Check (before classification).
    
    Detects safety triggers in user message and adds to context.
    Does NOT short-circuit pipeline.
    
    Args:
        message: User's message
        profile: Patient profile (if authenticated)
        ctx: Pipeline context to update
    
    Returns:
        Safety result dict with triggers and emergency numbers
    """
    if not profile:
        return {"has_triggers": False, "matched_keywords": []}
    
    try:
        stage_service = get_patient_stage_service()
        safety_result = check_for_safety_triggers(
            stage_service,
            user_message=message,
            country_code=profile.country_code or "GB"
        )
        
        if safety_result["has_triggers"]:
            logger.warning(
                f"Safety triggers detected for user {profile.user_id}: "
                f"{safety_result['matched_keywords']}"
            )
            # Add to context for reasoning agent
            ctx.metadata["safety_triggers"] = safety_result["matched_keywords"]
            ctx.metadata["emergency_number"] = safety_result["emergency_number"]
            ctx.metadata["urgent_number"] = safety_result[" urgent_number"]
        
        return safety_result
    
    except Exception as e:
        logger.error(f"Error in safety pre-check: {e}")
        return {"has_triggers": False, "matched_keywords": []}


def inject_verification_question(
    inferred_stage_id: Optional[str],
    proposed_stage_name: str
) -> Tuple[str, bool]:
    """
    PHASE 1.5: Add verification question to stage confirmation.
    
    Args:
        inferred_stage_id: Stage ID from StageAgentV2 (e.g., "2.1.1")
        proposed_stage_name: Human-readable stage name
    
    Returns:
        Tuple of (confirmation_text, has_question)
    """
    try:
        stage_service = get_patient_stage_service()
        
        # Get stage and verification questions
        if inferred_stage_id:
            stage = stage_service.get_stage_by_id(inferred_stage_id)
            if stage and stage.verification_questions:
                # Use first verification question
                verification_q = stage.verification_questions[0]
                confirmation = (
                    f"It sounds like you might be in the **{proposed_stage_name}** stage.\n\n"
                    f"{verification_q} Is that correct?"
                )
                return confirmation, True
        
        # Fallback to generic confirmation
        confirmation = (
            f"It sounds like you might be in the **{proposed_stage_name}** stage. "
            f"Is that correct?"
        )
        return confirmation, False
    
    except Exception as e:
        logger.error(f"Error injecting verification question: {e}")
        # Fallback
        return (
            f"It sounds like you might be in the **{proposed_stage_name}** stage. "
            f"Is that correct?"
        ), False


# Usage example for orchestrator:
"""
# In orchestrator.py:

from services.orchestrator_v2_1 import run_phase_0_safety_check, inject_verification_question

# PHASE 0: Safety Pre-Check (insert after line ~197)
safety_result = run_phase_0_safety_check(message, profile, ctx)

# PHASE 1.5: Verification Questions (modify stage confirmation response ~line 323)
confirmation_text, has_vq = inject_verification_question(
    inferred_stage_id=inferred_stage_id,
    proposed_stage_name=proposed_name
)

return PipelineResponse(
    response=confirmation_text,
    ...
)
"""
