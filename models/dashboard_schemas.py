"""
Dashboard Schemas
Pydantic models for the patient dashboard summary.
"""

from typing import Optional

from pydantic import BaseModel


class NextAppointment(BaseModel):
    id: str
    title: str
    date: str
    time: str
    location: Optional[str] = None


class DailyQuote(BaseModel):
    text: str
    author: str


class DashboardSummaryResponse(BaseModel):
    wellness_score: Optional[float] = None
    streak_days: int = 0
    avg_mood: Optional[float] = None
    trend_direction: Optional[str] = None
    trend_percentage: Optional[float] = None
    next_appointment: Optional[NextAppointment] = None
    daily_quote: Optional[DailyQuote] = None
