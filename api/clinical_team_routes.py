"""
Patient clinical team — read-only roster for associated clinician.

Prefix: /api/v2
Clinician-scoped via PatientProfiles.clinician_id (not hospital-filtered).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.auth import get_authenticated_user_id
from models.clinical_team_schemas import (
    PatientTeamMemberListResponse,
    TeamMemberResponse,
)
from services.admin_clinical_team_service import get_admin_clinical_team_service
from services.patient_profile_service import get_patient_profile_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Clinical Team"])


async def _profile_clinician_id(user_id: str) -> Optional[str]:
    profile = await get_patient_profile_service().get_profile(user_id)
    return getattr(profile, "clinician_id", None) if profile else None


@router.get("/clinical-team", response_model=PatientTeamMemberListResponse)
async def list_clinical_team(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_authenticated_user_id),
):
    """Care team roster for the patient's associated clinician."""
    clinician_id = await _profile_clinician_id(user_id)
    if not clinician_id:
        return PatientTeamMemberListResponse(
            team_members=[],
            total_count=0,
            clinician_id=None,
        )

    svc = get_admin_clinical_team_service()
    result = svc.list_members(clinician_id, limit=limit, offset=offset)
    return PatientTeamMemberListResponse(
        team_members=[TeamMemberResponse(**m) for m in result["team_members"]],
        total_count=result["total_count"],
        clinician_id=clinician_id,
    )
