"""
Integration tests for POST /api/v2/chat/ with unauthenticated test users.

Pre-seeds test profiles in DynamoDB, sends real chat requests via FastAPI
TestClient, and asserts on pipeline responses (intent, stage, response text, etc.).

Authentication is bypassed via IS_AUTHENTICATION_REQUIRED=N so no Bearer JWT
or X-User-ID header is needed — the pipeline resolves to a known test user id
whose profile is already in the DB.

Usage:
    PYTHONPATH=. pytest tests/test_chat_integration.py -v
"""

import asyncio
import logging
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from main import app
from config.pipeline_config import PatientStage
from models.patient_profile import PatientProfile
from services.patient_biomarkers_service import PatientBiomarkersService
from services.patient_profile_service import PatientProfileService

logger = logging.getLogger(__name__)

TEST_USER_ID = "test_user_integration"
CHAT_URL = "/api/v2/chat/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings_mock(user_id: str = TEST_USER_ID) -> MagicMock:
    """Return a Settings mock with authentication bypassed."""
    s = MagicMock()
    s.chat_authentication_required = False
    s.unauthenticated_test_user_id = user_id
    return s


def _build_profile(
    user_id: str = TEST_USER_ID,
    stage: PatientStage = PatientStage.ACTIVE_TREATMENT,
    onboarding_completed: bool = True,
) -> PatientProfile:
    """Build a PatientProfile for seeding into DynamoDB."""
    now = datetime.utcnow()
    return PatientProfile(
        user_id=user_id,
        created_at=now,
        updated_at=now,
        current_stage=stage,
        onboarding_completed=onboarding_completed,
        onboarding_completed_at=now if onboarding_completed else None,
    )


async def seed_profile(profile: PatientProfile) -> None:
    """Write a profile to DynamoDB."""
    svc = PatientProfileService()
    svc.table.put_item(Item=profile.to_dynamodb_item())
    logger.info(f"Seeded test profile: user_id={profile.user_id}, stage={profile.current_stage}")


async def delete_profile(user_id: str) -> None:
    """Remove a test profile from DynamoDB (cleanup)."""
    svc = PatientProfileService()
    try:
        svc.table.delete_item(Key={"user_id": user_id})
        logger.info(f"Deleted test profile: user_id={user_id}")
    except Exception as e:
        logger.warning(f"Cleanup failed for {user_id}: {e}")


async def delete_biomarkers(user_id: str) -> None:
    """Remove all biomarker rows for a user (including LATEST pointer)."""
    svc = PatientBiomarkersService()
    try:
        from boto3.dynamodb.conditions import Key

        response = svc.table.query(
            KeyConditionExpression=Key("user_id").eq(user_id),
            ScanIndexForward=False,
        )
        items = response.get("Items", [])
        for item in items:
            ts = item.get("timestamp")
            if ts:
                svc.table.delete_item(Key={"user_id": user_id, "timestamp": ts})
    except Exception as e:
        logger.warning(f"Biomarker cleanup failed for {user_id}: {e}")


