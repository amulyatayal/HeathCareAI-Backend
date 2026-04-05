"""
Symptom Tracking Routes
Endpoints for logging, retrieving, and analysing patient symptoms.
"""

import logging

from fastapi import APIRouter, Depends, Query

from api.auth import get_authenticated_user_id
from api.compliance_dependencies import require_active_data_processing
from models.symptom_schemas import (
    SymptomEntryCreate,
    SymptomEntry,
    SymptomListResponse,
    SymptomTrendsResponse,
    SymptomTrend,
)
from services.symptom_service import get_symptom_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Symptom Tracking"])


@router.post("/symptoms", response_model=SymptomEntry, status_code=201)
async def create_symptom_entry(
    body: SymptomEntryCreate,
    user_id: str = Depends(require_active_data_processing),
):
    """Log a new symptom entry."""
    service = get_symptom_service()
    result = await service.create_entry(user_id, body.model_dump())
    return SymptomEntry(**result)


@router.get("/symptoms", response_model=SymptomListResponse)
async def list_symptom_entries(
    limit: int = Query(30, ge=1, le=200),
    user_id: str = Depends(get_authenticated_user_id),
):
    """Get recent symptom entries."""
    service = get_symptom_service()
    result = await service.list_entries(user_id, limit=limit)
    return SymptomListResponse(**result)


@router.get("/symptoms/trends", response_model=SymptomTrendsResponse)
async def get_symptom_trends(
    user_id: str = Depends(get_authenticated_user_id),
):
    """Get per-symptom severity trends (last 7 days vs prior 7 days)."""
    service = get_symptom_service()
    trends = await service.get_trends(user_id)
    return SymptomTrendsResponse(trends=[SymptomTrend(**t) for t in trends])
