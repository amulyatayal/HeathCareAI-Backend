"""
Patient-Facing Resource Routes
Serves educational resources to patients based on their pathway stage.

If the patient is authenticated and has a clinician association,
resources are filtered to that clinician. Otherwise all resources
for the stage (or all resources if no stage) are returned.

Endpoint: GET /api/v2/resources?stage_id={stageId} (stage_id optional)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query, Request

from models.admin_schemas import (
    PatientResourceResponse,
    PatientResourceListResponse,
)
from services.pathway_resource_service import get_pathway_resource_service
from services.patient_profile_service import get_patient_profile_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Patient Resources"])


def _try_extract_user_id(request: Request) -> Optional[str]:
    """Best-effort extraction of user_id from JWT. Returns None on failure."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    try:
        from jwt import decode
        decoded = decode(auth_header[7:], options={"verify_signature": False})
        return decoded.get("sub") or decoded.get("user_id") or decoded.get("uid")
    except Exception:
        return None


@router.get("/resources", response_model=PatientResourceListResponse)
async def get_resources_for_stage(
    request: Request,
    stage_id: Optional[str] = Query(
        None,
        description=(
            "Treatment pathway stage ID (e.g. '2', '2.1', '2.1.1'). "
            "Omit to return resources for all stages (still scoped by clinician when associated)."
        ),
    ),
):
    """
    Get educational resources for a pathway stage, or all stages if ``stage_id`` is omitted.

    With ``stage_id``: uses hierarchical matching — a resource tagged with stage "2"
    also appears for a patient on stage "2.1.1".

    Without ``stage_id``: returns every non-deleted resource row (all stages), with the
    same clinician scoping rules as below.

    If the authenticated patient has a clinician association, only that clinician's
    resources are included. Otherwise resources from all clinicians are included.
    """
    resource_service = get_pathway_resource_service()

    user_id = _try_extract_user_id(request)
    clinician_id = None

    if user_id:
        try:
            profile_service = get_patient_profile_service()
            profile = await profile_service.get_profile(user_id)
            if profile:
                clinician_id = getattr(profile, "clinician_id", None)
        except Exception:
            pass

    stage = str(stage_id).strip() if stage_id is not None and str(stage_id).strip() else None

    if stage:
        if clinician_id:
            results = resource_service.get_resources_for_stage_and_clinician(stage, clinician_id)
        else:
            results = resource_service.get_resources_for_stage(stage)
    else:
        if clinician_id:
            results = resource_service.get_all_resources_for_clinician(clinician_id)
        else:
            results = resource_service.get_all_resources()

    return PatientResourceListResponse(
        resources=[PatientResourceResponse(**r) for r in results]
    )
