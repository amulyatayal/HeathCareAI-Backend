"""
Orchestrator Flow Eval: Answer-First Stage Confirmation

Tests the new "answer first, soft confirm later" flow:
  FLOW-01: Stage proposal is appended to helpful answer (not standalone)
  FLOW-02: "yes" confirms broad stage only, no child drilling
  FLOW-03: "no" reverts and suppresses re-proposal  
  FLOW-04: Deferred sub-stage question appears on next turn (one-shot)
  FLOW-05: Sub-stage question is NOT repeated on subsequent turns

Usage:
    python tests/eval_orchestrator_flow.py
"""

import asyncio
import sys
import os
import json
import time
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.agents.orchestrator import PipelineOrchestrator
from models.schemas_pipeline import PipelineResponse

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

@dataclass
class FlowTestResult:
    test_id: str
    name: str
    passed: bool
    checks: List[Dict]
    response_text: str
    latency_ms: int


async def send_message(
    orchestrator: PipelineOrchestrator,
    message: str,
    user_id: str,
    session_id: str,
    conversation_history: List[Dict],
) -> PipelineResponse:
    """Send a message through the orchestrator pipeline."""
    response = await orchestrator.process(
        message=message,
        session_id=session_id,
        user_id=user_id,
        is_guest=False,
        conversation_history=conversation_history,
        include_trace=False,
    )
    return response


def check(description: str, condition: bool) -> Dict:
    """Create a check result."""
    return {
        "description": description,
        "passed": condition,
        "symbol": "✅" if condition else "❌",
    }


# ─────────────────────────────────────────────
# Setup: Create a test user with adjuvant_chemo stage
# ─────────────────────────────────────────────

async def setup_test_user(user_id: str, stage: str = "adjuvant_chemo", detailed_stage_id: str = "3") -> None:
    """Create or reset a test user profile at the given stage."""
    from services.patient_profile_service import get_patient_profile_service
    from config.pipeline_config import PatientStage
    
    profile_service = get_patient_profile_service()
    profile = await profile_service.get_or_create_profile(user_id)
    
    # Set stage
    stage_enum = PatientStage(stage)
    profile.current_stage = stage_enum
    profile.detailed_stage_id = detailed_stage_id
    profile.detailed_stage_label = stage
    profile.onboarding_completed = True
    profile.sub_stage_asked = False
    
    # Save
    profile_service.table.put_item(Item=profile.to_dynamodb_item())
    logger.info(f"Test user {user_id} set to stage={stage}, detailed_id={detailed_stage_id}")


async def get_test_profile(user_id: str):
    """Get the current profile for a test user."""
    from services.patient_profile_service import get_patient_profile_service
    profile_service = get_patient_profile_service()
    return await profile_service.get_profile(user_id)


# ─────────────────────────────────────────────
# Test: FLOW-01  Answer-first proposal
# ─────────────────────────────────────────────

async def test_flow_01(orchestrator: PipelineOrchestrator) -> FlowTestResult:
    """
    FLOW-01: When stage change is detected, the response should contain
    BOTH a helpful answer AND the stage proposal appended at the end.
    The pipeline should NOT stop and return a proposal-only response.
    """
    user_id = "eval_flow_01"
    session_id = "eval_flow_01_session"
    
    await setup_test_user(user_id, "adjuvant_chemo", "3")
    
    start = time.time()
    response = await send_message(
        orchestrator,
        "had surgery yesterday",
        user_id=user_id,
        session_id=session_id,
        conversation_history=[],
    )
    latency = int((time.time() - start) * 1000)
    
    text = response.response
    checks = []
    
    # Check 1: Response contains the soft confirm question
    checks.append(check(
        "Contains soft confirm question",
        "Should I update your records?" in text
    ))
    
    # Check 2: Response is NOT just the proposal — it should have the helpful content too
    # A proposal-only response would be very short (< 100 chars)
    checks.append(check(
        "Response is more than just proposal (answer-first)",
        len(text) > 150
    ))
    
    # Check 3: Does NOT contain the old "Is that correct?" wording
    checks.append(check(
        "Does NOT use old 'Is that correct?' wording",
        "Is that correct?" not in text
    ))
    
    passed = all(c["passed"] for c in checks)
    return FlowTestResult("FLOW-01", "Answer-first proposal", passed, checks, text[:200], latency)


# ─────────────────────────────────────────────
# Test: FLOW-02  No drilling on confirmation
# ─────────────────────────────────────────────

