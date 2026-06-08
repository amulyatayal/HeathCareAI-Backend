"""
Patient community events — list, detail, RSVP.

Prefix: /api/v2
Clinician-scoped: patients see events from their associated clinician only.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import get_authenticated_user_id
from api.compliance_dependencies import require_active_community_consent
from models.event_schemas import (
    EventDetailResponse,
    EventMutationResponse,
    EventResponse,
    EventType,
    PatientEventListResponse,
)
from services.admin_events_service import STATUS_PUBLISHED, get_admin_events_service
from services.patient_events_service import get_patient_events_service
from services.patient_profile_service import get_patient_profile_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Community Events"])


async def _profile_clinician_id(user_id: str) -> Optional[str]:
    profile = await get_patient_profile_service().get_profile(user_id)
    return getattr(profile, "clinician_id", None) if profile else None


def _event_is_in_past(starts_at: str) -> bool:
    try:
        dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)
    except ValueError:
        return False


@router.get("/events", response_model=PatientEventListResponse)
async def list_events(
    when: str = Query("upcoming", pattern="^(upcoming|past)$"),
    type: Optional[EventType] = Query(None, alias="type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_authenticated_user_id),
):
    """List published events for the patient's associated clinician."""
    clinician_id = await _profile_clinician_id(user_id)
    svc = get_patient_events_service()
    result = svc.list_events(
        user_id,
        clinician_id,
        when=when,
        type_filter=type.value if type else None,
        limit=limit,
        offset=offset,
    )
    return PatientEventListResponse(**result)


@router.get("/events/{event_id}", response_model=EventDetailResponse)
async def get_event(
    event_id: str,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Single event detail with RSVP flag."""
    clinician_id = await _profile_clinician_id(user_id)
    svc = get_patient_events_service()
    event = svc.get_event(user_id, clinician_id, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventDetailResponse(event=EventResponse(**event))


@router.post("/events/{event_id}/rsvp", response_model=EventMutationResponse)
async def rsvp_to_event(
    event_id: str,
    user_id: str = Depends(require_active_community_consent),
):
    """RSVP to an upcoming published event (idempotent)."""
    clinician_id = await _profile_clinician_id(user_id)
    admin_svc = get_admin_events_service()
    raw = admin_svc.get_event_raw(event_id)
    if (
        not raw
        or raw.get("clinician_id") != clinician_id
        or raw.get("status") != STATUS_PUBLISHED
    ):
        raise HTTPException(status_code=404, detail="Event not found")
    if _event_is_in_past(raw.get("starts_at", "")):
        raise HTTPException(status_code=422, detail="Cannot RSVP to a past event")

    svc = get_patient_events_service()
    event = svc.rsvp(user_id, event_id, clinician_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventMutationResponse(message="RSVP confirmed", event=EventResponse(**event))


@router.delete("/events/{event_id}/rsvp", response_model=EventMutationResponse)
async def cancel_rsvp(
    event_id: str,
    user_id: str = Depends(require_active_community_consent),
):
    """Remove RSVP (idempotent)."""
    clinician_id = await _profile_clinician_id(user_id)
    svc = get_patient_events_service()
    event = svc.cancel_rsvp(user_id, event_id, clinician_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventMutationResponse(message="RSVP removed", event=EventResponse(**event))
