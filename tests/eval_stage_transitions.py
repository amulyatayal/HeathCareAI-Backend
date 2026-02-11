"""
Stage Transition Eval Tests
============================
Tests StageAgentV2's ability to correctly infer stage transitions,
respect temporal context, and avoid false transitions.

Run:  python -m pytest tests/eval_stage_transitions.py -v --tb=short
  or: python tests/eval_stage_transitions.py   (standalone)

Each test case is a (current_stage, user_message) pair with expected outputs.
The StageAgentV2 is called directly — no server needed.
"""

import asyncio
import sys
import os
import json
import logging
from dataclasses import dataclass
from typing import Optional, List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.schemas_pipeline import PipelineContext
from services.agents.stage_agent_v2 import StageAgentV2

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# ════════════════════════════════════════
# Test Case Definition
# ════════════════════════════════════════

@dataclass
class TransitionTestCase:
    """A single stage transition test case."""
    id: str                         # Short identifier
    description: str                # What we're testing
    current_stage: str              # Profile current_stage
    detailed_stage_id: Optional[str]  # Profile detailed_stage_id
    user_message: str               # Chat message
    conversation_history: list      # Prior conversation turns
    # Expectations
    expected_spec_stage: str        # Expected broad stage (spec_stage)
    expected_root_id: Optional[str] # Expected granular root ID (first digit)
    expected_certainty: str         # "high", "medium", or "low"
    should_change: bool             # Should stage differ from current?
    category: str                   # Test category for grouping


def build_context(tc: TransitionTestCase) -> PipelineContext:
    """Build a PipelineContext from a test case."""
    ctx = PipelineContext(
        user_message=tc.user_message,
        conversation_history=tc.conversation_history,
        metadata={
            "profile_current_stage": tc.current_stage,
            "profile_detailed_stage_id": tc.detailed_stage_id,
        }
    )
    return ctx


# ════════════════════════════════════════
# Test Cases
# ════════════════════════════════════════

