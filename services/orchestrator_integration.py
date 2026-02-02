"""
V2.1 Orchestrator Integration - Runtime Patch
Adds V2.1 features to orchestrator without modifying the original file.

Usage: Import this module in main.py BEFORE starting the server:
    from services.orchestrator_integration import activate_v2_1_features
    activate_v2_1_features()
"""

import logging
from typing import Optional
from services.agents.orchestrator import PipelineOrchestrator
from services.patient_stage_service import get_patient_stage_service
from services.stage_service_v2_1 import check_for_safety_triggers

logger = logging.getLogger(__name__)

# Store original method
_original_chat = None


def activate_v2_1_features():
    """Patch the orchestrator to include V2.1 features."""
    global _original_chat
    
    if _original_chat is not None:
        logger.info("V2.1 features already activated")
        return
    
    # Store original
    _original_chat = PipelineOrchestrator.chat
    
    # Create wrapped version
    async def chat_with_v2_1(self, *args, **kwargs):
        """Wrapped chat method with V2.1 enhancements."""
        
        # Extract args
        message = args[0] if args else kwargs.get('message')
        user_id = args[1] if len(args) > 1 else kwargs.get('user_id')
        conversation_id = args[2] if len(args) > 2 else kwargs.get('conversation_id')
        
        # PHASE 0: Safety Pre-Check (V2.1)
        if user_id and message:
            try:
                from services.patient_profile_service import get_patient_profile_service
                profile_service = get_patient_profile_service()
                profile = await profile_service.get_profile(user_id)
                
                if profile:
                    stage_service = get_patient_stage_service()
                    safety_result = check_for_safety_triggers(
                        stage_service,
                        user_message=message,
                        country_code=profile.country_code or "GB"
                    )
                    
                    if safety_result["has_triggers"]:
                        logger.warning(
                            f"[V2.1 Safety] Triggers detected: {safety_result['matched_keywords']}"
                        )
                        # Add to kwargs metadata if exists, or create
                        if 'metadata' not in kwargs:
                            kwargs['metadata'] = {}
                        kwargs['metadata']['safety_triggers'] = safety_result['matched_keywords']
                        kwargs['metadata']['emergency_number'] = safety_result['emergency_number']
                        kwargs['metadata']['urgent_number'] = safety_result['urgent_number']
            
            except Exception as e:
                logger.error(f"[V2.1 Safety] Pre-check failed: {e}")
        
        # Call original method
        result = await _original_chat(self, *args, **kwargs)
        
        # PHASE 1.5: Inject Verification Questions (V2.1)
        # Check if this is a stage confirmation response
        if hasattr(result, 'response') and result.response:
            if "It sounds like you might be in the" in result.response and "Is that correct?" in result.response:
                try:
                    # Extract stage ID from metadata if available
                    stage_id = getattr(result, 'metadata', {}).get('granular_stage_id')
                    if not stage_id and hasattr(self, '_last_inferred_stage_id'):
                        stage_id = self._last_inferred_stage_id
                    
                    if stage_id:
                        stage_service = get_patient_stage_service()
                        stage = stage_service.get_stage_by_id(stage_id)
                        
                        if stage and stage.verification_questions:
                            # Inject first verification question
                            vq = stage.verification_questions[0]
                            # Replace generic question with CSV question
                            result.response = result.response.replace(
                                "Is that correct?",
                                f"{vq}"
                            )
                            logger.info(f"[V2.1 Verification] Injected question for stage {stage_id}")
                
                except Exception as e:
                    logger.error(f"[V2.1 Verification] Question injection failed: {e}")
        
        return result
    
    # Apply patch
    PipelineOrchestrator.chat = chat_with_v2_1
    logger.info("✅ V2.1 features activated in orchestrator")


def deactivate_v2_1_features():
    """Restore original orchestrator behavior."""
    global _original_chat
    
    if _original_chat is not None:
        PipelineOrchestrator.chat = _original_chat
        _original_chat = None
        logger.info("V2.1 features deactivated")
