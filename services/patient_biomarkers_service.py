"""
Patient Biomarkers Service
DynamoDB CRUD for patient biomarker snapshots.
"""

import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from config.aws import get_dynamodb_resource

logger = logging.getLogger(__name__)

BIOMARKER_FIELDS = [
    "height_cm",
    "weight_kg",
    "bmi",
    "waist_circumference_cm",
    "hand_grip_strength_kg",
]

NUMERIC_FIELDS = set(BIOMARKER_FIELDS)


class PatientBiomarkersService:
    """
    Manages biomarker snapshots in DynamoDB.

    Table: PatientBioMarkers
    PK: user_id (String)
    SK: timestamp (String, ISO 8601)
    """

    TABLE_NAME = "PatientBioMarkers"
    LATEST_TIMESTAMP_KEY = "LATEST"

    def __init__(self):
        self.dynamodb = get_dynamodb_resource()
        self.table = self.dynamodb.Table(self.TABLE_NAME)

    async def create_entry(self, user_id: str, data: dict) -> dict:
        ts = data.get("timestamp") or datetime.utcnow().isoformat() + "Z"
        entry_id = str(uuid.uuid4())

        item = {
            "user_id": user_id,
            "timestamp": ts,
            "entry_id": entry_id,
        }

        for field in BIOMARKER_FIELDS:
            value = data.get(field)
            if value is not None:
                item[field] = Decimal(str(value)) if field in NUMERIC_FIELDS else value

        if "bmi" not in item and "height_cm" in item and "weight_kg" in item:
            height_m = float(item["height_cm"]) / 100
            bmi = float(item["weight_kg"]) / (height_m ** 2)
            item["bmi"] = Decimal(str(round(bmi, 1)))

        try:
            self.table.put_item(Item=item)
            self._upsert_latest_entry(user_id=user_id, snapshot=item)
            logger.info(f"Created biomarker entry {entry_id} for {user_id}")
            return self._to_response(item)
        except ClientError as e:
            logger.error(f"Error creating biomarker entry: {e}")
            raise

    async def get_latest_entry(self, user_id: str) -> Optional[dict]:
        """Get latest biomarker values quickly using a dedicated LATEST pointer item."""
        try:
            response = self.table.get_item(
                Key={"user_id": user_id, "timestamp": self.LATEST_TIMESTAMP_KEY}
            )
            latest = response.get("Item")
            if latest:
                return self._to_response(latest)

            # Fallback for older data before LATEST pointer existed.
            listed = await self.list_entries(user_id=user_id, limit=1)
            entries = listed.get("entries", [])
            return entries[0] if entries else None
        except ClientError as e:
            logger.error(f"Error getting latest biomarker entry: {e}")
            raise

    async def list_entries(self, user_id: str, limit: int = 30) -> dict:
        """List recent biomarker snapshots sorted newest-first."""
        try:
            entries: List[dict] = []
            last_evaluated_key = None
            page_size = max(limit * 2, 20)
            while len(entries) < limit:
                query_kwargs = {
                    "KeyConditionExpression": Key("user_id").eq(user_id),
                    "ScanIndexForward": False,
                    "Limit": page_size,
                }
                if last_evaluated_key:
                    query_kwargs["ExclusiveStartKey"] = last_evaluated_key
                response = self.table.query(**query_kwargs)
                for item in response.get("Items", []):
                    if self._is_snapshot_item(item):
                        entries.append(self._to_response(item))
                        if len(entries) >= limit:
                            break
                last_evaluated_key = response.get("LastEvaluatedKey")
                if not last_evaluated_key:
                    break

            return {
                "entries": entries,
                "total_count": len(entries),
            }
        except ClientError as e:
            logger.error(f"Error listing biomarker entries: {e}")
            raise

    def get_recent_entries(self, user_id: str, days: int = 30) -> List[dict]:
        """Get entries from the last N days (sync, used by dashboard)."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
        try:
            response = self.table.query(
                KeyConditionExpression=(
                    Key("user_id").eq(user_id) & Key("timestamp").gte(cutoff)
                ),
                ScanIndexForward=False,
            )
            return [item for item in response.get("Items", []) if self._is_snapshot_item(item)]
        except ClientError as e:
            logger.error(f"Error getting recent biomarker entries: {e}")
            return []

    def _upsert_latest_entry(self, user_id: str, snapshot: dict) -> None:
        existing_latest = None
        try:
            response = self.table.get_item(
                Key={"user_id": user_id, "timestamp": self.LATEST_TIMESTAMP_KEY}
            )
            existing_latest = response.get("Item")
        except ClientError as e:
            logger.warning(f"Could not read existing latest biomarker row for {user_id}: {e}")

        latest = {
            "user_id": user_id,
            "timestamp": self.LATEST_TIMESTAMP_KEY,
            "entry_id": "latest",
            "source_entry_id": snapshot.get("entry_id"),
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        # Preserve prior latest values so partial updates (e.g., only height) do not
        # erase previously captured fields (e.g., weight/waist).
        if existing_latest:
            for field in BIOMARKER_FIELDS:
                if existing_latest.get(field) is not None:
                    latest[field] = existing_latest[field]
        for field in BIOMARKER_FIELDS:
            if field in snapshot and snapshot[field] is not None:
                latest[field] = snapshot[field]
        self.table.put_item(Item=latest)

    @staticmethod
    def _is_snapshot_item(item: dict) -> bool:
        ts = item.get("timestamp")
        if not isinstance(ts, str):
            return False
        if ts == PatientBiomarkersService.LATEST_TIMESTAMP_KEY:
            return False
        try:
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False

    @staticmethod
    def _to_response(item: dict) -> dict:
        result = {
            "entry_id": item["entry_id"],
            "user_id": item["user_id"],
            "timestamp": item["timestamp"],
        }
        for field in BIOMARKER_FIELDS:
            value = item.get(field)
            if value is not None and field in NUMERIC_FIELDS:
                value = float(value)
            result[field] = value
        return result


# ================================
# Singleton
# ================================

_service_instance: Optional[PatientBiomarkersService] = None


def get_patient_biomarkers_service() -> PatientBiomarkersService:
    global _service_instance
    if _service_instance is None:
        _service_instance = PatientBiomarkersService()
    return _service_instance
