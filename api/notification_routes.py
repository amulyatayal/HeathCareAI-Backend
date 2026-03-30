"""
Patient notification routes (clinician broadcasts, per-patient read state).

Prefix: /api/v2
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_authenticated_user_id
from models.notification_schemas import (
    PatientNotificationItem,
    PatientNotificationListResponse,
    NotificationMessageResponse,
)
from services.patient_profile_service import get_patient_profile_service
from services.notification_service import get_notification_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Notifications"])

_INVALID_ID_TOKENS = frozenset({"", "undefined", "null", "none"})


def _require_valid_notification_id(notification_id: str) -> str:
    """Reject missing/placeholder IDs (common when frontend passes undefined as string)."""
    nid = (notification_id or "").strip()
    if not nid or nid.lower() in _INVALID_ID_TOKENS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid notification id. Use the `id` field from GET /api/v2/notifications "
                "(ensure the client does not send undefined/null)."
            ),
        )
    return nid


@router.get("/notifications", response_model=PatientNotificationListResponse)
async def list_my_notifications(
    user_id: str = Depends(get_authenticated_user_id),
):
    """
    List notifications for the patient's associated clinician, newest first.
    Empty list if the patient has no clinician association.
    """
    profile_service = get_patient_profile_service()
    profile = await profile_service.get_profile(user_id)
    clinician_id = getattr(profile, "clinician_id", None) if profile else None

    svc = get_notification_service()
    rows = svc.list_for_patient(user_id, clinician_id)
    return PatientNotificationListResponse(
        notifications=[PatientNotificationItem(**r) for r in rows]
    )


@router.patch("/notifications/read-all", response_model=NotificationMessageResponse)
async def mark_all_notifications_read(
    user_id: str = Depends(get_authenticated_user_id),
):
    """Mark all notifications from the patient's clinician as read."""
    profile_service = get_patient_profile_service()
    profile = await profile_service.get_profile(user_id)
    clinician_id = getattr(profile, "clinician_id", None) if profile else None

    svc = get_notification_service()
    svc.mark_all_read(user_id, clinician_id)
    return NotificationMessageResponse(message="All notifications marked as read")


@router.patch("/notifications/{notification_id}/read", response_model=NotificationMessageResponse)
async def mark_notification_read(
    notification_id: str,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Mark a single notification as read."""
    notification_id = _require_valid_notification_id(notification_id)

    profile_service = get_patient_profile_service()
    profile = await profile_service.get_profile(user_id)
    clinician_id = getattr(profile, "clinician_id", None) if profile else None

    svc = get_notification_service()
    ok = svc.mark_read(user_id, notification_id, clinician_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return NotificationMessageResponse(message="Notification marked as read")
