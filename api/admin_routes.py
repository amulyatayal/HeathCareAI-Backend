"""
Admin API Routes
Endpoints for clinician authentication and pathway resource management.

All endpoints are under /api/v2/admin (mounted with prefix="/api/v2/admin").
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from models.admin_schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminUser,
    PathwayResourceCreate,
    PathwayResourceUpdate,
    PathwayResourceResponse,
    PathwayResourceListResponse,
    DeleteResponse,
    AccessCodeCreateRequest,
    AccessCodeResponse,
    AccessCodeListResponse,
)
from models.notification_schemas import (
    NotificationCreateRequest,
    AdminNotificationResponse,
    AdminNotificationListResponse,
)
from services.admin_auth_service import get_admin_auth_service
from services.pathway_resource_service import get_pathway_resource_service
from services.access_code_service import get_access_code_service
from services.notification_service import get_notification_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin Portal"])


# ================================
# Admin Auth Dependency
# ================================

async def get_current_admin(request: Request) -> dict:
    """
    FastAPI dependency that validates the admin JWT from the
    Authorization header and returns the decoded payload.
    
    Raises 401 on missing/invalid/expired tokens.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    token = auth_header[7:]
    service = get_admin_auth_service()
    payload = service.verify_token(token)
    
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return payload


# ================================
# Authentication
# ================================

@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(body: AdminLoginRequest):
    """
    Authenticate a clinician and return a JWT.
    
    The token must be sent as `Authorization: Bearer <token>`
    on all subsequent admin requests.
    """
    service = get_admin_auth_service()
    result = service.authenticate(body.email, body.password)
    
    if not result:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    return AdminLoginResponse(
        token=result["token"],
        user=AdminUser(**result["user"]),
    )


# ================================
# Pathway Resources CRUD
# ================================

@router.get("/pathway-resources", response_model=PathwayResourceListResponse)
async def list_pathway_resources(
    admin: dict = Depends(get_current_admin),
):
    """
    List pathway resources for the authenticated clinician.
    """
    service = get_pathway_resource_service()
    clinician_id = admin["sub"]
    resources = service.list_resources(clinician_id=clinician_id)
    return PathwayResourceListResponse(
        resources=[PathwayResourceResponse(**r) for r in resources]
    )


@router.post("/pathway-resources", response_model=PathwayResourceResponse, status_code=201)
async def create_pathway_resource(
    body: PathwayResourceCreate,
    admin: dict = Depends(get_current_admin),
):
    """Create a new educational resource linked to pathway stages."""
    service = get_pathway_resource_service()
    result = service.create_resource(body.model_dump())
    return PathwayResourceResponse(**result)


@router.put("/pathway-resources/{resource_id}", response_model=PathwayResourceResponse)
async def update_pathway_resource(
    resource_id: str,
    body: PathwayResourceUpdate,
    admin: dict = Depends(get_current_admin),
):
    """Update an existing pathway resource."""
    service = get_pathway_resource_service()
    result = service.update_resource(resource_id, body.model_dump(exclude_unset=True))
    
    if result is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    
    return PathwayResourceResponse(**result)


@router.delete("/pathway-resources/{resource_id}", response_model=DeleteResponse)
async def delete_pathway_resource(
    resource_id: str,
    admin: dict = Depends(get_current_admin),
):
    """Delete a pathway resource (soft delete)."""
    service = get_pathway_resource_service()
    deleted = service.delete_resource(resource_id)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Resource not found")
    
    return DeleteResponse()


# ================================
# Access Codes
# ================================

@router.post("/access-codes", response_model=AccessCodeResponse, status_code=201)
async def create_access_code(
    body: AccessCodeCreateRequest,
    admin: dict = Depends(get_current_admin),
):
    """Generate a new access code for the authenticated clinician."""
    clinician_id = admin["sub"]
    clinician_name = admin.get("email", "")

    auth_service = get_admin_auth_service()
    user = auth_service.get_user_by_email(admin["email"])
    if user:
        clinician_name = user.get("name", clinician_name)

    service = get_access_code_service()
    result = service.create_code(
        clinician_id=clinician_id,
        clinician_name=clinician_name,
        hospital_id=body.hospital_id,
    )
    return AccessCodeResponse(**result)


@router.get("/access-codes", response_model=AccessCodeListResponse)
async def list_access_codes(
    admin: dict = Depends(get_current_admin),
):
    """List all access codes for the authenticated clinician."""
    clinician_id = admin["sub"]
    service = get_access_code_service()
    codes = service.list_codes(clinician_id)
    return AccessCodeListResponse(
        codes=[AccessCodeResponse(**c) for c in codes]
    )


@router.delete("/access-codes/{code}", response_model=DeleteResponse)
async def revoke_access_code(
    code: str,
    admin: dict = Depends(get_current_admin),
):
    """Revoke an access code (soft deactivate)."""
    service = get_access_code_service()
    revoked = service.revoke_code(code)

    if not revoked:
        raise HTTPException(status_code=404, detail="Access code not found or already revoked")

    return DeleteResponse(message="Access code revoked successfully")


# ================================
# Notifications
# ================================

@router.post("/notifications", response_model=AdminNotificationResponse, status_code=201)
async def create_notification(
    body: NotificationCreateRequest,
    admin: dict = Depends(get_current_admin),
):
    """Create and broadcast a notification to all patients associated with this clinician."""
    clinician_id = admin["sub"]
    clinician_name = admin.get("email", "")
    auth_service = get_admin_auth_service()
    user = auth_service.get_user_by_email(admin["email"])
    if user:
        clinician_name = user.get("name", clinician_name)

    svc = get_notification_service()
    result = svc.create_notification(
        clinician_id=clinician_id,
        clinician_name=clinician_name,
        title=body.title,
        message=body.message,
        priority=body.priority.value,
    )
    return AdminNotificationResponse(**result)


@router.get("/notifications", response_model=AdminNotificationListResponse)
async def list_notifications(
    admin: dict = Depends(get_current_admin),
):
    """List notifications sent by the authenticated clinician (newest first)."""
    svc = get_notification_service()
    items = svc.list_notifications_for_clinician(admin["sub"])
    return AdminNotificationListResponse(
        notifications=[AdminNotificationResponse(**i) for i in items]
    )


@router.delete("/notifications/{notification_id}", response_model=DeleteResponse)
async def delete_notification(
    notification_id: str,
    admin: dict = Depends(get_current_admin),
):
    """Soft-delete a notification (patients no longer see it)."""
    svc = get_notification_service()
    ok = svc.soft_delete_notification(notification_id, admin["sub"])
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return DeleteResponse(message="Notification deleted successfully")
