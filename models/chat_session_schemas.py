"""
Pydantic schemas for patient chat session persistence.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ChatSessionMessage(BaseModel):
    """A single message in a chat session."""
    role: str = Field(..., description="user or assistant")
    content: str = Field(..., description="Message text")
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="ISO timestamp when message was recorded",
    )
    intent: Optional[str] = Field(None, description="Classified intent for assistant turn")
    request_id: Optional[str] = Field(None, description="Pipeline request id for this turn")


class PatientChatSession(BaseModel):
    """Persistent chat session for an authenticated patient."""
    session_id: str
    user_id: str
    messages: List[ChatSessionMessage] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: int = Field(
        ...,
        description="Last update time in milliseconds (GSI sort key)",
    )
    ttl: Optional[int] = Field(
        None,
        description="DynamoDB TTL epoch seconds",
    )
