"""
V2.1 Journey Engine Enhancement Tests
Integration tests for verification questions, safety triggers, regression detection, and profile enhancements.
"""

import pytest
from datetime import datetime, date
from models.patient_stages import TreatmentStage
from models.patient_profile import PatientProfile, PatientStageHistory
from services.patient_stage_service import PatientStageService


class TestV2_1_Models:
    """Test model enhancements."""
    
    def test_treatment_stage_new_fields(self):
        """Test TreatmentStage has verification_questions and safety_triggers fields."""
        stage = TreatmentStage(
            stage_id="2.1",
            name="Surgery",
            verification_questions=["Have you been scheduled for surgery?"],
            safety_triggers=["bleeding", "fever"]
        )
        
        assert len(stage.verification_questions) == 1
        assert stage.verification_questions[0] == "Have you been scheduled for surgery?"
        assert "bleeding" in stage.safety_triggers
        assert "fever" in stage.safety_triggers
    
    def test_patient_profile_new_fields(self):
        """Test PatientProfile has all 13 new V2.1 fields."""
        profile = PatientProfile(
            user_id="test123",
            country_code="GB",
            region="London",
            current_stage_certainty="HIGH",
            has_recurrence=False,
            was_guest=True,
            guest_interactions_count=3
        )
        
        # Geo-awareness
        assert profile.country_code == "GB"
        assert profile.region == "London"
        
        # Stage certainty
        assert profile.current_stage_certainty == "HIGH"
        assert profile.last_verification_at is None
        
        # Regression tracking
        assert profile.has_recurrence is False
        assert profile.is_regression_detected is False
        assert profile.first_diagnosis_date is None
        
        # Guest conversion
        assert profile.was_guest is True
        assert profile.guest_interactions_count == 3
    
    def test_patient_stage_history_new_fields(self):
        """Test PatientStageHistory has 8 new transition metadata fields."""
        history = PatientStageHistory(
            from_stage="NEWLY_DIAGNOSED",
            to_stage="ACTIVE_TREATMENT",
            source="llm_inference",
            inference_certainty="HIGH",
            inference_signals=["User mentioned 'starting chemo'"],
            user_confirmed=True,
            from_detailed_stage_id="1.1",
            to_detailed_stage_id="8.1",
            treatment_type="chemotherapy",
            was_regression=False
        )
        
        assert history.inference_certainty == "HIGH"
        assert len(history.inference_signals) == 1
        assert history.user_confirmed is True
        assert history.from_detailed_stage_id == "1.1"
        assert history.to_detailed_stage_id == "8.1"
        assert history.treatment_type == "chemotherapy"
        assert history.was_regression is False


class TestV2_1_CSV_Processing:
    """Test CSV parsing and stage hierarchy generation."""
    
    def test_stage_hierarchy_loads_59_stages(self):
        """Test that stage_hierarchy.json contains 59 stages."""
        service = PatientStageService()
        stages = service.get_all_stages()
        
        # Expecting 59 stages from processed CSV
        assert len(stages) >= 59, f"Expected >= 59 stages, got {len(stages)}"
    
    def test_verification_questions_extracted(self):
        """Test that verification_questions are extracted from CSV."""
        service = PatientStageService()
        stages = service.get_all_stages()
        
        # At least some stages should have verification questions
        stages_with_questions = [s for s in stages.values() if s.verification_questions]
        assert len(stages_with_questions) > 0, "No stages have verification questions"
    
    def test_safety_triggers_extracted(self):
        """Test that safety_triggers are extracted."""
        service = PatientStageService()
        stages = service.get_all_stages()
        
        # At least some stages should have safety triggers
        stages_with_triggers = [s for s in stages.values() if s.safety_triggers]
        assert len(stages_with_triggers) > 0, "No stages have safety triggers"


