"""
Mood Tracking Service
DynamoDB CRUD and trend calculation for patient mood entries.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from config.settings import settings

logger = logging.getLogger(__name__)


class MoodService:
    """
    Manages mood entries in DynamoDB.
    
    Table: PatientMoodEntries
    PK: user_id (String)
    SK: timestamp (String, ISO 8601)
    """

    TABLE_NAME = "PatientMoodEntries"

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
            "note": data.get("note"),
            "emotions": data.get("emotions", []),
            "triggers": data.get("triggers", []),
        }
        if data.get("mood_score") is not None:
            item["mood_score"] = data["mood_score"]

        if data.get("quick_check"):
            qc = data["quick_check"]
            item["quick_check"] = qc if isinstance(qc, dict) else qc.dict()

        try:
            self.table.put_item(Item=item)
            logger.info(f"Created mood entry {entry_id} for {user_id}")
            return self._to_response(item)
        except ClientError as e:
            logger.error(f"Error creating mood entry: {e}")
            raise

    async def list_entries(self, user_id: str, limit: int = 30) -> dict:
        """
        List recent mood entries with aggregate stats.

        Returns entries sorted newest-first, plus avg_mood and trend.
        """
        try:
            response = self.table.query(
                KeyConditionExpression=Key("user_id").eq(user_id),
                ScanIndexForward=False,
                Limit=limit,
            )
            items = response.get("Items", [])
            entries = [self._to_response(item) for item in items]

            avg_mood = None
            trend_direction = None
            trend_percentage = None

            scored_entries = [e for e in entries if e.get("mood_score") is not None]
            if scored_entries:
                scores = [e["mood_score"] for e in scored_entries]
                avg_mood = round(sum(scores) / len(scores), 1)
                trend_direction, trend_percentage = self._calculate_trend(items)

            return {
                "entries": entries,
                "total_count": len(entries),
                "avg_mood": avg_mood,
                "trend_direction": trend_direction,
                "trend_percentage": trend_percentage,
            }
        except ClientError as e:
            logger.error(f"Error listing mood entries: {e}")
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
            logger.error(f"Error getting recent mood entries: {e}")
            return []

    # ================================
    # Trend Calculation
    # ================================

    @staticmethod
    def _calculate_trend(items: List[dict]):
        """
        Compare average mood in the last 7 days vs the prior 7 days.
        Returns (direction, percentage).
        """
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        recent_scores = []
        prior_scores = []

        for item in items:
            try:
                ts = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
            except (ValueError, KeyError):
                continue

            if item.get("mood_score") is None:
                continue
            score = int(item["mood_score"])
            if ts >= week_ago:
                recent_scores.append(score)
            elif ts >= two_weeks_ago:
                prior_scores.append(score)

        if not recent_scores or not prior_scores:
            return "stable", 0.0

        recent_avg = sum(recent_scores) / len(recent_scores)
        prior_avg = sum(prior_scores) / len(prior_scores)

        if prior_avg == 0:
            return "stable", 0.0

        change = ((recent_avg - prior_avg) / prior_avg) * 100
        direction = "up" if change > 2 else ("down" if change < -2 else "stable")

        return direction, round(abs(change), 1)

    # ================================
    # Helpers
    # ================================

    @staticmethod
    def _to_response(item: dict) -> dict:
        qc = item.get("quick_check")
        if qc:
            qc = {
                "sleep_quality": int(qc["sleep_quality"]) if qc.get("sleep_quality") is not None else None,
                "physical_discomfort": int(qc["physical_discomfort"]) if qc.get("physical_discomfort") is not None else None,
                "energy_level": int(qc["energy_level"]) if qc.get("energy_level") is not None else None,
            }

        mood_score = item.get("mood_score")
        return {
            "entry_id": item["entry_id"],
            "user_id": item["user_id"],
            "mood_score": int(mood_score) if mood_score is not None else None,
            "note": item.get("note"),
            "emotions": item.get("emotions", []),
            "triggers": item.get("triggers", []),
            "quick_check": qc,
            "timestamp": item["timestamp"],
        }


# ================================
# Singleton
# ================================

_service_instance: Optional[MoodService] = None


def get_mood_service() -> MoodService:
    global _service_instance
    if _service_instance is None:
        _service_instance = MoodService()
    return _service_instance
