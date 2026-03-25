"""
Admin Portal Schemas
Pydantic models for admin authentication and pathway resource management.
"""

from datetime import datetime
from typing import List, Optional
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from config.pipeline_config import IntentCategory


# ================================
# Resource Type Enum
# ================================

class ResourceType(str, Enum):
    PDF = "pdf"
    VIDEO = "video"
    LINK = "link"


# ================================
# Authentication Schemas
# ================================

class AdminLoginRequest(BaseModel):
    email: str = Field(..., description="Clinician email address")
    password: str = Field(..., description="Clinician password")


class AdminUser(BaseModel):
    id: str
    name: str
    email: str
    role: str = "clinician"


class AdminLoginResponse(BaseModel):
    token: str
    user: AdminUser


# ================================
# Pathway Resource Schemas
# ================================

class ResourceItem(BaseModel):
    """A single educational resource (PDF, video, or link)."""
    title: str = Field(..., min_length=1, max_length=500)
    url: str = Field(..., min_length=1)
    type: ResourceType


class PathwayResourceCreate(BaseModel):
    """Request body for creating a pathway resource."""
    clinician_name: str = Field(..., min_length=1, max_length=200)
    clinician_id: str = Field(..., min_length=1, max_length=100)
    pathway_stage_ids: List[str] = Field(default_factory=list)
    description: str = Field("", max_length=2000)
    intents: List[str] = Field(default_factory=list)
    resources: List[ResourceItem] = Field(..., min_length=1)

    @field_validator("intents", mode="before")
    @classmethod
    def validate_intents(cls, v):
        valid = {cat.value for cat in IntentCategory}
        for intent in v:
            if intent not in valid:
                raise ValueError(f"Invalid intent '{intent}'. Must be one of: {sorted(valid)}")
        return v


class PathwayResourceUpdate(BaseModel):
    """Request body for updating a pathway resource."""
    clinician_name: Optional[str] = Field(None, min_length=1, max_length=200)
    clinician_id: Optional[str] = Field(None, min_length=1, max_length=100)
    pathway_stage_ids: Optional[List[str]] = Field(None, min_length=1)
    description: Optional[str] = Field(None, max_length=2000)
    intents: Optional[List[str]] = None
    resources: Optional[List[ResourceItem]] = Field(None, min_length=1)

    @field_validator("intents", mode="before")
    @classmethod
    def validate_intents(cls, v):
        if v is None:
            return v
        valid = {cat.value for cat in IntentCategory}
        for intent in v:
            if intent not in valid:
                raise ValueError(f"Invalid intent '{intent}'. Must be one of: {sorted(valid)}")
        return v


class PathwayResourceResponse(BaseModel):
    """A pathway resource as returned by the API."""
    id: str
    clinician_name: str
    clinician_id: str
    pathway_stage_ids: List[str]
    description: str
    intents: List[str]
    resources: List[ResourceItem]
    created_at: str
    updated_at: str


class PathwayResourceListResponse(BaseModel):
    """Response containing a list of pathway resources."""
    resources: List[PathwayResourceResponse]


class DeleteResponse(BaseModel):
    message: str = "Resource deleted successfully"


# ================================
# Patient-Facing Resource Schemas
# ================================

class PatientResourceResponse(BaseModel):
    """A single resource as seen by the patient."""
    title: str
    description: str
    url: str
    type: ResourceType
    intents: List[str]


class PatientResourceListResponse(BaseModel):
    """Response containing resources for a patient's stage."""
    resources: List[PatientResourceResponse]
