"""
Pydantic schemas for community events (admin CRUD + patient RSVP).
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class EventType(str, Enum):
    WELLNESS = "wellness"
    SUPPORT = "support"
    EDUCATION = "education"


class EventStatus(str, Enum):
    PUBLISHED = "published"
    CANCELLED = "cancelled"


class EventCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    date: str = Field(..., description="YYYY-MM-DD")
    time: str = Field(..., description="HH:MM 24-hour")
    location: Optional[str] = Field(None, max_length=500)
    type: EventType = EventType.WELLNESS
    is_virtual: bool = False
    description: Optional[str] = Field(None, max_length=10000)

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        datetime.strptime(v.strip(), "%Y-%m-%d")
        return v.strip()

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        parts = v.strip().split(":")
        if len(parts) != 2:
            raise ValueError("time must be HH:MM (24-hour)")
        return v.strip()


class EventUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    date: Optional[str] = None
    time: Optional[str] = None
    location: Optional[str] = Field(None, max_length=500)
    type: Optional[EventType] = None
    is_virtual: Optional[bool] = None
    description: Optional[str] = Field(None, max_length=10000)

    @model_validator(mode="after")
    def date_time_pair(self) -> "EventUpdateRequest":
        if (self.date is None) ^ (self.time is None):
            raise ValueError("date and time must both be provided when updating schedule")
        return self


class EventResponse(BaseModel):
    id: str
    hospital_id: Optional[str] = None
    title: str
    starts_at: str
    location: Optional[str] = None
    type: EventType
    is_virtual: bool
    description: Optional[str] = None
    status: EventStatus
    attendee_count: int
    user_has_rsvp: Optional[bool] = None
    created_at: str
    updated_at: str


class AdminEventListResponse(BaseModel):
    events: List[EventResponse]
    total_count: int


class PatientEventListResponse(BaseModel):
    events: List[EventResponse]
    total_count: int


class EventDetailResponse(BaseModel):
    event: EventResponse


class AdminEventCreateResponse(BaseModel):
    id: str
    message: str
    event: EventResponse


class EventMutationResponse(BaseModel):
    message: str
    event: EventResponse


class EventMessageResponse(BaseModel):
    message: str
