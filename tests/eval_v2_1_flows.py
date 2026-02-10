#!/usr/bin/env python3
"""
LLM Prompt Eval: V2.1 Stage Classification Flows
=================================================

Tests whether the chatbot activates granular V2.1 stage flows
vs. falling back to the old generic "active_treatment" behavior.

Run with:
    python3 tests/eval_v2_1_flows.py

Requires backend running on http://localhost:8000
"""

import json
import time
import sys
import requests
from dataclasses import dataclass, field
from typing import Optional, List

# ================================
# Configuration
# ================================

BACKEND_URL = "http://localhost:8000"
CHAT_ENDPOINT = f"{BACKEND_URL}/api/v2/chat/"

# Colors for terminal output
class C:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


@dataclass
class EvalResult:
    """Result of a single eval test case."""
    test_name: str
    user_message: str
    passed: bool
    checks: dict  # {check_name: (passed, detail)}
    response_text: str = ""
    stage: str = ""
    granular_stage_id: Optional[str] = None
    latency_ms: int = 0
    error: Optional[str] = None


@dataclass
class EvalTestCase:
    """A single eval test case definition."""
    name: str
    message: str
    # Expected values
    expected_stage: str  # broad stage enum (e.g. "active_treatment")
    expected_granular_prefix: Optional[str] = None  # e.g. "2.1" for surgery
    expected_granular_exact: Optional[str] = None  # e.g. "2.1.1.1" for lumpectomy
    # Response content checks
    response_should_contain: List[str] = field(default_factory=list)
    response_should_not_contain: List[str] = field(default_factory=list)
    # Flow checks
    expect_verification_question: bool = False  # "Is that correct?" pattern
    expect_granular_id_in_metadata: bool = True
    # Guest vs authenticated
    user_id: str = "guest_eval_test"
    session_id: Optional[str] = None


# ================================
# Test Cases
# ================================

EVAL_CASES = [
    # ──────────────────────────────────────────────
    # SURGERY (Stage 2.x)
    # ──────────────────────────────────────────────
    EvalTestCase(
        name="Surgery: Lumpectomy",
        message="I had a lumpectomy yesterday and I'm recovering at home",
        expected_stage="active_treatment",
        expected_granular_prefix="2.1",
        expected_granular_exact="2.1.1.1",
        response_should_contain=["lumpectomy"],
        response_should_not_contain=[],
        expect_granular_id_in_metadata=True,
    ),
    EvalTestCase(
        name="Surgery: Mastectomy",
        message="I'm scheduled for a mastectomy next week and feeling anxious",
        expected_stage="active_treatment",
        expected_granular_prefix="2.1",
        response_should_contain=[],
        expect_granular_id_in_metadata=True,
    ),
    EvalTestCase(
        name="Surgery: Reconstruction",
        message="I just had breast reconstruction surgery after my mastectomy",
        expected_stage="active_treatment",
        expected_granular_prefix="2",
        response_should_contain=[],
        expect_granular_id_in_metadata=True,
    ),

    # ──────────────────────────────────────────────
    # CHEMOTHERAPY (Stage 3.x)
    # ──────────────────────────────────────────────
    EvalTestCase(
        name="Chemotherapy: General",
        message="I'm starting chemotherapy next week, what should I expect?",
        expected_stage="active_treatment",
        expected_granular_prefix="3",
        response_should_contain=["chemotherapy"],
        expect_granular_id_in_metadata=True,
    ),
    EvalTestCase(
        name="Chemotherapy: Side effects",
        message="I'm on my third cycle of chemo and feeling very nauseous",
        expected_stage="active_treatment",
        expected_granular_prefix="3",
        response_should_contain=[],
        expect_granular_id_in_metadata=True,
    ),

    # ──────────────────────────────────────────────
    # RADIOTHERAPY (Stage 4.x)
    # ──────────────────────────────────────────────
    EvalTestCase(
        name="Radiotherapy: Starting",
        message="I'm about to start radiotherapy treatment for breast cancer",
        expected_stage="active_treatment",
        expected_granular_prefix="4",
        response_should_contain=[],
        expect_granular_id_in_metadata=True,
    ),

    # ──────────────────────────────────────────────
    # HORMONE THERAPY / ENDOCRINE (Stage 6.x / 1.2.x)
    # ──────────────────────────────────────────────
    EvalTestCase(
        name="Hormone Therapy: Tamoxifen",
        message="I've been taking tamoxifen for 3 months now",
        expected_stage="active_treatment",
        expected_granular_prefix=None,  # Could be 6.x or other
        response_should_contain=[],
        expect_granular_id_in_metadata=True,
    ),

    # ──────────────────────────────────────────────
    # PRE-DIAGNOSIS (Stage 0)
    # ──────────────────────────────────────────────
    EvalTestCase(
        name="Pre-diagnosis: Waiting for results",
        message="I just had a mammogram and biopsy, waiting for my results",
        expected_stage="pre_diagnosis",
        expected_granular_prefix="0",
        response_should_contain=[],
        expect_granular_id_in_metadata=True,
    ),

    # ──────────────────────────────────────────────
    # NEWLY DIAGNOSED (Stage 1)
    # ──────────────────────────────────────────────
    EvalTestCase(
        name="Newly Diagnosed: Just told",
        message="I was just diagnosed with breast cancer last week",
        expected_stage="newly_diagnosed",
        expected_granular_prefix="1",
        response_should_contain=[],
        expect_granular_id_in_metadata=True,
    ),

    # ──────────────────────────────────────────────
    # SURVEILLANCE / FOLLOW-UP (Stage 5)
    # ──────────────────────────────────────────────
    EvalTestCase(
        name="Surveillance: Post-treatment",
        message="I finished all my treatment 6 months ago and now I'm just having regular check-ups",
        expected_stage="surveillance",
        expected_granular_prefix="5",
        response_should_contain=[],
        expect_granular_id_in_metadata=True,
    ),

    # ──────────────────────────────────────────────
    # GENERIC / AMBIGUOUS (Should still get granular)
    # ──────────────────────────────────────────────
    EvalTestCase(
        name="Ambiguous: General question",
        message="What are the side effects of treatment?",
        expected_stage="active_treatment",
        expected_granular_prefix=None,  # May not get granular
        expect_granular_id_in_metadata=False,  # Ambiguous → may not classify
    ),

    # ──────────────────────────────────────────────
    # EDGE CASE: Specific sub-stages
    # ──────────────────────────────────────────────
    EvalTestCase(
        name="Specific: Sentinel node biopsy",
        message="I had a sentinel lymph node biopsy during my surgery",
        expected_stage="active_treatment",
        expected_granular_prefix="2",
        response_should_contain=[],
        expect_granular_id_in_metadata=True,
    ),
    EvalTestCase(
        name="Specific: Palliative care",
        message="My cancer has spread and I've been told it's metastatic, I'm on palliative treatment now",
        expected_stage="newly_diagnosed",  # Could map to 1.1 palliative
        expected_granular_prefix="1.1",
        response_should_contain=[],
        expect_granular_id_in_metadata=True,
    ),
]