async def test_flow_02(orchestrator: PipelineOrchestrator) -> FlowTestResult:
    """
    FLOW-02: When user says "yes" to broad stage proposal,
    the stage should be confirmed at the ROOT level (no child drilling).
    The confirmation message should appear and no new proposal should be asked.
    """
    user_id = "eval_flow_02"
    session_id = "eval_flow_02_session"
    
    await setup_test_user(user_id, "adjuvant_chemo", "3")
    
    # Turn 1: Trigger proposal
    response1 = await send_message(
        orchestrator,
        "had surgery yesterday",
        user_id=user_id,
        session_id=session_id,
        conversation_history=[],
    )
    
    # Build conversation history
    history = [
        {"role": "user", "content": "had surgery yesterday"},
        {"role": "assistant", "content": response1.response},
    ]
    
    start = time.time()
    # Turn 2: Confirm with "yes"
    response2 = await send_message(
        orchestrator,
        "yes",
        user_id=user_id,
        session_id=session_id,
        conversation_history=history,
    )
    latency = int((time.time() - start) * 1000)
    
    text = response2.response
    checks = []
    
    # Check 1: Confirmation message appears
    checks.append(check(
        "Contains confirmation message (updated/got it)",
        "updated" in text.lower() or "got it" in text.lower() or "✅" in text
    ))
    
    # Check 2: Does NOT ask another proposal question (no drilling)
    checks.append(check(
        "Does NOT ask another 'Should I update your records?' (no drilling)",
        "Should I update your records?" not in text
    ))
    
    # Check 3: Profile updated to root stage (not a child like 6.2)
    profile = await get_test_profile(user_id)
    if profile and profile.detailed_stage_id:
        is_root = "." not in profile.detailed_stage_id
        checks.append(check(
            f"Profile saved at root stage ID (got '{profile.detailed_stage_id}')",
            is_root
        ))
    else:
        checks.append(check("Profile has detailed_stage_id", False))
    
    passed = all(c["passed"] for c in checks)
    return FlowTestResult("FLOW-02", "No drilling on confirmation", passed, checks, text[:200], latency)


# ─────────────────────────────────────────────
# Test: FLOW-03  Rejection suppresses re-proposal
# ─────────────────────────────────────────────

async def test_flow_03(orchestrator: PipelineOrchestrator) -> FlowTestResult:
    """
    FLOW-03: When user says "no" to a stage proposal,
    the system should revert to the profile stage and NOT re-propose.
    """
    user_id = "eval_flow_03"
    session_id = "eval_flow_03_session"
    
    await setup_test_user(user_id, "adjuvant_chemo", "3")
    
    # Turn 1: Trigger proposal
    response1 = await send_message(
        orchestrator,
        "had surgery yesterday",
        user_id=user_id,
        session_id=session_id,
        conversation_history=[],
    )
    
    # Build conversation history
    history = [
        {"role": "user", "content": "had surgery yesterday"},
        {"role": "assistant", "content": response1.response},
    ]
    
    start = time.time()
    # Turn 2: Reject with "no"
    response2 = await send_message(
        orchestrator,
        "no",
        user_id=user_id,
        session_id=session_id,
        conversation_history=history,
    )
    latency = int((time.time() - start) * 1000)
    
    text = response2.response
    checks = []
    
    # Check 1: Does NOT re-propose the same stage
    checks.append(check(
        "Does NOT re-propose with 'Should I update your records?'",
        "Should I update your records?" not in text
    ))
    
    # Check 2: Profile stage unchanged (still adjuvant_chemo)
    profile = await get_test_profile(user_id)
    if profile:
        checks.append(check(
            f"Profile stage unchanged (expected 'adjuvant_chemo', got '{profile.current_stage}')",
            str(profile.current_stage) == "adjuvant_chemo" or 
            profile.current_stage.value == "adjuvant_chemo"
        ))
    else:
        checks.append(check("Profile exists", False))
    
    passed = all(c["passed"] for c in checks)
    return FlowTestResult("FLOW-03", "Rejection suppresses re-proposal", passed, checks, text[:200], latency)


# ─────────────────────────────────────────────
# Test: FLOW-04  Deferred sub-stage question
# ─────────────────────────────────────────────