TRANSITION_TESTS: List[TransitionTestCase] = [

    # ──────────────────────────────────────────
    # Category 1: FORWARD TRANSITIONS (natural progression)
    # ──────────────────────────────────────────
    TransitionTestCase(
        id="FWD-01",
        description="Pre-diagnosis → Newly diagnosed",
        current_stage="pre_diagnosis",
        detailed_stage_id="0",
        user_message="I just got my biopsy results back and they confirmed it's breast cancer.",
        conversation_history=[],
        expected_spec_stage="newly_diagnosed",
        expected_root_id="1",
        expected_certainty="high",
        should_change=True,
        category="forward",
    ),
    TransitionTestCase(
        id="FWD-02",
        description="Newly diagnosed → Surgery",
        current_stage="newly_diagnosed",
        detailed_stage_id="1",
        user_message="I've been scheduled for a lumpectomy next Tuesday.",
        conversation_history=[],
        expected_spec_stage="surgery",
        expected_root_id="2",
        expected_certainty="high",
        should_change=True,
        category="forward",
    ),
    TransitionTestCase(
        id="FWD-03",
        description="Surgery → Adjuvant chemo",
        current_stage="surgery",
        detailed_stage_id="2.1",
        user_message="My surgeon said the surgery went well. Now I need to start chemotherapy.",
        conversation_history=[],
        expected_spec_stage="adjuvant_chemo",
        expected_root_id="8",
        expected_certainty="high",
        should_change=True,
        category="forward",
    ),
    TransitionTestCase(
        id="FWD-04",
        description="Surgery → Adjuvant radio",
        current_stage="surgery",
        detailed_stage_id="2.1.1",
        user_message="I finished surgery and I'm about to begin 3 weeks of radiotherapy.",
        conversation_history=[],
        expected_spec_stage="adjuvant_radio",
        expected_root_id="7",
        expected_certainty="high",
        should_change=True,
        category="forward",
    ),
    TransitionTestCase(
        id="FWD-05",
        description="Adjuvant chemo → Adjuvant radio",
        current_stage="adjuvant_chemo",
        detailed_stage_id="8",
        user_message="I've completed all my chemo cycles. My oncologist says I start radiotherapy next week.",
        conversation_history=[],
        expected_spec_stage="adjuvant_radio",
        expected_root_id="7",
        expected_certainty="high",
        should_change=True,
        category="forward",
    ),
    TransitionTestCase(
        id="FWD-06",
        description="Adjuvant radio → Adjuvant endocrine",
        current_stage="adjuvant_radio",
        detailed_stage_id="7",
        user_message="Radiotherapy is done. I've started taking tamoxifen now.",
        conversation_history=[],
        expected_spec_stage="adjuvant_endocrine",
        expected_root_id="9",
        expected_certainty="high",
        should_change=True,
        category="forward",
    ),
    TransitionTestCase(
        id="FWD-07",
        description="Adjuvant endocrine → Survivorship",
        current_stage="adjuvant_endocrine",
        detailed_stage_id="9",
        user_message="I finished all my treatments. I just had my 5-year check-up and got the all clear!",
        conversation_history=[],
        expected_spec_stage="survivorship",
        expected_root_id="5",
        expected_certainty="high",
        should_change=True,
        category="forward",
    ),

    # ──────────────────────────────────────────
    # Category 2: NEOADJUVANT PATH
    # ──────────────────────────────────────────
    TransitionTestCase(
        id="NEO-01",
        description="Newly diagnosed → Neoadjuvant chemo",
        current_stage="newly_diagnosed",
        detailed_stage_id="1",
        user_message="My oncologist wants me to have chemotherapy first to shrink the tumour before surgery.",
        conversation_history=[],
        expected_spec_stage="neoadjuvant_chemo",
        expected_root_id="3",
        expected_certainty="high",
        should_change=True,
        category="neoadjuvant",
    ),
    TransitionTestCase(
        id="NEO-02",
        description="Newly diagnosed → Neoadjuvant endocrine",
        current_stage="newly_diagnosed",
        detailed_stage_id="1",
        user_message="I've been put on letrozole before surgery to see how the tumour responds to hormonal treatment.",
        conversation_history=[],
        expected_spec_stage="neoadjuvant_endocrine",
        expected_root_id="4",
        expected_certainty="high",
        should_change=True,
        category="neoadjuvant",
    ),
    TransitionTestCase(
        id="NEO-03",
        description="Neoadjuvant chemo → Surgery (post-neoadjuvant)",
        current_stage="neoadjuvant_chemo",
        detailed_stage_id="3.1",
        user_message="Chemo finished and the tumour has shrunk. I'm now booked for a mastectomy.",
        conversation_history=[],
        expected_spec_stage="surgery",
        expected_root_id="2",
        expected_certainty="high",
        should_change=True,
        category="neoadjuvant",
    ),

    # ──────────────────────────────────────────
    # Category 3: TEMPORAL DISAMBIGUATION (the crucial cases)
    # ──────────────────────────────────────────
    TransitionTestCase(
        id="TMP-01",
        description="Surgery + 'chemo' → Adjuvant (NOT neoadjuvant)",
        current_stage="surgery",
        detailed_stage_id="2.1.2",
        user_message="I'm starting chemo after my surgery.",
        conversation_history=[],
        expected_spec_stage="adjuvant_chemo",
        expected_root_id="8",
        expected_certainty="high",
        should_change=True,
        category="temporal",
    ),
    TransitionTestCase(
        id="TMP-02",
        description="Adjuvant chemo + 'surgery' → Further surgery (NOT initial)",
        current_stage="adjuvant_chemo",
        detailed_stage_id="8",
        user_message="I am having surgery tomorrow.",
        conversation_history=[],
        expected_spec_stage="further_surgery",
        expected_root_id="6",
        expected_certainty="high",
        should_change=True,
        category="temporal",
    ),
    TransitionTestCase(
        id="TMP-03",
        description="Adjuvant radio + 'surgery' → Further surgery (NOT initial)",
        current_stage="adjuvant_radio",
        detailed_stage_id="7",
        user_message="They found I need another operation to get clearer margins.",
        conversation_history=[],
        expected_spec_stage="further_surgery",
        expected_root_id="6",
        expected_certainty="high",
        should_change=True,
        category="temporal",
    ),
    TransitionTestCase(
        id="TMP-04",
        description="Pre-diagnosis + 'chemo' → Neoadjuvant (NOT adjuvant)",
        current_stage="pre_diagnosis",
        detailed_stage_id="0",
        user_message="Even though I haven't had surgery yet, the doctor wants me to start chemotherapy first.",
        conversation_history=[],
        expected_spec_stage="neoadjuvant_chemo",
        expected_root_id="3",
        expected_certainty="high",
        should_change=True,
        category="temporal",
    ),

    # ──────────────────────────────────────────
    # Category 4: STAGE CONSISTENCY (should NOT change)
    # ──────────────────────────────────────────
    TransitionTestCase(
        id="CON-01",
        description="Adjuvant chemo + asks about side effects → no change",
        current_stage="adjuvant_chemo",
        detailed_stage_id="8",
        user_message="I'm feeling really nauseous after my last chemo session. Is this normal?",
        conversation_history=[],
        expected_spec_stage="adjuvant_chemo",
        expected_root_id="8",
        expected_certainty="low",
        should_change=False,
        category="consistency",
    ),
    TransitionTestCase(
        id="CON-02",
        description="Surgery + asks about recovery → no change",
        current_stage="surgery",
        detailed_stage_id="2.1.1",
        user_message="How long until my surgical wound fully heals?",
        conversation_history=[],
        expected_spec_stage="surgery",
        expected_root_id="2",
        expected_certainty="low",
        should_change=False,
        category="consistency",
    ),
    TransitionTestCase(
        id="CON-03",
        description="Survivorship + annual check-up → no change",
        current_stage="survivorship",
        detailed_stage_id="5",
        user_message="I have my annual mammogram next month and I'm feeling anxious about it.",
        conversation_history=[],
        expected_spec_stage="survivorship",
        expected_root_id="5",
        expected_certainty="low",
        should_change=False,
        category="consistency",
    ),
    TransitionTestCase(
        id="CON-04",
        description="Adjuvant endocrine + tamoxifen question → no change",
        current_stage="adjuvant_endocrine",
        detailed_stage_id="9",
        user_message="I've been getting hot flashes from tamoxifen. Any tips for managing them?",
        conversation_history=[],
        expected_spec_stage="adjuvant_endocrine",
        expected_root_id="9",
        expected_certainty="low",
        should_change=False,
        category="consistency",
    ),

    # ──────────────────────────────────────────
    # Category 5: BACKWARD TRANSITIONS
    # ──────────────────────────────────────────
    TransitionTestCase(
        id="BWD-01",
        description="Survivorship → Back to newly diagnosed (recurrence)",
        current_stage="survivorship",
        detailed_stage_id="5",
        user_message="I just found out my cancer has come back. They found a new tumour in the same breast.",
        conversation_history=[],
        expected_spec_stage="newly_diagnosed",
        expected_root_id="1",
        expected_certainty="high",
        should_change=True,
        category="backward",
    ),
    TransitionTestCase(
        id="BWD-02",
        description="Adjuvant chemo → Further surgery (backward step)",
        current_stage="adjuvant_chemo",
        detailed_stage_id="8",
        user_message="My oncologist is pausing chemo because they need to do more surgery first.",
        conversation_history=[],
        expected_spec_stage="further_surgery",
        expected_root_id="6",
        expected_certainty="high",
        should_change=True,
        category="backward",
    ),

    # ──────────────────────────────────────────
    # Category 6: PALLIATIVE / SECONDARY
    # ──────────────────────────────────────────
    TransitionTestCase(
        id="PAL-01",
        description="Adjuvant chemo → Palliative (cancer spread)",
        current_stage="adjuvant_chemo",
        detailed_stage_id="8",
        user_message="I've been told my breast cancer has spread to my bones and lungs. They said it's now secondary breast cancer and curative treatment is no longer possible.",
        conversation_history=[],
        expected_spec_stage="newly_diagnosed",
        expected_root_id="1",
        expected_certainty="high",
        should_change=True,
        category="palliative",
    ),
    TransitionTestCase(
        id="PAL-02",
        description="Survivorship → Palliative (metastatic recurrence)",
        current_stage="survivorship",
        detailed_stage_id="5",
        user_message="After 3 years in remission, my scan shows the cancer is now in my liver. My oncologist said it's metastatic and we'll be managing it long-term.",
        conversation_history=[],
        expected_spec_stage="newly_diagnosed",
        expected_root_id="1",
        expected_certainty="high",
        should_change=True,
        category="palliative",
    ),

    # ──────────────────────────────────────────
    # Category 7: CONFIRMATION FLOW
    # ──────────────────────────────────────────
    TransitionTestCase(
        id="CFM-01",
        description="User confirms proposed stage change with 'Yes'",
        current_stage="pre_diagnosis",
        detailed_stage_id="0",
        user_message="Yes, that's right.",
        conversation_history=[
            {"role": "user", "content": "I just got my diagnosis of breast cancer"},
            {"role": "assistant", "content": "It sounds like you might be in the Newly diagnosed (Results Clinic) stage. Is that correct?"}
        ],
        expected_spec_stage="newly_diagnosed",
        expected_root_id="1",
        expected_certainty="high",
        should_change=True,
        category="confirmation",
    ),
    TransitionTestCase(
        id="CFM-02",
        description="User corrects proposed stage with different info",
        current_stage="pre_diagnosis",
        detailed_stage_id="0",
        user_message="No, actually I'm about to start chemotherapy before my surgery.",
        conversation_history=[
            {"role": "user", "content": "I just got my diagnosis of breast cancer"},
            {"role": "assistant", "content": "It sounds like you might be in the Newly diagnosed (Results Clinic) stage. Is that correct?"}
        ],
        expected_spec_stage="neoadjuvant_chemo",
        expected_root_id="3",
        expected_certainty="high",
        should_change=True,
        category="confirmation",
    ),

    # ──────────────────────────────────────────
    # Category 8: AMBIGUOUS / UNKNOWN
    # ──────────────────────────────────────────
    TransitionTestCase(
        id="AMB-01",
        description="Generic greeting → no stage inference",
        current_stage="adjuvant_chemo",
        detailed_stage_id="8",
        user_message="Hi, how are you today?",
        conversation_history=[],
        expected_spec_stage="unknown",
        expected_root_id=None,
        expected_certainty="low",
        should_change=False,
        category="ambiguous",
    ),
    TransitionTestCase(
        id="AMB-02",
        description="General question without stage signal",
        current_stage="surgery",
        detailed_stage_id="2",
        user_message="What foods are good for staying healthy?",
        conversation_history=[],
        expected_spec_stage="unknown",
        expected_root_id=None,
        expected_certainty="low",
        should_change=False,
        category="ambiguous",
    ),
]