# ================================
# Eval Runner
# ================================

def run_single_eval(test: EvalTestCase) -> EvalResult:
    """Run a single eval test case against the backend."""
    checks = {}
    
    try:
        payload = {
            "message": test.message,
            "session_id": test.session_id or f"eval-{test.name.replace(' ', '-').lower()}",
            "conversation_history": [],
            "include_trace": False,
        }
        
        headers = {
            "Content-Type": "application/json",
            "X-User-ID": test.user_id,
        }
        
        start = time.time()
        resp = requests.post(CHAT_ENDPOINT, json=payload, headers=headers, timeout=120)
        latency_ms = int((time.time() - start) * 1000)
        
        if resp.status_code != 200:
            return EvalResult(
                test_name=test.name,
                user_message=test.message,
                passed=False,
                checks={"http_status": (False, f"Expected 200, got {resp.status_code}")},
                error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                latency_ms=latency_ms,
            )
        
        data = resp.json()
        response_text = data.get("response", "")
        stage = data.get("stage", "")
        metadata = data.get("metadata", {}) or {}
        granular_id = metadata.get("granular_stage_id")
        
        # ──────────── CHECK 1: Broad stage ────────────
        if test.expected_stage:
            stage_match = stage == test.expected_stage
            checks["broad_stage"] = (
                stage_match,
                f"expected='{test.expected_stage}', got='{stage}'"
            )
        
        # ──────────── CHECK 2: Granular stage ID exists ────────────
        if test.expect_granular_id_in_metadata:
            has_granular = granular_id is not None and granular_id != ""
            checks["has_granular_id"] = (
                has_granular,
                f"granular_stage_id={'✅ ' + str(granular_id) if has_granular else '❌ MISSING'}"
            )
        
        # ──────────── CHECK 3: Granular ID prefix ────────────
        if test.expected_granular_prefix and granular_id:
            prefix_match = str(granular_id).startswith(test.expected_granular_prefix)
            checks["granular_prefix"] = (
                prefix_match,
                f"expected prefix='{test.expected_granular_prefix}', got='{granular_id}'"
            )
        elif test.expected_granular_prefix and not granular_id:
            checks["granular_prefix"] = (
                False,
                f"expected prefix='{test.expected_granular_prefix}', but no granular_id returned"
            )
        
        # ──────────── CHECK 4: Exact granular ID ────────────
        if test.expected_granular_exact:
            exact_match = granular_id == test.expected_granular_exact
            checks["granular_exact"] = (
                exact_match,
                f"expected='{test.expected_granular_exact}', got='{granular_id}'"
            )
        
        # ──────────── CHECK 5: Response content ────────────
        response_lower = response_text.lower()
        for keyword in test.response_should_contain:
            found = keyword.lower() in response_lower
            checks[f"contains_{keyword}"] = (
                found,
                f"'{keyword}' {'found' if found else 'NOT FOUND'} in response"
            )
        
        for keyword in test.response_should_not_contain:
            not_found = keyword.lower() not in response_lower
            checks[f"excludes_{keyword}"] = (
                not_found,
                f"'{keyword}' {'correctly absent' if not_found else 'UNEXPECTEDLY FOUND'}"
            )
        
        # ──────────── CHECK 6: Non-empty response ────────────
        has_response = len(response_text) > 50
        checks["has_response"] = (
            has_response,
            f"response length={len(response_text)} chars"
        )
        
        # ──────────── CHECK 7: V2.1 flow activation ────────────
        # The KEY check: if granular_id is not "unknown" and not just 
        # the broad category number, then V2.1 is working
        if test.expect_granular_id_in_metadata and granular_id:
            is_v2_1_active = granular_id != "unknown" and "." in str(granular_id)
            checks["v2_1_flow_active"] = (
                is_v2_1_active,
                f"granular_id='{granular_id}' → {'✅ V2.1 ACTIVE (sub-stage)' if is_v2_1_active else '❌ OLD FLOW (no sub-stage)'}"
            )
        elif test.expect_granular_id_in_metadata:
            checks["v2_1_flow_active"] = (
                False,
                "❌ No granular_id → OLD FLOW"
            )
        
        all_passed = all(passed for passed, _ in checks.values())
        
        return EvalResult(
            test_name=test.name,
            user_message=test.message,
            passed=all_passed,
            checks=checks,
            response_text=response_text[:300],
            stage=stage,
            granular_stage_id=granular_id,
            latency_ms=latency_ms,
        )
        
    except requests.ConnectionError:
        return EvalResult(
            test_name=test.name,
            user_message=test.message,
            passed=False,
            checks={"connection": (False, "Cannot connect to backend")},
            error=f"Cannot connect to {BACKEND_URL}. Is the server running?",
        )
    except Exception as e:
        return EvalResult(
            test_name=test.name,
            user_message=test.message,
            passed=False,
            checks={"error": (False, str(e))},
            error=str(e),
        )


