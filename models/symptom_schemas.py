"""
Symptom Tracking Schemas
Pydantic models for symptom entry creation, listing, and trend analysis.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class SymptomEntryCreate(BaseModel):
    symptom_name: str = Field(..., min_length=1, max_length=200)
    severity: int = Field(..., ge=1, le=10, description="Severity 1 (mild) to 10 (severe)")
    notes: Optional[str] = Field(None, max_length=2000)
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp; defaults to now")


class SymptomEntry(BaseModel):
    entry_id: str
    user_id: str
    symptom_name: str
    severity: int
    notes: Optional[str] = None
    timestamp: str


class SymptomListResponse(BaseModel):
    entries: List[SymptomEntry]
    total_count: int


class SymptomTrend(BaseModel):
    symptom_name: str
    direction: str
    change_percentage: float


class SymptomTrendsResponse(BaseModel):
    trends: List[SymptomTrend]
