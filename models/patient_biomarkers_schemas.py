"""
Patient Biomarkers Schemas
Pydantic models for patient biomarker measurements (dynamic, time-series).
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class BiomarkerEntryCreate(BaseModel):
    height_cm: Optional[float] = Field(None, gt=0, description="Height in centimeters")
    weight_kg: Optional[float] = Field(None, gt=0, description="Weight in kilograms")
    bmi: Optional[float] = Field(None, gt=0, description="Body Mass Index")
    waist_circumference_cm: Optional[float] = Field(None, gt=0, description="Waist circumference in centimeters")
    hand_grip_strength_kg: Optional[float] = Field(None, ge=0, description="Hand grip strength in kilograms")
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp; defaults to now")


class BiomarkerEntry(BaseModel):
    entry_id: str
    user_id: str
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    bmi: Optional[float] = None
    waist_circumference_cm: Optional[float] = None
    hand_grip_strength_kg: Optional[float] = None
    timestamp: str


class BiomarkerListResponse(BaseModel):
    entries: List[BiomarkerEntry]
    total_count: int
