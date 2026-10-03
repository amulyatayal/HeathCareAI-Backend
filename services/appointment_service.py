"""
Appointment Service
DynamoDB CRUD for patient appointments.
"""

import logging
import uuid
from datetime import datetime, date as date_type
from typing import List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from config.aws import get_dynamodb_resource
from config.settings import settings

logger = logging.getLogger(__name__)


class AppointmentService:
    """
    Manages appointments in DynamoDB.
    
    Table: Appointments
    PK: user_id (String)
    SK: appointment_id (String, UUID)
    GSI: user_date-index (user_id PK, date SK) for sorted queries
    """

    TABLE_NAME = "Appointments"

    def __init__(self):
        self.dynamodb = get_dynamodb_resource()
        self.table = self.dynamodb.Table(self.TABLE_NAME)

    async def create_appointment(self, user_id: str, data: dict) -> dict:
        appointment_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + "Z"

        item = {
            "user_id": user_id,
            "appointment_id": appointment_id,
            "title": data["title"],
            "date": data["date"],
            "time": data["time"],
            "location": data.get("location"),
            "reminder": data.get("reminder", False),
            "status": "upcoming",
            "created_at": now,
        }

        try:
            self.table.put_item(Item=item)
            logger.info(f"Created appointment {appointment_id} for {user_id}")
            return self._to_response(item)
        except ClientError as e:
            logger.error(f"Error creating appointment: {e}")
            raise

    async def list_appointments(self, user_id: str, status: Optional[str] = None) -> dict:
        """
        List all appointments for a user.
        
        Automatically marks past appointments based on today's date.
        If status filter is provided, only returns matching appointments.
        """
        try:
            response = self.table.query(
                IndexName="user_date-index",
                KeyConditionExpression=Key("user_id").eq(user_id),
                ScanIndexForward=True,
            )
            items = response.get("Items", [])
        except ClientError as e:
            logger.error(f"Error listing appointments: {e}")
            raise

        today = date_type.today().isoformat()
        results = []

        for item in items:
            effective_status = "upcoming" if item.get("date", "") >= today else "past"
            if item.get("status") == "cancelled":
                effective_status = "cancelled"
            item["status"] = effective_status

            if status and effective_status != status:
                continue

            results.append(self._to_response(item))

        return {
            "appointments": results,
            "total_count": len(results),
        }

    async def delete_appointment(self, user_id: str, appointment_id: str) -> bool:
        """Delete an appointment. Returns True if deleted."""
        try:
            self.table.delete_item(
                Key={"user_id": user_id, "appointment_id": appointment_id},
                ConditionExpression="attribute_exists(appointment_id)",
            )
            logger.info(f"Deleted appointment {appointment_id} for {user_id}")
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            logger.error(f"Error deleting appointment: {e}")
            raise

    def get_next_upcoming(self, user_id: str) -> Optional[dict]:
        """Get the next upcoming appointment (sync, used by dashboard)."""
        today = date_type.today().isoformat()
        try:
            response = self.table.query(
                IndexName="user_date-index",
                KeyConditionExpression=(
                    Key("user_id").eq(user_id) & Key("date").gte(today)
                ),
                ScanIndexForward=True,
                Limit=1,
            )
            items = response.get("Items", [])
            if items:
                item = items[0]
                item["status"] = "upcoming"
                return self._to_response(item)
            return None
        except ClientError as e:
            logger.error(f"Error getting next appointment: {e}")
            return None

    @staticmethod
    def _to_response(item: dict) -> dict:
        return {
            "id": item["appointment_id"],
            "user_id": item["user_id"],
            "title": item["title"],
            "date": item["date"],
            "time": item["time"],
            "location": item.get("location"),
            "reminder": item.get("reminder", False),
            "status": item.get("status", "upcoming"),
            "created_at": item.get("created_at", ""),
        }


# ================================
# Singleton
# ================================

_service_instance: Optional[AppointmentService] = None


def get_appointment_service() -> AppointmentService:
    global _service_instance
    if _service_instance is None:
        _service_instance = AppointmentService()
    return _service_instance
