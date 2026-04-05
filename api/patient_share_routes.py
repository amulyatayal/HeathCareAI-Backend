"""Patient data share API. Prefix /share under /api/v2."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request

from api.auth import get_authenticated_user_id
from botocore.exceptions import ClientError
from models.patient_compliance_api_schemas import (
    ShareGenerateRequest,
    ShareGenerateResponse,
    ShareHistoryItem,
    ShareHistoryResponse,
    SharePublicPayload,
    ShareRevokeResponse,
)
from services.patient_data_share_service import get_patient_data_share_service
from services.patient_jurisdiction import resolve_jurisdiction
from services.patient_profile_service import get_patient_profile_service

router = APIRouter(prefix="/share", tags=["Patient Data Share"])


def _privacy_client_ip(request: Request):
    fwd = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _hospital_id(request: Request):
    return request.headers.get("X-Hospital-Id") or request.headers.get("x-hospital-id")


@router.post("/generate", response_model=ShareGenerateResponse)
async def generate_share(
    request: Request,
    body: ShareGenerateRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    profile = await get_patient_profile_service().get_profile(user_id)
    hid = profile.hospital_id if profile else None
    jurisdiction = resolve_jurisdiction(request, hid)
    try:
        out = await get_patient_data_share_service().generate_share(
            user_id,
            ip=_privacy_client_ip(request),
            user_agent=request.headers.get("user-agent") or request.headers.get("User-Agent"),
            hospital_id=_hospital_id(request) or hid,
            jurisdiction=jurisdiction,
            scope=body.scope,
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            raise HTTPException(
                status_code=503,
                detail="Data share storage is not provisioned (PatientDataShares table).",
            ) from e
        raise
    return ShareGenerateResponse(**out)


@router.get("/history", response_model=ShareHistoryResponse)
async def share_history(
    user_id: str = Depends(get_authenticated_user_id),
):
    rows: List[dict] = get_patient_data_share_service().list_history(user_id, limit=50)
    return ShareHistoryResponse(shares=[ShareHistoryItem(**r) for r in rows])


@router.get("/view/{token}", response_model=SharePublicPayload)
async def view_shared_data(token: str):
    """Public: resolve share token (no Bearer auth). Use path /share/view/{token}."""
    if not token or len(token) < 8:
        raise HTTPException(status_code=404, detail="Share not found or expired")
    data = await get_patient_data_share_service().get_by_token(token)
    if not data:
        raise HTTPException(status_code=404, detail="Share not found or expired")
    return SharePublicPayload(**data)


@router.delete("/{share_id}", response_model=ShareRevokeResponse)
async def revoke_share(
    share_id: str,
    request: Request,
    user_id: str = Depends(get_authenticated_user_id),
):
    ok = await get_patient_data_share_service().revoke(user_id, share_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Share not found")
    return ShareRevokeResponse(message="Share revoked.")
