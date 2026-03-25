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
    {"text": "She stood in the storm, and when the wind did not blow her way, she adjusted her sails.", "author": "Elizabeth Edwards"},
    {"text": "The wound is the place where the Light enters you.", "author": "Rumi"},
    {"text": "In the middle of difficulty lies opportunity.", "author": "Albert Einstein"},
    {"text": "You gain strength, courage, and confidence by every experience in which you really stop to look fear in the face.", "author": "Eleanor Roosevelt"},
    {"text": "When you come out of the storm, you won't be the same person who walked in. That's what the storm is all about.", "author": "Haruki Murakami"},
    {"text": "There is no medicine like hope, no incentive so great, and no tonic so powerful as expectation of something tomorrow.", "author": "Orison Swett Marden"},
    {"text": "Healing takes courage, and we all have courage, even if we have to dig a little to find it.", "author": "Tori Amos"},
    {"text": "Although the world is full of suffering, it is also full of the overcoming of it.", "author": "Helen Keller"},
    {"text": "Turn your wounds into wisdom.", "author": "Oprah Winfrey"},
    {"text": "Nothing is impossible. The word itself says 'I'm possible.'", "author": "Audrey Hepburn"},
    {"text": "Fall seven times, stand up eight.", "author": "Japanese Proverb"},
    {"text": "The only way out is through.", "author": "Robert Frost"},
    {"text": "Out of difficulties grow miracles.", "author": "Jean de La Bruyere"},
    {"text": "Keep your face always toward the sunshine, and shadows will fall behind you.", "author": "Walt Whitman"},
    {"text": "We must accept finite disappointment, but never lose infinite hope.", "author": "Martin Luther King Jr."},
    {"text": "Rock bottom became the solid foundation on which I rebuilt my life.", "author": "J.K. Rowling"},
    {"text": "Stars can't shine without darkness.", "author": "D.H. Sidebottom"},
    {"text": "Believe you can and you're halfway there.", "author": "Theodore Roosevelt"},
    {"text": "A smooth sea never made a skilled sailor.", "author": "Franklin D. Roosevelt"},
    {"text": "The struggle you're in today is developing the strength you need for tomorrow.", "author": "Robert Tew"},
    {"text": "Tough times never last, but tough people do.", "author": "Robert H. Schuller"},
    {"text": "Life is 10% what happens to us and 90% how we react to it.", "author": "Charles R. Swindoll"},
    {"text": "Your present circumstances don't determine where you can go; they merely determine where you start.", "author": "Nido Qubein"},
    {"text": "The best way out is always through.", "author": "Robert Frost"},
    {"text": "Do not judge me by my success, judge me by how many times I fell down and got back up again.", "author": "Nelson Mandela"},
    {"text": "It is during our darkest moments that we must focus to see the light.", "author": "Aristotle"},
    {"text": "We don't know how strong we are until being strong is the only option.", "author": "Unknown"},
    {"text": "Strength does not come from physical capacity. It comes from an indomitable will.", "author": "Mahatma Gandhi"},
    {"text": "With the new day comes new strength and new thoughts.", "author": "Eleanor Roosevelt"},
    {"text": "Be gentle with yourself. You're doing the best you can.", "author": "Unknown"},
    {"text": "This too shall pass.", "author": "Persian Proverb"},
    {"text": "Where there is no struggle, there is no strength.", "author": "Oprah Winfrey"},
    {"text": "Rest if you must, but don't you quit.", "author": "John Greenleaf Whittier"},
    {"text": "Sometimes the bravest thing you can do is ask for help.", "author": "Unknown"},
    {"text": "Not all storms come to disrupt your life; some come to clear your path.", "author": "Paulo Coelho"},
    {"text": "Difficult roads often lead to beautiful destinations.", "author": "Zig Ziglar"},
    {"text": "Healing is not linear.", "author": "Unknown"},
    {"text": "You are allowed to be both a masterpiece and a work in progress simultaneously.", "author": "Sophia Bush"},
    {"text": "Promise me you'll always remember: you're braver than you believe, and stronger than you seem, and smarter than you think.", "author": "A.A. Milne"},
    {"text": "The sun himself is weak when he first rises, and gathers strength and courage as the day gets on.", "author": "Charles Dickens"},
    {"text": "No one ever told me that grief felt so like fear.", "author": "C.S. Lewis"},
    {"text": "When everything seems to be going against you, remember that the airplane takes off against the wind, not with it.", "author": "Henry Ford"},
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
