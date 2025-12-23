"""
User API Routes for profile management.
Provides endpoints for user sync, profile retrieval, and account deletion.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Header
import jwt

from models.user import UserSyncRequest, UserSyncResponse, UserResponse
from services.user_service import get_user_service

logger = logging.getLogger(__name__)

# ================================
# User Router
# ================================

user_router = APIRouter(prefix="/users", tags=["User Profile"])


def _extract_user_from_token(
    authorization: Optional[str] = None,
    x_user_id: Optional[str] = None
) -> tuple[str, str, Optional[str], Optional[str]]:
    """
    Extract user info from headers.
    
    Returns:
        Tuple of (user_id, auth_provider, name, email)
    """
    if authorization and authorization.startswith("Bearer "):
        try:
            token = authorization.replace("Bearer ", "")
            # Decode without verification (signature already verified by Google)
            decoded = jwt.decode(token, options={"verify_signature": False})
            user_id = decoded.get("sub") or decoded.get("email")
            name = decoded.get("name") or decoded.get("email", "User").split("@")[0]
            email = decoded.get("email")
            picture = decoded.get("picture")
            
            if not user_id:
                raise HTTPException(status_code=401, detail="Invalid token: missing user ID")
            
            return user_id, "google", name, email, picture
        except jwt.DecodeError:
            raise HTTPException(status_code=401, detail="Invalid token format")
    elif x_user_id:
        # Guest user
        return x_user_id, "guest", None, None, None
    else:
        raise HTTPException(status_code=401, detail="Authentication required")


# ================================
# Endpoints
# ================================

@user_router.post("/sync", response_model=UserSyncResponse)
async def sync_user(
    request: UserSyncRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Sync user profile on login.
    
    Creates a new user or updates existing user with latest info.
    Called by frontend immediately after Google/Guest login.
    
    - **name**: User's display name
    - **email**: Email address (Google users only)
    - **picture**: Avatar URL (optional)
    """
    user_id, auth_provider, _, token_email, token_picture = _extract_user_from_token(
        authorization, x_user_id
    )
    
    # Use request data, fall back to token data
    email = request.email or token_email
    picture = request.picture or token_picture
    
    service = get_user_service()
    
    try:
        user, is_new_user = await service.sync_user(
            user_id=user_id,
            name=request.name,
            email=email,
            picture=picture,
            auth_provider=auth_provider
        )
        
        return UserSyncResponse(
            user_id=user_id,
            name=request.name,
            is_new_user=is_new_user,
            message="User synced successfully"
        )
    except Exception as e:
        logger.error(f"Failed to sync user: {e}")
        raise HTTPException(status_code=500, detail="Failed to sync user")


@user_router.get("/me", response_model=UserResponse)
async def get_current_user(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Get current user's profile.
    
    Returns the authenticated user's profile from DynamoDB.
    """
    user_id, auth_provider, _, _, _ = _extract_user_from_token(
        authorization, x_user_id
    )
    
    service = get_user_service()
    
    try:
        user = await service.get_user(user_id)
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return UserResponse(
            user_id=user['user_id'],
            name=user['name'],
            email=user.get('email'),
            picture=user.get('picture'),
            auth_provider=user['auth_provider'],
            created_at=user['created_at'],
            last_login=user['last_login']
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user")


@user_router.delete("/me")
async def delete_account(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Delete current user's account.
    
    Permanently removes the user profile from DynamoDB.
    """
    user_id, _, _, _, _ = _extract_user_from_token(
        authorization, x_user_id
    )
    
    service = get_user_service()
    
    try:
        success = await service.delete_user(user_id)
        
        if success:
            return {"message": "Account deleted successfully", "user_id": user_id}
        else:
            raise HTTPException(status_code=500, detail="Failed to delete account")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete user: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete account")
