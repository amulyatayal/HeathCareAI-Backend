"""
Pydantic Models for API Request/Response Schemas
Healthcare Companion App for Breast Cancer Patients
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


# ================================
# Enums
# ================================

class MessageRole(str, Enum):
    """Message role in conversation"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class QueryCategory(str, Enum):
    """Categories of breast cancer related queries"""
    SYMPTOMS = "symptoms"
    TREATMENT = "treatment"
    MEDICATION = "medication"
    SIDE_EFFECTS = "side_effects"
    LIFESTYLE = "lifestyle"
    EMOTIONAL_SUPPORT = "emotional_support"
    NUTRITION = "nutrition"
    FOLLOW_UP_CARE = "follow_up_care"
    GENERAL = "general"


class ContentType(str, Enum):
    """Types of knowledge base content"""
    MEDICAL_ARTICLE = "medical_article"
    FAQ = "faq"
    PATIENT_GUIDE = "patient_guide"
    RESEARCH_SUMMARY = "research_summary"
    SUPPORT_RESOURCE = "support_resource"


# ================================
# Chat Models
# ================================

class ChatMessage(BaseModel):
    """Single chat message"""
    role: MessageRole
    content: str
    timestamp: Optional[datetime] = None


class ChatRequest(BaseModel):
    """Request to chat with the AI agent"""
    message: str = Field(..., min_length=1, max_length=2000, description="User's question or message")
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity")
    user_id: Optional[str] = Field(None, description="User identifier for personalization")
    include_sources: bool = Field(True, description="Include source citations in response")
    index_name: Optional[str] = Field(
        None,
        description="OpenSearch index to search. Get available indexes from GET /api/v1/knowledge/indexes"
    )
    strict_mode: bool = Field(
        True,
        description="If True, only answers from knowledge base (refuses if no evidence). If False, uses general AI with knowledge base context."
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "message": "What are the common side effects of chemotherapy?",
                "session_id": "abc123",
                "include_sources": True,
                "index_name": "breast_cancer_knowledge",
                "strict_mode": True
            }
        }


class SourceCitation(BaseModel):
    """Citation for a knowledge base source with full text for popup display"""
    title: str  # Readable title (e.g., "Chemotherapy for Breast Cancer")
    content_type: ContentType
    relevance_score: float
    source_url: Optional[str] = None  # Original filename
    excerpt: Optional[str] = None  # Short excerpt (for inline display)
    
    # Enhanced fields for UI popup
    source_text: Optional[str] = None  # Full chunk text (for popup/modal display)
    document_name: Optional[str] = None  # Clean document name
    page_start: Optional[int] = None  # Starting page number
    page_end: Optional[int] = None  # Ending page number
    section: Optional[str] = None  # Section heading if available
    
    # Display-ready summary for frontend
    display_summary: Optional[str] = None  # e.g., "Information about exercises and recovery"


class ChatResponse(BaseModel):
    """Response from the AI agent"""
    answer: str  # Main answer content (without disclaimer or sources)
    session_id: str
    query_category: QueryCategory
    sources: List[SourceCitation] = []
    confidence_score: float = Field(ge=0, le=1)
    response_time_ms: float
    
    # Disclaimer as separate field for frontend styling (bold, different font)
    disclaimer: str = Field(
        default="This information is for educational purposes only and should not replace professional medical advice. Please consult your healthcare provider for personalized guidance."
    )
    
    # Sources section heading for frontend styling (different font/style)
    sources_heading: str = Field(default="Sources consulted")
    
    # Indicates if answer was generated from knowledge base or is a refusal
    has_sufficient_evidence: bool = Field(default=True)
    
    # Helpline info for easy frontend rendering
    support_helpline: str = Field(default="0808 800")
    support_helpline_name: str = Field(default="HealthCare AI Now")
    
    # Conversation tracking for feedback
    conversation_id: Optional[str] = Field(None, description="Unique ID for this conversation (for feedback)")
    conversation_created_at: Optional[str] = Field(None, description="ISO timestamp for feedback API")
    timestamp: Optional[str] = Field(None, description="Response timestamp in ISO format")
    
    class Config:
        json_schema_extra = {
            "example": {
                "answer": "Common side effects of chemotherapy include fatigue, nausea, hair loss...",
                "session_id": "abc123",
                "query_category": "side_effects",
                "sources": [
                    {
                        "title": "Chemotherapy for Breast Cancer (pages 15-17)",
                        "content_type": "medical_article",
                        "relevance_score": 8.5,
                        "source_url": "bcc17-chemotherapy-for-breast-cancer-web.pdf",
                        "source_text": "Full text of the source chunk for popup display...",
                        "document_name": "Chemotherapy for Breast Cancer",
                        "page_start": 15,
                        "page_end": 17
                    }
                ],
                "confidence_score": 0.85,
                "response_time_ms": 1250.5,
                "disclaimer": "This information is for educational purposes only...",
                "has_sufficient_evidence": True,
                "support_helpline": "0808 800 6000",
                "support_helpline_name": "Breast Cancer Now"
            }
        }


