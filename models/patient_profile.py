"""
Patient Profile Models
Pydantic schemas for patient profile persistence and onboarding.

These models store user-provided data only (no inference).
Profiles are linked to authenticated users via Firebase UID.
"""

from datetime import datetime, date
from typing import List, Optional
from pydantic import BaseModel, Field
from enum import Enum

from config.pipeline_config import PatientStage


# ================================
# Onboarding Situation Mapping
# ================================

class OnboardingSituation(str, Enum):
    """Options presented in the onboarding wizard."""
    WORRIED_ABOUT_SYMPTOMS = "worried_about_symptoms"
    WAITING_FOR_RESULTS = "waiting_for_results"
    RECENTLY_DIAGNOSED = "recently_diagnosed"
    CURRENTLY_IN_TREATMENT = "currently_in_treatment"
    FINISHED_TREATMENT = "finished_treatment"
    LONG_TERM_FOLLOWUP = "long_term_followup"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


# Mapping from onboarding choices to pipeline stages
SITUATION_TO_STAGE = {
    OnboardingSituation.WORRIED_ABOUT_SYMPTOMS: PatientStage.PRE_DIAGNOSIS,
    OnboardingSituation.WAITING_FOR_RESULTS: PatientStage.PRE_DIAGNOSIS,  # merged into pre_diagnosis
    OnboardingSituation.RECENTLY_DIAGNOSED: PatientStage.NEWLY_DIAGNOSED,
    OnboardingSituation.CURRENTLY_IN_TREATMENT: PatientStage.ACTIVE_TREATMENT,  # deprecated; upgraded on read
    OnboardingSituation.FINISHED_TREATMENT: PatientStage.SURVIVORSHIP,
    OnboardingSituation.LONG_TERM_FOLLOWUP: PatientStage.SURVIVORSHIP,
    OnboardingSituation.PREFER_NOT_TO_SAY: PatientStage.UNKNOWN,
}


# Mapping from hierarchical stage IDs → PatientStage enum (1:1 with root stages)
STAGE_ID_TO_PATIENT_STAGE = {
    "0":  PatientStage.PRE_DIAGNOSIS,           # Pre-diagnosis
    "1":  PatientStage.NEWLY_DIAGNOSED,          # Results Clinic
    "2":  PatientStage.SURGERY,                  # Surgery
    "3":  PatientStage.NEOADJUVANT_CHEMO,        # Neoadjuvant Chemotherapy
    "4":  PatientStage.NEOADJUVANT_ENDOCRINE,    # Neoadjuvant endocrine treatment
    "5":  PatientStage.SURVIVORSHIP,             # Survivorship
    "6":  PatientStage.FURTHER_SURGERY,          # Further surgery
    "7":  PatientStage.ADJUVANT_RADIO,           # Adjuvant radiotherapy
    "8":  PatientStage.ADJUVANT_CHEMO,           # Adjuvant chemotherapy
    "9":  PatientStage.ADJUVANT_ENDOCRINE,       # Adjuvant endocrine therapy
    "10": PatientStage.ADJUVANT_ZOLEDRONIC,      # Adjuvant Zoledronic acid
}


# ================================
# Explicit Data (User-Provided)
# ================================

class PatientExplicitData(BaseModel):
    """
    Information explicitly provided by the patient via onboarding.
    All fields are optional - users can skip detailed questions.
    """
    diagnosis_date: Optional[date] = Field(
        None, 
        description="When patient was diagnosed"
    )
    diagnosis_type: Optional[str] = Field(
        None,
        description="Type of diagnosis (e.g., 'invasive ductal carcinoma')"
    )
    current_treatments: List[str] = Field(
        default_factory=list,
        description="Current treatments (e.g., ['chemotherapy', 'surgery'])"
    )
    treatment_start_date: Optional[date] = Field(
        None,
        description="When treatment started"
    )
    treatment_end_date: Optional[date] = Field(
        None,
        description="When treatment ended (if applicable)"
    )


# ================================
# Stage History
# ================================

