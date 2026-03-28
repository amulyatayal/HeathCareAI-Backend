"""
Access Code Service
Manages short alphanumeric codes that link patients to clinicians.

Clinicians generate codes via the admin portal; patients enter them
to associate their profile with a specific clinician.
"""

import logging
import secrets
import string
from datetime import datetime
from typing import List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from config.settings import settings

logger = logging.getLogger(__name__)

_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_CHARS = _CODE_CHARS.replace("0", "").replace("O", "").replace("I", "").replace("1", "").replace("L", "")
_CODE_LENGTH = 8


def _generate_code() -> str:
    """Generate a short, unambiguous alphanumeric code like 'HK7M92XR'."""
    return "".join(secrets.choice(_CODE_CHARS) for _ in range(_CODE_LENGTH))


class AccessCodeService:
    """
    Manages access codes in DynamoDB.

    Table: AccessCodes
    PK: access_code (String)
    GSI: clinician_id-index (clinician_id PK)
    """

    TABLE_NAME = "AccessCodes"

    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self.dynamodb.Table(self.TABLE_NAME)

    def create_code(
        self,
        clinician_id: str,
        clinician_name: str,
        hospital_id: str,
    ) -> dict:
        """
        Generate a new access code for a clinician.

        Retries up to 3 times if a code collision occurs (extremely unlikely
        with 8 characters from a 31-char alphabet).
        """
        for _ in range(3):
            code = _generate_code()
            now = datetime.utcnow().isoformat() + "Z"

            item = {
                "access_code": code,
                "clinician_id": clinician_id,
                "clinician_name": clinician_name,
                "hospital_id": hospital_id,
                "created_at": now,
                "is_active": True,
            }

            try:
                self.table.put_item(
                    Item=item,
                    ConditionExpression="attribute_not_exists(access_code)",
                )
                logger.info(f"Created access code {code} for clinician {clinician_id}")
                return self._to_response(item)
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    logger.warning(f"Access code collision on {code}, retrying")
                    continue
                raise

        raise RuntimeError("Failed to generate unique access code after 3 attempts")

    def lookup_code(self, code: str) -> Optional[dict]:
        """Look up an access code. Returns None if not found or revoked."""
        try:
            response = self.table.get_item(Key={"access_code": code.upper()})
            item = response.get("Item")
            if item and item.get("is_active", False):
                return self._to_response(item)
            return None
        except ClientError as e:
            logger.error(f"Error looking up access code {code}: {e}")
            raise

    def list_codes(self, clinician_id: str) -> List[dict]:
        """List all access codes for a clinician (active and revoked)."""
        try:
            response = self.table.query(
                IndexName="clinician_id-index",
                KeyConditionExpression=Key("clinician_id").eq(clinician_id),
            )
            return [self._to_response(item) for item in response.get("Items", [])]
        except ClientError as e:
            logger.error(f"Error listing codes for clinician {clinician_id}: {e}")
            raise

    def revoke_code(self, code: str) -> bool:
        """
        Revoke an access code (soft deactivate).

        Returns True if revoked, False if not found or already revoked.
        """
        try:
            response = self.table.get_item(Key={"access_code": code.upper()})
            item = response.get("Item")
            if not item or not item.get("is_active", False):
                return False

            now = datetime.utcnow().isoformat() + "Z"
            self.table.update_item(
                Key={"access_code": code.upper()},
                UpdateExpression="SET is_active = :a, revoked_at = :r",
                ExpressionAttributeValues={":a": False, ":r": now},
            )
            logger.info(f"Revoked access code {code}")
            return True
        except ClientError as e:
            logger.error(f"Error revoking access code {code}: {e}")
            raise

    @staticmethod
    def _to_response(item: dict) -> dict:
        return {
            "access_code": item["access_code"],
            "clinician_id": item.get("clinician_id", ""),
            "clinician_name": item.get("clinician_name", ""),
            "hospital_id": item.get("hospital_id", ""),
            "created_at": item.get("created_at", ""),
            "is_active": item.get("is_active", False),
        }


# ================================
# Singleton
# ================================

_service_instance: Optional[AccessCodeService] = None


def get_access_code_service() -> AccessCodeService:
    global _service_instance
    if _service_instance is None:
        _service_instance = AccessCodeService()
    return _service_instance
