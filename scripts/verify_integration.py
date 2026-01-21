import asyncio
import sys
import logging
from unittest.mock import AsyncMock, MagicMock, patch
from dotenv import load_dotenv

# Setup path and env
sys.path.insert(0, '.')
load_dotenv()

# Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from services.agents.orchestrator import PipelineOrchestrator
from models.schemas import StageResult, IntentResult, AgentTrace, AgentStatus, PipelineContext

async def main():
    print("\n--- Verifying Orchestrator Chat Confirmation (Loop Prevention) ---\n")
    
    # Mock dependencies
    with patch('services.agents.orchestrator.get_patient_profile_service') as mock_get_profile:
        
        # 1. Mock Patient Profile
        mock_profile_service = AsyncMock()
        mock_profile = MagicMock()
        mock_profile.current_stage = "pre_diagnosis"
        mock_profile.onboarding_completed = True
        mock_profile_service.get_profile.return_value = mock_profile
        mock_profile_service.update_stage = AsyncMock()
        mock_get_profile.return_value = mock_profile_service
        
        # 3. Initialize Pipeline
        orchestrator = PipelineOrchestrator(enable_llm_validation=False)
        
        # 4. Mock Intent/Reasoning/Retrieval to focus on Orchestration Logic
        async def mock_intent_run(ctx):
            ctx.intent_result = IntentResult(intent="symptoms", confidence=0.9)
            trace = AgentTrace(agent_name="intent", status=AgentStatus.SUCCESS, latency_ms=10)
            return ctx, trace

        orchestrator.intent_agent.run = AsyncMock(side_effect=mock_intent_run)

        async def mock_skip_phase(ctx):
            from models.schemas import RetrievalResult
            if not ctx.retrieval_result:
                ctx.retrieval_result = RetrievalResult(chunks=[], total_retrieved=0)
            return ctx, AgentTrace(agent_name="mock", status=AgentStatus.SKIPPED, latency_ms=0)
            
        orchestrator.retrieval_agent.run = AsyncMock(side_effect=mock_skip_phase)
        orchestrator.validator_agent.run = AsyncMock(side_effect=mock_skip_phase)
        
        async def mock_reasoning_method(ctx):
             # This method must return just ctx
             return ctx
             
        orchestrator._run_reasoning_phase = AsyncMock(side_effect=mock_reasoning_method)
        
        # ==========================================================
        # SCENARIO 1: First Detection (Mismatch)
        # ==========================================================
        print("\n[Scenario 1] User says 'I had surgery yesterday'. Profile='pre_diagnosis'.")
        print("Expected: Orchestrator asks confirmation question.")
        
        # Run process
        response1 = await orchestrator.process(
            message="I had surgery yesterday",
            user_id="test_user",
            is_guest=False
        )
        
        print(f"Response: {response1.response}")
        
        if "Is that correct?" in response1.response:
            print("✅ SUCCESS: Confirmation question asked.")
        else:
            print("❌ FAILURE: Did not ask simple confirmation question.")
            
        # ==========================================================
        # SCENARIO 2: User Confirms ("Yes")
        # ==========================================================
        print("\n[Scenario 2] User says 'Yes'. History shows we just asked.")
        print("Expected: Orchestrator updates profile and acknowledges.")
        
        # Synthesize history causing the Bot to have asked last
        history = [
            {"role": "user", "content": "I had surgery yesterday"},
            {"role": "assistant", "content": "It sounds like you might be in the **Active Treatment** stage. Is that correct?"}
        ]
        
        # Mock StageAgentV2 to infer SAME stage (active_treatment) because of history
        # (Since we are using Real StageAgentV2, we trust it will infer correctly if we mock history)
        # But for speed/reliability in this unit-test-like script, let's mock StageAgentV2 too?
        # Ideally we validatethe REAL agent logic, but we can assume it works from previous test.
        # Let's mock StageAgentV2 to guarantee "High Certainty / Active Treatment".
        
        async def mock_stage_run(ctx):
            ctx.stage_result = StageResult(
                stage="active_treatment",
                certainty="high",
                certainty_score=0.95,
                signals=["Yes"]
            )
            ctx.metadata["granular_stage_id"] = "2.1"
            return ctx, AgentTrace(agent_name="stage", status=AgentStatus.SUCCESS, latency_ms=10)
        
        orchestrator.stage_agent.run = AsyncMock(side_effect=mock_stage_run)
        
        response2 = await orchestrator.process(
            message="Yes",
            user_id="test_user",
            is_guest=False,
            conversation_history=history
        )
        
        print(f"Response: {response2.response}")
        
        if mock_profile_service.update_stage.called:
            print("✅ SUCCESS: Profile Update called!")
            # Verify clean response (check for acknowledgement)
            if "Thanks, I've updated" in response2.response:
                print("✅ SUCCESS: Acknowledged update.")
        else:
            print("❌ FAILURE: Profile Update NOT called.")

        # ==========================================================
        # SCENARIO 3: User Ignores ("What is weather?")
        # ==========================================================
        print("\n[Scenario 3] User says 'What is weather?'. History shows we just asked.")
        print("Expected: NO Profile Update. Normal Answer (skipped proposal).")
        
        mock_profile_service.update_stage.reset_mock()
        
        response3 = await orchestrator.process(
            message="What is weather?",
            user_id="test_user",
            is_guest=False,
            conversation_history=history
        )
        
        if not mock_profile_service.update_stage.called:
             print("✅ SUCCESS: Profile Update Skipped (Correctly Ignored).")
        else:
             print("❌ FAILURE: Profile Update called unexpectedly.")

if __name__ == "__main__":
    asyncio.run(main())
