"""
Dashboard Service
Aggregates data from Mood and Appointment services for the patient dashboard.
"""

import logging
import random
from datetime import datetime, timedelta
from typing import Optional

from services.mood_service import get_mood_service
from services.appointment_service import get_appointment_service

logger = logging.getLogger(__name__)

QUOTES = [
    {"text": "You are braver than you believe, stronger than you seem, and smarter than you think.", "author": "A.A. Milne"},
    {"text": "The human spirit is stronger than anything that can happen to it.", "author": "C.C. Scott"},
    {"text": "Courage doesn't always roar. Sometimes courage is the quiet voice at the end of the day saying, 'I will try again tomorrow.'", "author": "Mary Anne Radmacher"},
    {"text": "You never know how strong you are until being strong is the only choice you have.", "author": "Bob Marley"},
    {"text": "Every day may not be good, but there is something good in every day.", "author": "Alice Morse Earle"},
    {"text": "What lies behind us and what lies before us are tiny matters compared to what lies within us.", "author": "Ralph Waldo Emerson"},
    {"text": "Hope is the thing with feathers that perches in the soul.", "author": "Emily Dickinson"},
    {"text": "One day at a time. One step at a time. One breath at a time.", "author": "Unknown"},
]


class DashboardService:

    def get_summary(self, user_id: str) -> dict:
        mood_service = get_mood_service()
        appt_service = get_appointment_service()

        recent_items = mood_service.get_recent_entries(user_id, days=30)

        avg_mood = None
        wellness_score = None
        trend_direction = None
        trend_percentage = None
        streak_days = 0

        if recent_items:
            scores = [int(item.get("mood_score", 0)) for item in recent_items]
            avg_mood = round(sum(scores) / len(scores), 1)
            wellness_score = avg_mood

            trend_direction, trend_percentage = mood_service._calculate_trend(recent_items)
            streak_days = self._calculate_streak(recent_items)

        next_appt_raw = appt_service.get_next_upcoming(user_id)
        next_appointment = None
        if next_appt_raw:
            next_appointment = {
                "id": next_appt_raw["id"],
                "title": next_appt_raw["title"],
                "date": next_appt_raw["date"],
                "time": next_appt_raw["time"],
                "location": next_appt_raw.get("location"),
            }

        daily_quote = random.choice(QUOTES)

        return {
            "wellness_score": wellness_score,
            "streak_days": streak_days,
            "avg_mood": avg_mood,
            "trend_direction": trend_direction,
            "trend_percentage": trend_percentage,
            "next_appointment": next_appointment,
            "daily_quote": daily_quote,
        }

    @staticmethod
    def _calculate_streak(items: list) -> int:
        """Count consecutive days (up to today) that have at least one entry."""
        if not items:
            return 0

        dates_with_entries = set()
        for item in items:
            try:
                ts = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
                dates_with_entries.add(ts.date())
            except (ValueError, KeyError):
                continue

        streak = 0
        day = datetime.utcnow().date()

        while day in dates_with_entries:
            streak += 1
            day -= timedelta(days=1)

        return streak


# ================================
# Singleton
# ================================

_service_instance: Optional[DashboardService] = None


def get_dashboard_service() -> DashboardService:
    global _service_instance
    if _service_instance is None:
        _service_instance = DashboardService()
    return _service_instance
