"""
Shared Authentication Dependencies
Extracted from profile_routes.py so all routers can use them.
"""

import logging

from fastapi import HTTPException, Request

from config import settings as app_settings
from services.patient_jwt import get_patient_token_identity

logger = logging.getLogger(__name__)


async def get_authenticated_user_id(request: Request) -> str:
    """
    Extract and verify user ID from authentication header.
    
    Supports:
    - Firebase JWT: Authorization: Bearer <firebase_jwt>
    - Google OAuth: Authorization: Bearer <google_jwt>
    
    Guest users (X-User-ID header) are NOT allowed.
    
    Raises:
        HTTPException 401: If not authenticated or using guest auth
    """
    auth_header = request.headers.get("Authorization")
    guest_id = request.headers.get("X-User-ID")

    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]

        try:
            if app_settings.patient_bearer_legacy_jwt_decode:
                from jwt import decode

                decoded = decode(token, options={"verify_signature": False})

                user_id = (
                    decoded.get("sub")
                    or decoded.get("user_id")
                    or decoded.get("uid")
                )

                if user_id:
                    return user_id
            else:
                ident = get_patient_token_identity(token, app_settings)
                if ident:
                    return ident[0]
        except Exception as e:
            logger.error(f"Token verification failed: {e}")

    if guest_id:
        raise HTTPException(
            status_code=401,
            detail="This feature requires authentication. Please sign in."
        )

    raise HTTPException(
        status_code=401,
        detail="Authentication required"
    )


async def get_user_id_allowing_guest(request: Request) -> str:
    """
    Get user ID from Auth header OR X-User-ID (guest).
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            token = auth_header[7:]
            if app_settings.patient_bearer_legacy_jwt_decode:
                from jwt import decode

                decoded = decode(token, options={"verify_signature": False})
                user_id = decoded.get("sub") or decoded.get("user_id") or decoded.get("uid")
                if user_id:
                    return user_id
            else:
                ident = get_patient_token_identity(token, app_settings)
                if ident:
                    return ident[0]
        except Exception:
            pass

    guest_id = request.headers.get("X-User-ID")
    if guest_id:
        return guest_id

    raise HTTPException(
        status_code=401,
        detail="Authentication methods restricted. Login or Guest ID required."
    )
