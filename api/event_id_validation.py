"""Shared validation for event id path segments."""

from fastapi import HTTPException

_INVALID_ID_TOKENS = frozenset({"", "undefined", "null", "none"})


def require_valid_event_id(event_id: str, *, list_endpoint: str) -> str:
    eid = (event_id or "").strip()
    if not eid or eid.lower() in _INVALID_ID_TOKENS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid event id. Use the `id` field from {list_endpoint} "
                "(do not use undefined/null in the URL)."
            ),
        )
    return eid
