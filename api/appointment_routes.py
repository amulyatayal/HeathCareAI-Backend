"""
Appointment Routes
Endpoints for managing patient appointments.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import get_authenticated_user_id
from api.compliance_dependencies import require_active_data_processing
from models.appointment_schemas import (
    AppointmentCreate,
    Appointment,
    AppointmentListResponse,
    DeleteResponse,
)
from services.appointment_service import get_appointment_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Appointments"])


@router.post("/appointments", response_model=Appointment, status_code=201)
async def create_appointment(
    body: AppointmentCreate,
    user_id: str = Depends(require_active_data_processing),
):
    """Create a new appointment."""
    service = get_appointment_service()
    result = await service.create_appointment(user_id, body.model_dump())
    return Appointment(**result)


@router.get("/appointments", response_model=AppointmentListResponse)
async def list_appointments(
    status: Optional[str] = Query(None, description="Filter by status: upcoming, past, cancelled"),
    user_id: str = Depends(get_authenticated_user_id),
):
    """List appointments with optional status filter."""
    service = get_appointment_service()
    result = await service.list_appointments(user_id, status=status)
    return AppointmentListResponse(**result)


@router.delete("/appointments/{appointment_id}", response_model=DeleteResponse)
async def delete_appointment(
    appointment_id: str,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Delete an appointment."""
    service = get_appointment_service()
    deleted = await service.delete_appointment(user_id, appointment_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Appointment not found")

    return DeleteResponse()
