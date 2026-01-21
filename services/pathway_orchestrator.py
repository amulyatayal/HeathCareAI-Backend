
import logging
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from enum import Enum

from services.patient_profile_service import PatientProfileService
from services.patient_stage_service import PatientStageService
from services.agents.stage_classifier import StageClassifierAgent
from services.agents.stage_classifier import StageClassifierAgent
from models.patient_stages import TreatmentStage
from config.pipeline_config import PatientStage

logger = logging.getLogger(__name__)

class StageUpdateType(Enum):
    EXPLICIT_OVERRIDE = "explicit_override"
    PROPOSAL = "proposal"
    VALIDATION_ERROR = "validation_error"
    NO_CHANGE = "no_change"

@dataclass
class StageUpdateResult:
    update_type: StageUpdateType
    stage_id: Optional[str] = None
    stage_name: Optional[str] = None
    confidence: float = 0.0
    message: str = ""
    error: Optional[str] = None

class PathwayOrchestrator:
    """
    Orchestrates the patient's journey through the clinical pathway graph.
    Enforces the 'One Stage Rule' and manages transition proposals.
    """
    
    def __init__(
        self, 
        profile_service: Optional[PatientProfileService] = None,
        stage_service: Optional[PatientStageService] = None,
        classifier_agent: Optional[StageClassifierAgent] = None
    ):
        self.profile_service = profile_service or PatientProfileService()
        self.stage_service = stage_service or PatientStageService()
        self.classifier_agent = classifier_agent or StageClassifierAgent(stage_service=self.stage_service)

    async def determine_current_stage(
        self,
        patient_id: str,
        user_text: str,
        explicit_stage_id: Optional[str] = None
    ) -> StageUpdateResult:
        """
        Determine the patient's stage based on explicit input OR text inference.
        
        Priority:
        1. Explicit Override (UI Selection) -> Force Update
        2. Text Inference -> Modification Proposal (Requires Confirmation)
        """
        
        # 1. Get Current Profile
        profile = await self.profile_service.get_profile(patient_id)
        if not profile:
             logger.warning(f"PathwayOrchestrator: No profile found for {patient_id}")
             return StageUpdateResult(
                update_type=StageUpdateType.VALIDATION_ERROR,
                error="Patient profile not found"
             )
             
        current_stage_id = profile.detailed_stage_id
        logger.info(f"PathwayOrchestrator: patient={patient_id}, current_stage={current_stage_id}, text='{user_text[:50]}...'")

        
        # 2. Handle Explicit Override
        if explicit_stage_id:
            logger.info(f"Processing EXPLICIT OVERRIDE for patient {patient_id} to stage {explicit_stage_id}")
            
            # Validation: Does stage exist?
            target_stage = self.stage_service.get_stage_by_id(explicit_stage_id)
            if not target_stage:
                return StageUpdateResult(
                    update_type=StageUpdateType.VALIDATION_ERROR,
                    error=f"Invalid stage ID: {explicit_stage_id}"
                )
                
            # Validation: Is transition valid? (Optional: We might allow jumps if explicit)
            # For now, we allow explicit jumps as "corrections", but we could log it.
            
            # Execute Update
            # In a real app, we'd persist this. Mocking persistence access via service.
            # Assuming profile_service has an update method or we modify profile directly and save.
            
            # 1. Update Detailed Stage
            await self.profile_service.update_stage_detailed(patient_id, explicit_stage_id)
            
            # 2. Derive and Update High-Level Stage (to prevent corruption)
            high_level_stage = self._map_stage_id_to_high_level(explicit_stage_id)
            if high_level_stage != PatientStage.UNKNOWN:
                 await self.profile_service.update_stage(patient_id, high_level_stage)
            
            return StageUpdateResult(
                update_type=StageUpdateType.EXPLICIT_OVERRIDE,
                stage_id=explicit_stage_id,
                stage_name=target_stage.name,
                confidence=1.0,
                message=f"Stage updated to {target_stage.name}"
            )

        # 3. Handle Inference
        if user_text:
            # Run classifier with constraint: current_stage_id
            results = await self.classifier_agent.classify(
                user_text, 
                current_stage_id=current_stage_id,
                top_k=1
            )
            
            if not results:
                return StageUpdateResult(update_type=StageUpdateType.NO_CHANGE)
                
            top_stage, score = results[0]
            logger.info(f"PathwayOrchestrator: Top candidate {top_stage.stage_id} ({top_stage.name}) score={score} current={current_stage_id}")
            
            # Threshold Check
            if score > 0.70 and top_stage.stage_id != current_stage_id:
                # We have a high confidence match that is DIFFERENT from current.
                # Return PROPOSAL.
                logger.info(f"Proposing stage change for {patient_id}: {current_stage_id} -> {top_stage.stage_id} (Score: {score})")
                
                return StageUpdateResult(
                    update_type=StageUpdateType.PROPOSAL,
                    stage_id=top_stage.stage_id,
                    stage_name=getattr(top_stage, 'display_name', top_stage.name),
                    confidence=score,
                    message=f"It sounds like you might be in the '{top_stage.name}' stage. Is that correct?"
                )
            
            # FALLBACK: Global Search if constrained search failed to find a good match
            # This handles jump aheads (e.g. from Results directly to Surgery 2.x)
            if score < 0.65:
                logger.info(f"Constrained search score low ({score}). Attempting GLOBAL search.")
                global_results = await self.classifier_agent.classify(
                    user_text,
                    current_stage_id=None, # Global
                    top_k=1
                )
                
                if global_results:
                    g_stage, g_score = global_results[0]
                    logger.info(f"Global search top: {g_stage.stage_id} ({g_stage.name}) score={g_score}")
                    
                    if g_score > 0.25 and g_stage.stage_id != current_stage_id:
                        logger.info(f"Proposing GLOBAL stage change for {patient_id}: {current_stage_id} -> {g_stage.stage_id} (Score: {g_score})")
                        return StageUpdateResult(
                            update_type=StageUpdateType.PROPOSAL,
                            stage_id=g_stage.stage_id,
                            stage_name=getattr(g_stage, 'display_name', g_stage.name),
                            confidence=g_score,
                            message=f"It seems you might be at '{g_stage.name}'. Is that correct?"
                        )
                
        return StageUpdateResult(update_type=StageUpdateType.NO_CHANGE)

    async def get_rag_context(self, patient_id: str) -> str:
        """
        Build the Past/Present/Future context for RAG injection.
        """
        profile = await self.profile_service.get_profile(patient_id)
        if not profile or not profile.current_stage_id:
            return "Patient Stage: Unknown"
            
        current_stage = self.stage_service.get_stage(profile.current_stage_id)
        if not current_stage:
            return "Patient Stage: Unknown ID"
            
        # Build Context
        context = []
        
        # PRESENT
        context.append(f"CURRENT STAGE: {current_stage.name}")
        context.append(f"Description: {current_stage.description}")
        if current_stage.transition_notes:
            context.append(f"Notes: {current_stage.transition_notes}")
            
        # FUTURE (Next likely steps)
        if current_stage.child_stage_ids:
            next_names = [self.stage_service.get_stage(sid).name for sid in current_stage.child_stage_ids if self.stage_service.get_stage(sid)]
            context.append(f"NEXT POSSIBLE STEPS (Drill-down): {', '.join(next_names)}")
        elif current_stage.after_stages:
            next_names = [self.stage_service.get_stage(sid).name for sid in current_stage.after_stages if self.stage_service.get_stage(sid)]
            context.append(f"NEXT POSSIBLE STEPS (Progression): {', '.join(next_names)}")
            
        return "\n".join(context)

    def _map_stage_id_to_high_level(self, stage_id: str) -> PatientStage:
        """
        Map a detailed stage ID (e.g., '1', '2.1.1') to a high-level PatientStage.
        Using simple heuristics based on root ID.
        """
        if not stage_id:
            return PatientStage.UNKNOWN
            
        root_id = stage_id.split('.')[0]
        
        mapping = {
            "0": PatientStage.PRE_DIAGNOSIS,
            "1": PatientStage.NEWLY_DIAGNOSED, # Results Clinic
            "2": PatientStage.ACTIVE_TREATMENT, # Surgery
            "3": PatientStage.ACTIVE_TREATMENT, # Chemo
            "4": PatientStage.ACTIVE_TREATMENT, # Radio
            "5": PatientStage.ACTIVE_TREATMENT, # Targeted
            "6": PatientStage.ACTIVE_TREATMENT, # Hormone
            "7": PatientStage.SURVEILLANCE,     # Follow Up
            "8": PatientStage.PALLIATIVE_SUPPORT,
            "9": PatientStage.PALLIATIVE_SUPPORT
        }
        
        return mapping.get(root_id, PatientStage.UNKNOWN)