class TestV2_1_SafetyDetection:
    """Test safety trigger detection."""
    
    def test_safety_trigger_detection_positive(self):
        """Test safety trigger detection with matching keywords."""
        service = PatientStageService()
        
        result = service.check_for_safety_triggers(
            "I have a high fever and severe bleeding",
            country_code="GB"
        )
        
        assert result["has_triggers"] is True
        assert len(result["matched_keywords"]) >= 2
        assert result["emergency_number"] == "999"
        assert result["urgent_number"] == "111"
    
    def test_safety_trigger_detection_negative(self):
        """Test no false positives."""
        service = PatientStageService()
        
        result = service.check_for_safety_triggers(
            "I have a question about recovery",
            country_code="GB"
        )
        
        assert result["has_triggers"] is False
        assert len(result["matched_keywords"]) == 0
    
    def test_geo_aware_emergency_numbers_us(self):
        """Test US emergency numbers."""
        service = PatientStageService()
        
        result = service.check_for_safety_triggers(
            "I have a fever",
            country_code="US"
        )
        
        assert result["emergency_number"] == "911"
        assert result["urgent_number"] == "811"
    
    def test_geo_aware_emergency_numbers_uk(self):
        """Test UK emergency numbers (default)."""
        service = PatientStageService()
        
        result = service.check_for_safety_triggers(
            "I have a fever",
            country_code="GB"
        )
        
        assert result["emergency_number"] == "999"
        assert result["urgent_number"] == "111"


class TestV2_1_RegressionDetection:
    """Test regression/recurrence detection logic."""
    
    def test_recurrence_detection(self):
        """Test Type 1: Survivorship → Treatment = Recurrence."""
        service = PatientStageService()
        
        result = service.detect_regression(from_stage_id="5.1", to_stage_id="8.1")
        
        assert result["is_regression"] is True
        assert result["regression_type"] == "recurrence"
        assert "recurrence" in result["message"].lower()
    
    def test_new_primary_detection(self):
        """Test Type 2: Post-treatment → Early stage = New Primary."""
        service = PatientStageService()
        
        result = service.detect_regression(from_stage_id="9.1", to_stage_id="1.1")
        
        assert result["is_regression"] is True
        assert result["regression_type"] == "new_primary"
        assert "new diagnosis" in result["message"].lower()
    
    def test_normal_progression(self):
        """Test normal progression (not regression)."""
        service = PatientStageService()
        
        result = service.detect_regression(from_stage_id="2.1", to_stage_id="8.1")
        
        assert result["is_regression"] is False
        assert result["regression_type"] is None
    
    def test_no_previous_stage(self):
        """Test with no previous stage."""
        service = PatientStageService()
        
        result = service.detect_regression(from_stage_id=None, to_stage_id="1.1")
        
        assert result["is_regression"] is False
        assert result["regression_type"] is None


class TestV2_1_IntegrationScenarios:
    """End-to-end scenario tests."""
    
    def test_full_patient_journey_with_recurrence(self):
        """Test complete patient journey with recurrence detection."""
        # Create patient profile
        profile = PatientProfile(
            user_id="patient456",
            country_code="GB",
            current_stage="SURVEILLANCE",
            detailed_stage_id="5.1",
            has_recurrence=False
        )
        
        # Simulate recurrence (5.1 → 8.1)
        service = PatientStageService()
        regression_result = service.detect_regression("5.1", "8.1")
        
        # Update profile
        assert regression_result["is_regression"] is True
        profile.has_recurrence = True
        profile.is_regression_detected = True
        profile.recurrence_date = datetime.utcnow()
        
        assert profile.has_recurrence is True
        assert profile.is_regression_detected is True
    
    def test_safety_detection_with_geo_awareness(self):
        """Test safety detection respects patient location."""
        # UK patient
        uk_profile = PatientProfile(
            user_id="uk_patient",
            country_code="GB"
        )
        
        service = PatientStageService()
        result = service.check_for_safety_triggers(
            "I have severe chest pain",
            country_code=uk_profile.country_code
        )
        
        assert result["has_triggers"] is True
        assert result["emergency_number"] == "999"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