class PatientStageHistory(BaseModel):
    """
    Record of user-confirmed stage changes.
    Tracks when and why stage was updated.
    """
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this change occurred"
    )
    from_stage: Optional[PatientStage] = Field(
        None,
        description="Previous stage (None if first entry)"
    )
    to_stage: PatientStage = Field(
        ...,
        description="New stage"
    )
    source: str = Field(
        ...,
        description="How stage was set: 'onboarding' | 'llm_inference' | 'manual_update' | 'verification'"
    )
    
    # ===== V2.1 Journey Engine Enhancements =====
    inference_certainty: Optional[str] = Field(
        None,
        description="Certainty level from LLM: HIGH | MEDIUM | LOW"
    )
    inference_signals: List[str] = Field(
        default_factory=list,
        description="Evidence signals from LLM (e.g., 'User mentioned surgery')"
    )
    user_confirmed: bool = Field(
        default=False,
        description="Whether user explicitly confirmed this stage change"
    )
    from_detailed_stage_id: Optional[str] = Field(
        None,
        description="Previous detailed stage ID (e.g., '2.1.1')"
    )
    to_detailed_stage_id: Optional[str] = Field(
        None,
        description="New detailed stage ID (e.g., '5.1')"
    )
    treatment_type: Optional[str] = Field(
        None,
        description="Type of treatment if relevant (e.g., 'chemotherapy', 'surgery')"
    )
    transition_notes: Optional[str] = Field(
        None,
        description="Additional context about this transition"
    )
    was_regression: bool = Field(
        default=False,
        description="Whether this represents a regression/recurrence"
    )
    
    class Config:
        use_enum_values = True


# ================================
# Patient Profile
# ================================

import secrets
import string

def generate_patient_ref_id() -> str:
    """Generate a unique patient reference ID like 'PAT-XK7M92'."""
    chars = string.ascii_uppercase + string.digits
    # Remove ambiguous characters (0, O, I, 1, L)
    chars = chars.replace('0', '').replace('O', '').replace('I', '').replace('1', '').replace('L', '')
    random_part = ''.join(secrets.choice(chars) for _ in range(6))
    return f"PAT-{random_part}"

class PatientProfile(BaseModel):
    """
    Persistent patient profile - stores user-provided data only.
    
    Linked to authenticated users via Firebase UID.
    Guest users do not have profiles.
    """
    # Primary key - Firebase UID
    user_id: str = Field(
        ...,
        description="Firebase UID from JWT token"
    )
    
    # Patient Reference ID for account linking
    patient_ref_id: str = Field(
        default_factory=generate_patient_ref_id,
        description="Unique patient reference ID (e.g., 'PAT-XK7M92') for account linking"
    )
    
    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When profile was created"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When profile was last updated"
    )
    
    # Current stage (user-provided only)
    current_stage: PatientStage = Field(
        default=PatientStage.UNKNOWN,
        description="Patient's current treatment stage"
    )
    stage_updated_at: Optional[datetime] = Field(
        None,
        description="When stage was last updated"
    )
    
    # Stage history (tracks all user changes)
    stage_history: List[PatientStageHistory] = Field(
        default_factory=list,
        description="History of stage changes"
    )
    
    # Explicit data from onboarding
    explicit_data: Optional[PatientExplicitData] = Field(
        None,
        description="User-provided medical journey details"
    )
    
    # Onboarding status
    onboarding_completed: bool = Field(
        default=False,
        description="Whether user completed onboarding wizard"
    )
    onboarding_completed_at: Optional[datetime] = Field(
        None,
        description="When onboarding was completed"
    )
    
    # Detailed stage from hierarchical treatment pathway (new system)
    detailed_stage_id: Optional[str] = Field(
        None,
        description="Detailed stage ID from treatment pathway (e.g., '2.1.1')"
    )
    detailed_stage_updated_at: Optional[datetime] = Field(
        None,
        description="When detailed stage was last updated"
    )
    detailed_stage_label: Optional[str] = Field(
        None,
        description="Patient-facing stage name (e.g., 'Wide local excision')"
    )
    
    # ===== V2.1 Journey Engine Enhancements =====
    
    # Geo-awareness (for UK deployment)
    country_code: Optional[str] = Field(
        "GB",
        description="ISO country code (e.g., 'GB', 'US') - default UK"
    )
    region: Optional[str] = Field(
        None,
        description="NHS region or state"
    )
    
    # Stage certainty tracking
    current_stage_certainty: Optional[str] = Field(
        None,
        description="Certainty level of current stage (HIGH/MEDIUM/LOW)"
    )
    detailed_stage_certainty: Optional[str] = Field(
        None,
        description="Certainty of detailed stage inference"
    )
    last_verification_at: Optional[datetime] = Field(
        None,
        description="When stage was last verified with user"
    )
    
    # Regression/recurrence tracking
    has_recurrence: bool = Field(
        default=False,
        description="Whether patient has experienced recurrence"
    )
    recurrence_date: Optional[datetime] = Field(
        None,
        description="When recurrence was detected"
    )
    is_regression_detected: bool = Field(
        default=False,
        description="System-detected backward stage movement"
    )
    treatment_phases_completed: List[str] = Field(
        default_factory=list,
        description="Completed treatments: ['surgery', 'chemotherapy']"
    )
    first_diagnosis_date: Optional[date] = Field(
        None,
        description="Date of initial diagnosis"
    )
    
    # Guest conversion tracking
    was_guest: bool = Field(
        default=False,
        description="Whether user started as guest"
    )
    guest_interactions_count: int = Field(
        default=0,
        description="Number of interactions before sign-up"
    )
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None,
            date: lambda v: v.isoformat() if v else None,
        }
    
    def to_dynamodb_item(self) -> dict:
        """Convert to DynamoDB-compatible dict."""
        data = self.dict()
        
        def _convert_datetimes(obj):
            """Recursively convert datetime/date objects to ISO strings."""
            if isinstance(obj, dict):
                return {k: _convert_datetimes(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_convert_datetimes(item) for item in obj]
            elif isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, date):
                return obj.isoformat()
            return obj
        
        data = _convert_datetimes(data)
        return data
    
    @classmethod
    def from_dynamodb_item(cls, item: dict) -> "PatientProfile":
        """Create from DynamoDB item with deprecated stage migration."""
        # ─── Read-time migration for deprecated current_stage values ───
        _DEPRECATED_DIRECT_UPGRADE = {
            "awaiting_results": "pre_diagnosis",
            "palliative_support": "newly_diagnosed",
            "surveillance": "survivorship",
        }
        stage = item.get('current_stage')
        if stage in _DEPRECATED_DIRECT_UPGRADE:
            item['current_stage'] = _DEPRECATED_DIRECT_UPGRADE[stage]
        elif stage in ("active_treatment", "post_treatment"):
            # Resolve from detailed_stage_id if available
            dsid = item.get('detailed_stage_id')
            if dsid:
                root_id = dsid.split('.')[0]
                new_val = STAGE_ID_TO_PATIENT_STAGE.get(root_id)
                if new_val:
                    item['current_stage'] = new_val.value
            # else: keep deprecated alias (still valid enum value)
        return cls(**item)


