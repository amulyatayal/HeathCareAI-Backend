"""
Pydantic schemas for clinician notifications and patient read state.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class NotificationPriority(str, Enum):
    INFO = "info"
    WARNING = "warning"
    URGENT = "urgent"


# ================================
# Admin
# ================================

class NotificationCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    message: str = Field(..., min_length=1, max_length=10000)
    priority: NotificationPriority


class AdminNotificationResponse(BaseModel):
    id: str
    title: str
    message: str
    priority: NotificationPriority
    clinician_id: str
    clinician_name: str
    created_at: str
    updated_at: Optional[str] = None
    recipient_count: int


class AdminNotificationListResponse(BaseModel):
    notifications: List[AdminNotificationResponse]


# ================================
# Patient
# ================================

class PatientNotificationItem(BaseModel):
    id: str
    title: str
    message: str
    priority: NotificationPriority
    timestamp: str
    read: bool
    read_at: Optional[str] = None


class PatientNotificationListResponse(BaseModel):
    notifications: List[PatientNotificationItem]


class NotificationMessageResponse(BaseModel):
    message: str
