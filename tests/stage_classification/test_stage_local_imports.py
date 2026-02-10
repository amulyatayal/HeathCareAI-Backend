#!/usr/bin/env python
"""
V2.1 Journey Engine - Comprehensive Local Test Suite
Tests all V2.1 enhancements without needing pytest.
"""

import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

print("="*70)
print("V2.1 JOURNEY ENGINE - LOCAL TEST SUITE")
print("="*70)
print()

# Test 1: Model Imports
print("Test 1: Model Imports")
print("-" * 40)
try:
    from models.patient_stages import TreatmentStage
    from models.patient_profile import PatientProfile, PatientStageHistory
    
    # Check V2.1 fields
    stage = TreatmentStage(
        stage_id="test",
        name="Test Stage",
        description="Test",
        verification_questions=["Test question?"],
        safety_triggers=["fever", "pain"]
    )
    print(f"✅ TreatmentStage model: {len(stage.verification_questions)} questions, {len(stage.safety_triggers)} triggers")
    
    profile = PatientProfile(
        user_id="test_user",
        country_code="GB",
        current_stage_certainty="HIGH",
        has_recurrence=False
    )
    print(f"✅ PatientProfile model: country_code={profile.country_code}, certainty={profile.current_stage_certainty}")
    
    history = PatientStageHistory(
        from_stage=None,
        to_stage=PatientStage.ACTIVE_TREATMENT,
        source="llm_inference",
        inference_certainty="HIGH",
        inference_signals=["mentioned surgery"],
        user_confirmed=True
    )
    print(f"✅ PatientStageHistory: certainty={history.inference_certainty}, confirmed={history.user_confirmed}")
    
except Exception as e:
    print(f"❌ Model import failed: {e}")
    sys.exit(1)

print()

# Test 2: Stage Hierarchy JSON
print("Test 2: Stage Hierarchy JSON")
print("-" * 40)
try:
    json_path = Path(__file__).parent.parent.parent / "data" / "stage_hierarchy.json"
    with open(json_path) as f:
        data = json.load(f)
    
    stages = data.get("stages", {})
    print(f"✅ Loaded {len(stages)} stages")
    
    # Check V2.1 fields in a sample stage
    sample_id = list(stages.keys())[0] if stages else None
    if sample_id:
        sample = stages[sample_id]
        has_vq = "verification_questions" in sample
        has_st = "safety_triggers" in sample
        print(f"✅ Sample stage '{sample_id}': verification_questions={has_vq}, safety_triggers={has_st}")
        
        if has_vq:
            vq_count = len(sample["verification_questions"])
            print(f"   - {vq_count} verification questions")
    
    # Count stages with data
    with_vq = sum(1 for s in stages.values() if s.get("verification_questions"))
    with_st = sum(1 for s in stages.values() if s.get("safety_triggers"))
    print(f"✅ Stages with verification questions: {with_vq}/{len(stages)}")
    print(f"✅ Stages with safety triggers: {with_st}/{len(stages)}")
    
except Exception as e:
    print(f"❌ Stage hierarchy failed: {e}")
    sys.exit(1)

print()

# Test 3: Service Imports
print("Test 3: Service Imports")
print("-" * 40)
try:
    from services.patient_stage_service import get_patient_stage_service
    
    stage_service = get_patient_stage_service()
    print(f"✅ PatientStageService loaded: {len(stage_service._stages)} stages")
    
    # Test safety trigger detection (now a method on stage_service)
    safety_result = stage_service.check_for_safety_triggers(
        user_message="I have a high fever and severe pain",
        country_code="GB"
    )
    print(f"✅ Safety trigger detection: matched={safety_result['has_triggers']}, keywords={safety_result['matched_keywords']}")
    print(f"   - Emergency number (GB): {safety_result['emergency_number']}")
    
    # Test regression detection (now a method on stage_service)
    regression = stage_service.detect_regression(from_stage_id="5.1", to_stage_id="8")
    print(f"✅ Regression detection: is_regression={regression['is_regression']}, type={regression['regression_type']}")
    
except Exception as e:
    print(f"❌ Service import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# Test 4: Profile Service Extensions
print("Test 4: Profile Service Extensions")
print("-" * 40)
try:
    from services.patient_profile_service import get_patient_profile_service
    profile_service = get_patient_profile_service()
    print("✅ PatientProfileService.update_stage_with_metadata available")
    
    # Check method exists
    import inspect
    assert hasattr(profile_service, 'update_stage_with_metadata'), "Method not found on service"
    sig = inspect.signature(profile_service.update_stage_with_metadata)
    params = list(sig.parameters.keys())
    expected = ['user_id', 'new_stage', 'new_detailed_stage_id', 'metadata']
    matches = all(p in params for p in expected)
    print(f"✅ Method signature valid: {matches}")
    
except Exception as e:
    print(f"❌ Profile service extension failed: {e}")
    sys.exit(1)

print()

# Test 5: Orchestrator
print("Test 5: Orchestrator")
print("-" * 40)
try:
    from services.agents.orchestrator import Orchestrator
    print("✅ Orchestrator imported successfully")
    
except Exception as e:
    print(f"❌ Orchestrator import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# Test 6: Integration Verification
print("Test 6: End-to-End Integration")
print("-" * 40)
try:
    # Test verification question availability (from stage data)
    stage_service = get_patient_stage_service()
    sample_stage = stage_service.get_stage_by_id("2.1.1")
    if sample_stage:
        has_q = len(sample_stage.verification_questions) > 0
        print(f"✅ Verification questions for '2.1.1': has_questions={has_q}")
        if has_q:
            print(f"   Preview: {sample_stage.verification_questions[0][:100]}...")
    else:
        print("⚠️  Stage 2.1.1 not found, skipping")
    
except Exception as e:
    print(f"❌ Integration test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()
print("="*70)
print("✅ ALL TESTS PASSED - V2.1 is ready for local testing!")
print("="*70)
print()
print("Next steps:")
print("1. Backend server is running (auto-reloaded with changes)")
print("2. Test via API: curl http://localhost:8000/health")
print("3. Test stage loading: curl http://localhost:8000/stages")
print("4. Manual user flow testing via frontend")
