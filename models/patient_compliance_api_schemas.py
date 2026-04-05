"""Request/response models for patient compliance APIs (nominee, grievance, share, activity)."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class NomineeUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)
    relationship: str = Field(..., min_length=1)
    phone: Optional[str] = None


class NomineeResponse(BaseModel):
    name: str
    email: str
    relationship: str
    phone: Optional[str] = None


class NomineeUpsertResponse(BaseModel):
    message: str
    nominee_id: str


class GrievanceSubmitRequest(BaseModel):
    subject: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)


class GrievanceSubmitResponse(BaseModel):
    message: str
    grievance_id: str
    expected_resolution_date: str


class ActivityItem(BaseModel):
    id: Optional[str] = None
    type: str
    description: str
    timestamp: str


class ActivityLogResponse(BaseModel):
    activities: List[ActivityItem]


class ShareGenerateRequest(BaseModel):
    scope: Optional[Dict[str, Any]] = None


class ShareGenerateResponse(BaseModel):
    share_id: str
    token: str
    expires_at: str
    share_url: str


class SharePublicPayload(BaseModel):
    share_id: Optional[str] = None
    expires_at: Optional[str] = None
    profile_summary: Dict[str, Any] = Field(default_factory=dict)
    scope: Dict[str, Any] = Field(default_factory=dict)


class ShareHistoryItem(BaseModel):
    share_id: Optional[str] = None
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None


class ShareHistoryResponse(BaseModel):
    shares: List[ShareHistoryItem]


class ShareRevokeResponse(BaseModel):
    message: str
