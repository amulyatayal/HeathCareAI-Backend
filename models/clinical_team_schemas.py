"""
Pydantic schemas for clinician care team (admin CRUD + patient read-only).
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class TeamMemberCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    role: str = Field(..., min_length=1, max_length=200)
    specialty: Optional[str] = Field(None, max_length=200)
    contact_email: Optional[str] = Field(None, max_length=320)
    contact_phone: Optional[str] = Field(None, max_length=50)
    display_order: Optional[int] = Field(None, ge=0)


class TeamMemberUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    role: Optional[str] = Field(None, min_length=1, max_length=200)
    specialty: Optional[str] = Field(None, max_length=200)
    contact_email: Optional[str] = Field(None, max_length=320)
    contact_phone: Optional[str] = Field(None, max_length=50)
    display_order: Optional[int] = Field(None, ge=0)


class TeamMemberResponse(BaseModel):
    id: str
    clinician_id: str
    name: str
    role: str
    specialty: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    avatar_url: Optional[str] = None
    display_order: int
    created_at: str
    updated_at: str


class AdminTeamMemberListResponse(BaseModel):
    team_members: List[TeamMemberResponse]
    total_count: int


class AdminTeamMemberCreateResponse(BaseModel):
    id: str
    message: str
    team_member: TeamMemberResponse


class AdminTeamMemberMutationResponse(BaseModel):
    message: str
    team_member: TeamMemberResponse


class PatientTeamMemberListResponse(BaseModel):
    team_members: List[TeamMemberResponse]
    total_count: int
    clinician_id: Optional[str] = None
