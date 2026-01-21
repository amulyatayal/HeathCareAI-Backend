import asyncio
import sys
import logging
from dotenv import load_dotenv

# Setup path and env
sys.path.insert(0, '.')
load_dotenv()

# Logger setup
logging.basicConfig(level=logging.ERROR) # Lower noise
logger = logging.getLogger("services.agents.stage_agent_v2")
logger.setLevel(logging.INFO)

from services.agents.stage_agent_v2 import StageAgentV2
from models.schemas import PipelineContext, IntentResult

async def main():
    agent = StageAgentV2()
    
    test_cases = [
        "I had surgery yesterday. tell me what to expect next?",
        "I just found a lump and I'm scared.",
        "I finished chemotherapy last month and now I'm on hormone pills."
    ]
    
    print("\n--- Verifying StageAgentV2 (BaseAgent Implementation) ---\n")
    
    for query in test_cases:
        print(f"Query: '{query}'")
        
        # Mock Context with Correct Field Name
        context = PipelineContext(
            request_id="test",
            user_message=query,
            intent_result=IntentResult(intent="unknown", confidence=0.0) 
        )
        
        try:
            # We call execute directly to skip trace wrapper for simple testing
            result_context = await agent.execute(context)
            
            res = result_context.stage_result
            metadata = result_context.metadata
            print("Result:")
            print(f"  Spec Stage: {res.stage}")
            print(f"  Granular:   {metadata.get('granular_stage_id')}")
            print(f"  Certainty:  {res.certainty} ({res.certainty_score})")
            print(f"  Evidence:   {res.signals}")
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        print("-" * 50)

if __name__ == "__main__":
    asyncio.run(main())
