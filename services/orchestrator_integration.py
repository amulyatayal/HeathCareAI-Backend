"""
V2.1 Journey Engine Integration Module

Monkey-patches PipelineOrchestrator to add V2.1 features:
- Granular stage tracking using 41-stage CSV hierarchy  
- Verification questions to confirm stage transitions (multi-question support!)
- Confirmation/rejection detection
- Enhanced safety checks for crisis keywords

Architecture: Runtime patching (not inheritance) to avoid modifying core orchestrator
"""

import logging
import re
from typing import Optional
from services.patient_stage_service import get_patient_stage_service
from config.pipeline_config import PatientStage

logger = logging.getLogger(__name__)


def activate_v2_1_features():
    """
    Activates V2.1 Journey Engine features by monkey-patching the orchestrator.
    Must be called at module level in main.py BEFORE routes are imported.
    """
    from services.agents.orchestrator import PipelineOrchestrator
    
    # Store original process method
    _original_process_func = PipelineOrchestrator.process
    
    async def process_with_v2_1(self, *args, **kwargs):
        """
        V2.1 wrapper around orchestrator.process() that injects verification questions
        and handles user confirmations/rejections.
        
        Execution Flow:
        1. PHASE 0 (Pre-processing): Safety check for crisis keywords
        2. PHASE 1.4: Check if user is responding to previous verification (NEW!)
        3. Call original orchestrator process (classification, retrieval, reasoning)
        4. PHASE 1.5 (Post-processing): If stage confirmation detected, inject verification questions
        """
        logger.info("🔵🔵🔵 V2.1 WRAPPER CALLED! 🔵🔵🔵")
        logger.info(f"V2.1 WRAPPER: args={args}, kwargs keys={list(kwargs.keys())}")
        
        # Preview the message (first 50 chars)
        message = kwargs.get('message', '')
        logger.info(f"V2.1 WRAPPER: message={message[:50]}...")
        
        # PHASE 0: Safety Pre-Check (V2.1)
        # Check for crisis keywords before processing
        if message:
            try:
                from services.safety_service import SafetyService
                safety_service = SafetyService()
                safety_result = await safety_service.check_crisis_keywords(message)
                
                if safety_result.get('has_crisis_keywords'):
                    logger.warning(f"[V2.1 Safety] Crisis keywords detected: {safety_result.get('matched_keywords')}")
                    # Inject crisis info into metadata for orchestrator
                    if 'metadata' not in kwargs:
                        kwargs['metadata'] = {}
                    kwargs['metadata']['crisis_detected'] = True
                    kwargs['metadata']['crisis_keywords'] = safety_result.get('matched_keywords', [])
                    if safety_result.get('urgent_number'):
                        kwargs['metadata']['urgent_number'] = safety_result['urgent_number']
            
            except Exception as e:
                logger.error(f"[V2.1 Safety] Pre-check failed: {e}")
        
        # Call original method (stored as attribute on this function)
        logger.info("V2.1 WRAPPER: About to call original process...")
        result = await process_with_v2_1._original(self, *args, **kwargs)
        logger.info(f"V2.1 WRAPPER: Original returned! Type: {type(result)}, has response: {hasattr(result, 'response')}")
        
        # PHASE 1.4: Check if user is responding to previous verification question (NEW!)
        if hasattr(result, 'metadata') and result.metadata:
            pending_verification = result.metadata.get('verification_asked_for_stage')
            
            if pending_verification:
                logger.info(f"[V2.1] Found pending verification for stage: {pending_verification}")
                message_lower = message.lower() if message else ""
                
                # Check for CONFIRMATION keywords
                confirmation_keywords = ['yes', 'correct', 'confirmed', 'confirm', 'right', 
                                        'exactly', 'yep', 'yeah', "that's right", 'absolutely']
                is_confirmed = any(keyword in message_lower for keyword in confirmation_keywords)
                
                # Check for REJECTION keywords
                rejection_keywords = ['no', 'not right', 'incorrect', 'wrong', 'not correct', 
                                     "that's not", 'nope', 'negative']
                is_rejected = any(keyword in message_lower for keyword in rejection_keywords)
                
                if is_confirmed:
                    logger.info(f"[V2.1] ✅ User CONFIRMED stage {pending_verification}")
                    
                    # Update profile with GRANULAR stage data
                    try:
                        from services.patient_profile_service import get_patient_profile_service
                        from services.profile_service_v2_1 import update_stage_with_metadata
                        
                        profile_service = get_patient_profile_service()
                        stage_service = get_patient_stage_service()
                        
                        user_id = kwargs.get('user_id')
                        if user_id:
                            # Get stage details (both granular and root)
                            stage_obj = stage_service.get_stage_by_id(pending_verification)
                            
                            if stage_obj:
                                # Get ROOT stage name (not generic enum!)
                                root_id = pending_verification.split('.')[0]
                                root_stage = stage_service.get_stage_by_id(root_id)
                                root_name = root_stage.name if root_stage else "Unknown Phase"
                                
                                # Map granular → broad enum (for system categorization)
                                stage_map = {
                                    '0': PatientStage.PRE_DIAGNOSIS,
                                    '1': PatientStage.NEWLY_DIAGNOSED,
                                    '2': PatientStage.ACTIVE_TREATMENT,
                                    '3': PatientStage.ACTIVE_TREATMENT,
                                    '4': PatientStage.ACTIVE_TREATMENT,
                                    '5': PatientStage.SURVEILLANCE,
                                    '6': PatientStage.ACTIVE_TREATMENT,
                                    '7': PatientStage.ACTIVE_TREATMENT,
                                    '8': PatientStage.ACTIVE_TREATMENT,
                                    '9': PatientStage.ACTIVE_TREATMENT,
                                    '10': PatientStage.ACTIVE_TREATMENT,
                                }
                                broad_stage = stage_map.get(root_id, PatientStage.ACTIVE_TREATMENT)
                                
                                # ✅ USE EXISTING V2.1 METHOD! (Not a new method!)
                                await update_stage_with_metadata(
                                    profile_service=profile_service,
                                    user_id=user_id,
                                    new_stage=broad_stage,
                                    new_detailed_stage_id=pending_verification,
                                    metadata={
                                        'source': 'verification',  # Not 'llm_inference'!
                                        'certainty': 'HIGH',  # User confirmed = high certainty
                                        'user_confirmed': True,  # Critical flag
                                        'treatment_type': stage_obj.name,
                                        'transition_notes': 'Confirmed via verification questions'
                                    }
                                )
                                
                                # ✅ ALSO update NEW label field
                                profile = await profile_service.get_profile(user_id)
                                profile.detailed_stage_label = stage_obj.name
                                await profile_service.update_profile(profile)
                                
                                logger.info(
                                    f"[V2.1] ✅ Updated profile: "
                                    f"broad={broad_stage.value}, "
                                    f"detailed_id={pending_verification}, "
                                    f"label={stage_obj.name}"
                                )
                                
                                # Show confirmation with GRANULAR + ROOT NAME
                                # (Root name from JSON - already better than generic enum!)
                                result.response = (
                                    f"✅ Great! I've updated your profile to **{stage_obj.name}** "
                                    f"({root_name}). {result.response}"
                                )
                            
                            # Clear verification state (CRITICAL for loop prevention!)
                            result.metadata['verification_asked_for_stage'] = None
                            
                            return result
                    
                    except Exception as e:
                        logger.error(f"[V2.1] Profile update failed: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                
                elif is_rejected:
                    logger.info(f"[V2.1] ❌ User REJECTED stage {pending_verification}")
                    
                    # Clear verification state to allow re-classification
                    result.metadata['verification_asked_for_stage'] = None
                    
                    # Add acknowledgment to response
                    result.response = "Thanks for letting me know! " + result.response
                    
                    # Re-trigger stage classification on next message
                    # (Orchestrator will naturally re-classify when it sees the correction)
                    
                    return result
        
        # PHASE 1.5: Inject Verification Questions (V2.1) - ENHANCED!
        # Check if this is a stage confirmation response
        if hasattr(result, 'response') and result.response:
            if "It sounds like you might be in the" in result.response and "Is that correct?" in result.response:
                try:
                    logger.info("[V2.1] Pattern matched - stage confirmation detected!")
                    
                    # Extract granular_stage_id from result.metadata (passed from orchestrator)
                    stage_id = None
                    if hasattr(result, 'metadata') and isinstance(result.metadata, dict):
                        stage_id = result.metadata.get('granular_stage_id')
                        if stage_id:
                            logger.info(f"[V2.1] ✅ Found granular_stage_id from metadata: {stage_id}")
                        else:
                            logger.warning("[V2.1] metadata exists but granular_stage_id not found")
                    else:
                        logger.warning("[V2.1] result has no metadata attribute")
                    
                    if stage_id:
                        # Load stage and inject verification questions
                        stage_service = get_patient_stage_service()
                        stage = stage_service.get_stage_by_id(stage_id)
                        
                        if stage and stage.verification_questions:
                            # Format ALL questions (multi-question support!)
                            if len(stage.verification_questions) > 1:
                                # Multiple questions: numbered list
                                formatted_questions = "\n".join(
                                    f"{i+1}. {q}" 
                                    for i, q in enumerate(stage.verification_questions)
                                )
                                vq = f"To confirm, please answer:\n{formatted_questions}"
                                logger.info(f"[V2.1] Formatted {len(stage.verification_questions)} verification questions")
                            else:
                                # Single question: use as-is
                                vq = stage.verification_questions[0]
                                logger.info(f"[V2.1] Using single verification question: {vq[:80]}...")
                            
                            # Replace generic "Is that correct?" with specific questions
                            # IMPORTANT: Create NEW response to avoid Content-Length mismatch
                            modified_response = re.sub(
                                r'Is that correct\?',
                                vq,
                                result.response
                            )
                            
                            # Create new PipelineResponse with modified text
                            from models.schemas import PipelineResponse
                            result = PipelineResponse(
                                response=modified_response,
                                sources=result.sources if hasattr(result, 'sources') else [],
                                intent_category=result.intent_category if hasattr(result, 'intent_category') else None,
                                safety_triggered=result.safety_triggered if hasattr(result, 'safety_triggered') else False,
                                show_sources=result.show_sources if hasattr(result, 'show_sources') else False,
                                onboarding_required=result.onboarding_required if hasattr(result, 'onboarding_required') else False,
                                sign_in_suggestion=result.sign_in_suggestion if hasattr(result, 'sign_in_suggestion') else None,
                                modification_proposal=result.modification_proposal if hasattr(result, 'modification_proposal') else None,
                                metadata=result.metadata if hasattr(result, 'metadata') else {}
                            )
                            
                            # Track that we asked (prevent loops!)
                            result.metadata['verification_asked_for_stage'] = stage_id
                            logger.info(f"[V2.1] Set verification_asked_for_stage = {stage_id}")
                            
                            
                            logger.info(f"[V2.1 SUCCESS] ✅ Injected {len(stage.verification_questions)} verification question(s) for stage {stage_id}")
                        else:
                            if stage:
                                logger.warning(f"[V2.1] Stage {stage_id} found but has NO verification_questions")
                            else:
                                logger.warning(f"[V2.1] Stage {stage_id} not found in service")
                    else:
                        logger.warning("[V2.1] Could not determine granular_stage_id for verification question")
                
                except Exception as e:
                    logger.error(f"[V2.1 Verification] Question injection FAILED: {e}")
                    import traceback
                    logger.error(f"[V2.1 Verification] Traceback:\\n{traceback.format_exc()}")
        
        return result
    
    # Store original as attribute on the wrapper (persists across imports!)
    process_with_v2_1._original = _original_process_func
    logger.info(f"ACTIVATION: Set _original attribute on wrapper")
    
    # Replace class method
    PipelineOrchestrator.process = process_with_v2_1
    logger.info("✅ V2.1 activated - PipelineOrchestrator.process patched successfully")
