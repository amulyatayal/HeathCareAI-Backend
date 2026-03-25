"""
Symptom Tracking Service
DynamoDB CRUD and trend analysis for patient symptom entries.
"""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from config.settings import settings

logger = logging.getLogger(__name__)


class SymptomService:
    """
    Manages symptom entries in DynamoDB.
    
    Table: SymptomEntries
    PK: user_id (String)
    SK: timestamp (String, ISO 8601)
    """

    TABLE_NAME = "SymptomEntries"

    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self.dynamodb.Table(self.TABLE_NAME)

    async def create_entry(self, user_id: str, data: dict) -> dict:
        ts = data.get("timestamp") or datetime.utcnow().isoformat() + "Z"
        entry_id = str(uuid.uuid4())

        item = {
            "user_id": user_id,
            "timestamp": ts,
            "entry_id": entry_id,
            "symptom_name": data["symptom_name"],
            "severity": data["severity"],
            "notes": data.get("notes"),
        }

        try:
            self.table.put_item(Item=item)
            logger.info(f"Created symptom entry {entry_id} for {user_id}")
            return self._to_response(item)
        except ClientError as e:
            logger.error(f"Error creating symptom entry: {e}")
            raise

    async def list_entries(self, user_id: str, limit: int = 30) -> dict:
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
            logger.error(f"Error listing symptom entries: {e}")
            raise

    async def get_trends(self, user_id: str) -> List[dict]:
        """
        Compute per-symptom trends by comparing the last 7 days
        against the prior 7 days.
        """
        cutoff = (datetime.utcnow() - timedelta(days=14)).isoformat() + "Z"

        try:
            response = self.table.query(
                KeyConditionExpression=(
                    Key("user_id").eq(user_id) & Key("timestamp").gte(cutoff)
                ),
            )
            items = response.get("Items", [])
        except ClientError as e:
            logger.error(f"Error fetching symptom trends: {e}")
            return []

        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)

        recent: dict[str, list] = defaultdict(list)
        prior: dict[str, list] = defaultdict(list)

        for item in items:
            name = item.get("symptom_name", "unknown")
            severity = int(item.get("severity", 0))
            try:
                ts = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
            except (ValueError, KeyError):
                continue

            if ts >= week_ago:
                recent[name].append(severity)
            else:
                prior[name].append(severity)

        all_names = set(recent.keys()) | set(prior.keys())
        trends = []

        for name in sorted(all_names):
            r = recent.get(name, [])
            p = prior.get(name, [])

            if not r and not p:
                continue

            r_avg = sum(r) / len(r) if r else 0
            p_avg = sum(p) / len(p) if p else 0

            if p_avg == 0:
                direction = "new" if r else "stable"
                change = 0.0
            else:
                change = ((r_avg - p_avg) / p_avg) * 100
                direction = "up" if change > 5 else ("down" if change < -5 else "stable")

            trends.append({
                "symptom_name": name,
                "direction": direction,
                "change_percentage": round(abs(change), 1),
            })

        return trends

    @staticmethod
    def _to_response(item: dict) -> dict:
        return {
            "entry_id": item["entry_id"],
            "user_id": item["user_id"],
            "symptom_name": item["symptom_name"],
            "severity": int(item["severity"]),
            "notes": item.get("notes"),
            "timestamp": item["timestamp"],
        }


# ================================
# Singleton
# ================================

_service_instance: Optional[SymptomService] = None


def get_symptom_service() -> SymptomService:
    global _service_instance
    if _service_instance is None:
        _service_instance = SymptomService()
    return _service_instance
