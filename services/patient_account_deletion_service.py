"""
Orchestrate permanent patient account erasure (GDPR right to erasure).
Deletes user-linked rows across DynamoDB tables. Audit trail for the user is removed
after logging a final account_deletion_requested event (full erasure posture).
"""

import logging
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from config.settings import settings
from services.patient_compliance_audit_service import get_patient_compliance_audit_service
from services.patient_data_share_service import get_patient_data_share_service
from services.patient_grievance_service import get_patient_grievance_service
from services.patient_nominee_service import get_patient_nominee_service
from services.patient_profile_service import get_patient_profile_service

logger = logging.getLogger(__name__)

MOOD_TABLE = "PatientMoodEntries"
SYMPTOM_TABLE = "SymptomEntries"
APPOINTMENTS_TABLE = "Appointments"
NOTIFICATION_READS_TABLE = "NotificationReads"
CHAT_TABLE = "ChatConversations"
FORUM_POSTS = "ForumPosts"
FORUM_COMMENTS = "ForumComments"
FORUM_VOTES = "ForumVotes"
PATIENT_CONSENTS = "PatientConsents"
USER_CREATED_GSI = "user_id-created_at-index"


def _table(name: str):
    return boto3.resource("dynamodb", region_name=settings.aws_region).Table(name)


def _query_pk(table_name: str, pk: str, user_id: str) -> List[Dict[str, Any]]:
    t = _table(table_name)
    items: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {"KeyConditionExpression": Key(pk).eq(user_id)}
    while True:
        r = t.query(**kwargs)
        items.extend(r.get("Items", []))
        lek = r.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


def _delete_pk_sk(
    table_name: str,
    pk_name: str,
    sk_name: str,
    user_id: str,
) -> int:
    items = _query_pk(table_name, pk_name, user_id)
    if not items:
        return 0
    t = _table(table_name)
    n = 0
    with t.batch_writer() as w:
        for it in items:
            w.delete_item(Key={pk_name: user_id, sk_name: it[sk_name]})
            n += 1
    return n


def _query_chat_all(user_id: str) -> List[Dict[str, Any]]:
    t = _table(CHAT_TABLE)
    items: List[Dict[str, Any]] = []
    try:
        kwargs: Dict[str, Any] = {
            "IndexName": USER_CREATED_GSI,
            "KeyConditionExpression": Key("user_id").eq(user_id),
        }
        while True:
            r = t.query(**kwargs)
            items.extend(r.get("Items", []))
            lek = r.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
        return items
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code not in ("ValidationException", "ResourceNotFoundException"):
            raise
        logger.warning("Chat delete GSI unavailable, scanning: %s", e)
    items = []
    kwargs = {"FilterExpression": Attr("user_id").eq(user_id)}
    while True:
        r = t.scan(**kwargs)
        items.extend(r.get("Items", []))
        lek = r.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


def _delete_chat_items(user_id: str) -> int:
    rows = _query_chat_all(user_id)
    if not rows:
        return 0
    t = _table(CHAT_TABLE)
    n = 0
    with t.batch_writer() as w:
        for it in rows:
            w.delete_item(
                Key={
                    "conversation_id": it["conversation_id"],
                    "created_at": it["created_at"],
                }
            )
            n += 1
    return n


def _scan_delete_forum_user(table_name: str, user_id: str) -> int:
    try:
        t = _table(table_name)
    except Exception:
        return 0
    deleted = 0
    try:
        kwargs: Dict[str, Any] = {"FilterExpression": Attr("user_id").eq(user_id)}
        while True:
            resp = t.scan(**kwargs)
            for it in resp.get("Items", []):
                if table_name == FORUM_POSTS:
                    t.delete_item(
                        Key={
                            "category_id": it["category_id"],
                            "created_at": it["created_at"],
                        }
                    )
                elif table_name == FORUM_COMMENTS:
                    t.delete_item(
                        Key={
                            "post_id": it["post_id"],
                            "created_at": it["created_at"],
                        }
                    )
                deleted += 1
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return 0
        logger.warning("Forum delete %s: %s", table_name, e)
    return deleted


def _delete_consents(user_id: str) -> int:
    t = _table(PATIENT_CONSENTS)
    n = 0
    for ctype in ("cookies", "data"):
        try:
            t.delete_item(Key={"user_id": user_id, "consent_type": ctype})
            n += 1
        except ClientError:
            pass
    return n


class PatientAccountDeletionService:
    async def erase_patient_data(
        self,
        user_id: str,
        *,
        ip: Optional[str],
        user_agent: Optional[str],
        hospital_id: Optional[str],
        jurisdiction: str = "UNKNOWN",
    ) -> Dict[str, Any]:
        audit = get_patient_compliance_audit_service()
        await audit.record_event(
            user_id=user_id,
            action="account_deletion_requested",
            payload={"source": "patient_self_service"},
            ip=ip,
            user_agent=user_agent,
            hospital_id=hospital_id,
            jurisdiction=jurisdiction,
        )

        summary: Dict[str, Any] = {}

        summary["grievances"] = await get_patient_grievance_service().delete_all_for_user(user_id)
        summary["nominee"] = get_patient_nominee_service().delete_for_user(user_id)
        summary["data_shares"] = get_patient_data_share_service().delete_all_for_user(user_id)

        summary["forum_votes"] = _delete_pk_sk(FORUM_VOTES, "user_id", "target_key", user_id)
        summary["forum_posts"] = _scan_delete_forum_user(FORUM_POSTS, user_id)
        summary["forum_comments"] = _scan_delete_forum_user(FORUM_COMMENTS, user_id)
        summary["chat_conversations"] = _delete_chat_items(user_id)
        summary["mood_entries"] = _delete_pk_sk(MOOD_TABLE, "user_id", "timestamp", user_id)
        summary["symptom_entries"] = _delete_pk_sk(SYMPTOM_TABLE, "user_id", "timestamp", user_id)
        summary["appointments"] = _delete_pk_sk(
            APPOINTMENTS_TABLE, "user_id", "appointment_id", user_id
        )
        summary["notification_reads"] = _delete_pk_sk(
            NOTIFICATION_READS_TABLE, "user_id", "notification_id", user_id
        )
        summary["patient_consents"] = _delete_consents(user_id)

        summary["compliance_audit_events"] = await audit.delete_all_events_for_user(user_id)

        profile_svc = get_patient_profile_service()
        try:
            await profile_svc.delete_profile(user_id)
            summary["profile_deleted"] = True
        except Exception as e:
            logger.error("Profile delete failed for %s: %s", user_id, e)
            summary["profile_deleted"] = False
            summary["profile_error"] = str(e)

        logger.info("Account erasure completed for user %s summary=%s", user_id, summary)
        return summary


_service: Optional[PatientAccountDeletionService] = None


def get_patient_account_deletion_service() -> PatientAccountDeletionService:
    global _service
    if _service is None:
        _service = PatientAccountDeletionService()
    return _service
