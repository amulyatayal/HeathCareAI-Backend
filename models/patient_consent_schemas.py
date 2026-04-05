"""
Pydantic models for patient consent APIs (GDPR / DPDPA).
"""

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class CookiePreferences(BaseModel):
    necessary: bool = True
    functional: bool = False
    analytics: bool = False
    marketing: bool = False


class CookieConsentRequest(BaseModel):
    preferences: CookiePreferences
    source: str = Field(..., min_length=1)


class DataProcessingChoices(BaseModel):
    """Optional consent flags; coreService and clinicalSharing are contract basis — forced true server-side."""

    coreService: bool = True
    healthData: bool = False
    aiModelProviders: bool = False
    documentStorage: bool = False
    community: bool = False
    clinicalSharing: bool = True


class DataConsentRequest(BaseModel):
    choices: DataProcessingChoices
    source: str = Field(..., min_length=1)


class ConsentAckResponse(BaseModel):
    message: str
    consent_id: str


class CookieConsentState(BaseModel):
    preferences: Dict[str, Any]
    granted_at: str


class DataConsentState(BaseModel):
    choices: Dict[str, Any]
    granted_at: str


class ConsentStatusResponse(BaseModel):
    data_consent: Optional[DataConsentState] = None
    cookie_consent: Optional[CookieConsentState] = None


class ConsentWithdrawResponse(BaseModel):
    message: str


ConsentTypeLiteral = Literal["data", "cookies"]
