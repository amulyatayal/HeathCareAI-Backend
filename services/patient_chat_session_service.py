"""
Patient Chat Session Service
DynamoDB CRUD for multi-turn chat memory (authenticated users only).
"""

import logging
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

import boto3
from botocore.exceptions import ClientError

from config.settings import settings
from models.chat_session_schemas import ChatSessionMessage, PatientChatSession

logger = logging.getLogger(__name__)

TABLE_NAME = "PatientChatSessions"
MAX_MESSAGES = 20
TTL_DAYS = 30


class SessionNotFoundError(Exception):
    """Raised when a session_id does not exist."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Chat session not found: {session_id}")


class SessionOwnershipError(Exception):
    """Raised when session belongs to a different user."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Chat session access denied: {session_id}")


class PatientChatSessionService:
    """Manages patient chat sessions in DynamoDB."""

    def __init__(self):
        self.table_name = TABLE_NAME
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self.dynamodb.Table(self.table_name)

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _ttl_epoch(self) -> int:
        return int(time.time()) + (TTL_DAYS * 24 * 3600)

    def _parse_session(self, item: Dict[str, Any]) -> PatientChatSession:
        messages = [
            ChatSessionMessage(**msg) if isinstance(msg, dict) else msg
            for msg in item.get("messages", [])
        ]
        return PatientChatSession(
            session_id=item["session_id"],
            user_id=item["user_id"],
            messages=messages,
            created_at=item.get("created_at", datetime.utcnow().isoformat()),
            updated_at=int(item["updated_at"]),
            ttl=int(item["ttl"]) if item.get("ttl") is not None else None,
        )

    async def get_or_create_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> PatientChatSession:
        """
        Load an existing session or create a new one.

        Raises SessionNotFoundError if session_id is provided but missing.
        Raises SessionOwnershipError if session belongs to another user.
        """
        if session_id:
            try:
                response = self.table.get_item(Key={"session_id": session_id})
            except ClientError as e:
                logger.error(f"Error loading session {session_id}: {e}")
                raise

            item = response.get("Item")
            if not item:
                raise SessionNotFoundError(session_id)

            if item.get("user_id") != user_id:
                raise SessionOwnershipError(session_id)

            return self._parse_session(item)

        new_id = str(uuid.uuid4())
        now_ms = self._now_ms()
        session = PatientChatSession(
            session_id=new_id,
            user_id=user_id,
            messages=[],
            created_at=datetime.utcnow().isoformat(),
            updated_at=now_ms,
            ttl=self._ttl_epoch(),
        )

        try:
            self.table.put_item(
                Item={
                    "session_id": session.session_id,
                    "user_id": session.user_id,
                    "messages": [],
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                    "ttl": session.ttl,
                }
            )
            logger.info(f"Created chat session {new_id} for user {user_id}")
        except ClientError as e:
            logger.error(f"Error creating session for user {user_id}: {e}")
            raise

        return session

    async def get_recent_messages(
        self,
        session_id: str,
        max_messages: int = 10,
    ) -> List[Dict[str, str]]:
        """Return recent messages as {role, content} dicts for the pipeline."""
        try:
            response = self.table.get_item(Key={"session_id": session_id})
        except ClientError as e:
            logger.error(f"Error loading messages for session {session_id}: {e}")
            return []

        item = response.get("Item")
        if not item:
            return []

        messages = item.get("messages", [])
        recent = messages[-max_messages:] if len(messages) > max_messages else messages
        return [
            {"role": msg.get("role", "user"), "content": msg.get("content", "")}
            for msg in recent
            if msg.get("content")
        ]

    async def append_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append a user/assistant exchange and trim to MAX_MESSAGES."""
        metadata = metadata or {}
        now_iso = datetime.utcnow().isoformat()
        now_ms = self._now_ms()

        user_entry = {
            "role": "user",
            "content": user_message,
            "timestamp": now_iso,
        }
        assistant_entry = {
            "role": "assistant",
            "content": assistant_message,
            "timestamp": now_iso,
            "intent": metadata.get("intent"),
            "request_id": metadata.get("request_id"),
        }

        try:
            response = self.table.get_item(Key={"session_id": session_id})
            item = response.get("Item")
            if not item:
                logger.warning(f"Cannot append turn: session {session_id} not found")
                return

            messages = list(item.get("messages", []))
            messages.extend([user_entry, assistant_entry])
            if len(messages) > MAX_MESSAGES:
                messages = messages[-MAX_MESSAGES:]

            self.table.update_item(
                Key={"session_id": session_id},
                UpdateExpression=(
                    "SET messages = :messages, updated_at = :updated_at, #ttl = :ttl"
                ),
                ExpressionAttributeNames={"#ttl": "ttl"},
                ExpressionAttributeValues={
                    ":messages": messages,
                    ":updated_at": now_ms,
                    ":ttl": self._ttl_epoch(),
                },
            )
            logger.info(
                f"Appended turn to session {session_id} "
                f"({len(messages)} messages total)"
            )
        except ClientError as e:
            logger.error(f"Error appending turn to session {session_id}: {e}")


_session_service: Optional[PatientChatSessionService] = None


def get_patient_chat_session_service() -> PatientChatSessionService:
    """Get or create the session service singleton."""
    global _session_service
    if _session_service is None:
        _session_service = PatientChatSessionService()
    return _session_service
