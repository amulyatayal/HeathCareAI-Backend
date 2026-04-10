"""
DPDPA nominee (India): one record per patient, sensitive fields encrypted with Fernet.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

from config.settings import settings
from services.nominee_crypto import decrypt_field, encrypt_field
from services.patient_compliance_audit_service import get_patient_compliance_audit_service

logger = logging.getLogger(__name__)

TABLE_NAME = "PatientNominees"


class PatientNomineeService:
    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self.dynamodb.Table(TABLE_NAME)

    async def upsert_nominee(
        self,
        user_id: str,
        *,
        name: str,
        email: str,
        relationship: str,
        phone: Optional[str],
        ip: Optional[str],
        user_agent: Optional[str],
        hospital_id: Optional[str],
        jurisdiction: str,
    ) -> str:
        now = datetime.utcnow().isoformat() + "Z"
        existing = self.table.get_item(Key={"user_id": user_id}).get("Item")
        nominee_id = (existing or {}).get("nominee_id") or str(uuid.uuid4())
        created_at = (existing or {}).get("created_at") or now
        item = {
            "user_id": user_id,
            "nominee_id": nominee_id,
            "name_cipher": encrypt_field(name),
            "email_cipher": encrypt_field(email),
            "phone_cipher": encrypt_field(phone or ""),
            "relationship": relationship,
            "updated_at": now,
            "created_at": created_at,
        }
        self.table.put_item(Item=item)

        await get_patient_compliance_audit_service().record_event(
            user_id=user_id,
            action="nominee_updated",
            payload={"nominee_id": nominee_id},
            ip=ip,
            user_agent=user_agent,
            hospital_id=hospital_id,
            jurisdiction=jurisdiction,
        )
        return nominee_id

    def get_decrypted(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            r = self.table.get_item(Key={"user_id": user_id})
            it = r.get("Item")
            if not it:
                return None
            return {
                "name": decrypt_field(it.get("name_cipher") or ""),
                "email": decrypt_field(it.get("email_cipher") or ""),
                "relationship": it.get("relationship") or "",
                "phone": decrypt_field(it.get("phone_cipher") or "") or None,
            }
        except ClientError as e:
            logger.error("get nominee failed: %s", e)
            raise

    def delete_for_user(self, user_id: str) -> bool:
        try:
            self.table.delete_item(Key={"user_id": user_id})
            return True
        except ClientError:
            return False


_service: Optional[PatientNomineeService] = None


def get_patient_nominee_service() -> PatientNomineeService:
    global _service
    if _service is None:
        _service = PatientNomineeService()
    return _service
