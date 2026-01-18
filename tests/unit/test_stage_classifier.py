
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio

from services.agents.stage_classifier import StageClassifierAgent
from models.patient_stages import TreatmentStage

class TestStageClassifierAgent(unittest.TestCase):
    
    def setUp(self):
        # Mock dependencies
        self.mock_stage_service = MagicMock()
        self.mock_embedding_service = MagicMock()
        
        # Setup dummy stages
        self.stages = {
            "1": TreatmentStage(
                stage_id="1", 
                name="Diagnosis", 
                description="Initial diagnosis",
                child_stage_ids=["1.1"],
                after_stages=["2"]
            ),
            "1.1": TreatmentStage(
                stage_id="1.1", 
                name="Biopsy", 
                description="Tissue sampling",
                parent_stage_id="1"
            ),
            "2": TreatmentStage(
                stage_id="2", 
                name="Surgery", 
                description="Surgical removal",
                before_stages=["1"],
                after_stages=["3"]
            ),
            "3": TreatmentStage(
                stage_id="3",
                name="Chemotherapy",
                description="Systemic therapy",
                before_stages=["2"]
            )
        }
        self.mock_stage_service.get_all_stages.return_value = self.stages
        self.mock_stage_service.get_stage.side_effect = lambda eid: self.stages.get(eid)
        
        # Patch the EmbeddingService within the module
        with patch('services.agents.stage_classifier.EmbeddingService') as MockEmbeddingService:
            MockEmbeddingService.return_value = self.mock_embedding_service
            self.agent = StageClassifierAgent(stage_service=self.mock_stage_service)

        # Mock embedding generation (simplistic: higher value for match)
        # We'll use a side effect that returns dummy vectors based on checking if string is in input
        def mock_create_embedding(text):
            text_lower = text.lower()
            if "surgery" in text_lower or "removal" in text_lower:
                return [0.9, 0.1, 0.0]
            elif "chemo" in text_lower or "therapy" in text_lower:
                return [0.1, 0.9, 0.0]
            elif "diagnosis" in text_lower:
                return [0.0, 0.1, 0.9]
            else:
                return [0.1, 0.1, 0.1]
                
        self.mock_embedding_service.create_embedding.side_effect = mock_create_embedding

    def test_initialization(self):
        """Test that initialization computes embeddings for all stages."""
        asyncio.run(self.agent.initialize())
        
        # Should have called create_embedding for each stage
        self.assertEqual(self.mock_embedding_service.create_embedding.call_count, 4)
        self.assertTrue(self.agent._initialized)

    def test_classify_simple(self):
        """Test simple classification without constraints."""
        asyncio.run(self.agent.initialize())
        
        # "I am having surgery" -> Should match Stage 2 (Surgery) [0.9, 0.1, 0.0]
        # Stage 2 text "Surgery: Surgical removal" -> [0.9, 0.1, 0.0]
        # Dot product ~0.82
        
        results = asyncio.run(self.agent.classify("I am having surgery", top_k=3))
        
        print("\nDEBUG SCORES:")
        for stage, score in results:
            print(f"Stage {stage.stage_id} ({stage.name}): {score}")
            
        self.assertEqual(len(results), 3)
        top_stage, score = results[0]
        self.assertEqual(top_stage.stage_id, "2")
        self.assertGreater(score, 0.0)

    def test_classify_with_constraint(self):
        """Test constraint: current_stage=1 (Diagnosis) should allow 1.1 (Biopsy) or 2 (Surgery)."""
        asyncio.run(self.agent.initialize())
        
        # Input looks like Chemo (Stage 3)
        # But we are at Stage 1. 
        # Valid candidates from Stage 1: {1, 1.1, 2}
        # Stage 3 is NOT a candidate.
        
        # Mock embedding for input matching chemo
        text = "I am starting chemotherapy" 
        # Matches Stage 3 best. But Stage 3 is not valid next from Stage 1.
        
        results = asyncio.run(self.agent.classify(text, current_stage_id="1"))
        
        # Should find valid candidates. 
        # Stage 3 should NOT be in results.
        found_ids = [r[0].stage_id for r in results]
        self.assertNotIn("3", found_ids)
        
    def test_candidates_logic(self):
        """Test the _get_candidates logic explicitly."""
        # From Stage 1:
        # Children: 1.1
        # After: 2
        # Parent: None
        # Self: 1
        expected = {"1", "1.1", "2"}
        candidates = set(self.agent._get_candidates("1"))
        self.assertEqual(candidates, expected)
        
    def test_candidates_logic_leaf(self):
        """Test candidates for a leaf node."""
        # Stage 1.1 (Biopsy), Parent=1
        # Children: []
        # After: []
        # Valid: {1.1, 1} (Self + Parent)
        
        expected = {"1.1", "1"}
        candidates = set(self.agent._get_candidates("1.1"))
        self.assertEqual(candidates, expected)

if __name__ == '__main__':
    unittest.main()
