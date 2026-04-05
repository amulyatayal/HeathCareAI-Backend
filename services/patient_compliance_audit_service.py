"""
Append-only audit events for patient compliance (consent, export, etc.).
Writes to DynamoDB table PatientComplianceAuditEvents (PutItem only).
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from config.settings import settings

logger = logging.getLogger(__name__)

TABLE_NAME = "PatientComplianceAuditEvents"
GSI_USER_OCCURRED = "user_id-occurred_at-index"


class PatientComplianceAuditService:
    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self.dynamodb.Table(TABLE_NAME)

    async def record_event(
        self,
        *,
        user_id: str,
        action: str,
        payload: Dict[str, Any],
        ip: Optional[str],
        user_agent: Optional[str],
        hospital_id: Optional[str] = None,
        jurisdiction: str = "UNKNOWN",
    ) -> str:
        """
        Persist one audit event. Returns event_id.
        """
        event_id = str(uuid.uuid4())
        occurred_at = datetime.utcnow().isoformat() + "Z"

        item = {
            "event_id": event_id,
            "user_id": user_id,
            "occurred_at": occurred_at,
            "action": action,
            "payload": payload,
            "ip": ip or "",
            "user_agent": (user_agent or "")[:2048],
            "hospital_id": hospital_id or "",
            "jurisdiction": jurisdiction,
        }

        try:
            self.table.put_item(Item=item)
            logger.info("Recorded compliance event %s action=%s user=%s", event_id, action, user_id)
            return event_id
        except ClientError as e:
            logger.error("Failed to record compliance event: %s", e)
            raise

    async def list_events_for_user(self, user_id: str, limit: int = 2000) -> List[Dict[str, Any]]:
        """Return audit rows for this user (newest first), for data export / activity APIs."""
        items: List[Dict[str, Any]] = []
        try:
            kwargs: Dict[str, Any] = {
                "IndexName": GSI_USER_OCCURRED,
                "KeyConditionExpression": Key("user_id").eq(user_id),
                "ScanIndexForward": False,
            }
            while len(items) < limit:
                resp = self.table.query(**kwargs)
                batch = resp.get("Items", [])
                items.extend(batch)
                lek = resp.get("LastEvaluatedKey")
                if not lek:
                    break
                kwargs["ExclusiveStartKey"] = lek
            return items[:limit]
        except ClientError as e:
            logger.error("list_events_for_user failed: %s", e)
            raise

    async def delete_all_events_for_user(self, user_id: str) -> int:
        """Remove all audit events for user (used on account erasure). Returns count deleted."""
        deleted = 0
        try:
            kwargs: Dict[str, Any] = {
                "IndexName": GSI_USER_OCCURRED,
                "KeyConditionExpression": Key("user_id").eq(user_id),
                "ProjectionExpression": "event_id",
            }
            while True:
                resp = self.table.query(**kwargs)
                batch = resp.get("Items", [])
                if batch:
                    with self.table.batch_writer() as writer:
                        for it in batch:
                            writer.delete_item(Key={"event_id": it["event_id"]})
                            deleted += 1
                lek = resp.get("LastEvaluatedKey")
                if not lek:
                    break
                kwargs["ExclusiveStartKey"] = lek
        except ClientError as e:
            logger.error("delete_all_events_for_user failed: %s", e)
            raise
        return deleted


_service: Optional[PatientComplianceAuditService] = None


def get_patient_compliance_audit_service() -> PatientComplianceAuditService:
    global _service
    if _service is None:
        _service = PatientComplianceAuditService()
    return _service
