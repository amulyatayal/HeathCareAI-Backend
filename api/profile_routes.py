"""
Profile API Routes
Endpoints for patient profile management.

Requires authentication - guest users cannot access profile features.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from config.pipeline_config import PatientStage
from models.patient_profile import (
    PatientProfile,
    OnboardingRequest,
    StageUpdateRequest,
    LinkAccountRequest,
    ProfileResponse,
    OnboardingStatusResponse,
)
from models.patient_stages import (
    TreatmentStage,
    StageTreeNode,
    StageSelectionRequest,
    StageTreeResponse,
    StageDetailResponse,
)
from services.patient_profile_service import get_patient_profile_service
from services.patient_stage_service import get_patient_stage_service
from api.auth import get_authenticated_user_id, get_user_id_allowing_guest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["Patient Profile"])

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


@router.post("/link", response_model=ProfileResponse)
async def link_account(
    data: LinkAccountRequest,
    user_id: str = Depends(get_authenticated_user_id)
):
    """
    Link a profile from another account using Patient Reference ID.
    
    This transfers the profile from the old account (ref_id) to the current user.
    Useful when a user changes login methods or emails.
    """
    logger.info(f"Linking account for user {user_id} with ref_id {data.patient_ref_id}")
    
    service = get_patient_profile_service()
    try:
        profile = await service.link_account(user_id, data.patient_ref_id)
        return ProfileResponse(
            profile=profile,
            message="Account linked successfully! Your medical journey has been restored."
        )
    except ValueError as e:
        logger.warning(f"Link account failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error linking account: {e}")
        raise HTTPException(status_code=500, detail="Failed to link account")


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


# ================================
# Treatment Stage Endpoints
# ================================

@router.get("/stages", response_model=StageTreeResponse)
async def get_stages():
    """
    Get hierarchical tree of treatment stages for UI selector.
    
    Returns all patient-facing stages organized as a tree structure.
    No authentication required - stages are public reference data.
    """
    service = get_patient_stage_service()
    tree = service.get_stage_tree(patient_facing_only=True)
    
    return StageTreeResponse(
        stages=tree,
        total_count=len(service.get_all_stages())
    )


@router.get("/stages/{stage_id}", response_model=StageDetailResponse)
async def get_stage_details(stage_id: str):
    """
    Get details for a specific treatment stage.
    
    Includes parent, children, and breadcrumb path.
    No authentication required.
    """
    service = get_patient_stage_service()
    stage = service.get_stage_by_id(stage_id)
    
    if not stage:
        raise HTTPException(
            status_code=404,
            detail=f"Stage '{stage_id}' not found"
        )
    
    parent = service.get_parent(stage_id)
    children = service.get_children(stage_id)
    breadcrumb = service.get_breadcrumb(stage_id)
    
    return StageDetailResponse(
        stage=stage,
        parent=parent,
        children=children,
        breadcrumb=breadcrumb
    )


@router.put("/stage/select", response_model=dict)
async def select_treatment_stage(
    data: StageSelectionRequest,
    user_id: str = Depends(get_user_id_allowing_guest)
):
    """
    Select a treatment stage for personalized responses.
    
    Updates the user's profile with the selected stage.
    Stage will be used to personalize AI responses.
    """
    logger.info(f"User {user_id} selecting stage: {data.stage_id}")
    
    try:
        # Validate stage exists
        stage_service = get_patient_stage_service()
        stage = stage_service.get_stage_by_id(data.stage_id)
        
        if not stage:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid stage ID: {data.stage_id}"
            )
        
        # Update user profile with selected stage
        profile_service = get_patient_profile_service()
        
        # Get or create profile (handles both OAuth and guest users)
        profile = await profile_service.get_or_create_profile(user_id)
        
        # Update the detailed stage using existing service method
        await profile_service.update_stage_detailed(user_id, data.stage_id)
        
        # Get breadcrumb for response
        breadcrumb = stage_service.get_breadcrumb(data.stage_id)
        
        logger.info(f"Successfully updated stage for {user_id} to {stage.name} ({data.stage_id})")
        
        return {
            "message": f"Stage updated to {stage.name}",
            "stage_id": data.stage_id,
            "stage_name": stage.name,
            "breadcrumb": breadcrumb
        }
    except HTTPException:
        # Re-raise HTTP exceptions (they're intentional)
        raise
    except Exception as e:
        logger.error(f"Error selecting stage for {user_id}: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to select stage: {str(e)}"
        )


@router.get("/my-stage", response_model=dict)
async def get_my_stage(
    user_id: str = Depends(get_authenticated_user_id)
):
    """
    Get the current user's selected treatment stage with full context.
    
    Returns stage details, breadcrumb, and AI context.
    """
    profile_service = get_patient_profile_service()
    profile = await profile_service.get_profile(user_id)
    
    if not profile:
        return {
            "stage_id": None,
            "stage_name": "Not selected",
            "breadcrumb": [],
            "message": "Please complete onboarding to set your stage"
        }
    
    # Get detailed stage if set
    stage_service = get_patient_stage_service()
    detailed_stage_id = getattr(profile, 'detailed_stage_id', None)
    
    if detailed_stage_id:
        stage = stage_service.get_stage_by_id(detailed_stage_id)
        if stage:
            return {
                "stage_id": detailed_stage_id,
                "stage_name": stage.name,
                "description": stage.description,
                "breadcrumb": stage_service.get_breadcrumb(detailed_stage_id),
                "ai_context": stage_service.format_stage_context_prompt(detailed_stage_id)
            }
    
    # Fall back to basic stage
    return {
        "stage_id": profile.current_stage,
        "stage_name": profile.current_stage,
        "breadcrumb": [],
        "message": "Using basic stage. Select a detailed stage for personalized responses."
    }

