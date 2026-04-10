"""
Time-limited patient data shares (token in URL; only token hash stored).
"""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from config.settings import settings
from services.patient_compliance_audit_service import get_patient_compliance_audit_service
from services.patient_profile_service import get_patient_profile_service

logger = logging.getLogger(__name__)

TABLE_NAME = "PatientDataShares"
GSI_TOKEN = "token_hash-index"
GSI_USER_CREATED = "user_id-created_at-index"


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class PatientDataShareService:
    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self.dynamodb.Table(TABLE_NAME)

    async def generate_share(
        self,
        user_id: str,
        *,
        ip: Optional[str],
        user_agent: Optional[str],
        hospital_id: Optional[str],
        jurisdiction: str,
        scope: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        raw = secrets.token_urlsafe(32)
        th = _hash_token(raw)
        share_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat().replace("+00:00", "Z")
        ttl_hours = max(1, int(settings.patient_share_ttl_hours))
        exp = now + timedelta(hours=ttl_hours)
        exp_iso = exp.isoformat().replace("+00:00", "Z")

        item = {
            "share_id": share_id,
            "user_id": user_id,
            "token_hash": th,
            "created_at": now_iso,
            "expires_at": exp_iso,
            "scope": scope or {},
        }
        self.table.put_item(Item=item)

        await get_patient_compliance_audit_service().record_event(
            user_id=user_id,
            action="share_generated",
            payload={"share_id": share_id},
            ip=ip,
            user_agent=user_agent,
            hospital_id=hospital_id,
            jurisdiction=jurisdiction,
        )

        base = (settings.patient_share_public_base_url or "").rstrip("/")
        path = f"/api/v2/share/view/{raw}"
        share_url = f"{base}{path}" if base else path

        return {
            "share_id": share_id,
            "token": raw,
            "expires_at": exp_iso,
            "share_url": share_url,
        }

    async def get_by_token(self, raw_token: str) -> Optional[Dict[str, Any]]:
        th = _hash_token(raw_token.strip())
        try:
            r = self.table.query(
                IndexName=GSI_TOKEN,
                KeyConditionExpression=Key("token_hash").eq(th),
                Limit=1,
            )
            items = r.get("Items", [])
            if not items:
                return None
            it = items[0]
            if it.get("revoked_at"):
                return None
            exp = it.get("expires_at") or ""
            try:
                exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > exp_dt:
                    return None
            except ValueError:
                return None

            owner = it.get("user_id")
            profile = await get_patient_profile_service().get_profile(owner)
            summary: Dict[str, Any] = {
                "patient_ref_id": getattr(profile, "patient_ref_id", None) if profile else None,
                "current_stage": str(profile.current_stage) if profile else None,
                "hospital_id": profile.hospital_id if profile else None,
            }
            return {
                "share_id": it.get("share_id"),
                "expires_at": it.get("expires_at"),
                "profile_summary": summary,
                "scope": it.get("scope") or {},
            }
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return None
            logger.error("get_by_token failed: %s", e)
            raise

    async def revoke(self, user_id: str, share_id: str) -> bool:
        try:
            r = self.table.get_item(Key={"share_id": share_id})
            it = r.get("Item")
            if not it or it.get("user_id") != user_id:
                return False
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            self.table.update_item(
                Key={"share_id": share_id},
                UpdateExpression="SET revoked_at = :r",
                ExpressionAttributeValues={":r": now},
            )
            await get_patient_compliance_audit_service().record_event(
                user_id=user_id,
                action="share_revoked",
                payload={"share_id": share_id},
                ip=None,
                user_agent=None,
                hospital_id=None,
                jurisdiction="UNKNOWN",
            )
            return True
        except ClientError:
            return False

    def list_history(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            kwargs: Dict[str, Any] = {
                "IndexName": GSI_USER_CREATED,
                "KeyConditionExpression": Key("user_id").eq(user_id),
                "ScanIndexForward": False,
                "Limit": min(limit, 100),
            }
            while len(out) < limit:
                r = self.table.query(**kwargs)
                for it in r.get("Items", []):
                    out.append(
                        {
                            "share_id": it.get("share_id"),
                            "created_at": it.get("created_at"),
                            "expires_at": it.get("expires_at"),
                            "revoked_at": it.get("revoked_at"),
                        }
                    )
                    if len(out) >= limit:
                        break
                lek = r.get("LastEvaluatedKey")
                if not lek or len(out) >= limit:
                    break
                kwargs["ExclusiveStartKey"] = lek
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return []
            raise
        return out[:limit]

    async def delete_all_for_user(self, user_id: str) -> int:
        deleted = 0
        try:
            kwargs: Dict[str, Any] = {
                "IndexName": GSI_USER_CREATED,
                "KeyConditionExpression": Key("user_id").eq(user_id),
                "ProjectionExpression": "share_id",
            }
            while True:
                r = self.table.query(**kwargs)
                batch = r.get("Items", [])
                if batch:
                    with self.table.batch_writer() as w:
                        for it in batch:
                            w.delete_item(Key={"share_id": it["share_id"]})
                            deleted += 1
                lek = r.get("LastEvaluatedKey")
                if not lek:
                    break
                kwargs["ExclusiveStartKey"] = lek
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return 0
            raise
        return deleted


_service: Optional[PatientDataShareService] = None


def get_patient_data_share_service() -> PatientDataShareService:
    global _service
    if _service is None:
        _service = PatientDataShareService()
    return _service
