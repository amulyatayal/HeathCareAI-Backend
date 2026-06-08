"""
Patient community events — list/detail and RSVP against clinician-scoped AdminEvents.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from config.settings import settings
from services.admin_events_service import (
    ADMIN_EVENTS_TABLE,
    GSI_NAME,
    STATUS_PUBLISHED,
    get_admin_events_service,
)
from services.event_helpers import to_event_response, utc_now_iso

logger = logging.getLogger(__name__)

PATIENT_EVENT_RSVPS_TABLE = "PatientEventRsvps"


class PatientEventsService:
    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.events = self.dynamodb.Table(ADMIN_EVENTS_TABLE)
        self.rsvps = self.dynamodb.Table(PATIENT_EVENT_RSVPS_TABLE)
        self._admin = get_admin_events_service()

    def list_events(
        self,
        user_id: str,
        clinician_id: Optional[str],
        when: str = "upcoming",
        type_filter: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        if not clinician_id:
            return {"events": [], "total_count": 0}

        now_iso = utc_now_iso()
        try:
            if when == "past":
                kwargs: Dict[str, Any] = {
                    "IndexName": GSI_NAME,
                    "KeyConditionExpression": Key("clinician_id").eq(clinician_id)
                    & Key("starts_at").lt(now_iso),
                    "ScanIndexForward": False,
                }
            else:
                kwargs = {
                    "IndexName": GSI_NAME,
                    "KeyConditionExpression": Key("clinician_id").eq(clinician_id)
                    & Key("starts_at").gte(now_iso),
                    "ScanIndexForward": True,
                }

            items = self._query_events(kwargs)
            items = [
                i
                for i in items
                if i.get("status") == STATUS_PUBLISHED
                and (not type_filter or i.get("type") == type_filter)
            ]

            if when == "past":
                items.sort(key=lambda x: x.get("starts_at", ""), reverse=True)
            else:
                items.sort(key=lambda x: x.get("starts_at", ""))

            total = len(items)
            page = items[offset : offset + limit]
            rsvp_ids = self._rsvp_event_ids_for_user(user_id, [i["event_id"] for i in page])
            events = [
                to_event_response(i, user_has_rsvp=(i["event_id"] in rsvp_ids))
                for i in page
            ]
            return {"events": events, "total_count": total}
        except ClientError as e:
            logger.error(f"Error listing patient events for {user_id}: {e}")
            raise

    def get_event(
        self, user_id: str, clinician_id: Optional[str], event_id: str
    ) -> Optional[dict]:
        if not clinician_id:
            return None
        item = self._admin.get_event_raw(event_id)
        if (
            not item
            or item.get("clinician_id") != clinician_id
            or item.get("status") != STATUS_PUBLISHED
        ):
            return None
        has_rsvp = self._has_rsvp(user_id, event_id)
        return to_event_response(item, user_has_rsvp=has_rsvp)

    def rsvp(
        self, user_id: str, event_id: str, clinician_id: Optional[str]
    ) -> Optional[dict]:
        item = self._validated_event_for_rsvp(event_id, clinician_id)
        if not item:
            return None

        if self._has_rsvp(user_id, event_id):
            return to_event_response(item, user_has_rsvp=True)

        now = utc_now_iso()
        try:
            self.rsvps.put_item(
                Item={
                    "event_id": event_id,
                    "user_id": user_id,
                    "rsvp_at": now,
                }
            )
            self.events.update_item(
                Key={"event_id": event_id},
                UpdateExpression="SET attendee_count = if_not_exists(attendee_count, :zero) + :one, updated_at = :u",
                ExpressionAttributeValues={
                    ":one": 1,
                    ":zero": 0,
                    ":u": now,
                },
            )
            updated = self._admin.get_event_raw(event_id) or item
            return to_event_response(updated, user_has_rsvp=True)
        except ClientError as e:
            logger.error(f"Error RSVP {event_id} for {user_id}: {e}")
            raise

    def cancel_rsvp(
        self, user_id: str, event_id: str, clinician_id: Optional[str]
    ) -> Optional[dict]:
        item = self._admin.get_event_raw(event_id)
        if not item or item.get("clinician_id") != clinician_id:
            return None

        had_rsvp = self._has_rsvp(user_id, event_id)
        now = utc_now_iso()
        try:
            if had_rsvp:
                self.rsvps.delete_item(
                    Key={"event_id": event_id, "user_id": user_id}
                )
                self.events.update_item(
                    Key={"event_id": event_id},
                    UpdateExpression=(
                        "SET attendee_count = if_not_exists(attendee_count, :zero) - :one, "
                        "updated_at = :u"
                    ),
                    ExpressionAttributeValues={
                        ":one": 1,
                        ":zero": 0,
                        ":u": now,
                    },
                )
            updated = self._admin.get_event_raw(event_id) or item
            if updated.get("attendee_count") is not None and int(updated.get("attendee_count", 0)) < 0:
                self.events.update_item(
                    Key={"event_id": event_id},
                    UpdateExpression="SET attendee_count = :zero, updated_at = :u",
                    ExpressionAttributeValues={":zero": 0, ":u": now},
                )
                updated = self._admin.get_event_raw(event_id) or updated
            return to_event_response(updated, user_has_rsvp=False)
        except ClientError as e:
            logger.error(f"Error cancel RSVP {event_id} for {user_id}: {e}")
            raise

    def _validated_event_for_rsvp(
        self, event_id: str, clinician_id: Optional[str]
    ) -> Optional[dict]:
        if not clinician_id:
            return None
        item = self._admin.get_event_raw(event_id)
        if not item or item.get("clinician_id") != clinician_id:
            return None
        if item.get("status") != STATUS_PUBLISHED:
            return None
        starts_at = item.get("starts_at", "")
        if starts_at:
            try:
                dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
                if dt.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
                    return None
            except ValueError:
                pass
        return item

    def _has_rsvp(self, user_id: str, event_id: str) -> bool:
        try:
            r = self.rsvps.get_item(Key={"event_id": event_id, "user_id": user_id})
            return bool(r.get("Item"))
        except ClientError as e:
            logger.error(f"Error checking RSVP {event_id}/{user_id}: {e}")
            raise

    def _rsvp_event_ids_for_user(
        self, user_id: str, event_ids: List[str]
    ) -> Set[str]:
        if not event_ids:
            return set()
        client = self.dynamodb.meta.client
        keys = [{"event_id": eid, "user_id": user_id} for eid in event_ids]
        found: Set[str] = set()
        try:
            for i in range(0, len(keys), 100):
                chunk = keys[i : i + 100]
                request: Optional[Dict[str, Any]] = {
                    PATIENT_EVENT_RSVPS_TABLE: {"Keys": chunk, "ConsistentRead": False}
                }
                while request:
                    resp = client.batch_get_item(RequestItems=request)
                    for it in resp.get("Responses", {}).get(
                        PATIENT_EVENT_RSVPS_TABLE, []
                    ):
                        found.add(it["event_id"])
                    unprocessed = resp.get("UnprocessedKeys") or {}
                    if unprocessed:
                        request = unprocessed
                        time.sleep(0.05)
                    else:
                        request = None
            return found
        except ClientError as e:
            logger.error(f"Error batch_get RSVPs for {user_id}: {e}")
            raise

    def _query_events(self, kwargs: Dict[str, Any]) -> List[dict]:
        items: List[dict] = []
        while True:
            response = self.events.query(**kwargs)
            items.extend(response.get("Items", []))
            lek = response.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
        return items


_service: Optional[PatientEventsService] = None


def get_patient_events_service() -> PatientEventsService:
    global _service
    if _service is None:
        _service = PatientEventsService()
    return _service
