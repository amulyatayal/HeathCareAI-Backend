"""
Patient Stage Service
Loads and manages breast cancer treatment pathway stages.

Stages are loaded from a pre-built JSON file for fast startup.
The JSON is generated from CSV using scripts/build_stage_hierarchy.py.
"""

import json
import csv
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime, timedelta
import uuid

from models.patient_stages import (
    TreatmentStage,
    StageTreeNode,
    PatientProfileGDPR,
    AgeRange,
    hash_email,
    extract_postal_area,
)
from config.pipeline_config import PatientStage

logger = logging.getLogger(__name__)


# ================================
# Stage Data Service
# ================================

class PatientStageService:
    """
    Service for loading and managing breast cancer treatment stages.
    
    Loads stages from pre-built JSON file (generated from CSV).
    Provides hierarchical tree, breadcrumb, and context generation for AI prompts.
    """
    
    def __init__(self, json_path: str = None, csv_path: str = None):
        """
        Initialize the stage service.
        
        Args:
            json_path: Path to pre-built JSON file (primary, fast loading)
            csv_path: Path to CSV file (fallback if JSON missing)
        """
        data_dir = Path(__file__).parent.parent / "data"
        self.json_path = json_path or str(data_dir / "stage_hierarchy.json")
        self.csv_path = csv_path or str(data_dir / "Breast cancer stages" / "Knowledge Base Bank - BreastCancerStagesProcessed.csv")
        
        self._stages: Dict[str, TreatmentStage] = {}
        self._root_stages: List[str] = []
        self._loaded = False
        self._version: Optional[str] = None
        self._generated_at: Optional[str] = None
    
    def _ensure_loaded(self):
        """Ensure stages are loaded."""
        if not self._loaded:
            self._load_stages()
    
    def _load_stages(self) -> int:
        """
        Load stages from JSON (preferred) or CSV (fallback).
        
        Returns:
            Number of stages loaded
        """
        # Try JSON first (fast path)
        json_file = Path(self.json_path)
        if json_file.exists():
            return self._load_from_json()
        
        # Fallback to CSV with warning
        logger.warning(
            f"JSON file not found: {self.json_path}. "
            f"Falling back to CSV parsing. Run 'python scripts/build_stage_hierarchy.py' to generate JSON."
        )
        return self._load_from_csv()
    
    def _load_from_json(self) -> int:
        """Load stages from pre-built JSON file (fast)."""
        logger.info(f"Loading stages from JSON: {self.json_path}")
        
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Store metadata
            self._version = data.get("version")
            self._generated_at = data.get("generated_at")
            self._root_stages = data.get("root_stage_ids", [])
            
            # Load stages
            stages_data = data.get("stages", {})
            for stage_id, stage_dict in stages_data.items():
                self._stages[stage_id] = TreatmentStage(**stage_dict)
            
            self._loaded = True
            logger.info(
                f"Loaded {len(self._stages)} stages from JSON "
                f"(version={self._version}, generated={self._generated_at})"
            )
            
            return len(self._stages)
            
        except Exception as e:
            logger.error(f"Error loading JSON: {e}")
            raise
    
    def _load_from_csv(self) -> int:
        """Load stages from CSV (fallback when JSON missing)."""
        logger.info(f"Loading stages from CSV: {self.csv_path}")
        
        try:
            with open(self.csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    stage = self._parse_row(row)
                    if stage:
                        self._stages[stage.stage_id] = stage
                        
                        # Track root stages (no parent)
                        if stage.parent_stage_id is None:
                            self._root_stages.append(stage.stage_id)
            
            # Build parent-child relationships
            self._build_relationships()
            
            self._loaded = True
            logger.info(f"Loaded {len(self._stages)} stages from CSV")
            
            return len(self._stages)
            
        except FileNotFoundError:
            logger.error(f"CSV file not found: {self.csv_path}")
            raise
        except Exception as e:
            logger.error(f"Error loading CSV: {e}")
            raise
    
    def _parse_row(self, row: dict) -> Optional[TreatmentStage]:
        """Parse a CSV row into a TreatmentStage."""
        stage_no = row.get('Stage No.', '').strip()
        sub_stage = row.get('Sub Stage', '').strip()
        name = row.get('Name', '').strip()
        
        # Skip rows without a name
        if not name:
            return None
        
        # Determine stage ID (prefer sub_stage if available)
        stage_id = sub_stage if sub_stage else stage_no
        if not stage_id:
            return None
        
        # Clean up multiline name
        name = ' '.join(name.split())
        
        # Parse description
        description = row.get('Description', '').strip()
        description = ' '.join(description.split())  # Clean multiline
        
        # Parse transition stages
        before_raw = row.get('Before Stage (can be multipl', '').strip()
        before_stages = [s.strip() for s in before_raw.split(',') if s.strip() and s.strip() != '<start>']
        
        after_raw = row.get('After Stage', '').strip()
        after_stages = [s.strip() for s in after_raw.split(',') if s.strip() and s.strip() != '<End of Pathways>']
        
        # Parse transition notes
        transition_notes = row.get('Transition notes from this stage to next stage', '').strip()
        
        # Parse patient facing flag
        patient_facing_raw = row.get('Patient Facing (Y/N)?', 'Y').strip().upper()
        is_patient_facing = patient_facing_raw != 'N'
        
        # Determine parent stage from ID structure
        parent_stage_id = self._get_parent_id(stage_id)
        
        return TreatmentStage(
            stage_id=stage_id,
            name=name,
            description=description,
            parent_stage_id=parent_stage_id,
            before_stages=before_stages,
            after_stages=after_stages,
            transition_notes=transition_notes if transition_notes else None,
            is_patient_facing=is_patient_facing,
        )
    
    def _get_parent_id(self, stage_id: str) -> Optional[str]:
        """
        Determine the parent stage ID from a stage ID.
        
        Examples:
            '2.1.1' -> '2.1'
            '2.1' -> '2'
            '2' -> None
            '0.1' -> None (treat as root)
        """
        if '.' not in stage_id:
            return None
        
        parts = stage_id.rsplit('.', 1)
        if parts[0]:
            return parts[0]
        return None
    
    def _build_relationships(self):
        """Build parent-child relationships between stages."""
        for stage_id, stage in self._stages.items():
            if stage.parent_stage_id and stage.parent_stage_id in self._stages:
                parent = self._stages[stage.parent_stage_id]
                if stage_id not in parent.child_stage_ids:
                    parent.child_stage_ids.append(stage_id)
    
    # ================================
    # Lookup Methods
    # ================================
    
    def get_all_stages(self) -> List[TreatmentStage]:
        """Get all loaded stages."""
        self._ensure_loaded()
        return list(self._stages.values())
    
    def get_stage_by_id(self, stage_id: str) -> Optional[TreatmentStage]:
        """Get a specific stage by ID."""
        self._ensure_loaded()
        return self._stages.get(stage_id)
    
    def get_root_stages(self) -> List[TreatmentStage]:
        """Get all root (top-level) stages."""
        self._ensure_loaded()
        return [self._stages[sid] for sid in self._root_stages if sid in self._stages]
    
    def get_children(self, stage_id: str) -> List[TreatmentStage]:
        """Get child stages for a given stage."""
        self._ensure_loaded()
        stage = self._stages.get(stage_id)
        if not stage:
            return []
        return [self._stages[cid] for cid in stage.child_stage_ids if cid in self._stages]
    
    def get_parent(self, stage_id: str) -> Optional[TreatmentStage]:
        """Get the parent stage for a given stage."""
        self._ensure_loaded()
        stage = self._stages.get(stage_id)
        if not stage or not stage.parent_stage_id:
            return None
        return self._stages.get(stage.parent_stage_id)
    
    def get_breadcrumb(self, stage_id: str) -> List[str]:
        """
        Get the path from root to this stage as a list of names.
        
        Example: '2.1.1' -> ['Surgery', 'Breast surgery', 'Breast Conservation Surgery']
        """
        self._ensure_loaded()
        
        breadcrumb = []
        current_id = stage_id
        
        while current_id:
            stage = self._stages.get(current_id)
            if stage:
                breadcrumb.insert(0, stage.name)
                current_id = stage.parent_stage_id
            else:
                break
        
        return breadcrumb
    
    # ================================
    # Tree Building
    # ================================
    
    def get_stage_tree(self, patient_facing_only: bool = True) -> List[StageTreeNode]:
        """
        Build hierarchical tree of stages for UI rendering.
        
        Args:
            patient_facing_only: If True, only include patient-facing stages
            
        Returns:
            List of root-level StageTreeNode objects with nested children
        """
        self._ensure_loaded()
        
        def build_node(stage_id: str) -> Optional[StageTreeNode]:
            stage = self._stages.get(stage_id)
            if not stage:
                return None
            
            if patient_facing_only and not stage.is_patient_facing:
                return None
            
            children = []
            for child_id in stage.child_stage_ids:
                child_node = build_node(child_id)
                if child_node:
                    children.append(child_node)
            
            return StageTreeNode(stage=stage, children=children)
        
        tree = []
        for root_id in self._root_stages:
            node = build_node(root_id)
            if node:
                tree.append(node)
        
        return tree
    
    # ================================
    # Context for AI Prompts
    # ================================
    
    def get_stage_context_for_ai(self, stage_id: str) -> Dict[str, Any]:
        """
        Get stage context formatted for inclusion in AI prompts.
        
        Returns a dict with stage name, description, breadcrumb, and
        transition notes for personalized responses.
        """
        self._ensure_loaded()
        
        stage = self._stages.get(stage_id)
        if not stage:
            return {
                "stage_id": None,
                "stage_name": "Unknown",
                "stage_description": "Patient stage not specified",
                "breadcrumb": [],
                "transition_notes": None,
            }
        
        return {
            "stage_id": stage.stage_id,
            "stage_name": stage.name,
            "stage_description": stage.description,
            "breadcrumb": self.get_breadcrumb(stage_id),
            "transition_notes": stage.transition_notes,
        }
    
    def format_stage_context_prompt(self, stage_id: str) -> str:
        """
        Format stage context as a prompt section for the reasoning agent.
        """
        ctx = self.get_stage_context_for_ai(stage_id)
        
        if not ctx["stage_id"]:
            return "Patient's treatment stage: Not specified\n"
        
        lines = [
            f"**Patient's Current Treatment Stage:**",
            f"- Stage: {ctx['stage_name']} ({ctx['stage_id']})",
            f"- Journey: {' → '.join(ctx['breadcrumb'])}",
        ]
        
        if ctx["stage_description"]:
            lines.append(f"- Description: {ctx['stage_description'][:200]}")
        
        if ctx["transition_notes"]:
            lines.append(f"- Transition context: {ctx['transition_notes']}")
        

    def get_rag_context(self, stage_id: str) -> str:
        """
        Build the Past/Present/Future context for RAG injection based on a stage ID.
        """
        stage = self.get_stage_by_id(stage_id)
        if not stage:
            return "Patient Stage: Unknown ID"
            
        # Build Context
        context = []
        
        # Get treatment phase (root node name)
        root_id = stage_id.split('.')[0]
        root_stage = self.get_stage_by_id(root_id)
        root_name = root_stage.name if root_stage else ""
        
        # PRESENT - Natural language only (no technical IDs!)
        context.append(f"CURRENT STAGE: {stage.name}")
        
        # Add treatment phase if different from stage name
        if root_name and root_name != stage.name:
            context.append(f"TREATMENT PHASE: {root_name}")
        
        # Add Journey (Breadcrumb)
        breadcrumb = self.get_breadcrumb(stage_id)
        if breadcrumb:
             # Remove current stage from breadcrumb to avoid duplication if present, or just show full path
             context.append(f"Journey: {' → '.join(breadcrumb)}")
             
        context.append(f"Description: {stage.description}")
        if stage.transition_notes:
            context.append(f"Notes: {stage.transition_notes}")
            
        # FUTURE (Next likely steps)
        if stage.child_stage_ids:
            next_names = [self.get_stage_by_id(sid).name for sid in stage.child_stage_ids if self.get_stage_by_id(sid)]
            context.append(f"NEXT POSSIBLE STEPS (Drill-down): {', '.join(next_names)}")
        elif stage.after_stages:
            next_names = [self.get_stage_by_id(sid).name for sid in stage.after_stages if self.get_stage_by_id(sid)]
            context.append(f"NEXT POSSIBLE STEPS (Progression): {', '.join(next_names)}")
        
        # Log stage ID for debugging (not in LLM context!)
        logger.debug(
            f"RAG context generated: stage_id={stage.stage_id}, "
            f"name={stage.name}, root={root_name}"
        )
            
        return "\n".join(context)

    def map_to_high_level(self, stage_id: str) -> PatientStage:
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

    # ===== Merged from stage_service_v2_1.py =====

    def check_for_safety_triggers(self, user_message: str, country_code: str = "GB") -> Dict[str, Any]:
        """
        Check user message for safety triggers with geo-aware emergency numbers.

        Returns:
            {
                "has_triggers": bool,
                "matched_keywords": List[str],
                "emergency_number": str,
                "urgent_number": str
            }
        """
        self._ensure_loaded()

        # Collect safety keywords from all stages
        safety_keywords = set()
        for stage in self._stages.values():
            safety_keywords.update(stage.safety_triggers)

        # Check message
        message_lower = user_message.lower()
        matched = [k for k in safety_keywords if k in message_lower]

        # Geo-aware emergency numbers
        emergency_numbers = {
            "GB": {"emergency": "999", "urgent": "111"},
            "US": {"emergency": "911", "urgent": "811"},
        }
        numbers = emergency_numbers.get(country_code, {"emergency": "911", "urgent": "811"})

        return {
            "has_triggers": len(matched) > 0,
            "matched_keywords": matched,
            "emergency_number": numbers["emergency"],
            "urgent_number": numbers.get("urgent"),
        }

    def detect_regression(self, from_stage_id: Optional[str], to_stage_id: str) -> Dict[str, Any]:
        """
        Detect if stage transition represents regression/recurrence.

        Logic:
            - Type 1 (Recurrence): Survivorship (Group 5) → Treatment (6, 7, 8, 9)
            - Type 2 (New Primary): Post-treatment (7-10) → Early stages (0-1)

        Returns:
            {
                "is_regression": bool,
                "regression_type": "recurrence" | "new_primary" | None,
                "message": str (empathy message)
            }
        """
        if not from_stage_id:
            return {"is_regression": False, "regression_type": None, "message": ""}

        try:
            from_group = int(from_stage_id.split('.')[0])
            to_group = int(to_stage_id.split('.')[0])
        except (ValueError, IndexError):
            return {"is_regression": False, "regression_type": None, "message": ""}

        # Type 1: Recurrence (Survivorship → Treatment)
        if from_group == 5 and to_group in [6, 7, 8, 9]:
            return {
                "is_regression": True,
                "regression_type": "recurrence",
                "message": "I'm sorry to hear about your recurrence. This must be incredibly difficult.",
            }

        # Type 2: New Primary (Post-treatment → Early stages)
        if from_group in [7, 8, 9, 10] and to_group in [0, 1]:
            return {
                "is_regression": True,
                "regression_type": "new_primary",
                "message": "I see this is a new diagnosis. I'm here to support you.",
            }

        return {"is_regression": False, "regression_type": None, "message": ""}
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


# ================================
# Profile Service
# ================================

class PatientProfileGDPRService:
    """
    Service for managing GDPR-compliant patient profiles.
    
    Stores profiles in DynamoDB with email hashing and data retention.
    """
    
    DEFAULT_RETENTION_DAYS = 365 * 2  # 2 years
    
    def __init__(self):
        """Initialize the profile service."""
        self._stage_service = PatientStageService()
    
    def create_profile(
        self,
        email: str,
        firebase_uid: Optional[str] = None,
        age_range: Optional[AgeRange] = None,
        postal_code: Optional[str] = None,
    ) -> PatientProfileGDPR:
        """
        Create a new GDPR-compliant patient profile.
        
        Args:
            email: Patient's email (will be hashed, not stored)
            firebase_uid: Firebase UID if authenticated
            age_range: Patient's age bracket
            postal_code: Full postal code (will be truncated)
            
        Returns:
            New PatientProfileGDPR instance
        """
        now = datetime.utcnow()
        
        profile = PatientProfileGDPR(
            patient_reference_id=str(uuid.uuid4()),
            email_hash=hash_email(email),
            firebase_uid=firebase_uid,
            age_range=age_range,
            postal_area=extract_postal_area(postal_code) if postal_code else None,
            consent_given_at=now,
            data_retention_until=now + timedelta(days=self.DEFAULT_RETENTION_DAYS),
            created_at=now,
            updated_at=now,
        )
        
        logger.info(f"Created profile: {profile.patient_reference_id}")
        return profile
    
    def update_stage(
        self,
        profile: PatientProfileGDPR,
        stage_id: str,
    ) -> PatientProfileGDPR:
        """
        Update the patient's selected treatment stage.
        
        Args:
            profile: The patient profile to update
            stage_id: New stage ID to select
            
        Returns:
            Updated profile
        """
        now = datetime.utcnow()
        
        # Record history
        if profile.selected_stage_id:
            profile.stage_history.append({
                "from_stage": profile.selected_stage_id,
                "to_stage": stage_id,
                "changed_at": now.isoformat(),
            })
        
        profile.selected_stage_id = stage_id
        profile.stage_updated_at = now
        profile.updated_at = now
        
        logger.info(f"Updated stage for {profile.patient_reference_id}: {stage_id}")
        return profile
    
    def get_profile_response(self, profile: PatientProfileGDPR) -> Dict[str, Any]:
        """
        Build a profile response with stage details.
        """
        stage = None
        breadcrumb = []
        
        if profile.selected_stage_id:
            stage = self._stage_service.get_stage_by_id(profile.selected_stage_id)
            breadcrumb = self._stage_service.get_breadcrumb(profile.selected_stage_id)
        
        return {
            "patient_reference_id": profile.patient_reference_id,
            "age_range": profile.age_range,
            "postal_area": profile.postal_area,
            "selected_stage": stage.dict() if stage else None,
            "stage_breadcrumb": breadcrumb,
            "consent_version": profile.consent_version,
            "data_retention_until": profile.data_retention_until.isoformat(),
        }


# ================================
# Singleton Instances
# ================================

_stage_service_instance: Optional[PatientStageService] = None
_profile_service_instance: Optional[PatientProfileGDPRService] = None


def get_patient_stage_service() -> PatientStageService:
    """Get or create the PatientStageService singleton."""
    global _stage_service_instance
    if _stage_service_instance is None:
        _stage_service_instance = PatientStageService()
    return _stage_service_instance


def get_patient_profile_gdpr_service() -> PatientProfileGDPRService:
    """Get or create the PatientProfileGDPRService singleton."""
    global _profile_service_instance
    if _profile_service_instance is None:
        _profile_service_instance = PatientProfileGDPRService()
    return _profile_service_instance
