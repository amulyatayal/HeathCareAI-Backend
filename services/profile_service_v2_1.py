"""
V2.1 Enhanced Profile Service Methods
Extension methods for PatientProfileService with metadata tracking.
"""

from typing import Optional, Dict
from datetime import datetime
import logging

from models.patient_profile import PatientProfile, PatientStageHistory
from config.pipeline_config import PatientStage

logger = logging.getLogger(__name__)


async def update_stage_with_metadata(
    profile_service,
    user_id: str,
    new_stage: PatientStage,
    new_detailed_stage_id: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> PatientProfile:
    """
    Enhanced stage update with transition metadata for V2.1.
    
    Args:
        profile_service: PatientProfileService instance
        user_id: Firebase UID
        new_stage: New patient stage
        new_detailed_stage_id: Detailed stage ID (e.g., '2.1.1')
        metadata: {
            'source': 'llm_inference' | 'verification' | 'manual_update',
            'certainty': 'HIGH' | 'MEDIUM' | 'LOW',
            'signals': List[str] - Evidence from LLM,
            'was_regression': bool,
            'regression_type': 'recurrence' | 'new_primary' | None,
            'user_confirmed': bool,
            'treatment_type': str,
            'transition_notes': str
        }
    
    Returns:
        Updated PatientProfile with enhanced history
    """
    profile = await profile_service.get_profile(user_id)
    if not profile:
        raise ValueError(f"Profile not found for user {user_id}")
    
    now = datetime.utcnow()
    old_stage = profile.current_stage
    old_detailed_id = profile.detailed_stage_id
    
    metadata = metadata or {}
    
    # Skip if same stage (unless metadata indicates regression)
    if old_stage == new_stage and not metadata.get('was_regression'):
        logger.info(f"Stage unchanged for user {user_id}: {new_stage}")
        return profile
    
    # Update profile
    profile.current_stage = new_stage
    profile.stage_updated_at = now
    profile.updated_at = now
    
    if new_detailed_stage_id:
        profile.detailed_stage_id = new_detailed_stage_id
        profile.detailed_stage_updated_at = now
    
    # Update stage certainty
    if metadata.get('certainty'):
        profile.current_stage_certainty = metadata['certainty']
        profile.detailed_stage_certainty = metadata['certainty']
    
    # Track regression if detected
    if metadata.get('was_regression'):
        profile.is_regression_detected = True
        if metadata.get('regression_type') == 'recurrence':
            profile.has_recurrence = True
            profile.recurrence_date = now
    
    # Track verification
    if metadata.get('user_confirmed'):
        profile.last_verification_at = now
    
    # Create enhanced history entry
    history_entry = PatientStageHistory(
        timestamp=now,
        from_stage=old_stage,
        to_stage=new_stage,
        source=metadata.get('source', 'manual_update'),
        inference_certainty=metadata.get('certainty'),
        inference_signals=metadata.get('signals', []),
        user_confirmed=metadata.get('user_confirmed', False),
        from_detailed_stage_id=old_detailed_id,
        to_detailed_stage_id=new_detailed_stage_id,
        treatment_type=metadata.get('treatment_type'),
        transition_notes=metadata.get('transition_notes'),
        was_regression=metadata.get('was_regression', False)
    )
    
    profile.stage_history.append(history_entry)
    
    try:
        profile_service.table.put_item(Item=profile.to_dynamodb_item())
        logger.info(
            f"Updated stage for user {user_id}: {old_stage} -> {new_stage} "
            f"(detailed: {old_detailed_id} -> {new_detailed_stage_id}, "
            f"source: {metadata.get('source')}, regression: {metadata.get('was_regression')})"
        )
        return profile
    except Exception as e:
        logger.error(f"Error updating stage with metadata for {user_id}: {e}")
        raise
