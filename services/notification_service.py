"""
Notification Service
Clinician broadcasts to associated patients; per-patient read state in NotificationReads.
"""

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from config.settings import settings

logger = logging.getLogger(__name__)

PROFILES_TABLE = "PatientProfiles"
NOTIFICATIONS_TABLE = "Notifications"
READS_TABLE = "NotificationReads"
GSI_NAME = "clinician_id-created_at-index"
NOTIFICATION_RETENTION_DAYS = 90


def _notifications_created_since_iso() -> str:
    """ISO8601 UTC with Z suffix; lexicographically comparable with stored created_at."""
    dt = datetime.now(timezone.utc) - timedelta(days=NOTIFICATION_RETENTION_DAYS)
    return dt.isoformat().replace("+00:00", "Z")


class NotificationService:
    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.notifications = self.dynamodb.Table(NOTIFICATIONS_TABLE)
        self.reads = self.dynamodb.Table(READS_TABLE)
        self.profiles = self.dynamodb.Table(PROFILES_TABLE)

    def count_patients_for_clinician(self, clinician_id: str) -> int:
        """Count PatientProfiles with this clinician_id (scan with filter)."""
        total = 0
        try:
            kwargs: Dict[str, Any] = {
                "FilterExpression": Attr("clinician_id").eq(clinician_id),
                "ProjectionExpression": "user_id",
            }
            while True:
                response = self.profiles.scan(**kwargs)
                total += len(response.get("Items", []))
                lek = response.get("LastEvaluatedKey")
                if not lek:
                    break
                kwargs["ExclusiveStartKey"] = lek
            return total
        except ClientError as e:
            logger.error(f"Error counting patients for clinician {clinician_id}: {e}")
            raise

    def create_notification(
        self,
        clinician_id: str,
        clinician_name: str,
        title: str,
        message: str,
        priority: str,
    ) -> dict:
        now = datetime.utcnow().isoformat() + "Z"
        notification_id = str(uuid.uuid4())
        recipient_count = self.count_patients_for_clinician(clinician_id)

        item = {
            "notification_id": notification_id,
            "title": title,
            "message": message,
            "priority": priority,
            "clinician_id": clinician_id,
            "clinician_name": clinician_name,
            "recipient_count": recipient_count,
            "created_at": now,
            "updated_at": now,
            "is_deleted": False,
        }
        try:
            self.notifications.put_item(Item=item)
            logger.info(
                f"Created notification {notification_id} for {clinician_id}, "
                f"recipient_count={recipient_count}"
            )
            return self._to_admin_response(item)
        except ClientError as e:
            logger.error(f"Error creating notification: {e}")
            raise

    def list_notifications_for_clinician(self, clinician_id: str) -> List[dict]:
        """Newest first; excludes soft-deleted. Only items from the last NOTIFICATION_RETENTION_DAYS."""
        cutoff = _notifications_created_since_iso()
        try:
            response = self.notifications.query(
                IndexName=GSI_NAME,
                KeyConditionExpression=Key("clinician_id").eq(clinician_id)
                & Key("created_at").gte(cutoff),
                ScanIndexForward=False,
            )
            items = response.get("Items", [])
            while "LastEvaluatedKey" in response:
                response = self.notifications.query(
                    IndexName=GSI_NAME,
                    KeyConditionExpression=Key("clinician_id").eq(clinician_id)
                    & Key("created_at").gte(cutoff),
                    ScanIndexForward=False,
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            out = []
            for item in items:
                if item.get("is_deleted", False):
                    continue
                out.append(self._to_admin_response(item))
            return out
        except ClientError as e:
            logger.error(f"Error listing notifications for {clinician_id}: {e}")
            raise

    def get_notification_raw(self, notification_id: str) -> Optional[dict]:
        try:
            r = self.notifications.get_item(Key={"notification_id": notification_id})
            return r.get("Item")
        except ClientError as e:
            logger.error(f"Error getting notification {notification_id}: {e}")
            raise

    def soft_delete_notification(self, notification_id: str, clinician_id: str) -> bool:
        item = self.get_notification_raw(notification_id)
        if not item or item.get("is_deleted", False):
            return False
        if item.get("clinician_id") != clinician_id:
            return False
        now = datetime.utcnow().isoformat() + "Z"
        try:
            self.notifications.update_item(
                Key={"notification_id": notification_id},
                UpdateExpression="SET is_deleted = :d, updated_at = :u",
                ExpressionAttributeValues={":d": True, ":u": now},
            )
            logger.info(f"Soft-deleted notification {notification_id}")
            return True
        except ClientError as e:
            logger.error(f"Error deleting notification {notification_id}: {e}")
            raise

    def list_for_patient(self, user_id: str, clinician_id: Optional[str]) -> List[dict]:
        """Patient-facing rows with read flag; newest first."""
        if not clinician_id:
            return []

        cutoff = _notifications_created_since_iso()
        try:
            response = self.notifications.query(
                IndexName=GSI_NAME,
                KeyConditionExpression=Key("clinician_id").eq(clinician_id)
                & Key("created_at").gte(cutoff),
                ScanIndexForward=False,
            )
            items = list(response.get("Items", []))
            while "LastEvaluatedKey" in response:
                response = self.notifications.query(
                    IndexName=GSI_NAME,
                    KeyConditionExpression=Key("clinician_id").eq(clinician_id)
                    & Key("created_at").gte(cutoff),
                    ScanIndexForward=False,
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            visible = [i for i in items if not i.get("is_deleted", False)]
            if not visible:
                return []

            read_ids, read_at_by_nid = self._read_state_for_notifications_batch(
                user_id, [i["notification_id"] for i in visible]
            )

            result = []
            for item in visible:
                nid = item["notification_id"]
                result.append({
                    "id": nid,
                    "title": item.get("title", ""),
                    "message": item.get("message", ""),
                    "priority": item.get("priority", "info"),
                    "timestamp": item.get("created_at", ""),
                    "read": nid in read_ids,
                    "read_at": read_at_by_nid.get(nid),
                })
            return result
        except ClientError as e:
            logger.error(f"Error listing notifications for patient {user_id}: {e}")
            raise

    def _read_state_for_notifications_batch(
        self, user_id: str, notification_ids: List[str]
    ) -> Tuple[Set[str], Dict[str, str]]:
        """Read notification ids for this user, plus optional read_at (ISO) when stored."""
        if not notification_ids:
            return set(), {}
        client = self.dynamodb.meta.client
        read_ids: Set[str] = set()
        read_at_by_nid: Dict[str, str] = {}
        keys = [{"user_id": user_id, "notification_id": nid} for nid in notification_ids]
        try:
            for i in range(0, len(keys), 100):
                chunk = keys[i : i + 100]
                request: Optional[Dict[str, Any]] = {
                    READS_TABLE: {"Keys": chunk, "ConsistentRead": False}
                }
                while request:
                    resp = client.batch_get_item(RequestItems=request)
                    for it in resp.get("Responses", {}).get(READS_TABLE, []):
                        nid = it["notification_id"]
                        read_ids.add(nid)
                        ra = it.get("read_at")
                        if isinstance(ra, str) and ra:
                            read_at_by_nid[nid] = ra
                    unprocessed = resp.get("UnprocessedKeys") or {}
                    if unprocessed:
                        request = unprocessed
                        time.sleep(0.05)
                    else:
                        request = None
            return read_ids, read_at_by_nid
        except ClientError as e:
            logger.error(f"Error batch_get reads for user {user_id}: {e}")
            raise

    def mark_read(
        self, user_id: str, notification_id: str, clinician_id: Optional[str]
    ) -> bool:
        if not clinician_id:
            return False
        item = self.get_notification_raw(notification_id)
        if not item or item.get("is_deleted", False):
            return False
        if item.get("clinician_id") != clinician_id:
            return False
        now = datetime.utcnow().isoformat() + "Z"
        try:
            self.reads.put_item(
                Item={
                    "user_id": user_id,
                    "notification_id": notification_id,
                    "read_at": now,
                }
            )
            return True
        except ClientError as e:
            logger.error(f"Error marking read {notification_id} for {user_id}: {e}")
            raise

    def mark_all_read(self, user_id: str, clinician_id: Optional[str]) -> int:
        """Mark all visible notifications for this clinician as read; returns count written."""
        if not clinician_id:
            return 0
        rows = self.list_for_patient(user_id, clinician_id)
        now = datetime.utcnow().isoformat() + "Z"
        count = 0
        try:
            with self.reads.batch_writer() as batch:
                for row in rows:
                    if not row.get("read"):
                        batch.put_item(
                            Item={
                                "user_id": user_id,
                                "notification_id": row["id"],
                                "read_at": now,
                            }
                        )
                        count += 1
            return count
        except ClientError as e:
            logger.error(f"Error mark_all_read for {user_id}: {e}")
            raise

    @staticmethod
    def _to_admin_response(item: dict) -> dict:
        rc = item.get("recipient_count", 0)
        if isinstance(rc, Decimal):
            rc = int(rc)
        else:
            rc = int(rc) if rc is not None else 0
        out = {
            "id": item["notification_id"],
            "title": item.get("title", ""),
            "message": item.get("message", ""),
            "priority": item.get("priority", "info"),
            "clinician_id": item.get("clinician_id", ""),
            "clinician_name": item.get("clinician_name", ""),
            "created_at": item.get("created_at", ""),
            "recipient_count": rc,
        }
        if item.get("updated_at"):
            out["updated_at"] = item["updated_at"]
        return out


_service_instance: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    global _service_instance
    if _service_instance is None:
        _service_instance = NotificationService()
    return _service_instance
