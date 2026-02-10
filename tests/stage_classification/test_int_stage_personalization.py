import unittest
import logging
import asyncio
from unittest.mock import MagicMock, patch

from services.agents.reasoning_agent import ReasoningAgent
from models.schemas_pipeline import PipelineContext, ReasoningResult
from config.pipeline_config import PatientStage, IntentCategory
from config.agent_routing import ReasoningAgentType
from services.patient_stage_service import get_patient_stage_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TestReasoningAgentStageIntegration(unittest.TestCase):
    """
    Integration tests to verify the Reasoning Agent correctly incorporates
    detailed patient stage information into its prompts.
    """
    
    @classmethod
    def setUpClass(cls):
        """Set up services once."""
        # Ensure stage service is loaded
        cls.stage_service = get_patient_stage_service()
        
    def setUp(self):
        """Set up for each test."""
        self.agent = ReasoningAgent(agent_type=ReasoningAgentType.GENERAL)
        

    def test_prompt_includes_detailed_stage_context_chemotherapy(self):
        """
        Verify that a context with detailed_stage_id '3.2' (Chemotherapy)
        results in a prompt containing chemotherapy-specific information.
        """
        # Create context with detailed stage info
        context = PipelineContext(
            user_message="Should I be worried about hair loss?",
            conversation_id="test_conv_123",
            metadata={"detailed_stage_id": "3.2"}  # Chemotherapy
        )
        
        # Build prompt
        prompt = asyncio.run(self.agent._build_user_prompt(context))
        
        # Verify prompt content
        logger.info(f"Generated prompt for Chemotherapy:\n{prompt[:500]}...")
        
        # Check for stage name
        self.assertIn("Chemotherapy", prompt, "Prompt should contain stage name 'Chemotherapy'")
        # Check for stage ID
        self.assertIn("(3.2)", prompt, "Prompt should contain stage ID '3.2'")
        
        # Check for parent path keywords (data has 'systemic treatment')
        self.assertIn("systemic treatment", prompt, "Prompt should contain parent stage context")
        
        # If the backend is running and data is loaded, we expect description too
        # But even if we just get the name and ID, that proves the integration works.
        
    def test_prompt_includes_detailed_stage_context_surgery(self):
        """
        Verify that a context with detailed_stage_id '2' (Surgery)
        results in a prompt containing surgery-specific information.
        """
        context = PipelineContext(
            user_message="How long is recovery?",
            conversation_id="test_conv_456",
            metadata={"detailed_stage_id": "2"}  # Surgery
        )
        
        prompt = asyncio.run(self.agent._build_user_prompt(context))
        
        logger.info(f"Generated prompt for Surgery:\n{prompt[:500]}...")
        
        self.assertIn("Surgery", prompt)
        self.assertIn("(2)", prompt)
        
    def test_prompt_fallback_when_invalid_stage_id(self):
        """
        Verify that an invalid stage ID falls back gracefully (no crash).
        """
        context = PipelineContext(
            user_message="Hello",
            conversation_id="test_conv_789",
            metadata={"detailed_stage_id": "999.999"}  # Invalid
        )
        
        # Should not raise exception
        try:
            prompt = asyncio.run(self.agent._build_user_prompt(context))
            logger.info("Prompt generated successfully with invalid ID")
        except Exception as e:
            self.fail(f"Prompt generation failed with invalid stage ID: {e}")
            
        # Should not contain specific stage info but should be valid prompt
        self.assertIn("Hello", prompt)

if __name__ == '__main__':
    unittest.main()