def print_result(result: EvalResult, verbose: bool = True):
    """Print a single eval result."""
    status = f"{C.GREEN}✅ PASS{C.RESET}" if result.passed else f"{C.RED}❌ FAIL{C.RESET}"
    
    print(f"\n{'─' * 70}")
    print(f"  {status}  {C.BOLD}{result.test_name}{C.RESET}")
    print(f"  {C.DIM}Message: \"{result.user_message}\"{C.RESET}")
    print(f"  {C.DIM}Latency: {result.latency_ms}ms | Stage: {result.stage} | Granular: {result.granular_stage_id}{C.RESET}")
    
    if result.error:
        print(f"  {C.RED}Error: {result.error}{C.RESET}")
    
    if verbose or not result.passed:
        for check_name, (passed, detail) in result.checks.items():
            icon = f"{C.GREEN}✓{C.RESET}" if passed else f"{C.RED}✗{C.RESET}"
            print(f"    {icon} {check_name}: {detail}")
    
    if verbose and result.response_text:
        print(f"  {C.CYAN}Response preview:{C.RESET}")
        # Show first 200 chars, indented
        preview = result.response_text[:200].replace('\n', '\n    ')
        print(f"    {preview}...")


def print_summary(results: List[EvalResult]):
    """Print eval summary."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    
    # V2.1 flow activation rate
    v2_1_checks = [(r.test_name, r.checks.get("v2_1_flow_active", (None, ""))) 
                   for r in results 
                   if "v2_1_flow_active" in r.checks]
    v2_1_active = sum(1 for _, (p, _) in v2_1_checks if p)
    v2_1_total = len(v2_1_checks)
    
    # Granular ID rates
    granular_present = sum(1 for r in results if r.granular_stage_id and r.granular_stage_id != "unknown")
    
    print(f"\n{'═' * 70}")
    print(f"  {C.BOLD}EVAL SUMMARY{C.RESET}")
    print(f"{'═' * 70}")
    print(f"  Total tests:     {total}")
    print(f"  {C.GREEN}Passed:          {passed}{C.RESET}")
    print(f"  {C.RED}Failed:          {failed}{C.RESET}")
    print(f"  Pass rate:       {passed/total*100:.0f}%")
    print()
    print(f"  {C.BOLD}V2.1 Flow Activation:{C.RESET}")
    print(f"    Granular IDs:  {granular_present}/{total} responses have granular_stage_id")
    if v2_1_total > 0:
        rate = v2_1_active / v2_1_total * 100
        color = C.GREEN if rate >= 80 else C.YELLOW if rate >= 50 else C.RED
        print(f"    V2.1 active:   {color}{v2_1_active}/{v2_1_total} ({rate:.0f}%){C.RESET}")
    print()
    
    # Show granular ID distribution
    print(f"  {C.BOLD}Granular Stage Distribution:{C.RESET}")
    for r in results:
        gid = r.granular_stage_id or "—"
        icon = C.GREEN + "●" + C.RESET if r.passed else C.RED + "●" + C.RESET
        print(f"    {icon} {r.test_name:40s} → stage={r.stage:20s} granular={gid}")
    
    # Failed tests detail
    if failed > 0:
        print(f"\n  {C.RED}{C.BOLD}FAILED TESTS:{C.RESET}")
        for r in results:
            if not r.passed:
                failed_checks = [
                    f"{name}: {detail}" 
                    for name, (passed, detail) in r.checks.items() 
                    if not passed
                ]
                print(f"    ❌ {r.test_name}")
                for fc in failed_checks:
                    print(f"       → {fc}")
    
    print(f"{'═' * 70}\n")
    
    # Write JSON report
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "backend_url": BACKEND_URL,
        "total": total,
        "passed": passed,
        "failed": failed,
        "v2_1_activation_rate": f"{v2_1_active}/{v2_1_total}" if v2_1_total else "N/A",
        "results": [
            {
                "name": r.test_name,
                "message": r.user_message,
                "passed": r.passed,
                "stage": r.stage,
                "granular_stage_id": r.granular_stage_id,
                "latency_ms": r.latency_ms,
                "response_preview": r.response_text[:200],
                "checks": {k: {"passed": p, "detail": d} for k, (p, d) in r.checks.items()},
            }
            for r in results
        ],
    }
    
    report_path = "tests/eval_v2_1_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Report saved to: {report_path}")


# ================================
# Main
# ================================

def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    quick = "--quick" in sys.argv or "-q" in sys.argv
    
    cases = EVAL_CASES
    if quick:
        # Run only first 5 cases for quick check
        cases = EVAL_CASES[:5]
        print(f"{C.YELLOW}Quick mode: running {len(cases)}/{len(EVAL_CASES)} cases{C.RESET}")
    
    print(f"\n{C.BOLD}{'═' * 70}{C.RESET}")
    print(f"  {C.BOLD}V2.1 Stage Flow Eval{C.RESET}")
    print(f"  Backend: {BACKEND_URL}")
    print(f"  Tests: {len(cases)}")
    print(f"{C.BOLD}{'═' * 70}{C.RESET}")
    
    # Health check
    try:
        r = requests.get(f"{BACKEND_URL}/api/v2/health", timeout=5)
        print(f"  Health: {C.GREEN}OK{C.RESET}")
    except Exception:
        print(f"  Health: {C.RED}Backend not reachable!{C.RESET}")
        print(f"  Start backend with: python3 -m uvicorn main:app --reload --port 8000")
        sys.exit(1)
    
    results = []
    for i, test in enumerate(cases, 1):
        print(f"\n  {C.DIM}[{i}/{len(cases)}] Running: {test.name}...{C.RESET}", end="", flush=True)
        result = run_single_eval(test)
        results.append(result)
        
        status = f"{C.GREEN}PASS{C.RESET}" if result.passed else f"{C.RED}FAIL{C.RESET}"
        print(f" {status} ({result.latency_ms}ms)")
    
    # Print details
    for r in results:
        print_result(r, verbose=verbose or not r.passed)
    
    # Print summary
    print_summary(results)
    
    # Exit code based on results
    sys.exit(0 if all(r.passed for r in results) else 1)


if __name__ == "__main__":
    main()
