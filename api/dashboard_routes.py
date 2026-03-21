"""
Dashboard Routes
Aggregated patient dashboard summary.
"""

import logging

from fastapi import APIRouter, Depends

from api.auth import get_authenticated_user_id
from models.dashboard_schemas import DashboardSummaryResponse
from services.dashboard_service import get_dashboard_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Dashboard"])


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    user_id: str = Depends(get_authenticated_user_id),
):
    """
    Get an aggregated dashboard summary for the authenticated patient.
    
    Includes wellness score (from mood), mood trend, streak, next appointment,
    and a daily inspirational quote.
    """
    service = get_dashboard_service()
    result = service.get_summary(user_id)
    return DashboardSummaryResponse(**result)
