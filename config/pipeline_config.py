"""
Pipeline Configuration for Multi-Agent Patient Education System
Defines intent categories, patient stages, and confidence thresholds.

This is the single source of truth for pipeline behavior parameters.
Spec Reference: ProjectSpec.md v1.2
"""

from typing import List, Dict, Any
from enum import Enum


# ================================
# Intent Categories (Section 6.2)
# ================================

class IntentCategory(str, Enum):
    """
    Categories for classifying user intent.
    The Intent Agent maps user queries to one of these categories.
    """
    # Core Medical
    SYMPTOMS = "symptoms"
    SURGERY_PROCEDURES = "surgery_procedures"
    DRAINS_WOUND_CARE = "drains_wound_care"
    CANCER_TREATMENT = "cancer_treatment"
    MEDICATION_INFO = "medication_info"
    SIDE_EFFECTS = "side_effects"
    
    # Perioperative
    PRE_SURGERY_PREHAB = "pre_surgery_prehab"
    POST_SURGERY_RECOVERY = "post_surgery_recovery"
    
    # Follow-up Care Categories
    FOLLOW_UP_CARE = "follow_up_care"  # General follow-up queries
    NUTRITION = "nutrition"
    EXERCISE = "exercise"
    CLOTHING = "clothing"
    
    # Support & Admin
    EMOTIONAL_SUPPORT = "emotional_support"
    DIAGNOSIS_TESTING = "diagnosis_testing"
    ADMIN_LOGISTICS = "admin_logistics"
    
    # Safety & Info
    SAFETY_RED_FLAGS = "safety_red_flags"
    STATISTICS = "statistics"
    
    # Fallback
    UNKNOWN = "unknown"


# List of all intent categories for prompts
INTENT_CATEGORIES: List[str] = [cat.value for cat in IntentCategory]


# ================================
# Patient Stages (Section 7.2)
# Aligned 1:1 with root stages in stage_hierarchy.json
# ================================

class PatientStage(str, Enum):
    """
    Stages in a patient's medical journey.
    Each value maps 1:1 to a root stage in stage_hierarchy.json.
    The Stage Agent infers which stage the user appears to be in.
    """
    # ─── Active values (1:1 with root stage IDs) ───
    PRE_DIAGNOSIS = "pre_diagnosis"                     # Root ID 0
    NEWLY_DIAGNOSED = "newly_diagnosed"                 # Root ID 1
    SURGERY = "surgery"                                 # Root ID 2
    NEOADJUVANT_CHEMO = "neoadjuvant_chemo"             # Root ID 3
    NEOADJUVANT_ENDOCRINE = "neoadjuvant_endocrine"     # Root ID 4
    SURVIVORSHIP = "survivorship"                       # Root ID 5
    FURTHER_SURGERY = "further_surgery"                 # Root ID 6
    ADJUVANT_RADIO = "adjuvant_radio"                   # Root ID 7
    ADJUVANT_CHEMO = "adjuvant_chemo"                   # Root ID 8
    ADJUVANT_ENDOCRINE = "adjuvant_endocrine"           # Root ID 9
    ADJUVANT_ZOLEDRONIC = "adjuvant_zoledronic"         # Root ID 10
    UNKNOWN = "unknown"

    # ─── Deprecated aliases (for DB backward compat) ───
    # These allow old DynamoDB records to deserialize.
    # Will be removed after all records are migrated.
    ACTIVE_TREATMENT = "active_treatment"
    POST_TREATMENT = "post_treatment"
    AWAITING_RESULTS = "awaiting_results"
    PALLIATIVE_SUPPORT = "palliative_support"
    SURVEILLANCE = "surveillance"  # Renamed → SURVIVORSHIP


# Active stages only (excludes deprecated — used for LLM prompts)
_DEPRECATED_STAGE_VALUES = {
    "active_treatment", "post_treatment", "awaiting_results",
    "palliative_support", "surveillance",
}
PATIENT_STAGES: List[str] = [
    stage.value for stage in PatientStage
    if stage.value not in _DEPRECATED_STAGE_VALUES
]


