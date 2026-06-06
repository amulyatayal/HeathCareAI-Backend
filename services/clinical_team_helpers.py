"""
Shared helpers for clinician care team (API mapping, sorting).
"""

from decimal import Decimal
from typing import Any, Dict, List

from services.event_helpers import utc_now_iso


def _int_field(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return int(value)
    return int(value)


def to_team_member_response(item: dict) -> dict:
    return {
        "id": item["team_member_id"],
        "clinician_id": item.get("clinician_id", ""),
        "name": item.get("name", ""),
        "role": item.get("role", ""),
        "specialty": item.get("specialty"),
        "contact_email": item.get("contact_email"),
        "contact_phone": item.get("contact_phone"),
        "avatar_url": item.get("avatar_url"),
        "display_order": _int_field(item.get("display_order"), 0),
        "created_at": item.get("created_at", ""),
        "updated_at": item.get("updated_at", ""),
    }


def sort_team_members(items: List[dict]) -> List[dict]:
    return sorted(
        items,
        key=lambda x: (
            _int_field(x.get("display_order"), 0),
            (x.get("name") or "").lower(),
        ),
    )
