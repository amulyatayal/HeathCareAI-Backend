"""
User-facing activity log derived from PatientComplianceAuditEvents.
"""

import logging
from typing import Any, Dict, List, Optional

from services.patient_compliance_audit_service import get_patient_compliance_audit_service

logger = logging.getLogger(__name__)

ALLOWED_TYPES = frozenset(
    {
        "consent_granted",
        "consent_withdrawn",
        "consent_updated",
        "data_exported",
        "account_deletion_requested",
        "nominee_updated",
        "grievance_submitted",
        "share_generated",
        "share_revoked",
        "login",
        "account_created",
    }
)


def _describe(action: str, payload: Optional[Dict[str, Any]]) -> str:
    p = payload or {}
    if action == "consent_granted":
        return f"Consent granted ({p.get('consent_type', 'unknown')})."
    if action == "consent_withdrawn":
        return f"Consent withdrawn ({p.get('consent_type', 'unknown')})."
    if action == "consent_updated":
        return f"Consent updated ({p.get('consent_type', 'unknown')})."
    if action == "data_exported":
        return "Data export downloaded."
    if action == "account_deletion_requested":
        return "Account deletion requested."
    if action == "nominee_updated":
        return "Nominee details updated."
    if action == "grievance_submitted":
        return f"Grievance submitted ({p.get('grievance_id', '')})."
    if action == "share_generated":
        return "Data share link generated."
    if action == "share_revoked":
        return "Data share revoked."
    if action == "login":
        return "Login recorded."
    if action == "account_created":
        return "Account created."
    return action.replace("_", " ").title()


class PatientActivityLogService:
    async def list_for_user(self, user_id: str, limit: int = 20) -> Dict[str, Any]:
        raw = await get_patient_compliance_audit_service().list_events_for_user(
            user_id, limit=max(limit * 3, 100)
        )
        activities: List[Dict[str, Any]] = []
        for it in raw:
            action = it.get("action") or ""
            if action not in ALLOWED_TYPES:
                continue
            activities.append(
                {
                    "id": it.get("event_id"),
                    "type": action,
                    "description": _describe(action, it.get("payload")),
                    "timestamp": it.get("occurred_at") or "",
                }
            )
            if len(activities) >= limit:
                break
        return {"activities": activities}


_service: Optional[PatientActivityLogService] = None


def get_patient_activity_log_service() -> PatientActivityLogService:
    global _service
    if _service is None:
        _service = PatientActivityLogService()
    return _service