# ════════════════════════════════════════
# Runner
# ════════════════════════════════════════

async def run_single_test(agent: StageAgentV2, tc: TransitionTestCase) -> dict:
    """Run a single test case and return results."""
    ctx = build_context(tc)
    
    try:
        result_ctx = await agent.execute(ctx)
        
        inferred_stage = result_ctx.stage_result.stage if result_ctx.stage_result else "error"
        certainty = result_ctx.stage_result.certainty if result_ctx.stage_result else "error"
        granular_id = result_ctx.metadata.get("granular_stage_id", "none")
        inferred_root = granular_id.split(".")[0] if granular_id and granular_id != "none" else None
        
        # Normalize for comparison
        inferred_stage_str = inferred_stage.value if hasattr(inferred_stage, 'value') else str(inferred_stage)
        certainty_str = certainty.value if hasattr(certainty, 'value') else str(certainty)
        
        stage_changed = (inferred_stage_str != tc.current_stage and inferred_stage_str != "unknown")
        
        # Evaluate pass/fail
        spec_stage_ok = (inferred_stage_str == tc.expected_spec_stage)
        root_id_ok = (tc.expected_root_id is None) or (inferred_root == tc.expected_root_id)
        change_ok = (stage_changed == tc.should_change) or (not tc.should_change and inferred_stage_str in [tc.current_stage, "unknown"])
        
        # Certainty check: for "consistency" tests, accept low OR medium
        if tc.category == "consistency":
            certainty_ok = certainty_str in ["low", "medium"]
        elif tc.category == "ambiguous":
            certainty_ok = certainty_str in ["low", "medium"]  
        else:
            certainty_ok = (certainty_str == tc.expected_certainty)
        
        passed = spec_stage_ok and root_id_ok and change_ok
        
        return {
            "id": tc.id,
            "description": tc.description,
            "category": tc.category,
            "passed": passed,
            "inferred_stage": inferred_stage_str,
            "expected_stage": tc.expected_spec_stage,
            "spec_stage_ok": spec_stage_ok,
            "granular_id": granular_id,
            "expected_root": tc.expected_root_id,
            "root_id_ok": root_id_ok,
            "certainty": certainty_str,
            "expected_certainty": tc.expected_certainty,
            "certainty_ok": certainty_ok,
            "stage_changed": stage_changed,
            "should_change": tc.should_change,
            "change_ok": change_ok,
        }
        
    except Exception as e:
        return {
            "id": tc.id,
            "description": tc.description,
            "category": tc.category,
            "passed": False,
            "error": str(e),
        }


