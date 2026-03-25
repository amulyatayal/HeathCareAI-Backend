"""
Appointment Schemas
Pydantic models for appointment management.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class AppointmentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    time: str = Field(..., description="Time in HH:MM format")
    location: Optional[str] = Field(None, max_length=500)
    reminder: bool = Field(False)


class Appointment(BaseModel):
    id: str
    user_id: str
    title: str
    date: str
    time: str
    location: Optional[str] = None
    reminder: bool = False
    status: str = "upcoming"
    created_at: str


class AppointmentListResponse(BaseModel):
    appointments: List[Appointment]
    total_count: int


class DeleteResponse(BaseModel):
    message: str = "Appointment deleted successfully"