async def test_flow_04(orchestrator: PipelineOrchestrator) -> FlowTestResult:
    """
    FLOW-04: After broad stage is confirmed (root-only detailed_stage_id),
    the next turn should include a deferred sub-stage question.
    """
    user_id = "eval_flow_04"
    session_id = "eval_flow_04_session"
    
    # Set user to a confirmed broad stage (root-only ID, e.g. "6" for further_surgery)
    await setup_test_user(user_id, "further_surgery", "6")
    
    start = time.time()
    # Turn 1: Ask a normal question — should trigger deferred sub-stage
    response = await send_message(
        orchestrator,
        "my arm feels really stiff and swollen",
        user_id=user_id,
        session_id=session_id,
        conversation_history=[],
    )
    latency = int((time.time() - start) * 1000)
    
    text = response.response
    checks = []
    
    # Check 1: Contains sub-stage question markers
    has_sub_stage_q = (
        "knowing your specific" in text.lower() or
        "type of surgery" in text.lower() or
        "was it" in text.lower()
    )
    checks.append(check(
        "Contains deferred sub-stage question",
        has_sub_stage_q
    ))
    
    # Check 2: Also contains helpful answer (not just sub-stage question)
    checks.append(check(
        "Response includes helpful answer content",
        len(text) > 100
    ))
    
    # Check 3: Profile marked as sub_stage_asked
    profile = await get_test_profile(user_id)
    if profile:
        checks.append(check(
            f"Profile sub_stage_asked=True (got {getattr(profile, 'sub_stage_asked', 'N/A')})",
            getattr(profile, 'sub_stage_asked', False) == True
        ))
    else:
        checks.append(check("Profile exists", False))
    
    passed = all(c["passed"] for c in checks)
    return FlowTestResult("FLOW-04", "Deferred sub-stage question", passed, checks, text[:300], latency)


# ─────────────────────────────────────────────
# Test: FLOW-05  Sub-stage one-shot (not repeated)
# ─────────────────────────────────────────────

async def test_flow_05(orchestrator: PipelineOrchestrator) -> FlowTestResult:
    """
    FLOW-05: After the sub-stage question has been asked once,
    it should NOT be asked again on subsequent turns.
    """
    user_id = "eval_flow_05"
    session_id = "eval_flow_05_session"
    
    # Set user to a confirmed broad stage with sub_stage_asked=True
    await setup_test_user(user_id, "further_surgery", "6")
    
    # Manually set sub_stage_asked=True to simulate it was already asked
    from services.patient_profile_service import get_patient_profile_service
    profile_service = get_patient_profile_service()
    profile_service.table.update_item(
        Key={'user_id': user_id},
        UpdateExpression='SET sub_stage_asked = :val',
        ExpressionAttributeValues={':val': True}
    )
    
    start = time.time()
    # Next turn — sub-stage should NOT be asked again
    response = await send_message(
        orchestrator,
        "what foods help with recovery after surgery?",
        user_id=user_id,
        session_id=session_id,
        conversation_history=[],
    )
    latency = int((time.time() - start) * 1000)
    
    text = response.response
    checks = []
    
    # Check 1: Does NOT contain sub-stage question
    has_sub_stage_q = (
        "knowing your specific" in text.lower() and
        "was it" in text.lower()
    )
    checks.append(check(
        "Does NOT repeat sub-stage question",
        not has_sub_stage_q
    ))
    
    # Check 2: Still provides helpful answer
    checks.append(check(
        "Response provides helpful answer",
        len(text) > 50
    ))
    
    passed = all(c["passed"] for c in checks)
    return FlowTestResult("FLOW-05", "Sub-stage one-shot (not repeated)", passed, checks, text[:200], latency)


# ─────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────

async def run_all():
    orchestrator = PipelineOrchestrator(enable_llm_validation=True)
    
    tests = [
        test_flow_01,
        test_flow_02,
        test_flow_03,
        test_flow_04,
        test_flow_05,
    ]
    
    results: List[FlowTestResult] = []
    
    print()
    print("═" * 80)
    print("  ORCHESTRATOR FLOW EVAL: Answer-First Stage Confirmation")
    print("═" * 80)
    
    for test_fn in tests:
        try:
            result = await test_fn(orchestrator)
            results.append(result)
            
            status = "✅" if result.passed else "❌"
            print(f"  {status} {result.test_id:<10} {result.name:<45} {result.latency_ms:>5}ms")
            
            for c in result.checks:
                print(f"       {c['symbol']} {c['description']}")
            
        except Exception as e:
            print(f"  💥 {test_fn.__name__:<10} CRASHED: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    
    print()
    print("─" * 80)
    print(f"  TOTAL: {passed}/{total} passed")
    print("═" * 80)
    
    # Save report
    report_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "eval_orchestrator_flow_report.json"
    )
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "summary": f"{passed}/{total} passed",
        "results": [
            {
                "test_id": r.test_id,
                "name": r.name,
                "passed": r.passed,
                "checks": r.checks,
                "response_preview": r.response_text,
                "latency_ms": r.latency_ms,
            }
            for r in results
        ],
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  📄 Detailed report: {report_path}")
    
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(run_all())
