"""
Profile API Routes
Endpoints for patient profile management.

Requires authentication - guest users cannot access profile features.
"""

import logging
from datetime import datetime
from typing import Optional

from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response

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
from models.admin_schemas import AssociateRequest, AssociateResponse
from models.patient_compliance_api_schemas import (
    ActivityLogResponse,
    NomineeResponse,
    NomineeUpsertRequest,
    NomineeUpsertResponse,
)
from models.patient_privacy_schemas import (
    AccountDeletionRequest,
    AccountDeletionResponse,
    DELETE_ACCOUNT_CONFIRMATION,
)
from services.patient_profile_service import get_patient_profile_service
from services.patient_data_export_service import get_patient_data_export_service
from services.patient_account_deletion_service import get_patient_account_deletion_service
from services.patient_compliance_audit_service import get_patient_compliance_audit_service
from services.patient_activity_log_service import get_patient_activity_log_service
from services.patient_jurisdiction import is_india, resolve_jurisdiction
from services.patient_nominee_service import get_patient_nominee_service
from services.patient_stage_service import get_patient_stage_service
from services.access_code_service import get_access_code_service
from api.auth import get_authenticated_user_id, get_user_id_allowing_guest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["Patient Profile"])
me_router = APIRouter(prefix="/me", tags=["Patient Profile"])


def _privacy_client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _privacy_hospital_id(request: Request) -> Optional[str]:
    return request.headers.get("X-Hospital-Id") or request.headers.get("x-hospital-id")


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


# ================================
# Patient-Clinician Association
# ================================

@me_router.post("/associate", response_model=AssociateResponse)
async def associate_with_clinician(
    body: AssociateRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    """
    Associate the authenticated patient with a clinician via access code.

    Looks up the access code to find the clinician, then stores the
    association on the patient's profile. Idempotent — re-calling with
    the same code updates the association rather than duplicating it.
    """
    if not body.access_code:
        raise HTTPException(
            status_code=400,
            detail="access_code is required to associate with a clinician",
        )

    code_service = get_access_code_service()
    code_info = code_service.lookup_code(body.access_code)

    if not code_info:
        raise HTTPException(
            status_code=404,
            detail="Invalid or expired access code",
        )

    profile_service = get_patient_profile_service()
    profile = await profile_service.get_or_create_profile(user_id)

    profile.clinician_id = code_info["clinician_id"]
    profile.clinician_name = code_info["clinician_name"]
    profile.hospital_id = body.hospital_id
    profile.updated_at = datetime.utcnow()

    from botocore.exceptions import ClientError
    try:
        profile_service.table.put_item(Item=profile.to_dynamodb_item())
        logger.info(
            f"Patient {user_id} associated with clinician {code_info['clinician_id']} "
            f"at hospital {body.hospital_id}"
        )
    except ClientError as e:
        logger.error(f"Error saving association for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to save association")

    return AssociateResponse(
        clinician_id=code_info["clinician_id"],
        clinician_name=code_info["clinician_name"],
        hospital_id=body.hospital_id,
    )


# ================================
# GDPR / DPDPA — activity, nominee (India), export & erasure
# ================================


@me_router.get("/activity-log", response_model=ActivityLogResponse)
async def get_my_activity_log(
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_authenticated_user_id),
):
    return await get_patient_activity_log_service().list_for_user(user_id, limit=limit)


@me_router.post("/nominee", response_model=NomineeUpsertResponse)
async def upsert_my_nominee(
    request: Request,
    body: NomineeUpsertRequest,
    user_id: str = Depends(get_authenticated_user_id),
):
    profile = await get_patient_profile_service().get_profile(user_id)
    hid = profile.hospital_id if profile else None
    jurisdiction = resolve_jurisdiction(request, hid)
    if not is_india(jurisdiction):
        raise HTTPException(
            status_code=403,
            detail="Nominee registration is only available for India jurisdiction (DPDPA).",
        )
    nid = await get_patient_nominee_service().upsert_nominee(
        user_id,
        name=body.name,
        email=body.email,
        relationship=body.relationship,
        phone=body.phone,
        ip=_privacy_client_ip(request),
        user_agent=request.headers.get("user-agent") or request.headers.get("User-Agent"),
        hospital_id=_privacy_hospital_id(request) or hid,
        jurisdiction=jurisdiction,
    )
    return NomineeUpsertResponse(message="Nominee saved.", nominee_id=nid)


@me_router.get("/nominee", response_model=Optional[NomineeResponse])
async def get_my_nominee(
    request: Request,
    user_id: str = Depends(get_authenticated_user_id),
):
    profile = await get_patient_profile_service().get_profile(user_id)
    hid = profile.hospital_id if profile else None
    jurisdiction = resolve_jurisdiction(request, hid)
    if not is_india(jurisdiction):
        raise HTTPException(
            status_code=403,
            detail="Nominee is only applicable for India jurisdiction (DPDPA).",
        )
    data = get_patient_nominee_service().get_decrypted(user_id)
    if not data:
        return None
    return NomineeResponse(**data)


@me_router.get("/export")
async def export_my_data(
    request: Request,
    user_id: str = Depends(get_authenticated_user_id),
):
    """
    Download a ZIP containing export.json (machine-readable patient data copy).
    Logs a data_exported compliance event.
    """
    profile = await get_patient_profile_service().get_profile(user_id)
    hid = profile.hospital_id if profile else None
    jurisdiction = resolve_jurisdiction(request, hid)

    export_svc = get_patient_data_export_service()
    doc = await export_svc.build_export_document(user_id)
    zbytes = export_svc.build_zip_bytes(doc)

    await get_patient_compliance_audit_service().record_event(
        user_id=user_id,
        action="data_exported",
        payload={
            "export_version": doc.get("export_version"),
            "artifact": "patient_export.zip",
        },
        ip=_privacy_client_ip(request),
        user_agent=request.headers.get("user-agent") or request.headers.get("User-Agent"),
        hospital_id=_privacy_hospital_id(request) or hid,
        jurisdiction=jurisdiction,
    )

    date_str = datetime.utcnow().strftime("%Y%m%d")
    filename = f"patient-data-export-{date_str}.zip"
    quoted = quote(filename)
    return Response(
        content=zbytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quoted}'
            ),
        },
    )


@me_router.delete("", response_model=AccountDeletionResponse)
async def delete_my_account(
    request: Request,
    body: AccountDeletionRequest = Body(...),
    user_id: str = Depends(get_authenticated_user_id),
):
    """
    Permanently delete the authenticated patient's account and associated DynamoDB rows.
    Requires JSON body: {"confirmation": "DELETE MY ACCOUNT"}.
    """
    if body.confirmation != DELETE_ACCOUNT_CONFIRMATION:
        raise HTTPException(
            status_code=400,
            detail=f'Confirmation must be exactly "{DELETE_ACCOUNT_CONFIRMATION}"',
        )

    profile = await get_patient_profile_service().get_profile(user_id)
    hid = profile.hospital_id if profile else None
    jurisdiction = resolve_jurisdiction(request, hid)

    await get_patient_account_deletion_service().erase_patient_data(
        user_id,
        ip=_privacy_client_ip(request),
        user_agent=request.headers.get("user-agent") or request.headers.get("User-Agent"),
        hospital_id=_privacy_hospital_id(request) or hid,
        jurisdiction=jurisdiction,
    )

    return AccountDeletionResponse(
        message="Your account and associated data have been deleted.",
    )

