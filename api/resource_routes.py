"""
Patient-Facing Resource Routes
Serves educational resources to patients based on their pathway stage.

Endpoint: GET /api/v2/resources?stage_id={stageId}
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from models.admin_schemas import (
    PatientResourceResponse,
    PatientResourceListResponse,
)
from services.pathway_resource_service import get_pathway_resource_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Patient Resources"])


@router.get("/resources", response_model=PatientResourceListResponse)
async def get_resources_for_stage(
    stage_id: str = Query(..., description="Treatment pathway stage ID (e.g., '2', '2.1', '2.1.1')"),
):
    """
    Get educational resources relevant to a patient's pathway stage.
    
    Uses hierarchical matching — a resource tagged with stage "2" (Surgery)
    will also appear for a patient on stage "2.1.1" (Lumpectomy).
    """
    service = get_pathway_resource_service()
    results = service.get_resources_for_stage(stage_id)
    
    return PatientResourceListResponse(
        resources=[PatientResourceResponse(**r) for r in results]
    )