# ================================
# API Request/Response Models
# ================================

class OnboardingRequest(BaseModel):
    """Request body for onboarding submission."""
    current_situation: OnboardingSituation = Field(
        ...,
        description="Selected situation from onboarding wizard"
    )
    # Optional treatment type (patient-friendly selection)
    treatment_type: Optional[str] = Field(
        None,
        description="Type of treatment (surgery, chemotherapy, etc.)"
    )
    # Optional detailed stage ID (mapped from treatment_type)
    detailed_stage_id: Optional[str] = Field(
        None,
        description="Detailed stage ID from treatment pathway"
    )
    # GDPR-compliant profile fields
    age_range: Optional[str] = Field(
        None,
        description="Age range bracket (e.g., '40-49')"
    )
    postal_code: Optional[str] = Field(
        None,
        description="Postal code area (first part only, e.g., 'SW1')"
    )
    # Optional detailed information
    diagnosis_date: Optional[str] = Field(
        None,
        description="Diagnosis date (YYYY-MM-DD format)"
    )
    diagnosis_type: Optional[str] = Field(
        None,
        description="Type of diagnosis"
    )
    current_treatments: List[str] = Field(
        default_factory=list,
        description="List of current treatments"
    )
    treatment_start_date: Optional[str] = Field(
        None,
        description="Treatment start date (YYYY-MM-DD format)"
    )


class StageUpdateRequest(BaseModel):
    """Request to manually update patient stage."""
    new_stage: PatientStage = Field(
        ...,
        description="New stage to set"
    )


class LinkAccountRequest(BaseModel):
    """Request to link a profile from another account."""
    patient_ref_id: str = Field(
        ...,
        description="Patient Reference ID of the profile to link (e.g., 'PAT-XK7M92')"
    )


class ProfileResponse(BaseModel):
    """Response containing patient profile."""
    profile: PatientProfile
    message: str = "Success"


class OnboardingStatusResponse(BaseModel):
    """Response for checking onboarding status."""
    onboarding_completed: bool
    current_stage: PatientStage
    needs_onboarding: bool
    
    class Config:
        use_enum_values = True
