"""
Patient Stage Models
Defines hierarchical treatment stages and GDPR-compliant patient profile.

Based on breast cancer treatment pathway from Knowledge Base CSV.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum
import hashlib


# ================================
# Treatment Stage Models
# ================================

class TreatmentStage(BaseModel):
    """
    A stage in the breast cancer treatment pathway.
    
    Stages are hierarchical - each stage may have a parent and children.
    Example: 2.1.1 (Breast Conservation Surgery) has parent 2.1 (Breast Surgery)
    and children like 2.1.1.1 (Wide Local Excision).
    """
    stage_id: str = Field(
        ...,
        description="Unique identifier (e.g., '2.1.1')"
    )
    name: str = Field(
        ...,
        description="Display name (e.g., 'Breast Conservation Surgery')"
    )
    description: str = Field(
        default="",
        description="Detailed description of this stage"
    )
    parent_stage_id: Optional[str] = Field(
        None,
        description="Parent stage ID (None for root stages)"
    )
    child_stage_ids: List[str] = Field(
        default_factory=list,
        description="IDs of child stages"
    )
    before_stages: List[str] = Field(
        default_factory=list,
        description="Possible previous stages"
    )
    after_stages: List[str] = Field(
        default_factory=list,
        description="Possible next stages"
    )
    transition_notes: Optional[str] = Field(
        None,
        description="Notes about transitioning from this stage"
    )
    is_patient_facing: bool = Field(
        default=True,
        description="Whether to show this stage to patients"
    )
    # NEW: Added for embedding enrichment and user-friendly display
    display_name: Optional[str] = Field(
        None,
        description="User-friendly display name (e.g., 'Full Breast Removal')"
    )
    search_terms: List[str] = Field(
        default_factory=list,
        description="Patient-friendly search terms for better embedding matching"
    )
    
    # ===== V2.1 Journey Engine Enhancements =====
    verification_questions: List[str] = Field(
        default_factory=list,
        description="Questions to verify patient is in this stage (from CSV 'Patient Facing Questions' column)"
    )
    safety_triggers: List[str] = Field(
        default_factory=list,
        description="Safety keywords extracted from stage description for chat escalation"
    )



class StageTreeNode(BaseModel):
    """Hierarchical view of stages for UI rendering."""
    stage: TreatmentStage
    children: List["StageTreeNode"] = Field(default_factory=list)


# ================================
# Age Range Options
# ================================

class AgeRange(str, Enum):
    """Age ranges for GDPR-compliant age collection."""
    UNDER_30 = "under_30"
    AGE_30_39 = "30-39"
    AGE_40_49 = "40-49"
    AGE_50_59 = "50-59"
    AGE_60_69 = "60-69"
    AGE_70_79 = "70-79"
    AGE_80_PLUS = "80+"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


# ================================
# GDPR-Compliant Patient Profile
# ================================

class PatientProfileGDPR(BaseModel):
    """
    GDPR-compliant patient profile.
    
    Stores NO directly identifiable PII:
    - Email is hashed (one-way, for linking only)
    - Age stored as range, not exact value
    - Postal code truncated to area only
    - Consent and data retention tracking included
    """
    # Identifiers (non-PII)
    patient_reference_id: str = Field(
        ...,
        description="System-generated UUID for this patient"
    )
    email_hash: str = Field(
        ...,
        description="SHA-256 hash of email (for linking, email not stored)"
    )
    firebase_uid: Optional[str] = Field(
        None,
        description="Firebase UID if authenticated"
    )
    
    # Non-PII demographic data for personalization
    age_range: Optional[AgeRange] = Field(
        None,
        description="Age bracket (e.g., '40-49')"
    )
    postal_area: Optional[str] = Field(
        None,
        description="First part of postal code only (e.g., 'SW1' not 'SW1A 1AA')"
    )
    
    # Treatment stage
    selected_stage_id: Optional[str] = Field(
        None,
        description="Selected treatment stage ID (e.g., '2.1.1')"
    )
    stage_updated_at: Optional[datetime] = Field(
        None,
        description="When stage was last updated"
    )
    stage_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="History of stage changes"
    )
    
    # GDPR consent tracking
    consent_given_at: datetime = Field(
        ...,
        description="When user gave consent for data storage"
    )
    consent_version: str = Field(
        default="1.0",
        description="Version of consent terms accepted"
    )
    data_retention_until: datetime = Field(
        ...,
        description="Data will be auto-deleted after this date"
    )
    
    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Profile creation time"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update time"
    )
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None,
        }


# ================================
# Helper Functions
# ================================

def hash_email(email: str) -> str:
    """
    Create a SHA-256 hash of an email address.
    
    Used for linking accounts without storing the actual email.
    """
    normalized = email.lower().strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def extract_postal_area(postal_code: str) -> str:
    """
    Extract the area portion of a UK postal code.
    
    Examples:
        'SW1A 1AA' -> 'SW1A'
        'M1 1AA' -> 'M1'
        'B1 1AA' -> 'B1'
    """
    if not postal_code:
        return ""
    
    # Remove spaces and get the outward code (before space)
    parts = postal_code.strip().upper().split()
    if parts:
        # Return just the first part (area + district)
        return parts[0]
    return ""


# ================================
# API Request/Response Models
# ================================

class StageSelectionRequest(BaseModel):
    """Request to update patient's selected stage."""
    stage_id: str = Field(
        ...,
        description="Stage ID to select (e.g., '2.1.1')"
    )


class ProfileUpdateRequest(BaseModel):
    """Request to update patient profile."""
    age_range: Optional[AgeRange] = None
    postal_code: Optional[str] = Field(
        None,
        description="Full postal code (will be truncated for storage)"
    )
    stage_id: Optional[str] = None


class ProfileCreateRequest(BaseModel):
    """Request to create a new patient profile."""
    email: str = Field(
        ...,
        description="Email (will be hashed, not stored)"
    )
    age_range: Optional[AgeRange] = None
    postal_code: Optional[str] = None
    consent_given: bool = Field(
        ...,
        description="User must confirm consent"
    )


class StageTreeResponse(BaseModel):
    """Response containing hierarchical stage tree."""
    stages: List[StageTreeNode]
    total_count: int


class StageDetailResponse(BaseModel):
    """Response containing details of a single stage."""
    stage: TreatmentStage
    parent: Optional[TreatmentStage] = None
    children: List[TreatmentStage] = []
    breadcrumb: List[str] = Field(
        default_factory=list,
        description="Path from root to this stage (e.g., ['Surgery', 'Breast Surgery', 'Breast Conservation'])"
    )


class ProfileResponse(BaseModel):
    """Response containing patient profile."""
    patient_reference_id: str
    age_range: Optional[str] = None
    postal_area: Optional[str] = None
    selected_stage: Optional[TreatmentStage] = None
    stage_breadcrumb: List[str] = []
    consent_version: str
    data_retention_until: datetime
