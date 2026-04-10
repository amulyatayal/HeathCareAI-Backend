"""
Patient consent storage (PatientConsents) and audit integration.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Literal, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from config.settings import settings
from models.patient_consent_schemas import (
    CookieConsentRequest,
    DataConsentRequest,
    DataProcessingChoices,
)
from services.patient_compliance_audit_service import get_patient_compliance_audit_service
from services.patient_profile_service import get_patient_profile_service

logger = logging.getLogger(__name__)

TABLE_NAME = "PatientConsents"
CONSENT_COOKIES = "cookies"
CONSENT_DATA = "data"


def _normalize_data_choices(choices: DataProcessingChoices) -> Dict[str, Any]:
    d = choices.model_dump()
    d["coreService"] = True
    d["clinicalSharing"] = True
    return d


def _cookie_prefs_dict(prefs: Any) -> Dict[str, Any]:
    if hasattr(prefs, "model_dump"):
        return prefs.model_dump()
    return dict(prefs)


class PatientConsentService:
    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self.dynamodb.Table(TABLE_NAME)

    def _get_row(self, user_id: str, consent_type: str) -> Optional[Dict[str, Any]]:
        try:
            r = self.table.get_item(Key={"user_id": user_id, "consent_type": consent_type})
            return r.get("Item")
        except ClientError as e:
            logger.error("PatientConsents get_item failed: %s", e)
            raise

    def _is_active(self, item: Optional[Dict[str, Any]]) -> bool:
        if not item:
            return False
        return not item.get("withdrawn_at")

    async def save_cookie_consent(
        self,
        user_id: str,
        body: CookieConsentRequest,
        *,
        ip: Optional[str],
        user_agent: Optional[str],
        hospital_id: Optional[str],
        jurisdiction: str = "UNKNOWN",
    ) -> Tuple[str, str]:
        prefs = _cookie_prefs_dict(body.preferences)
        prefs["necessary"] = True

        prev = self._get_row(user_id, CONSENT_COOKIES)
        had_active = self._is_active(prev)
        consent_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + "Z"

        item = {
            "user_id": user_id,
            "consent_type": CONSENT_COOKIES,
            "consent_id": consent_id,
            "granted_at": now,
            "source": body.source,
            "preferences": prefs,
        }

        self.table.put_item(Item=item)

        audit = get_patient_compliance_audit_service()
        action = "consent_updated" if had_active else "consent_granted"
        await audit.record_event(
            user_id=user_id,
            action=action,
            payload={
                "consent_type": CONSENT_COOKIES,
                "consent_id": consent_id,
                "preferences": prefs,
                "source": body.source,
            },
            ip=ip,
            user_agent=user_agent,
            hospital_id=hospital_id,
            jurisdiction=jurisdiction,
        )
        return consent_id, "Cookie preferences saved."

    async def save_data_consent(
        self,
        user_id: str,
        body: DataConsentRequest,
        *,
        ip: Optional[str],
        user_agent: Optional[str],
        hospital_id: Optional[str],
        jurisdiction: str = "UNKNOWN",
    ) -> Tuple[str, str]:
        choices = _normalize_data_choices(body.choices)
        prev = self._get_row(user_id, CONSENT_DATA)
        had_active = self._is_active(prev)
        consent_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + "Z"

        item = {
            "user_id": user_id,
            "consent_type": CONSENT_DATA,
            "consent_id": consent_id,
            "granted_at": now,
            "source": body.source,
            "choices": choices,
        }

        self.table.put_item(Item=item)

        profile_service = get_patient_profile_service()
        await profile_service.set_data_processing_paused(user_id, False)

        audit = get_patient_compliance_audit_service()
        action = "consent_updated" if had_active else "consent_granted"
        await audit.record_event(
            user_id=user_id,
            action=action,
            payload={
                "consent_type": CONSENT_DATA,
                "consent_id": consent_id,
                "choices": choices,
                "source": body.source,
            },
            ip=ip,
            user_agent=user_agent,
            hospital_id=hospital_id,
            jurisdiction=jurisdiction,
        )
        return consent_id, "Data processing consent saved."

    async def get_status(self, user_id: str) -> Dict[str, Any]:
        cookies = self._get_row(user_id, CONSENT_COOKIES)
        data = self._get_row(user_id, CONSENT_DATA)

        cookie_consent = None
        if cookies and self._is_active(cookies):
            cookie_consent = {
                "preferences": cookies.get("preferences") or {},
                "granted_at": cookies.get("granted_at") or "",
            }

        data_consent = None
        if data and self._is_active(data):
            data_consent = {
                "choices": data.get("choices") or {},
                "granted_at": data.get("granted_at") or "",
            }

        return {"data_consent": data_consent, "cookie_consent": cookie_consent}

    async def withdraw(
        self,
        user_id: str,
        consent_type: Literal["data", "cookies"],
        *,
        ip: Optional[str],
        user_agent: Optional[str],
        hospital_id: Optional[str],
        jurisdiction: str = "UNKNOWN",
    ) -> str:
        sk = CONSENT_DATA if consent_type == "data" else CONSENT_COOKIES
        row = self._get_row(user_id, sk)
        if not row or not self._is_active(row):
            return "No active consent to withdraw."

        now = datetime.utcnow().isoformat() + "Z"
        try:
            self.table.update_item(
                Key={"user_id": user_id, "consent_type": sk},
                UpdateExpression="SET withdrawn_at = :w",
                ExpressionAttributeValues={":w": now},
            )
        except ClientError as e:
            logger.error("PatientConsents withdraw failed: %s", e)
            raise

        if consent_type == "data":
            await get_patient_profile_service().set_data_processing_paused(user_id, True)

        await get_patient_compliance_audit_service().record_event(
            user_id=user_id,
            action="consent_withdrawn",
            payload={
                "consent_type": sk,
                "consent_id": row.get("consent_id"),
                "withdrawn_at": now,
            },
            ip=ip,
            user_agent=user_agent,
            hospital_id=hospital_id,
            jurisdiction=jurisdiction,
        )
        return "Consent withdrawn."

    def get_consent_rows_for_export(self, user_id: str) -> Dict[str, Any]:
        """Raw consent rows (including withdrawn) for GDPR data export."""
        cookies = self._get_row(user_id, CONSENT_COOKIES)
        data = self._get_row(user_id, CONSENT_DATA)
        return {"cookies": cookies, "data": data}


_service: Optional[PatientConsentService] = None


def get_patient_consent_service() -> PatientConsentService:
    global _service
    if _service is None:
        _service = PatientConsentService()
    return _service