async def run_all_tests():
    """Run all stage transition evals."""
    agent = StageAgentV2()
    
    results = []
    categories = {}
    
    print("\n" + "═" * 80)
    print("  STAGE TRANSITION EVAL SUITE")
    print("═" * 80)
    
    for tc in TRANSITION_TESTS:
        result = await run_single_test(agent, tc)
        results.append(result)
        
        # Track by category
        cat = tc.category
        if cat not in categories:
            categories[cat] = {"passed": 0, "failed": 0, "tests": []}
        categories[cat]["tests"].append(result)
        if result["passed"]:
            categories[cat]["passed"] += 1
        else:
            categories[cat]["failed"] += 1
        
        # Print result
        status = "✅" if result["passed"] else "❌"
        detail = ""
        if not result["passed"]:
            if "error" in result:
                detail = f" ERROR: {result['error']}"
            else:
                issues = []
                if not result.get("spec_stage_ok"):
                    issues.append(f"stage: got {result['inferred_stage']} expected {result['expected_stage']}")
                if not result.get("root_id_ok"):
                    issues.append(f"root: got {result['granular_id']} expected {result['expected_root']}")
                if not result.get("change_ok"):
                    issues.append(f"change: got {result['stage_changed']} expected {result['should_change']}")
                detail = f" [{'; '.join(issues)}]"
        
        print(f"  {status} {tc.id:8s} {tc.description}{detail}")
    
    # Print summary
    total_passed = sum(1 for r in results if r["passed"])
    total_failed = len(results) - total_passed
    
    print("\n" + "─" * 80)
    print("  SUMMARY BY CATEGORY")
    print("─" * 80)
    
    for cat, data in categories.items():
        icon = "✅" if data["failed"] == 0 else "⚠️"
        print(f"  {icon} {cat:15s}  {data['passed']}/{data['passed'] + data['failed']} passed")
    
    print(f"\n  TOTAL: {total_passed}/{len(results)} passed ({total_failed} failed)")
    print("═" * 80 + "\n")
    
    # Save detailed report
    report_path = os.path.join(os.path.dirname(__file__), "eval_stage_transitions_report.json")
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  📄 Detailed report: {report_path}\n")
    
    return total_failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
