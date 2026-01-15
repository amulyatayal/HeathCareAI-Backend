"""
Pydantic Schemas for Multi-Agent Pipeline
Defines request/response models and intermediate data structures.

Spec Reference: ProjectSpec.md v1.2, Sections 5, 6, 7, 8, 9
"""

from typing import List, Dict, Optional, Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
import uuid

from config.pipeline_config import (
    IntentCategory,
    PatientStage,
    CertaintyLevel,
    SPEC_VERSION
)


# ================================
# Agent Output Status
# ================================

class AgentStatus(str, Enum):
    """Status of an agent's execution."""
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


# ================================
# Citation Model (Section 9.4)
# ================================

class Citation(BaseModel):
    """Reference to source material used in generating a response."""
    source_file: str = Field(..., description="Name of source document")
    section: Optional[str] = Field(None, description="Section or chapter")
    page_start: Optional[int] = Field(None, description="Starting page number")
    page_end: Optional[int] = Field(None, description="Ending page number")
    relevance_score: float = Field(default=0.0, description="How relevant this source was")


# ================================
# Intent Agent Output (Section 6)
# ================================

class IntentResult(BaseModel):
    """Output from the Intent Extraction Agent."""
    intent: IntentCategory = Field(..., description="Classified intent category")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Classification confidence")
    reasoning: Optional[str] = Field(None, description="Why this intent was chosen")
    clarification_needed: bool = Field(default=False, description="Whether to ask for clarification")
    suggested_clarification: Optional[str] = Field(None, description="Question to ask if clarification needed")
    
    class Config:
        use_enum_values = True


# ================================
# Stage Agent Output (Section 7)
# ================================

class StageResult(BaseModel):
    """Output from the Stage Identification Agent."""
    stage: PatientStage = Field(..., description="Inferred patient stage")
    certainty: CertaintyLevel = Field(..., description="Certainty level (high/medium/low)")
    certainty_score: float = Field(..., ge=0.0, le=1.0, description="Numeric certainty score")
    signals: List[str] = Field(default_factory=list, description="Signals that led to this inference")
    
    class Config:
        use_enum_values = True


# ================================
# Retrieval Result
# ================================

class RetrievalChunk(BaseModel):
    """A single chunk retrieved from the knowledge base."""
    chunk_id: str = Field(..., description="Unique identifier for the chunk")
    content: str = Field(..., description="Text content of the chunk")
    score: float = Field(..., description="Relevance score")
    source_file: Optional[str] = Field(None, description="Source document")
    section: Optional[str] = Field(None, description="Section within document")
    page_start: Optional[int] = Field(None)
    page_end: Optional[int] = Field(None)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    """Output from knowledge base retrieval."""
    chunks: List[RetrievalChunk] = Field(default_factory=list)
    total_retrieved: int = Field(default=0)
    above_threshold: int = Field(default=0)
    sufficient_evidence: bool = Field(default=False)
    knowledge_base_used: str = Field(default="")


# ================================
# Reasoning Agent Output (Section 8)
# ================================

class ReasoningResult(BaseModel):
    """Output from a Reasoning Agent."""
    response_text: str = Field(..., description="Generated response content")
    citations: List[Citation] = Field(default_factory=list, description="Sources used")
    abstained: bool = Field(default=False, description="Whether agent abstained from answering")
    abstention_reason: Optional[str] = Field(None, description="Reason for abstention if applicable")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Response confidence")
    agent_type: str = Field(default="", description="Which reasoning agent generated this")


# ================================
# Validation Result (Section 9)
# ================================

class ValidationFlag(BaseModel):
    """A specific validation issue found."""
    rule_id: str = Field(..., description="Identifier for the validation rule")
    severity: str = Field(..., description="high/medium/low")
    message: str = Field(..., description="Description of the issue")
    suggested_fix: Optional[str] = Field(None)


class ValidationResult(BaseModel):
    """Output from the Validator Agent."""
    is_safe: bool = Field(..., description="Whether response passed all safety checks")
    flags: List[ValidationFlag] = Field(default_factory=list)
    modified_response: Optional[str] = Field(None, description="Corrected response if modifications needed")
    disclaimer_added: bool = Field(default=False)


# ================================
# Pipeline Context (Section 5)
# ================================

class PipelineContext(BaseModel):
    """
    Shared context passed through the pipeline.
    This is the 'blackboard' that all agents can read from and write to.
    """
    # Request identification
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    spec_version: str = Field(default=SPEC_VERSION)
    
    # User input
    user_message: str = Field(..., description="Original user message")
    conversation_history: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Previous messages in the conversation"
    )
    session_id: Optional[str] = Field(None, description="Session identifier for tracking")
    
    # Agent outputs (populated as pipeline progresses)
    intent_result: Optional[IntentResult] = Field(None)
    stage_result: Optional[StageResult] = Field(None)
    retrieval_result: Optional[RetrievalResult] = Field(None)
    reasoning_result: Optional[ReasoningResult] = Field(None)
    validation_result: Optional[ValidationResult] = Field(None)
    
    # Pipeline control
    should_abort: bool = Field(default=False, description="Whether to abort pipeline early")
    abort_reason: Optional[str] = Field(None)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# ================================
# Agent Trace (Section 20)
# ================================

class AgentTrace(BaseModel):
    """Trace record for a single agent execution."""
    agent_name: str
    status: AgentStatus
    latency_ms: int
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ================================
# Pipeline Response
# ================================

class PipelineResponse(BaseModel):
    """Final response from the multi-agent pipeline."""
    request_id: str
    response: str = Field(..., description="Final response to user")
    intent: IntentCategory
    stage: PatientStage
    citations: List[Citation] = Field(default_factory=list)
    confidence: float = Field(default=0.8)
    abstained: bool = Field(default=False)
    disclaimer_included: bool = Field(default=False)
    
    # Debug/trace info (optional, for logging)
    trace: List[AgentTrace] = Field(default_factory=list)
    total_latency_ms: int = Field(default=0)
    
    # Profile/Onboarding prompts
    needs_onboarding: bool = Field(
        default=False,
        description="True if authenticated user needs to complete onboarding"
    )
    sign_in_suggestion: Optional[str] = Field(
        None,
        description="Markdown text suggesting guest user sign in (shown in response)"
    )
    
    class Config:
        use_enum_values = True



# ================================
# API Request/Response Models
# ================================

class PipelineRequest(BaseModel):
    """API request to the multi-agent pipeline."""
    message: str = Field(..., min_length=1, max_length=5000)
    session_id: Optional[str] = Field(None)
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    include_trace: bool = Field(default=False, description="Include debug trace in response")


class HealthCheckResponse(BaseModel):
    """Health check response for the pipeline."""
    status: str
    spec_version: str
    agents_available: List[str]
    knowledge_bases_available: List[str]


# ================================
# Factory Functions
# ================================

def create_pipeline_context(
    message: str,
    session_id: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> PipelineContext:
    """Create a new pipeline context for a user message."""
    return PipelineContext(
        user_message=message,
        session_id=session_id,
        conversation_history=conversation_history or []
    )


def create_citation_from_chunk(chunk: RetrievalChunk) -> Citation:
    """Convert a retrieval chunk to a citation."""
    return Citation(
        source_file=chunk.source_file or "Unknown",
        section=chunk.section,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        relevance_score=chunk.score
    )

