"""
User models and schemas for backend user profile storage.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class UserBase(BaseModel):
    """Base user fields"""
    name: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    picture: Optional[str] = Field(None, max_length=500)


class UserCreate(UserBase):
    """Schema for creating/syncing a user on login"""
    user_id: str = Field(..., description="Google 'sub' or 'guest_<uuid>'")
    auth_provider: str = Field(..., pattern="^(google|guest)$")


class UserResponse(UserBase):
    """Schema for user profile response"""
    user_id: str
    auth_provider: str
    created_at: datetime
    last_login: datetime
    
    class Config:
        from_attributes = True


class UserSyncRequest(BaseModel):
    """Request body for POST /users/sync"""
    name: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = None
    picture: Optional[str] = None


class UserSyncResponse(BaseModel):
    """Response for POST /users/sync"""
    user_id: str
    name: str
    is_new_user: bool
    message: str