async def seed_biomarkers(user_id: str, **kwargs: float) -> None:
    """Create a biomarker snapshot with provided fields."""
    svc = PatientBiomarkersService()
    await svc.create_entry(user_id=user_id, data=kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def settings_patch():
    """Module-scoped patch: bypass auth for all tests in this file."""
    with patch("api.routes.get_settings", return_value=_make_settings_mock()) as p:
        yield p


@pytest.fixture()
async def seeded_profile():
    """Seed a default test profile before a test and clean up after."""
    profile = _build_profile()
    await delete_biomarkers(profile.user_id)
    await seed_profile(profile)
    await seed_biomarkers(
        profile.user_id,
        weight_kg=65.0,
        height_cm=165.0,
        waist_circumference_cm=82.0,
    )
    yield profile
    await delete_biomarkers(profile.user_id)
    await delete_profile(profile.user_id)


@pytest.fixture()
async def seeded_profile_with_weight():
    """Seed profile + biomarker weight and clean up profile after test."""
    profile = _build_profile()
    await delete_biomarkers(profile.user_id)
    await seed_profile(profile)
    await seed_biomarkers(profile.user_id, weight_kg=65.0)
    yield profile
    await delete_biomarkers(profile.user_id)
    await delete_profile(profile.user_id)


@pytest.fixture()
async def client(settings_patch):
    """Async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestChatIntegration:
    """
    End-to-end chat tests hitting POST /api/v2/chat/ without authentication.

    Each test:
      1. Optionally seeds a profile in DynamoDB for TEST_USER_ID.
      2. Sends a chat message via the FastAPI TestClient.
      3. Asserts on the PipelineResponse fields.
    """

    @pytest.mark.asyncio
    async def test_nutrition_query_returns_nutrition_intent(self, client, seeded_profile):
        """Asking about food should classify as nutrition intent."""
        resp = await client.post(
            CHAT_URL,
            json={"message": "What should I eat during chemotherapy?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "nutrition"
        assert len(data["response"]) > 0

    @pytest.mark.asyncio
    async def test_exercise_query_returns_exercise_intent(self, client, seeded_profile):
        """Asking about exercise should classify as exercise intent."""
        resp = await client.post(
            CHAT_URL,
            json={"message": "What exercises can I do after surgery?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "exercise"

    @pytest.mark.asyncio
    async def test_guest_without_profile_still_works(self, client):
        """Chat should work even when no profile is seeded (pure guest)."""
        resp = await client.post(
            CHAT_URL,
            json={"message": "What are common side effects of chemotherapy?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"]
        assert data["intent"] in (
            "side_effects",
            "cancer_treatment",
            "symptoms",
            "medication_info",
        )

    @pytest.mark.asyncio
    async def test_conversation_history_is_forwarded(self, client, seeded_profile):
        """Pipeline should accept and use conversation_history."""
        history = [
            {"role": "user", "content": "I was diagnosed last month"},
            {"role": "assistant", "content": "I'm sorry to hear that. How can I help?"},
        ]
        resp = await client.post(
            CHAT_URL,
            json={
                "message": "What foods help with recovery?",
                "conversation_history": history,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "nutrition"

    @pytest.mark.asyncio
    async def test_response_includes_citations(self, client, seeded_profile):
        """Responses for medical queries should include citation metadata."""
        resp = await client.post(
            CHAT_URL,
            json={"message": "What are the side effects of tamoxifen?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "citations" in data

    @pytest.mark.asyncio
    async def test_trace_returned_when_requested(self, client, seeded_profile):
        """include_trace=true should populate the trace array."""
        resp = await client.post(
            CHAT_URL,
            json={
                "message": "How do I manage fatigue during treatment?",
                "include_trace": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data.get("trace"), list)
        assert len(data["trace"]) > 0

    @pytest.mark.asyncio
    async def test_weight_followup_maintains_context(self, client, seeded_profile_with_weight):
        """
        Simulates: user asks nutrition question → bot confirms known weight → user
        replies with updated weight. The pipeline should restore the original
        question and persist updated weight in biomarkers.
        """
        history = [
            {"role": "user", "content": "What should I eat during chemo?"},
            {
                "role": "assistant",
                "content": (
                    "I have your current weight as 65.0 kg. "
                    "Has this changed? If yes, please share your updated weight in kg."
                ),
            },
        ]
        resp = await client.post(
            CHAT_URL,
            json={
                "message": "70 kg",
                "conversation_history": history,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "nutrition"
        assert len(data["response"]) > 0

        biomarker_svc = PatientBiomarkersService()
        latest = await biomarker_svc.list_entries(TEST_USER_ID, limit=1)
        assert latest["total_count"] > 0
        assert latest["entries"][0]["weight_kg"] == pytest.approx(70.0)

    @pytest.mark.asyncio
    async def test_after_weight_update_agent_asks_for_height(self, client, seeded_profile_with_weight):
        """
        If only weight is available, user providing a new weight should trigger
        a follow-up prompt for height.
        """
        history = [
            {"role": "user", "content": "What should I eat during chemo?"},
            {
                "role": "assistant",
                "content": (
                    "I have your current weight as 65.0 kg. "
                    "Has this changed? If yes, please share your updated weight in kg."
                ),
            },
        ]
        resp = await client.post(
            CHAT_URL,
            json={
                "message": "70 kg",
                "conversation_history": history,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "height in cm" in data["response"].lower()

    @pytest.mark.asyncio
    async def test_after_height_update_agent_asks_for_waist(self, client, seeded_profile_with_weight):
        """
        If only weight and height are available, after height update the next
        required follow-up should ask for waist circumference.
        """
        await seed_biomarkers(TEST_USER_ID, height_cm=165.0)
        history = [
            {"role": "user", "content": "What should I eat during chemo?"},
            {
                "role": "assistant",
                "content": (
                    "I have your current height as 165.0 cm. "
                    "Has this changed? If yes, please share your updated height in cm."
                ),
            },
        ]
        resp = await client.post(
            CHAT_URL,
            json={
                "message": "166 cm",
                "conversation_history": history,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "waist circumference" in data["response"].lower()
