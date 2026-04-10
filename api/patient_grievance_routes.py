"""Patient grievance API. Prefix /grievance under /api/v2."""

from fastapi import APIRouter, Depends, Request

from api.auth import get_authenticated_user_id
from models.patient_compliance_api_schemas import (
    GrievanceSubmitRequest,
    GrievanceSubmitResponse,
)
from services.patient_grievance_service import get_patient_grievance_service
from services.patient_jurisdiction import resolve_jurisdiction
from services.patient_profile_service import get_patient_profile_service

router = APIRouter(prefix="/grievance", tags=["Patient Grievance"])


def _privacy_client_ip(request: Request):
    fwd = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _hospital_id(request: Request):
    return request.headers.get("X-Hospital-Id") or request.headers.get("x-hospital-id")


@router.post("", response_model=GrievanceSubmitResponse)
async def submit_grievance(
    request: Request,
    body: GrievanceSubmitRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    profile = await get_patient_profile_service().get_profile(user_id)
    hid = profile.hospital_id if profile else None
    jurisdiction = resolve_jurisdiction(request, hid)

    result = await get_patient_grievance_service().submit(
        user_id,
        body.subject,
        body.description,
        ip=_privacy_client_ip(request),
        user_agent=request.headers.get("user-agent") or request.headers.get("User-Agent"),
        hospital_id=_hospital_id(request) or hid,
        jurisdiction=jurisdiction,
    )
    return GrievanceSubmitResponse(**result)