# ================================
# Certainty Levels (Section 7.4)
# ================================

class CertaintyLevel(str, Enum):
    """Certainty levels for stage inference."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ================================
# Confidence Thresholds (Section 17)
# ================================

class IntentThresholds:
    """Thresholds for intent classification confidence."""
    CLARIFICATION_REQUIRED = 0.6  # Below this → ask for clarification
    LOW_CONFIDENCE = 0.7          # Below this → use hedged language
    HIGH_CONFIDENCE = 0.85        # Above this → direct response


class StageThresholds:
    """Thresholds for stage certainty classification."""
    LOW = 0.5      # Below this → stage = unknown
    MEDIUM = 0.75  # Below this → conditional phrasing
    HIGH = 0.9     # Above this → direct stage-appropriate content


# ================================
# Error Handling (Section 18)
# ================================

class ErrorPolicy:
    """Error handling configuration for agent failures."""
    MAX_RETRIES = 1              # Maximum retry attempts per agent
    RETRY_DELAY_MS = 500         # Delay between retries
    TIMEOUT_PER_AGENT_MS = 30000 # 30 seconds timeout per agent
    FALLBACK_ON_FAILURE = True   # Use safe fallback if agent fails


# ================================
# Model Selection (Section 19.2)
# ================================

class ModelType(str, Enum):
    """Model types for agent selection."""
    FAST = "fast"        # Claude Haiku - for simple tasks
    ACCURATE = "accurate" # Claude Sonnet - for complex/medical tasks


# Model ID mapping for AWS Bedrock
MODEL_IDS = {
    ModelType.FAST: "anthropic.claude-3-haiku-20240307-v1:0",
    ModelType.ACCURATE: "anthropic.claude-3-sonnet-20240229-v1:0"  # Using Sonnet v1 (on-demand supported)
}


# ================================
# Retrieval Configuration (Section 13.2)
# ================================

class RetrievalConfig:
    """Default retrieval configuration."""
    SEARCH_TYPE = "hybrid"  # vector + keyword
    MAX_CHUNKS = 15         # Maximum chunks to retrieve
    
    # Thresholds by query type
    MEDICAL_MIN_CHUNKS = 2
    MEDICAL_MIN_SCORE = 2.0
    MEDICAL_REQUIRE_KEYWORD = True
    
    NUTRITION_MIN_CHUNKS = 1
    NUTRITION_MIN_SCORE = 1.0
    NUTRITION_REQUIRE_KEYWORD = False
    
    GENERAL_MIN_CHUNKS = 1
    GENERAL_MIN_SCORE = 1.5
    GENERAL_REQUIRE_KEYWORD = False


# ================================
# Safe Fallback Response (Section 18.3)
# ================================

SAFE_FALLBACK_RESPONSE = """I'm sorry, I wasn't able to fully process your question. For accurate information, please speak with your healthcare team or call the support helpline at 0808 800 6000."""


# ================================
# Required Disclaimer (Section 9.5)
# ================================

MEDICAL_DISCLAIMER = """This information is educational and not a substitute for medical advice. For guidance specific to your situation, please consult your care team."""


# ================================
# Logging Configuration (Section 20)
# ================================

SPEC_VERSION = "1.2"  # For logging compliance


# ================================
# Helper Functions
# ================================

def get_all_intents() -> List[str]:
    """Get all intent categories as a list of strings."""
    return INTENT_CATEGORIES


def get_all_stages() -> List[str]:
    """Get all patient stages as a list of strings."""
    return PATIENT_STAGES


def is_valid_intent(intent: str) -> bool:
    """Check if an intent string is valid."""
    return intent in INTENT_CATEGORIES


def is_valid_stage(stage: str) -> bool:
    """Check if a stage string is valid."""
    return stage in PATIENT_STAGES


def get_model_id(model_type: ModelType) -> str:
    """Get the Bedrock model ID for a model type."""
    return MODEL_IDS.get(model_type, MODEL_IDS[ModelType.FAST])

