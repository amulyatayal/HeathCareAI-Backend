"""
Optional test-user session endpoint (non-Google) controlled by ENABLE_TEST_USER_LOGIN.
"""

import logging

from botocore.exceptions import ClientError, NoCredentialsError
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException

from config.settings import get_settings
from services.patient_jwt import mint_test_user_access_token
from services.patient_profile_service import get_patient_profile_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


class TestSessionRequest(BaseModel):
    user_id: str = Field(..., min_length=4, max_length=128)


class TestSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TestSessionStatusResponse(BaseModel):
    """Whether the server allows test-user sign-in (mirrors ENABLE_TEST_USER_LOGIN)."""

    enabled: bool


@router.get("/test-session/status", response_model=TestSessionStatusResponse)
async def test_session_status():
    return TestSessionStatusResponse(enabled=get_settings().enable_test_user_login)


@router.post("/test-session", response_model=TestSessionResponse)
async def create_test_session(body: TestSessionRequest):
    cfg = get_settings()
    if not cfg.enable_test_user_login:
        raise HTTPException(
            status_code=403,
            detail="Test user login is not enabled on this server",
        )
    uid = body.user_id.strip()
    try:
        token, expires_in = mint_test_user_access_token(uid, cfg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Test login only: ensure PatientProfiles row exists (Google login does not do this on sign-in).
    try:
        profile_svc = get_patient_profile_service()
        await profile_svc.get_or_create_profile(uid)
    except (ClientError, NoCredentialsError) as e:
        logger.error("Test user login: could not seed PatientProfiles for %s: %s", uid, e)
        raise HTTPException(
            status_code=503,
            detail="Could not create or load patient profile in DynamoDB. Configure AWS credentials (e.g. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY or aws configure) and ensure the PatientProfiles table exists.",
        ) from e

    return TestSessionResponse(access_token=token, expires_in=expires_in)