# ================================
# Knowledge Base Models
# ================================

class KnowledgeDocument(BaseModel):
    """Document in the knowledge base"""
    id: Optional[str] = None
    title: str
    content: str
    content_type: ContentType
    category: QueryCategory
    source_url: Optional[str] = None
    author: Optional[str] = None
    published_date: Optional[datetime] = None
    tags: List[str] = []
    metadata: Dict[str, Any] = {}


class KnowledgeSearchRequest(BaseModel):
    """Request to search the knowledge base"""
    query: str = Field(..., min_length=1, max_length=500)
    category: Optional[QueryCategory] = None
    content_type: Optional[ContentType] = None
    limit: int = Field(10, ge=1, le=50)


class KnowledgeSearchResult(BaseModel):
    """Single search result from knowledge base"""
    document_id: str
    title: str
    content_excerpt: str
    relevance_score: float
    content_type: ContentType
    category: QueryCategory
    source_url: Optional[str] = None


class KnowledgeSearchResponse(BaseModel):
    """Response from knowledge base search"""
    results: List[KnowledgeSearchResult]
    total_results: int
    search_time_ms: float


# ================================
# Document Upload Models
# ================================

class DocumentUploadResponse(BaseModel):
    """Response after uploading a document"""
    document_id: str
    title: str
    status: str
    chunks_created: int
    message: str


# ================================
# Health Check Models
# ================================

class ServiceHealth(BaseModel):
    """Health status of a service"""
    name: str
    status: str  # "healthy", "unhealthy", "degraded"
    latency_ms: Optional[float] = None
    message: Optional[str] = None


class HealthCheckResponse(BaseModel):
    """Overall health check response"""
    status: str
    version: str
    services: List[ServiceHealth]
    timestamp: datetime


# ================================
# User Session Models
# ================================

class UserSession(BaseModel):
    """User session information"""
    session_id: str
    user_id: Optional[str] = None
    created_at: datetime
    last_active: datetime
    message_count: int
    conversation_history: List[ChatMessage] = []


class SessionSummary(BaseModel):
    """Summary of a user session"""
    session_id: str
    message_count: int
    topics_discussed: List[str]
    created_at: datetime
    last_active: datetime


# ================================
# Feedback Schemas
# ================================

class FeedbackRequest(BaseModel):
    """Request to submit feedback for a conversation"""
    conversation_id: str = Field(..., description="The conversation ID to provide feedback for")
    created_at: str = Field(..., description="The created_at timestamp in ISO format (e.g., 2025-01-01T00:00:00Z)")
    rating: str = Field(..., description="Feedback rating: 'thumbs_up' or 'thumbs_down'")
    feedback_text: Optional[str] = Field(None, max_length=2000, description="Optional detailed feedback")
    
    class Config:
        json_schema_extra = {
            "example": {
                "conversation_id": "session123_abc12345",
                "created_at": "2025-01-01T12:00:00Z",
                "rating": "thumbs_up",
                "feedback_text": "Very helpful response!"
            }
        }


class FeedbackResponse(BaseModel):
    """Response after submitting feedback"""
    success: bool
    message: str
    conversation_id: str

