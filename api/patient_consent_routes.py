"""
Patient consent API (GDPR / DPDPA). Prefix: /consent (mounted under /api/v2).
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Path, Request

from api.auth import get_authenticated_user_id
from models.patient_consent_schemas import (
    ConsentAckResponse,
    ConsentStatusResponse,
    ConsentWithdrawResponse,
    CookieConsentRequest,
    DataConsentRequest,
)
from services.patient_consent_service import get_patient_consent_service
from services.patient_jurisdiction import resolve_jurisdiction
from services.patient_profile_service import get_patient_profile_service

router = APIRouter(prefix="/consent", tags=["Patient Consent"])

HOSPITAL_HEADER = "X-Hospital-Id"


def _client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _user_agent(request: Request) -> Optional[str]:
    return request.headers.get("user-agent") or request.headers.get("User-Agent")


def _hospital_id(request: Request) -> Optional[str]:
    return request.headers.get(HOSPITAL_HEADER) or request.headers.get("x-hospital-id")


@router.post("/cookies", response_model=ConsentAckResponse)
async def post_cookie_consent(
    request: Request,
    body: CookieConsentRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    profile = await get_patient_profile_service().get_profile(user_id)
    hid = profile.hospital_id if profile else None
    jurisdiction = resolve_jurisdiction(request, hid)
    svc = get_patient_consent_service()
    consent_id, message = await svc.save_cookie_consent(
        user_id,
        body,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
        hospital_id=_hospital_id(request) or hid,
        jurisdiction=jurisdiction,
    )
    return ConsentAckResponse(message=message, consent_id=consent_id)


@router.post("/data", response_model=ConsentAckResponse)
async def post_data_consent(
    request: Request,
    body: DataConsentRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    profile = await get_patient_profile_service().get_profile(user_id)
    hid = profile.hospital_id if profile else None
    jurisdiction = resolve_jurisdiction(request, hid)
    svc = get_patient_consent_service()
    consent_id, message = await svc.save_data_consent(
        user_id,
        body,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
        hospital_id=_hospital_id(request) or hid,
        jurisdiction=jurisdiction,
    )
    return ConsentAckResponse(message=message, consent_id=consent_id)


@router.get("", response_model=ConsentStatusResponse)
async def get_consent(
    user_id: str = Depends(get_authenticated_user_id),
):
    status = await get_patient_consent_service().get_status(user_id)
    return ConsentStatusResponse(**status)


@router.delete(
    "/{consent_type}",
    response_model=ConsentWithdrawResponse,
)
async def delete_consent(
    request: Request,
    consent_type: Literal["data", "cookies"] = Path(
        ...,
        description="Withdraw data or cookies consent",
    ),
    user_id: str = Depends(get_authenticated_user_id),
):
    profile = await get_patient_profile_service().get_profile(user_id)
    hid = profile.hospital_id if profile else None
    jurisdiction = resolve_jurisdiction(request, hid)
    msg = await get_patient_consent_service().withdraw(
        user_id,
        consent_type,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
        hospital_id=_hospital_id(request) or hid,
        jurisdiction=jurisdiction,
    )
    return ConsentWithdrawResponse(message=msg)

