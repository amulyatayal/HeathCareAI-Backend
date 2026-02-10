"""
Base Agent Interface for Multi-Agent Pipeline
Defines the abstract contract that all agents must implement.

Spec Reference: ProjectSpec.md v1.2
"""

from abc import ABC, abstractmethod
from typing import Optional, Any, Dict
import time
import logging
import asyncio
from datetime import datetime

from models.schemas_pipeline import (
    PipelineContext,
    AgentTrace,
    AgentStatus
)
from config.pipeline_config import (
    ModelType,
    MODEL_IDS,
    ErrorPolicy,
    SAFE_FALLBACK_RESPONSE
)

logger = logging.getLogger(__name__)


# ================================
# Custom Exceptions
# ================================

class AgentError(Exception):
    """Base exception for agent errors."""
    def __init__(self, message: str, agent_name: str, recoverable: bool = True):
        self.message = message
        self.agent_name = agent_name
        self.recoverable = recoverable
        super().__init__(f"[{agent_name}] {message}")


class AgentTimeoutError(AgentError):
    """Agent execution timed out."""
    def __init__(self, agent_name: str, timeout_ms: int):
        super().__init__(
            f"Execution timed out after {timeout_ms}ms",
            agent_name,
            recoverable=True
        )


class AgentRetryExhaustedError(AgentError):
    """Agent exhausted all retry attempts."""
    def __init__(self, agent_name: str, attempts: int):
        super().__init__(
            f"Failed after {attempts} retry attempts",
            agent_name,
            recoverable=False
        )


# ================================
# Base Agent Interface
# ================================

