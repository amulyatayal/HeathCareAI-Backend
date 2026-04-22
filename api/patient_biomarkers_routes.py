"""
Patient Biomarkers Routes
Endpoints for logging and retrieving patient biomarker entries.
"""

import logging

from fastapi import APIRouter, Depends, Query

from api.auth import get_authenticated_user_id
from api.compliance_dependencies import require_active_data_processing
from models.patient_biomarkers_schemas import BiomarkerEntryCreate, BiomarkerEntry, BiomarkerListResponse
from services.patient_biomarkers_service import get_patient_biomarkers_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Biomarker Tracking"])


@router.post("/biomarkers", response_model=BiomarkerEntry, status_code=201)
async def create_biomarker_entry(
    body: BiomarkerEntryCreate,
    user_id: str = Depends(require_active_data_processing),
):
    """Log a new biomarker snapshot."""
    service = get_patient_biomarkers_service()
    result = await service.create_entry(user_id, body.model_dump())
    return BiomarkerEntry(**result)


@router.get("/biomarkers", response_model=BiomarkerListResponse)
async def list_biomarker_entries(
    limit: int = Query(30, ge=1, le=200),
    user_id: str = Depends(get_authenticated_user_id),
):
    """Get recent biomarker snapshots."""
    service = get_patient_biomarkers_service()
    result = await service.list_entries(user_id, limit=limit)
    return BiomarkerListResponse(**result)
