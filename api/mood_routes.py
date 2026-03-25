"""
Mood Tracking Routes
Endpoints for logging and retrieving patient mood entries.
"""

import logging

from fastapi import APIRouter, Depends, Query

from api.auth import get_authenticated_user_id
from models.mood_schemas import MoodEntryCreate, MoodEntry, MoodListResponse
from services.mood_service import get_mood_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Mood Tracking"])


@router.post("/mood", response_model=MoodEntry, status_code=201)
async def create_mood_entry(
    body: MoodEntryCreate,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Log a new mood entry."""
    service = get_mood_service()
    result = await service.create_entry(user_id, body.model_dump())
    return MoodEntry(**result)


@router.get("/mood", response_model=MoodListResponse)
async def list_mood_entries(
    limit: int = Query(30, ge=1, le=200),
    user_id: str = Depends(get_authenticated_user_id),
):
    """Get recent mood entries with trend analysis."""
    service = get_mood_service()
    result = await service.list_entries(user_id, limit=limit)
    return MoodListResponse(**result)
