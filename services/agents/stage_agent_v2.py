import json
import logging
from typing import Any, Dict, List, Optional

from services.agents.base_agent import BaseAgent
from services.patient_stage_service import PatientStageService
from models.schemas import PipelineContext, StageResult
from config.pipeline_config import ModelType, PatientStage, CertaintyLevel, IntentCategory
from config.user_data_config import (
    USER_PROFILE_JSON_PATH,
    FIELD_DEFINITIONS,
    get_mandatory_field_rules_for_intent,
)
from services.mandatory_followup_context import parse_weight_kg as parse_weight_kg_shared

logger = logging.getLogger(__name__)


class StageAgentV2(BaseAgent):
    """
    LLM-based Stage Classifier (ProjectSpec.md Section 7).

    Also loads and validates mandatory user profile fields (e.g. weight) from
    the nutrition dataset JSON, merges message-extracted values, and may set
    should_abort with user_data_clarification_message when required data is missing.
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

    async def _apply_user_profile_data(self, context: PipelineContext) -> None:
        """
        Merge mandatory fields from (in order of increasing precedence):
        1) Nutrition JSON file (demo / fallback)
        2) DynamoDB patient profile (explicit_data), when signed-in
        3) Current user message (parsed)

        If still missing after merge → should_abort + ask user.
        If the user message supplied new values and user is signed-in → persist to DynamoDB.

        Mandatory fields depend on Intent Agent output (see config/user_data_config.py).
        """
        # Intent is str when IntentResult uses use_enum_values=True
        raw_intent = context.intent_result.intent if context.intent_result else None
        mandatory_rules = get_mandatory_field_rules_for_intent(raw_intent)
        context.metadata["mandatory_field_keys_for_intent"] = list(mandatory_rules.keys())
        if raw_intent is None:
            context.metadata["intent_for_mandatory_fields"] = IntentCategory.UNKNOWN.value
        elif isinstance(raw_intent, str):
            context.metadata["intent_for_mandatory_fields"] = raw_intent
        else:
            context.metadata["intent_for_mandatory_fields"] = raw_intent.value

        user_key = self._user_data_lookup_key(context)

        json_user_data = self._load_user_data_from_json(user_key=user_key)
        db_user_data = await self._load_user_data_from_db(context)
        # After a mandatory-field prompt, weight may be only in supplemental_user_message
        extraction_text = (
            context.metadata.get("supplemental_user_message") or context.user_message or ""
        ).strip()
        extracted_user_data = self._extract_user_data_from_message(extraction_text)

        # JSON < DB < message (last wins)
        merged_user_data: Dict[str, Any] = {
            **json_user_data,
            **db_user_data,
            **extracted_user_data,
        }

        missing_fields: List[str] = []
        for field_key, rules in mandatory_rules.items():
            value = merged_user_data.get(field_key)
            if not self._is_valid_field_value(field_key, value, rules):
                missing_fields.append(field_key)

        context.metadata["user_data"] = merged_user_data

        # Persist only validated values the user explicitly typed this turn (signed-in users)
        to_persist: Dict[str, Any] = {}
        for key, val in extracted_user_data.items():
            if key not in FIELD_DEFINITIONS:
                continue
            if self._is_valid_field_value(key, val, FIELD_DEFINITIONS[key]):
                to_persist[key] = val
        if to_persist and not context.metadata.get("is_guest", True) and context.user_id:
            await self._persist_mandatory_fields_to_db(context.user_id, to_persist)

        if missing_fields:
            context.should_abort = True
            context.abort_reason = "user_data_missing"
            context.metadata["user_data_missing_fields"] = missing_fields
            context.metadata["user_data_clarification_message"] = self._build_missing_fields_prompt(
                missing_fields, mandatory_rules
            )

    async def _load_user_data_from_db(self, context: PipelineContext) -> Dict[str, Any]:
        """
        Load user data from PatientProfiles and PatientBioMarkers (DynamoDB).

        From profile: weight (mandatory pipeline field).
        From biomarkers: latest measurements (height, weight, BMI, waist, grip strength).
        """
        if context.metadata.get("is_guest", True):
            return {}
        uid = context.user_id
        if not uid:
            return {}

        out: Dict[str, Any] = {}

        # --- Patient Profile ---
        try:
            from services.patient_profile_service import get_patient_profile_service

            profile = await get_patient_profile_service().get_profile(uid)
            if profile and profile.explicit_data:
                ed = profile.explicit_data

                if ed.weight_kg is not None:
                    rules = FIELD_DEFINITIONS.get("weight", {})
                    if self._is_valid_field_value("weight", ed.weight_kg, rules):
                        out["weight"] = float(ed.weight_kg)
        except Exception as e:
            logger.warning(f"Failed to load profile data from DB: {e}")

        # --- Patient Biomarkers (latest dynamic measurements) ---
        try:
            from services.patient_biomarkers_service import get_patient_biomarkers_service

            biomarker_result = await get_patient_biomarkers_service().list_entries(uid, limit=1)
            entries = biomarker_result.get("entries", [])
            if entries:
                latest = entries[0]
                for field in [
                    "height_cm", "weight_kg", "bmi",
                    "waist_circumference_cm", "hand_grip_strength_kg",
                ]:
                    val = latest.get(field)
                    if val is not None:
                        out[field] = val
        except Exception as e:
            logger.warning(f"Failed to load biomarker data from DB: {e}")

        return out

    async def _persist_mandatory_fields_to_db(self, user_id: str, extracted: Dict[str, Any]) -> None:
        """Save chat-derived mandatory fields to DynamoDB."""
        if not extracted:
            return
        try:
            from services.patient_profile_service import get_patient_profile_service

            await get_patient_profile_service().upsert_explicit_mandatory_fields(user_id, extracted)
        except Exception as e:
            logger.warning(f"Failed to persist mandatory fields for user {user_id}: {e}")

    def _user_data_lookup_key(self, context: PipelineContext) -> Optional[str]:
        if context.user_id:
            return context.user_id
        if context.session_id:
            return str(context.session_id)
        return None

    def _load_user_data_from_json(self, user_key: Optional[str]) -> Dict[str, Any]:
        if not user_key:
            return {}

        try:
            if not USER_PROFILE_JSON_PATH.exists():
                logger.info(f"User profile JSON not found: {USER_PROFILE_JSON_PATH}")
                return {}

            raw = json.loads(USER_PROFILE_JSON_PATH.read_text(encoding="utf-8"))
            user_data = self._lookup_user_record(raw, user_key)
            if not user_data:
                return {}

            normalized: Dict[str, Any] = {}
            if user_data.get("weight") is not None:
                normalized["weight"] = user_data.get("weight")
            elif user_data.get("Weight_kg") is not None:
                normalized["weight"] = user_data.get("Weight_kg")

            return normalized
        except Exception as e:
            logger.warning(f"Failed to load user data from JSON: {e}")
            return {}

    def _lookup_user_record(self, raw: Any, user_key: str) -> Optional[Dict[str, Any]]:
        if isinstance(raw, dict):
            row = raw.get(user_key)
            return row if isinstance(row, dict) else None

        if isinstance(raw, list):
            for row in raw:
                if not isinstance(row, dict):
                    continue
                patient_id = str(row.get("Patient_ID", "")).strip()
                if patient_id and patient_id == str(user_key).strip():
                    return row

        return None

    def _extract_user_data_from_message(self, message: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        weight_kg = self._parse_weight_kg(message)
        if weight_kg is not None:
            out["weight"] = weight_kg
        return out

    def _parse_weight_kg(self, message: str) -> Optional[float]:
        return parse_weight_kg_shared(message)

    def _is_valid_field_value(self, field_key: str, value: Any, rules: Dict[str, Any]) -> bool:
        if value is None:
            return False

        try:
            v = float(value)
        except (TypeError, ValueError):
            return False

        min_value = rules.get("min_value")
        max_value = rules.get("max_value")
        if min_value is not None and v < float(min_value):
            return False
        if max_value is not None and v > float(max_value):
            return False

        return True

    def _build_missing_fields_prompt(
        self,
        missing_fields: List[str],
        mandatory_rules: Dict[str, Dict[str, Any]],
    ) -> str:
        prompts: List[str] = []
        for field in missing_fields:
            cfg = mandatory_rules.get(field) or FIELD_DEFINITIONS.get(field, {})
            label = cfg.get("label", field)
            prompt = cfg.get("prompt")
            prompts.append(prompt or f"Please provide your {label}.")

        return "To personalize your recommendations, I need the following information:\n" + "\n".join(
            f"- {p}" for p in prompts
        )

    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        User profile load/validate first, then LLM stage classification (if not aborted).
        """
        await self._apply_user_profile_data(context)
        if context.should_abort and context.abort_reason == "user_data_missing":
            logger.info("StageAgentV2: mandatory user data missing; skipping stage LLM")
            return context

        user_query = context.user_message

        try:
            hierarchy_context = self._get_hierarchy_context()

            history_text = ""
            if context.conversation_history:
                recent_history = context.conversation_history[-3:]
                history_text = "\n".join(
                    [f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" for msg in recent_history]
                )

            system_prompt = (
                "You are an expert breast oncologist assistant. Your task is to infer where the patient "
                "appears to be in their medical journey based on their text and conversation history.\n\n"
                "You must strictly adhere to the following rules:\n"
                "1. Analyze the 'User Query' and 'Conversation History' against the 'Stage Hierarchy'.\n"
                "2. Identify the most specific Stage ID (e.g., '2.1.2') that matches their situation.\n"
                "3. Map this ID to one of the following broad categories: "
                "['pre_diagnosis', 'awaiting_results', 'newly_diagnosed', 'active_treatment', "
                "'post_treatment', 'surveillance', 'palliative_support', 'unknown'].\n"
                "4. Determine certainty: 'high' (>90%), 'medium' (>75%), 'low' (<50%).\n"
                "5. SPECIAL RULE: If the 'Conversation History' shows the Assistant asking if the user is at a specific stage, "
                "and the User replies with positive confirmation (e.g., 'Yes', 'Correct'), you MUST infer that stage with 'high' certainty.\n"
                "6. Extract exact quotes from the user text as 'evidence_snippets'.\n"
                "7. If the user does not provide enough information to infer a stage, set stage='unknown'.\n"
                "8. Output valid JSON only."
            )

            user_prompt = (
                f"<stage_hierarchy>\n{hierarchy_context}\n</stage_hierarchy>\n\n"
                f"<conversation_history>\n{history_text}\n</conversation_history>\n\n"
                f"<user_query>\n{user_query}\n</user_query>\n\n"
                "Classify the stage. Respond with this JSON structure:\n"
                "{\n"
                '  "stage": "granular_id_or_unknown",\n'
                '  "spec_stage": "broad_category_from_list",\n'
                '  "certainty": "high|medium|low",\n'
                '  "evidence_snippets": ["quote1"],\n'
                '  "reasoning": "brief explanation"\n'
                "}"
            )

            result_data = await self.invoke_llm_with_json(
                system_prompt=system_prompt,
                user_message=user_prompt,
                temperature=0.0
            )

            certainty_str = result_data.get("certainty", "low").lower()
            certainty_score = 0.95 if certainty_str == "high" else (0.8 if certainty_str == "medium" else 0.4)

            stage_result = StageResult(
                stage=result_data.get("spec_stage", "unknown"),
                certainty=certainty_str,
                certainty_score=certainty_score,
                signals=result_data.get("evidence_snippets", [])
            )

            context.stage_result = stage_result
            context.metadata["granular_stage_id"] = result_data.get("stage")

            logger.info(f"StageAgentV2 inferred: {context.stage_result.stage} (Granular: {result_data.get('stage')})")
            return context

        except Exception as e:
            logger.error(f"Error in StageAgentV2: {e}")
            context.stage_result = StageResult(
                stage=PatientStage.UNKNOWN,
                certainty=CertaintyLevel.LOW,
                certainty_score=0.0,
                signals=[]
            )
            return context

    def _get_output_summary(self, context: PipelineContext) -> Optional[str]:
        parts: List[str] = []
        if context.metadata and context.metadata.get("user_data"):
            ud = context.metadata["user_data"]
            summary_fields = []
            for key in ["weight", "height_cm", "bmi",
                        "waist_circumference_cm", "hand_grip_strength_kg"]:
                if ud.get(key) is not None:
                    summary_fields.append(f"{key}={ud[key]}")
            if summary_fields:
                parts.append(f"user_data({', '.join(summary_fields)})")
        if context.stage_result:
            parts.append(f"stage={context.stage_result.stage}")
        return ", ".join(parts) if parts else None
