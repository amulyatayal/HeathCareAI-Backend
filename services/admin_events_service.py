"""
Admin community events — DynamoDB CRUD scoped by clinician_id.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from config.settings import settings
from services.event_helpers import combine_date_time_iso, to_event_response, utc_now_iso

logger = logging.getLogger(__name__)

ADMIN_EVENTS_TABLE = "AdminEvents"
GSI_NAME = "clinician_id-starts_at-index"
STATUS_PUBLISHED = "published"
STATUS_CANCELLED = "cancelled"


class AdminEventsService:
    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self.dynamodb.Table(ADMIN_EVENTS_TABLE)

    def create_event(
        self, clinician_id: str, hospital_id: Optional[str], data: dict
    ) -> dict:
        now = utc_now_iso()
        event_id = str(uuid.uuid4())
        starts_at = combine_date_time_iso(data["date"], data["time"])
        event_type = data.get("type", "wellness")
        if hasattr(event_type, "value"):
            event_type = event_type.value

        item = {
            "event_id": event_id,
            "clinician_id": clinician_id,
            "title": data["title"],
            "starts_at": starts_at,
            "location": data.get("location"),
            "type": event_type,
            "is_virtual": bool(data.get("is_virtual", False)),
            "description": data.get("description"),
            "status": STATUS_PUBLISHED,
            "attendee_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        if hospital_id:
            item["hospital_id"] = hospital_id

        try:
            self.table.put_item(Item=item)
            logger.info(f"Created event {event_id} for clinician {clinician_id}")
            return to_event_response(item)
        except ClientError as e:
            logger.error(f"Error creating event: {e}")
            raise

    def list_events(
        self,
        clinician_id: str,
        status: str = "all",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        try:
            items = self._query_all_for_clinician(clinician_id)
            if status == STATUS_PUBLISHED:
                items = [i for i in items if i.get("status") == STATUS_PUBLISHED]
            elif status == STATUS_CANCELLED:
                items = [i for i in items if i.get("status") == STATUS_CANCELLED]

            items.sort(key=lambda x: x.get("starts_at", ""), reverse=True)
            total = len(items)
            page = items[offset : offset + limit]
            events = [to_event_response(i) for i in page]
            return {"events": events, "total_count": total}
        except ClientError as e:
            logger.error(f"Error listing events for {clinician_id}: {e}")
            raise

    def get_event_raw(self, event_id: str) -> Optional[dict]:
        try:
            r = self.table.get_item(Key={"event_id": event_id})
            return r.get("Item")
        except ClientError as e:
            logger.error(f"Error getting event {event_id}: {e}")
            raise

    def update_event(
        self, event_id: str, clinician_id: str, data: dict
    ) -> Optional[dict]:
        item = self.get_event_raw(event_id)
        if not item or item.get("clinician_id") != clinician_id:
            return None

        if data.get("title") is not None:
            item["title"] = data["title"]
        if data.get("location") is not None:
            item["location"] = data["location"]
        if data.get("type") is not None:
            t = data["type"]
            item["type"] = t.value if hasattr(t, "value") else t
        if data.get("is_virtual") is not None:
            item["is_virtual"] = data["is_virtual"]
        if data.get("description") is not None:
            item["description"] = data["description"]
        if data.get("date") is not None and data.get("time") is not None:
            item["starts_at"] = combine_date_time_iso(data["date"], data["time"])

        item["updated_at"] = utc_now_iso()
        try:
            self.table.put_item(Item=item)
            logger.info(f"Updated event {event_id}")
            return to_event_response(item)
        except ClientError as e:
            logger.error(f"Error updating event {event_id}: {e}")
            raise

    def cancel_event(self, event_id: str, clinician_id: str) -> bool:
        item = self.get_event_raw(event_id)
        if not item or item.get("clinician_id") != clinician_id:
            return False
        if item.get("status") == STATUS_CANCELLED:
            return True
        now = utc_now_iso()
        try:
            self.table.update_item(
                Key={"event_id": event_id},
                UpdateExpression="SET #s = :c, updated_at = :u",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":c": STATUS_CANCELLED,
                    ":u": now,
                },
            )
            logger.info(f"Cancelled event {event_id}")
            return True
        except ClientError as e:
            logger.error(f"Error cancelling event {event_id}: {e}")
            raise

    def _query_all_for_clinician(self, clinician_id: str) -> List[dict]:
        items: List[dict] = []
        kwargs: Dict[str, Any] = {
            "IndexName": GSI_NAME,
            "KeyConditionExpression": Key("clinician_id").eq(clinician_id),
        }
        while True:
            response = self.table.query(**kwargs)
            items.extend(response.get("Items", []))
            lek = response.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
        return items


_service: Optional[AdminEventsService] = None


def get_admin_events_service() -> AdminEventsService:
    global _service
    if _service is None:
        _service = AdminEventsService()
    return _service