class BaseAgent(ABC):
    """
    Abstract base class for all pipeline agents.
    
    All agents in the multi-agent pipeline must inherit from this class
    and implement the `execute` method.
    
    Features:
    - Automatic timing/tracing
    - Error handling with retries
    - Model selection support
    - Logging integration
    """
    
    def __init__(
        self,
        name: str,
        model_type: ModelType = ModelType.FAST,
        timeout_ms: int = ErrorPolicy.TIMEOUT_PER_AGENT_MS,
        max_retries: int = ErrorPolicy.MAX_RETRIES
    ):
        """
        Initialize the base agent.
        
        Args:
            name: Unique identifier for this agent
            model_type: Which LLM model to use (fast/accurate)
            timeout_ms: Maximum execution time in milliseconds
            max_retries: Maximum retry attempts on failure
        """
        self.name = name
        self.model_type = model_type
        self.model_id = MODEL_IDS.get(model_type, MODEL_IDS[ModelType.FAST])
        self.timeout_ms = timeout_ms
        self.max_retries = max_retries
        self._bedrock_client = None  # Lazy initialization
    
    @property
    def bedrock_client(self):
        """Lazy initialization of Bedrock client."""
        if self._bedrock_client is None:
            import boto3
            from config.settings import settings
            
            # Build client kwargs
            client_kwargs = {
                'service_name': 'bedrock-runtime',
                'region_name': settings.aws_region
            }
            
            # Add credentials if provided in settings
            if settings.aws_access_key_id and settings.aws_secret_access_key:
                client_kwargs['aws_access_key_id'] = settings.aws_access_key_id
                client_kwargs['aws_secret_access_key'] = settings.aws_secret_access_key
            
            self._bedrock_client = boto3.client(**client_kwargs)
        return self._bedrock_client
    
    @abstractmethod
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Execute the agent's logic.
        
        This is the core method that each agent must implement.
        The agent should:
        1. Read necessary inputs from the context
        2. Perform its specific task
        3. Write its outputs back to the context
        4. Return the updated context
        
        Args:
            context: The shared pipeline context
            
        Returns:
            Updated PipelineContext with agent's outputs
            
        Raises:
            AgentError: If the agent encounters an unrecoverable error
        """
        pass
    
    async def run(self, context: PipelineContext) -> tuple[PipelineContext, AgentTrace]:
        """
        Run the agent with error handling, retries, and tracing.
        
        This is the public method that the orchestrator calls.
        It wraps `execute` with:
        - Timing measurements
        - Retry logic
        - Error handling
        - Trace generation
        
        Args:
            context: The shared pipeline context
            
        Returns:
            Tuple of (updated context, agent trace)
        """
        start_time = time.time()
        trace = AgentTrace(
            agent_name=self.name,
            status=AgentStatus.SUCCESS,
            latency_ms=0,
            timestamp=datetime.utcnow()
        )
        
        attempt = 0
        last_error: Optional[Exception] = None
        
        while attempt <= self.max_retries:
            try:
                # Execute with timeout
                updated_context = await asyncio.wait_for(
                    self.execute(context),
                    timeout=self.timeout_ms / 1000  # Convert to seconds
                )
                
                # Success
                trace.status = AgentStatus.SUCCESS
                trace.latency_ms = int((time.time() - start_time) * 1000)
                trace.output_summary = self._get_output_summary(updated_context)
                
                logger.info(
                    f"Agent {self.name} completed successfully in {trace.latency_ms}ms"
                )
                
                return updated_context, trace
                
            except asyncio.TimeoutError:
                last_error = AgentTimeoutError(self.name, self.timeout_ms)
                logger.warning(f"Agent {self.name} timed out (attempt {attempt + 1})")
                
            except AgentError as e:
                last_error = e
                if not e.recoverable:
                    break
                logger.warning(
                    f"Agent {self.name} failed (attempt {attempt + 1}): {e.message}"
                )
                
            except Exception as e:
                last_error = AgentError(str(e), self.name, recoverable=True)
                logger.error(
                    f"Agent {self.name} unexpected error (attempt {attempt + 1}): {e}"
                )
            
            attempt += 1
            if attempt <= self.max_retries:
                await asyncio.sleep(ErrorPolicy.RETRY_DELAY_MS / 1000)
        
        # All retries exhausted
        trace.status = AgentStatus.FAILED
        trace.latency_ms = int((time.time() - start_time) * 1000)
        trace.error_message = str(last_error) if last_error else "Unknown error"
        
        logger.error(
            f"Agent {self.name} failed after {attempt} attempts: {trace.error_message}"
        )
        
        # Apply fallback behavior if configured
        if ErrorPolicy.FALLBACK_ON_FAILURE:
            context = self._apply_fallback(context)
        
        return context, trace
    
    def _apply_fallback(self, context: PipelineContext) -> PipelineContext:
        """
        Apply safe fallback behavior when agent fails.
        Can be overridden by specific agents for custom fallback logic.
        """
        # Default: just mark that we should be cautious
        # Specific agents can override this
        return context
    
    def _get_output_summary(self, context: PipelineContext) -> Optional[str]:
        """
        Generate a summary of the agent's output for logging.
        Can be overridden by specific agents.
        """
        return None
    
    async def invoke_llm(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: int = 1000
    ) -> str:
        """
        Invoke the LLM with the configured model.
        
        Args:
            system_prompt: System instructions for the LLM
            user_message: User message/query
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum response tokens
            
        Returns:
            LLM response text
        """
        import json
        
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_message}
            ]
        })
        
        # Run synchronous boto3 call in executor
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.bedrock_client.invoke_model(
                modelId=self.model_id,
                body=body
            )
        )
        
        response_body = json.loads(response['body'].read())
        return response_body['content'][0]['text']
    
    async def invoke_llm_with_json(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.2,
        max_tokens: int = 1000
    ) -> Dict[str, Any]:
        """
        Invoke the LLM and parse response as JSON.
        
        Args:
            system_prompt: System instructions (should request JSON output)
            user_message: User message/query
            temperature: Sampling temperature (lower for structured output)
            max_tokens: Maximum response tokens
            
        Returns:
            Parsed JSON response as dictionary
        """
        import json
        
        response_text = await self.invoke_llm(
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        # Try to extract JSON from response
        # Handle cases where LLM wraps JSON in markdown code blocks
        text = response_text.strip()
        if text.startswith("```"):
            # Remove markdown code block wrapper
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```"):
                    in_block = not in_block
                elif in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            # Try to find JSON object in the text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
            raise AgentError(
                f"Could not parse LLM response as JSON",
                self.name,
                recoverable=True
            )
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, model={self.model_type})"


# ================================
# Skip Agent (Utility)
# ================================

class SkipAgent(BaseAgent):
    """
    A no-op agent that simply passes context through.
    Useful for conditional pipeline stages.
    """
    
    def __init__(self, name: str = "skip"):
        super().__init__(name=name, model_type=ModelType.FAST)
    
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """Pass through without modification."""
        logger.debug(f"SkipAgent {self.name}: passing through")
        return context

