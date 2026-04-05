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
    OnboardingSituation.WAITING_FOR_RESULTS: PatientStage.AWAITING_RESULTS,
    OnboardingSituation.RECENTLY_DIAGNOSED: PatientStage.NEWLY_DIAGNOSED,
    OnboardingSituation.CURRENTLY_IN_TREATMENT: PatientStage.ACTIVE_TREATMENT,
    OnboardingSituation.FINISHED_TREATMENT: PatientStage.POST_TREATMENT,
    OnboardingSituation.LONG_TERM_FOLLOWUP: PatientStage.SURVEILLANCE,
    OnboardingSituation.PREFER_NOT_TO_SAY: PatientStage.UNKNOWN,
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
        description="How stage was set: 'onboarding' | 'manual_update'"
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
    
    # Clinician association (set via access code)
    clinician_id: Optional[str] = Field(
        None,
        description="Associated clinician's user ID"
    )
    clinician_name: Optional[str] = Field(
        None,
        description="Associated clinician's display name"
    )
    hospital_id: Optional[str] = Field(
        None,
        description="Hospital the patient is associated with"
    )

    # GDPR / DPDPA: when True, optional processing should stop until data consent is re-granted
    data_processing_paused: bool = Field(
        default=False,
        description="Set when patient withdraws data-processing consent (not erasure)",
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
        # Convert datetime objects to ISO strings
        for key in ['created_at', 'updated_at', 'stage_updated_at', 'onboarding_completed_at', 'detailed_stage_updated_at']:
            if data.get(key):
                data[key] = data[key].isoformat() if isinstance(data[key], datetime) else data[key]
        # Convert nested datetimes in stage_history
        for entry in data.get('stage_history', []):
            if entry.get('timestamp'):
                entry['timestamp'] = entry['timestamp'].isoformat() if isinstance(entry['timestamp'], datetime) else entry['timestamp']
        # Convert dates in explicit_data
        if data.get('explicit_data'):
            for key in ['diagnosis_date', 'treatment_start_date', 'treatment_end_date']:
                if data['explicit_data'].get(key):
                    val = data['explicit_data'][key]
                    data['explicit_data'][key] = val.isoformat() if isinstance(val, date) else val
        return data
    
    @classmethod
    def from_dynamodb_item(cls, item: dict) -> "PatientProfile":
        """Create from DynamoDB item."""
        # DynamoDB stores everything as strings, parse back
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
