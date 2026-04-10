"""
Resolve patient legal jurisdiction from X-Hospital-Id header and/or profile hospital_id.
"""

from typing import Optional

from fastapi import Request

from config.settings import settings


def resolve_jurisdiction(request: Request, profile_hospital_id: Optional[str]) -> str:
    hdr = request.headers.get("X-Hospital-Id") or request.headers.get("x-hospital-id")
    hid = (hdr or profile_hospital_id or "").strip()
    if not hid:
        return "UNKNOWN"
    m = settings.hospital_jurisdiction_map
    return str(m.get(hid, "UNKNOWN")).upper()


def is_india(jurisdiction: str) -> bool:
    return jurisdiction.upper() == "IN"
