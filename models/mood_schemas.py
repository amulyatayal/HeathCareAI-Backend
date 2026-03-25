"""
Mood Tracking Schemas
Pydantic models for mood entry creation and listing.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class QuickCheck(BaseModel):
    """Optional quick health check alongside mood."""
    sleep_quality: Optional[int] = Field(None, ge=0, le=10)
    physical_discomfort: Optional[int] = Field(None, ge=0, le=10)
    energy_level: Optional[int] = Field(None, ge=0, le=10)


class MoodEntryCreate(BaseModel):
    mood_score: int = Field(..., ge=0, le=10, description="Mood score 0 (worst) to 10 (best)")
    note: Optional[str] = Field(None, max_length=2000)
    emotions: List[str] = Field(default_factory=list)
    triggers: List[str] = Field(default_factory=list)
    quick_check: Optional[QuickCheck] = None
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp; defaults to now")


class MoodEntry(BaseModel):
    entry_id: str
    user_id: str
    mood_score: int
    note: Optional[str] = None
    emotions: List[str] = Field(default_factory=list)
    triggers: List[str] = Field(default_factory=list)
    quick_check: Optional[QuickCheck] = None
    timestamp: str


class MoodListResponse(BaseModel):
    entries: List[MoodEntry]
    total_count: int
    avg_mood: Optional[float] = None
    trend_direction: Optional[str] = None
    trend_percentage: Optional[float] = None
