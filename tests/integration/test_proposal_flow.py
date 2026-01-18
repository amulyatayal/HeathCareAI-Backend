
import pytest
from fastapi.testclient import TestClient
from main import app
from services.patient_profile_service import get_patient_profile_service
from services.pathway_orchestrator import PathwayOrchestrator
from models.schemas import PipelineResponse
import asyncio

client = TestClient(app)

# Use a specific test user ID to avoid conflict with real data
TEST_USER_ID = "integration_test_user_v2"

@pytest.fixture
async def setup_profile():
    service = get_patient_profile_service()
    # Clean start
    await service.delete_profile(TEST_USER_ID)
    # Create profile
    profile = await service.create_profile(TEST_USER_ID)
    return profile

@pytest.mark.asyncio
async def test_proposal_generation_flow():
    """
    Test that sending a message implying a stage change triggers a proposal.
    Flow:
    1. Set stage to 'awaiting_results'
    2. Send 'I had surgery yesterday'
    3. Expect modification_proposal in response
    """
    print(f"\n[TEST] Starting proposal flow test for {TEST_USER_ID}")
    
    # 1. Setup Service
    service = get_patient_profile_service()
    await service.delete_profile(TEST_USER_ID)
    await service.create_profile(TEST_USER_ID)
    
    # Set initial stage: Awaiting Results
    # We use update_stage_detailed to ensure detailed ID is set (1 = Results Clinic)
    await service.update_stage_detailed(TEST_USER_ID, "1")
    
    # Verify initial state
    profile = await service.get_profile(TEST_USER_ID)
    print(f"[TEST] Initial Stage: {profile.current_stage} (Detailed: {profile.detailed_stage_id})")
    assert profile.detailed_stage_id == "1"
    
    # 2. Simulate Chat Request
    # We need to manually construct the request context or mock auth
    # For integration, it's easier to call the orchestrator directly if we want to bypass auth headers complexity,
    # OR we can just mock the dependency `get_authenticated_user_id` in main.py if needed.
    # But let's try direct Orchestrator call for simplicity and speed.
    
    from services.agents.orchestrator import PipelineOrchestrator
    orchestrator = PipelineOrchestrator()
    
    print("[TEST] Processing message: 'I had surgery yesterday'")
    response = await orchestrator.process(
        message="I had surgery yesterday",
        user_id=TEST_USER_ID,
        is_guest=False
    )
    
    # 3. Validation
    print(f"[TEST] Response Intent: {response.intent}")
    
    if response.modification_proposal:
        print(f"[TEST] SUCCESS: Proposal Received!")
        print(f"       Message: {response.modification_proposal.message}")
        print(f"       New Stage ID: {response.modification_proposal.stage_id}")
        
        assert response.modification_proposal.stage_id == "2.1" # Breast surgery via Global Search
    else:
        print("[TEST] FAILURE: No proposal received.")
        # Print debug info from stage result if available
        print(f"       Inferred Stage: {response.stage}")
            
        assert False, "Modification proposal should be present"

if __name__ == "__main__":
    asyncio.run(test_proposal_generation_flow())
