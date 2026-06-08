"""
Admin clinical team — DynamoDB CRUD scoped by clinician_id.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from config.settings import settings
from services.clinical_team_helpers import (
    sort_team_members,
    to_team_member_response,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

TABLE_NAME = "AdminClinicalTeam"
GSI_NAME = "clinician_id-index"


class AdminClinicalTeamService:
    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self.dynamodb.Table(TABLE_NAME)

    def create_member(self, clinician_id: str, data: dict) -> dict:
        now = utc_now_iso()
        team_member_id = str(uuid.uuid4())
        display_order = data.get("display_order")
        if display_order is None:
            display_order = 0

        item = {
            "team_member_id": team_member_id,
            "clinician_id": clinician_id,
            "name": data["name"],
            "role": data["role"],
            "specialty": data.get("specialty"),
            "contact_email": data.get("contact_email"),
            "contact_phone": data.get("contact_phone"),
            "avatar_url": None,
            "display_order": display_order,
            "created_at": now,
            "updated_at": now,
        }

        try:
            self.table.put_item(Item=item)
            logger.info(
                f"Created team member {team_member_id} for clinician {clinician_id}"
            )
            return to_team_member_response(item)
        except ClientError as e:
            logger.error(f"Error creating team member: {e}")
            raise

    def list_members(
        self, clinician_id: str, limit: int = 50, offset: int = 0
    ) -> dict:
        try:
            items = self._query_all_for_clinician(clinician_id)
            items = sort_team_members(items)
            total = len(items)
            page = items[offset : offset + limit]
            members = [to_team_member_response(i) for i in page]
            return {"team_members": members, "total_count": total}
        except ClientError as e:
            logger.error(f"Error listing team for {clinician_id}: {e}")
            raise

    def get_member_raw(self, team_member_id: str) -> Optional[dict]:
        try:
            r = self.table.get_item(Key={"team_member_id": team_member_id})
            return r.get("Item")
        except ClientError as e:
            logger.error(f"Error getting team member {team_member_id}: {e}")
            raise

    def update_member(
        self, team_member_id: str, clinician_id: str, data: dict
    ) -> Optional[dict]:
        item = self.get_member_raw(team_member_id)
        if not item or item.get("clinician_id") != clinician_id:
            return None

        if data.get("name") is not None:
            item["name"] = data["name"]
        if data.get("role") is not None:
            item["role"] = data["role"]
        if "specialty" in data:
            item["specialty"] = data["specialty"]
        if "contact_email" in data:
            item["contact_email"] = data["contact_email"]
        if "contact_phone" in data:
            item["contact_phone"] = data["contact_phone"]
        if data.get("display_order") is not None:
            item["display_order"] = data["display_order"]

        item["updated_at"] = utc_now_iso()
        try:
            self.table.put_item(Item=item)
            logger.info(f"Updated team member {team_member_id}")
            return to_team_member_response(item)
        except ClientError as e:
            logger.error(f"Error updating team member {team_member_id}: {e}")
            raise

    def delete_member(self, team_member_id: str, clinician_id: str) -> bool:
        item = self.get_member_raw(team_member_id)
        if not item or item.get("clinician_id") != clinician_id:
            return False
        try:
            self.table.delete_item(Key={"team_member_id": team_member_id})
            logger.info(f"Deleted team member {team_member_id}")
            return True
        except ClientError as e:
            logger.error(f"Error deleting team member {team_member_id}: {e}")
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


_service: Optional[AdminClinicalTeamService] = None


def get_admin_clinical_team_service() -> AdminClinicalTeamService:
    global _service
    if _service is None:
        _service = AdminClinicalTeamService()
    return _service
