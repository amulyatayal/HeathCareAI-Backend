import json
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from services.agents.base_agent import BaseAgent
from services.patient_stage_service import PatientStageService
from models.schemas_pipeline import PipelineContext, StageResult, AgentTrace
from config.pipeline_config import ModelType, PATIENT_STAGES

logger = logging.getLogger(__name__)

class StageAgentV2(BaseAgent):
    """
    LLM-based Stage Classifier acting as a pure agent.
    Adheres to ProjectSpec.md Section 7.
    """
    
    def __init__(self, name: str = "stage_classifier"):
        super().__init__(name=name, model_type=ModelType.FAST)
        self.stage_service = PatientStageService()
        self._hierarchy_cache = None

    def _get_hierarchy_context(self) -> str:
        """Loads and formats the stage hierarchy for the prompt context."""
        if not self._hierarchy_cache:
            stages = self.stage_service.get_all_stages()
            simplified_stages = []
            for s in stages:
                stage_data = {
                    "id": s.stage_id,
                    "name": s.name,
                    "description": s.description
                }
                if s.search_terms:
                    stage_data["keywords"] = s.search_terms
                simplified_stages.append(stage_data)
            
            self._hierarchy_cache = json.dumps(simplified_stages, indent=2)
        return self._hierarchy_cache

    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Executes the stage classification logic using an LLM.
        """
        user_query = context.user_message
        
        try:
            hierarchy_context = self._get_hierarchy_context()
            
            # Format history for context
            history_text = ""
            if context.conversation_history:
                # Take last 3 turns to keep context relevant but concise
                recent_history = context.conversation_history[-3:]
                history_text = "\n".join([f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" for msg in recent_history])

            system_prompt = (
                "You are an expert breast oncologist assistant. Your task is to infer where the patient "
                "appears to be in their medical journey based on their text and conversation history.\n\n"
                "You must strictly adhere to the following rules:\n"
                "1. Analyze the 'User Query' and 'Conversation History' against the 'Stage Hierarchy'.\n"
                "2. Identify the most specific Stage ID (e.g., '2.1.2') that matches their situation.\n"
                "3. Map this ID to one of the following broad categories: "
                f"{PATIENT_STAGES}.\n"
                "4. Determine certainty: 'high' (>90%), 'medium' (>75%), 'low' (<50%).\n"
                "5. SPECIAL RULE: If the 'Conversation History' shows the Assistant asking if the user is at a specific stage, "
                "and the User replies with positive confirmation (e.g., 'Yes', 'Correct'), you MUST infer that stage with 'high' certainty.\n"
                "6. Extract exact quotes from the user text as 'evidence_snippets'.\n"
                "7. If the user does not provide enough information to infer a stage, set stage='unknown'.\n"
                "8. TEMPORAL CONTEXT RULES: Pay close attention to the 'Patient Current Stage'. "
                "Use it to disambiguate ambiguous references:\n"
                "   a) CHEMO TIMING: If patient is in 'surgery' or later and mentions chemo, "
                "infer adjuvant chemo (Stage 8), NOT neoadjuvant (Stage 3).\n"
                "   b) SURGERY TIMING: If patient is in any post-surgery stage (adjuvant_chemo, adjuvant_radio, "
                "adjuvant_endocrine, adjuvant_zoledronic, further_surgery, survivorship) and mentions 'surgery', "
                "infer further_surgery (Stage 6), NOT initial surgery (Stage 2) — they already had initial surgery.\n"
                "   c) STAGE CONSISTENCY: If the user's message is broadly consistent with their current stage "
                "(e.g., current=adjuvant_chemo and user asks about chemo side effects), keep the current stage "
                "and set certainty='low'. Only infer a DIFFERENT stage when the user clearly indicates a "
                "TRANSITION (e.g., 'I finished chemo and I'm starting radiotherapy now').\n"
                "9. Output valid JSON only."
            )
            
            # Build patient context section
            current_stage = context.metadata.get("profile_current_stage", "unknown")
            detailed_id = context.metadata.get("profile_detailed_stage_id")
            detailed_label = context.metadata.get("profile_detailed_stage_label")
            patient_context = f"Current stage: {current_stage}"
            if detailed_id:
                patient_context += f" (detailed: {detailed_id}"
                if detailed_label:
                    patient_context += f" - {detailed_label}"
                patient_context += ")"
            
            user_prompt = (
                f"<stage_hierarchy>\n{hierarchy_context}\n</stage_hierarchy>\n\n"
                f"<patient_current_stage>\n{patient_context}\n</patient_current_stage>\n\n"
                f"<conversation_history>\n{history_text}\n</conversation_history>\n\n"
                f"<user_query>\n{user_query}\n</user_query>\n\n"
                "Classify the stage. Respond with this JSON structure:\n"
                "{\n"
                "  \"stage\": \"granular_id_or_unknown\",\n"
                "  \"spec_stage\": \"broad_category_from_list\",\n"
                "  \"certainty\": \"high|medium|low\",\n"
                "  \"evidence_snippets\": [\"quote1\"],\n"
                "  \"reasoning\": \"brief explanation\"\n"
                "}"
            )

            # Use BaseAgent's json helper
            result_data = await self.invoke_llm_with_json(
                system_prompt=system_prompt,
                user_message=user_prompt,
                temperature=0.0
            )
            
            # Map valid certainty strings for schema validation
            certainty_str = result_data.get("certainty", "low").lower()
            certainty_score = 0.95 if certainty_str == "high" else (0.8 if certainty_str == "medium" else 0.4)
            
            # Map Pydantic model to PipelineContext
            stage_result = StageResult(
                stage=result_data.get("spec_stage", "unknown"), # Spec requires broad category in main field
                certainty=certainty_str,
                certainty_score=certainty_score,
                signals=result_data.get("evidence_snippets", [])
            )
            
            context.stage_result = stage_result
            
            # Metadata for granular logic
            context.metadata["granular_stage_id"] = result_data.get("stage")
            
            logger.info(f"StageAgentV2 inferred: {context.stage_result.stage} (Granular: {result_data.get('stage')})")
            return context

        except Exception as e:
            logger.error(f"Error in StageAgentV2: {e}")
            # Fallback per spec
            context.stage_result = StageResult(
                stage="unknown",
                certainty="low",
                certainty_score=0.0,
                signals=[]
            )
            return context
