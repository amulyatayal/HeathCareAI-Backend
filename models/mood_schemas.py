"""
Mood Tracking Schemas
Pydantic models for mood entry creation and listing.
"""

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class QuickCheck(BaseModel):
    """Optional quick health check alongside mood."""
    sleep_quality: Optional[int] = Field(None, ge=0, le=10)
    physical_discomfort: Optional[int] = Field(None, ge=0, le=10)
    energy_level: Optional[int] = Field(None, ge=0, le=10)


def _quick_check_has_content(qc: Optional[QuickCheck]) -> bool:
    if qc is None:
        return False
    return any(
        v is not None
        for v in (qc.sleep_quality, qc.physical_discomfort, qc.energy_level)
    )


class MoodEntryCreate(BaseModel):
    mood_score: Optional[int] = Field(
        None, ge=0, le=10, description="Mood score 0 (worst) to 10 (best)"
    )
    note: Optional[str] = Field(None, max_length=2000)
    emotions: List[str] = Field(default_factory=list)
    triggers: List[str] = Field(default_factory=list)
    quick_check: Optional[QuickCheck] = None
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp; defaults to now")

    @model_validator(mode="after")
    def require_content_without_score(self) -> "MoodEntryCreate":
        if self.mood_score is not None:
            return self
        has_other = (
            bool(self.note and self.note.strip())
            or bool(self.emotions)
            or bool(self.triggers)
            or _quick_check_has_content(self.quick_check)
        )
        if not has_other:
            raise ValueError(
                "Provide mood_score or at least one of: note, emotions, triggers, quick_check"
            )
        return self


class MoodEntry(BaseModel):
    entry_id: str
    user_id: str
    mood_score: Optional[int] = None
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
