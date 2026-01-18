
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio

from services.pathway_orchestrator import PathwayOrchestrator, StageUpdateType
from models.patient_stages import TreatmentStage
# Mock PatientProfile for testing
class MockProfile:
    def __init__(self, current_stage_id):
        self.patient_id = "p1"
        self.current_stage_id = current_stage_id

class TestPathwayOrchestrator(unittest.TestCase):
    
    def setUp(self):
        # Mock dependencies
        self.mock_profile_service = MagicMock()
        self.mock_stage_service = MagicMock()
        self.mock_classifier_agent = AsyncMock() # Classifier is async
        
        # Instantiate Orchestrator
        self.orchestrator = PathwayOrchestrator(
            profile_service=self.mock_profile_service,
            stage_service=self.mock_stage_service,
            classifier_agent=self.mock_classifier_agent
        )
        
        # Setup common mocks
        self.mock_profile_service.get_profile.return_value = MockProfile("1") # Currently in Stage 1
        
        # Mock Stage Service behavior
        self.mock_stage_service.get_stage.side_effect = lambda sid: TreatmentStage(
            stage_id=sid, 
            name=f"Stage {sid}", 
            description="desc",
            transition_notes="Notes" if sid=="1" else None
        )

    def test_explicit_override_success(self):
        """Test explicit override successfully updates profile."""
        result = asyncio.run(self.orchestrator.determine_current_stage(
            patient_id="p1", 
            user_text="irrelevant", 
            explicit_stage_id="2"
        ))
        
        # Should be Explicit Override
        self.assertEqual(result.update_type, StageUpdateType.EXPLICIT_OVERRIDE)
        self.assertEqual(result.stage_id, "2")
        
        # Should have called update_stage
        self.mock_profile_service.update_stage.assert_called_with("p1", "2")

    def test_explicit_override_invalid_stage(self):
        """Test explicit override fails with invalid stage ID."""
        self.mock_stage_service.get_stage.side_effect = None # Clear side effect
        self.mock_stage_service.get_stage.return_value = None # Invalid ID
        
        result = asyncio.run(self.orchestrator.determine_current_stage(
            patient_id="p1", 
            user_text="foo", 
            explicit_stage_id="999"
        ))
        
        self.assertEqual(result.update_type, StageUpdateType.VALIDATION_ERROR)
        self.assertIn("Invalid stage ID", result.error)

    def test_inference_proposal_high_confidence(self):
        """Test high confidence inference suggests a proposal."""
        # Classifier returns Stage 2 with 0.9 confidence
        stage2 = TreatmentStage(stage_id="2", name="Surgery", description="Surgery")
        self.mock_classifier_agent.classify.return_value = [(stage2, 0.9)]
        
        result = asyncio.run(self.orchestrator.determine_current_stage(
            patient_id="p1", 
            user_text="I am having surgery"
        ))
        
        # Should be Proposal (NOT auto update)
        self.assertEqual(result.update_type, StageUpdateType.PROPOSAL)
        self.assertEqual(result.stage_id, "2")
        self.assertGreater(result.confidence, 0.85)
        # Should NOT update profile automatically
        self.mock_profile_service.update_stage.assert_not_called()

    def test_inference_low_confidence(self):
        """Test low confidence inference results in NO_CHANGE."""
        # Classifier returns Stage 2 with 0.5 confidence
        stage2 = TreatmentStage(stage_id="2", name="Surgery", description="Surgery")
        self.mock_classifier_agent.classify.return_value = [(stage2, 0.5)]
        
        result = asyncio.run(self.orchestrator.determine_current_stage(
            patient_id="p1", 
            user_text="I might have surgery"
        ))
        
        self.assertEqual(result.update_type, StageUpdateType.NO_CHANGE)

    def test_get_rag_context(self):
        """Test context generation string."""
        # Mock Stage 1 with children
        s1 = TreatmentStage(stage_id="1", name="Stage 1", description="Desc 1", transition_notes="Note 1", child_stage_ids=["1.1"])
        s11 = TreatmentStage(stage_id="1.1", name="Stage 1.1", description="Desc 1.1")
        
        self.mock_stage_service.get_stage.side_effect = lambda sid: s1 if sid == "1" else s11
        
        context = self.orchestrator.get_rag_context("p1")
        
        self.assertIn("CURRENT STAGE: Stage 1", context)
        self.assertIn("Notes: Note 1", context)
        self.assertIn("Drill-down", context)
        self.assertIn("Stage 1.1", context)

if __name__ == '__main__':
    unittest.main()
