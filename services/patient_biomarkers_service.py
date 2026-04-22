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
            logger.info(f"Created biomarker entry {entry_id} for {user_id}")
            return self._to_response(item)
        except ClientError as e:
            logger.error(f"Error creating biomarker entry: {e}")
            raise

    async def list_entries(self, user_id: str, limit: int = 30) -> dict:
        """List recent biomarker snapshots sorted newest-first."""
        try:
            response = self.table.query(
                KeyConditionExpression=Key("user_id").eq(user_id),
                ScanIndexForward=False,
                Limit=limit,
            )
            items = response.get("Items", [])
            entries = [self._to_response(item) for item in items]

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
            return response.get("Items", [])
        except ClientError as e:
            logger.error(f"Error getting recent biomarker entries: {e}")
            return []

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
