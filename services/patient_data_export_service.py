"""
Assemble patient data export (GDPR Art. 15 / portability) as JSON inside a ZIP.
"""

import io
import json
import logging
import zipfile
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from config.settings import settings
from services.patient_compliance_audit_service import get_patient_compliance_audit_service
from services.patient_consent_service import get_patient_consent_service
from services.patient_data_share_service import get_patient_data_share_service
from services.patient_grievance_service import get_patient_grievance_service
from services.patient_nominee_service import get_patient_nominee_service
from services.patient_profile_service import get_patient_profile_service
from services.notification_service import NotificationService

logger = logging.getLogger(__name__)

MOOD_TABLE = "PatientMoodEntries"
SYMPTOM_TABLE = "SymptomEntries"
APPOINTMENTS_TABLE = "Appointments"
NOTIFICATION_READS_TABLE = "NotificationReads"
CHAT_TABLE = "ChatConversations"
USER_CREATED_GSI = "user_id-created_at-index"
FORUM_POSTS = "ForumPosts"
FORUM_COMMENTS = "ForumComments"
FORUM_VOTES = "ForumVotes"


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


def _query_all_pk(table_name: str, pk_name: str, user_id: str) -> List[Dict[str, Any]]:
    dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
    table = dynamodb.Table(table_name)
    items: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {
        "KeyConditionExpression": Key(pk_name).eq(user_id),
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


def _query_chat_for_user(user_id: str, limit: int = 5000) -> List[Dict[str, Any]]:
    dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
    table = dynamodb.Table(CHAT_TABLE)
    items: List[Dict[str, Any]] = []
    try:
        kwargs: Dict[str, Any] = {
            "IndexName": USER_CREATED_GSI,
            "KeyConditionExpression": Key("user_id").eq(user_id),
            "ScanIndexForward": False,
        }
        while len(items) < limit:
            resp = table.query(**kwargs)
            batch = resp.get("Items", [])
            items.extend(batch)
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
        return _jsonify(items[:limit])
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("ValidationException", "ResourceNotFoundException"):
            logger.warning("Chat export falling back to scan: %s", e)
        else:
            raise
    items = []
    try:
        scan_kwargs: Dict[str, Any] = {
            "FilterExpression": Attr("user_id").eq(user_id),
        }
        while len(items) < limit:
            resp = table.scan(**scan_kwargs)
            items.extend(resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            scan_kwargs["ExclusiveStartKey"] = lek
        return _jsonify(items[:limit])
    except ClientError as e:
        logger.error("Chat export scan failed: %s", e)
        return []


def _scan_forum_by_user_id(table_name: str, user_id: str, limit: int = 2000) -> List[Dict[str, Any]]:
    dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
    table = dynamodb.Table(table_name)
    items: List[Dict[str, Any]] = []
    try:
        kwargs: Dict[str, Any] = {
            "FilterExpression": Attr("user_id").eq(user_id),
        }
        while len(items) < limit:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
        return _jsonify(items[:limit])
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return []
        logger.warning("Forum scan %s: %s", table_name, e)
        return []


class PatientDataExportService:
    async def build_export_document(self, user_id: str) -> Dict[str, Any]:
        profile_svc = get_patient_profile_service()
        profile = await profile_svc.get_profile(user_id)
        profile_dict: Optional[Dict[str, Any]] = None
        if profile:
            try:
                profile_dict = _jsonify(profile.model_dump(mode="json"))
            except Exception:
                profile_dict = _jsonify(profile.model_dump())

        clinician_id = profile.clinician_id if profile else None
        notif_svc = NotificationService()
        notifications_view = notif_svc.list_for_patient(user_id, clinician_id)
        reads_raw = _jsonify(_query_all_pk(NOTIFICATION_READS_TABLE, "user_id", user_id))

        mood_items = _jsonify(_query_all_pk(MOOD_TABLE, "user_id", user_id))
        symptom_items = _jsonify(_query_all_pk(SYMPTOM_TABLE, "user_id", user_id))
        appt_items = _jsonify(_query_all_pk(APPOINTMENTS_TABLE, "user_id", user_id))

        consent_rows = get_patient_consent_service().get_consent_rows_for_export(user_id)
        consent_export = _jsonify(consent_rows)

        audit = await get_patient_compliance_audit_service().list_events_for_user(user_id, limit=5000)
        audit_export = _jsonify(audit)

        chat = _query_chat_for_user(user_id)

        forum_posts = _scan_forum_by_user_id(FORUM_POSTS, user_id)
        forum_comments = _scan_forum_by_user_id(FORUM_COMMENTS, user_id)
        forum_votes = _jsonify(_query_all_pk(FORUM_VOTES, "user_id", user_id))

        grievances = _jsonify(get_patient_grievance_service().list_all_for_export(user_id))
        nominee_export = None
        try:
            nominee_raw = get_patient_nominee_service().get_decrypted(user_id)
            nominee_export = _jsonify(nominee_raw) if nominee_raw else None
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                nominee_export = None
            else:
                logger.warning("Nominee export: %s", e)
                nominee_export = None
        try:
            shares = _jsonify(get_patient_data_share_service().list_history(user_id, limit=500))
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                shares = []
            else:
                logger.warning("Shares export: %s", e)
                shares = []

        return {
            "export_version": 1,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "user_id": user_id,
            "profile": profile_dict,
            "consent_records": consent_export,
            "compliance_audit_events": audit_export,
            "mood_entries": mood_items,
            "symptom_entries": symptom_items,
            "appointments": appt_items,
            "notifications_inbox_view": notifications_view,
            "notification_reads": reads_raw,
            "chat_conversations": chat,
            "forum_posts": forum_posts,
            "forum_comments": forum_comments,
            "forum_votes": forum_votes,
            "grievances": grievances,
            "nominee": nominee_export,
            "data_shares": shares,
            "uploaded_documents_metadata": [],
            "note_documents": "Patient-uploaded document metadata is not yet stored in DynamoDB; list may be empty.",
        }

    def build_zip_bytes(self, document: Dict[str, Any]) -> bytes:
        payload = json.dumps(document, ensure_ascii=False, indent=2, default=str)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("export.json", payload.encode("utf-8"))
        buf.seek(0)
        return buf.read()


_service: Optional[PatientDataExportService] = None


def get_patient_data_export_service() -> PatientDataExportService:
    global _service
    if _service is None:
        _service = PatientDataExportService()
    return _service
