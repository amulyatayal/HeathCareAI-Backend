"""
Shared helpers for community events (date/time, API mapping).
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_date_time_utc(date_str: str, time_str: str) -> datetime:
    """Parse YYYY-MM-DD and HH:MM as UTC."""
    return datetime.strptime(
        f"{date_str.strip()} {time_str.strip()}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=timezone.utc)


def combine_date_time_iso(date_str: str, time_str: str) -> str:
    return parse_date_time_utc(date_str, time_str).isoformat().replace("+00:00", "Z")


def _int_field(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return int(value)
    return int(value)


def to_event_response(item: dict, user_has_rsvp: Optional[bool] = None) -> dict:
    out: Dict[str, Any] = {
        "id": item["event_id"],
        "hospital_id": item.get("hospital_id"),
        "title": item.get("title", ""),
        "starts_at": item.get("starts_at", ""),
        "location": item.get("location"),
        "type": item.get("type", "wellness"),
        "is_virtual": bool(item.get("is_virtual", False)),
        "description": item.get("description"),
        "status": item.get("status", "published"),
        "attendee_count": _int_field(item.get("attendee_count"), 0),
        "created_at": item.get("created_at", ""),
        "updated_at": item.get("updated_at", ""),
    }
    if user_has_rsvp is not None:
        out["user_has_rsvp"] = user_has_rsvp
    return out
