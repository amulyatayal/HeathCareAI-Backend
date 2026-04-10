"""
Patient grievance submissions (DPDPA Sec. 13 / UK complaint reference).
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import boto3
import httpx
from botocore.exceptions import ClientError

from config.settings import settings
from services.patient_compliance_audit_service import get_patient_compliance_audit_service

logger = logging.getLogger(__name__)

TABLE_NAME = "PatientGrievances"


def _expected_resolution_iso(created: datetime, jurisdiction: str) -> str:
    # DPDPA: resolve within 30 days; UK GDPR typical 30 calendar days for access-style complaints
    days = 30
    return (created + timedelta(days=days)).date().isoformat()


class PatientGrievanceService:
    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self.dynamodb.Table(TABLE_NAME)

    async def submit(
        self,
        user_id: str,
        subject: str,
        description: str,
        *,
        ip: Optional[str],
        user_agent: Optional[str],
        hospital_id: Optional[str],
        jurisdiction: str,
    ) -> Dict[str, Any]:
        gid = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat().replace("+00:00", "Z")
        expected = _expected_resolution_iso(now, jurisdiction)

        item = {
            "grievance_id": gid,
            "user_id": user_id,
            "subject": subject,
            "description": description,
            "status": "open",
            "created_at": now_iso,
            "expected_resolution_date": expected,
            "jurisdiction": jurisdiction,
            "hospital_id": hospital_id or "",
        }
        self.table.put_item(Item=item)

        await get_patient_compliance_audit_service().record_event(
            user_id=user_id,
            action="grievance_submitted",
            payload={"grievance_id": gid, "subject": subject[:200]},
            ip=ip,
            user_agent=user_agent,
            hospital_id=hospital_id,
            jurisdiction=jurisdiction,
        )

        url = (settings.grievance_notify_webhook_url or "").strip()
        if url:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        url,
                        json={
                            "grievance_id": gid,
                            "user_id": user_id,
                            "subject": subject,
                            "created_at": now_iso,
                            "expected_resolution_date": expected,
                        },
                    )
            except Exception as e:
                logger.warning("Grievance webhook notify failed: %s", e)

        return {
            "message": "Grievance received.",
            "grievance_id": gid,
            "expected_resolution_date": expected,
        }

    async def delete_all_for_user(self, user_id: str) -> int:
        """Delete all grievances for user (account erasure)."""
        from boto3.dynamodb.conditions import Key

        deleted = 0
        kwargs: Dict[str, Any] = {
            "IndexName": "user_id-created_at-index",
            "KeyConditionExpression": Key("user_id").eq(user_id),
            "ProjectionExpression": "grievance_id",
        }
        try:
            while True:
                resp = self.table.query(**kwargs)
                batch = resp.get("Items", [])
                if batch:
                    with self.table.batch_writer() as w:
                        for it in batch:
                            w.delete_item(Key={"grievance_id": it["grievance_id"]})
                            deleted += 1
                lek = resp.get("LastEvaluatedKey")
                if not lek:
                    break
                kwargs["ExclusiveStartKey"] = lek
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return 0
            raise
        return deleted

    def list_all_for_export(self, user_id: str) -> List[Dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        items: List[Dict[str, Any]] = []
        try:
            kwargs: Dict[str, Any] = {
                "IndexName": "user_id-created_at-index",
                "KeyConditionExpression": Key("user_id").eq(user_id),
            }
            while True:
                resp = self.table.query(**kwargs)
                items.extend(resp.get("Items", []))
                lek = resp.get("LastEvaluatedKey")
                if not lek:
                    break
                kwargs["ExclusiveStartKey"] = lek
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return []
            raise
        return items


_service: Optional[PatientGrievanceService] = None


def get_patient_grievance_service() -> PatientGrievanceService:
    global _service
    if _service is None:
        _service = PatientGrievanceService()
    return _service
