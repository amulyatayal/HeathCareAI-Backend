"""
List patient data shares visible to a clinician (admin portal).

Scans PatientProfiles for clinician_id, then queries PatientDataShares per patient.
Raw share tokens are not stored and are never returned.
"""

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from config.settings import settings

logger = logging.getLogger(__name__)

PROFILE_TABLE = "PatientProfiles"
SHARES_TABLE = "PatientDataShares"
GSI_USER_CREATED = "user_id-created_at-index"
PER_USER_SHARE_LIMIT = 100
GLOBAL_SHARE_CAP = 500


def _jsonify(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonify(v) for v in value]
    return value


def _scan_patient_user_ids_for_clinician(clinician_id: str) -> Dict[str, str]:
    """Return map user_id -> patient_ref_id for profiles with this clinician_id."""
    dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
    table = dynamodb.Table(PROFILE_TABLE)
    uid_to_ref: Dict[str, str] = {}
    kwargs: Dict[str, Any] = {
        "FilterExpression": Attr("clinician_id").eq(clinician_id),
        "ProjectionExpression": "user_id, patient_ref_id",
    }
    try:
        while True:
            resp = table.scan(**kwargs)
            for it in resp.get("Items", []):
                uid = it.get("user_id")
                if not uid:
                    continue
                uid_to_ref[str(uid)] = str(it.get("patient_ref_id") or "")
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ResourceNotFoundException":
            logger.warning("PatientProfiles table missing for admin share list")
            return {}
        raise
    return uid_to_ref


def _query_shares_for_user(table, user_id: str, limit: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {
        "IndexName": GSI_USER_CREATED,
        "KeyConditionExpression": Key("user_id").eq(user_id),
        "ScanIndexForward": False,
    }
    while len(items) < limit:
        kwargs["Limit"] = min(limit - len(items), 100)
        r = table.query(**kwargs)
        batch = r.get("Items", [])
        items.extend(batch)
        lek = r.get("LastEvaluatedKey")
        if not lek or len(items) >= limit:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items[:limit]


class AdminPatientShareService:
    def list_for_clinician(self, clinician_id: str) -> List[Dict[str, Any]]:
        cid = (clinician_id or "").strip()
        if not cid:
            return []

        uid_to_ref = _scan_patient_user_ids_for_clinician(cid)
        if not uid_to_ref:
            return []

        dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        try:
            shares_table = dynamodb.Table(SHARES_TABLE)
        except Exception:
            return []

        merged: List[Dict[str, Any]] = []
        try:
            for user_id, patient_ref_id in uid_to_ref.items():
                rows = _query_shares_for_user(
                    shares_table, user_id, PER_USER_SHARE_LIMIT
                )
                for it in rows:
                    sid = it.get("share_id")
                    if not sid:
                        continue
                    rev = it.get("revoked_at")
                    merged.append(
                        {
                            "share_id": str(sid),
                            "patient_ref_id": patient_ref_id,
                            "created_at": str(it.get("created_at") or ""),
                            "expires_at": str(it.get("expires_at") or ""),
                            "revoked_at": str(rev) if rev is not None else None,
                            "scope": _jsonify(it.get("scope") or {}),
                            "token": None,
                        }
                    )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                logger.warning("PatientDataShares table missing for admin share list")
                return []
            raise

        merged.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return merged[:GLOBAL_SHARE_CAP]


_service: Optional[AdminPatientShareService] = None


def get_admin_patient_share_service() -> AdminPatientShareService:
    global _service
    if _service is None:
        _service = AdminPatientShareService()
    return _service
