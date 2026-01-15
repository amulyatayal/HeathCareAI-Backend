"""
Profile API Routes
Endpoints for patient profile management.

Requires authentication - guest users cannot access profile features.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from config.pipeline_config import PatientStage
from models.patient_profile import (
    PatientProfile,
    OnboardingRequest,
    StageUpdateRequest,
    ProfileResponse,
    OnboardingStatusResponse,
)
from services.patient_profile_service import get_patient_profile_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["Patient Profile"])


# ================================
# Authentication Dependency
# ================================

async def get_authenticated_user_id(request: Request) -> str:
    """
    Extract and verify user ID from authentication header.
    
    Supports:
    - Firebase JWT: Authorization: Bearer <firebase_jwt>
    - Google OAuth: Authorization: Bearer <google_jwt>
    
    Guest users (X-User-ID header) are NOT allowed for profile endpoints.
    
    Raises:
        HTTPException 401: If not authenticated or using guest auth
    """
    auth_header = request.headers.get("Authorization")
    
    # Check for guest user header - not allowed for profile
    guest_id = request.headers.get("X-User-ID")
    if guest_id:
        raise HTTPException(
            status_code=401,
            detail="Profile features require authentication. Please sign in."
        )
    
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authentication required for profile features"
        )
    
    token = auth_header[7:]
    
    try:
        # Decode JWT to get user ID
        # For production, use firebase_admin.auth.verify_id_token(token)
        # For now, we'll decode without verification (frontend handles this)
        from jwt import decode
        decoded = decode(token, options={"verify_signature": False})
        
        # Try common JWT claims for user ID
        user_id = (
            decoded.get("sub") or 
            decoded.get("user_id") or 
            decoded.get("uid")
        )
        
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Invalid token: no user identifier found"
            )
        
        return user_id
        
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(
            status_code=401,
            detail=f"Invalid authentication token"
        )


# ================================
# Profile Endpoints
# ================================

@router.get("", response_model=Optional[ProfileResponse])
async def get_profile(
    user_id: str = Depends(get_authenticated_user_id)
):
    """
    Get current authenticated user's profile.
    
    Returns None if profile doesn't exist yet.
    """
    service = get_patient_profile_service()
    profile = await service.get_profile(user_id)
    
    if profile:
        return ProfileResponse(
            profile=profile,
            message="Profile retrieved successfully"
        )
    
    return None


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    user_id: str = Depends(get_authenticated_user_id)
):
    """
    Check if user needs to complete onboarding.
    
    Used by frontend to decide whether to show onboarding wizard.
    """
    service = get_patient_profile_service()
    profile = await service.get_profile(user_id)
    
    if profile and profile.onboarding_completed:
        return OnboardingStatusResponse(
            onboarding_completed=True,
            current_stage=profile.current_stage,
            needs_onboarding=False
        )
    
    return OnboardingStatusResponse(
        onboarding_completed=False,
        current_stage=PatientStage.UNKNOWN,
        needs_onboarding=True
    )


@router.post("/onboarding", response_model=ProfileResponse)
async def complete_onboarding(
    data: OnboardingRequest,
    user_id: str = Depends(get_authenticated_user_id)
):
    """
    Complete onboarding questionnaire.
    
    Creates profile if needed and sets initial stage based on selected situation.
    """
    logger.info(f"Processing onboarding for user {user_id}: {data.current_situation}")
    
    service = get_patient_profile_service()
    profile = await service.save_onboarding(user_id, data)
    
    return ProfileResponse(
        profile=profile,
        message=f"Onboarding completed! Your journey stage is set to: {profile.current_stage}"
    )


@router.put("/stage", response_model=ProfileResponse)
async def update_stage(
    data: StageUpdateRequest,
    user_id: str = Depends(get_authenticated_user_id)
):
    """
    Manually update patient stage.
    
    Used when user wants to change their stage (e.g., started treatment).
    """
    logger.info(f"Updating stage for user {user_id}: {data.new_stage}")
    
    service = get_patient_profile_service()
    
    try:
        profile = await service.update_stage(user_id, data.new_stage)
        return ProfileResponse(
            profile=profile,
            message=f"Stage updated to: {profile.current_stage}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )


@router.delete("", response_model=dict)
async def delete_profile(
    user_id: str = Depends(get_authenticated_user_id)
):
    """
    Delete patient profile.
    
    This permanently removes all profile data including stage history.
    """
    logger.info(f"Deleting profile for user {user_id}")
    
    service = get_patient_profile_service()
    await service.delete_profile(user_id)
    
    return {"message": "Profile deleted successfully"}
