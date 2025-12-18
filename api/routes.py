"""
API Routes for Healthcare Companion Backend
Provides endpoints for chat, knowledge base, and health checks
"""

import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse

from models.schemas import (
    ChatRequest, ChatResponse,
    KnowledgeSearchRequest, KnowledgeSearchResponse,
    KnowledgeDocument, DocumentUploadResponse,
    HealthCheckResponse, ServiceHealth,
    QueryCategory, ContentType,
    FeedbackRequest, FeedbackResponse
)
from services.ai_agent import chat_with_agent, SessionManager
from services.knowledge_base import get_knowledge_base
from services.conversation_logger import get_conversation_logger
from config import settings

logger = logging.getLogger(__name__)


# ================================
# Chat Router
# ================================

chat_router = APIRouter(prefix="/chat", tags=["Chat"])


@chat_router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Chat with the breast cancer companion AI agent.
    
    Send a message and receive an empathetic, informative response
    backed by medical knowledge base.
    
    Options:
    - index_name: Get available indexes from GET /api/v1/knowledge/indexes
    - strict_mode: True = only knowledge base answers, False = general AI with KB context
    
    Returns conversation_id for feedback submission.
    """
    try:
        response = await chat_with_agent(
            message=request.message,
            session_id=request.session_id,
            user_id=request.user_id,
            include_sources=request.include_sources,
            index_name=request.index_name,
            use_strict_rag=request.strict_mode
        )
        
        # Log conversation to DynamoDB (async, non-blocking)
        try:
            conversation_logger = get_conversation_logger()
            log_result = await conversation_logger.log_conversation(
                session_id=response.session_id,
                user_id=request.user_id,
                question=request.message,
                answer=response.answer,
                query_category=response.query_category.value,
                index_name=request.index_name or "breast_cancer_knowledge",
                strict_mode=request.strict_mode,
                has_sufficient_evidence=response.has_sufficient_evidence,
                confidence_score=response.confidence_score,
                response_time_ms=response.response_time_ms,
                sources=[{"title": s.title, "score": s.relevance_score} for s in response.sources]
            )
            
            # Add conversation tracking to response for feedback
            if log_result:
                response.conversation_id = log_result["conversation_id"]
                # Convert milliseconds to ISO timestamp
                from datetime import datetime
                created_at_ms = log_result["created_at"]
                iso_timestamp = datetime.utcfromtimestamp(created_at_ms / 1000).isoformat() + "Z"
                response.conversation_created_at = iso_timestamp
                response.timestamp = iso_timestamp
            
        except Exception as log_error:
            logger.warning(f"Failed to log conversation (non-fatal): {log_error}")
        
        return response
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing your request. Please try again."
        )


@chat_router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest):
    """
    Submit feedback for a conversation.
    
    Use the conversation_id and conversation_created_at from the chat response.
    Rating should be 'thumbs_up' or 'thumbs_down'.
    """
    try:
        # Validate rating
        if request.rating not in ["thumbs_up", "thumbs_down"]:
            raise HTTPException(
                status_code=400,
                detail="Rating must be 'thumbs_up' or 'thumbs_down'"
            )
        
        # Convert ISO timestamp to milliseconds for DynamoDB
        from datetime import datetime, timezone
        try:
            # Parse ISO format and treat as UTC
            iso_str = request.created_at.replace("Z", "")
            dt = datetime.fromisoformat(iso_str).replace(tzinfo=timezone.utc)
            created_at_ms = int(dt.timestamp() * 1000)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid timestamp format. Expected ISO format (e.g., 2025-01-01T12:00:00Z)"
            )
        
        conversation_logger = get_conversation_logger()
        success = await conversation_logger.update_feedback(
            conversation_id=request.conversation_id,
            created_at=created_at_ms,
            feedback_rating=request.rating,
            feedback_text=request.feedback_text
        )
        
        if success:
            return FeedbackResponse(
                success=True,
                message="Thank you for your feedback!",
                conversation_id=request.conversation_id
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to save feedback"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Feedback error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Error submitting feedback"
        )


@chat_router.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """Clear a chat session and its history"""
    SessionManager.clear_session(session_id)
    return {"message": "Session cleared successfully", "session_id": session_id}


# ================================
# Knowledge Base Router
# ================================

knowledge_router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


@knowledge_router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge_base(request: KnowledgeSearchRequest):
    """
    Search the medical knowledge base.
    
    Uses keyword search to find relevant information about breast cancer.
    """
    try:
        kb = get_knowledge_base(use_vectors=False)  # Keyword search for SEARCH collections
        response = await kb.search(
            query=request.query,
            category=request.category,
            content_type=request.content_type,
            limit=request.limit
        )
        return response
        
    except Exception as e:
        logger.error(f"Knowledge search error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Error searching knowledge base"
        )


@knowledge_router.post("/document", response_model=DocumentUploadResponse)
async def add_document(document: KnowledgeDocument):
    """
    Add a document to the knowledge base.
    
    Documents are indexed for keyword search.
    """
    try:
        kb = get_knowledge_base(use_vectors=False)
        doc_id = await kb.add_document(document)
        
        return DocumentUploadResponse(
            document_id=doc_id,
            title=document.title,
            status="indexed",
            chunks_created=1,  # Will be updated when chunking is implemented
            message="Document successfully added to knowledge base"
        )
        
    except Exception as e:
        logger.error(f"Document upload error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Error adding document to knowledge base"
        )


@knowledge_router.delete("/document/{document_id}")
async def delete_document(document_id: str):
    """Delete a document from the knowledge base"""
    try:
        kb = get_knowledge_base(use_vectors=False)
        success = await kb.delete_document(document_id)
        
        if success:
            return {"message": "Document deleted successfully", "document_id": document_id}
        else:
            raise HTTPException(status_code=404, detail="Document not found")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document deletion error: {e}")
        raise HTTPException(status_code=500, detail="Error deleting document")


@knowledge_router.get("/stats")
async def get_knowledge_stats():
    """Get knowledge base statistics"""
    try:
        kb = get_knowledge_base(use_vectors=False)
        stats = await kb.get_stats()
        return stats
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail="Error getting statistics")


@knowledge_router.get("/indexes")
async def list_available_indexes():
    """
    List all available knowledge base indexes from OpenSearch.
    
    Returns index names and document counts for UI selection.
    """
    try:
        from config.aws import get_opensearch_client
        client = get_opensearch_client()
        
        # Get all indexes (excluding system indexes starting with '.')
        indices = client.cat.indices(format='json')
        
        available_indexes = []
        for idx in indices:
            index_name = idx.get('index', '')
            # Skip system/hidden indexes
            if index_name.startswith('.'):
                continue
            
            # Get document count
            doc_count = int(idx.get('docs.count', 0))
            
            # Create display name from index name
            display_name = index_name.replace('_', ' ').replace('-', ' ').title()
            
            # Add description based on index name pattern
            if 'qa' in index_name.lower():
                description = "Pre-generated Q&A pairs from medical documents"
            elif 'knowledge' in index_name.lower():
                description = "Document chunks from medical leaflets"
            else:
                description = "Medical knowledge base"
            
            available_indexes.append({
                "index_name": index_name,
                "display_name": display_name,
                "description": description,
                "document_count": doc_count,
                "status": idx.get('health', 'unknown')
            })
        
        # Sort by document count (descending)
        available_indexes.sort(key=lambda x: x['document_count'], reverse=True)
        
        return {
            "indexes": available_indexes,
            "count": len(available_indexes)
        }
        
    except Exception as e:
        logger.error(f"Error listing indexes: {e}")
        raise HTTPException(status_code=500, detail="Error listing available indexes")


# ================================
# Health Check Router
# ================================

health_router = APIRouter(prefix="/health", tags=["Health"])


@health_router.get("/", response_model=HealthCheckResponse)
async def health_check():
    """
    Check the health of all services.
    
    Returns status of Bedrock, OpenSearch, and other dependencies.
    """
    services = []
    overall_status = "healthy"
    
    # Check Bedrock
    try:
        from config.aws import bedrock
        client = bedrock()
        services.append(ServiceHealth(
            name="bedrock",
            status="healthy",
            message="Bedrock client initialized"
        ))
    except Exception as e:
        services.append(ServiceHealth(
            name="bedrock",
            status="unhealthy",
            message=str(e)
        ))
        overall_status = "degraded"
    
    # Check OpenSearch
    try:
        from config.aws import opensearch
        client = opensearch()
        # Try a simple health check
        health = client.cluster.health()
        services.append(ServiceHealth(
            name="opensearch",
            status="healthy" if health.get("status") != "red" else "unhealthy",
            message=f"Cluster status: {health.get('status', 'unknown')}"
        ))
    except Exception as e:
        services.append(ServiceHealth(
            name="opensearch",
            status="unhealthy",
            message=str(e)
        ))
        overall_status = "degraded"
    
    # Check S3
    try:
        from config.aws import s3
        client = s3()
        services.append(ServiceHealth(
            name="s3",
            status="healthy",
            message="S3 client initialized"
        ))
    except Exception as e:
        services.append(ServiceHealth(
            name="s3",
            status="unhealthy",
            message=str(e)
        ))
        overall_status = "degraded"
    
    return HealthCheckResponse(
        status=overall_status,
        version="1.0.0",
        services=services,
        timestamp=datetime.utcnow()
    )


@health_router.get("/ping")
async def ping():
    """Simple ping endpoint for load balancer health checks"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ================================
# Categories Router
# ================================

categories_router = APIRouter(prefix="/categories", tags=["Categories"])


@categories_router.get("/query")
async def get_query_categories():
    """Get available query categories"""
    return {
        "categories": [
            {"value": cat.value, "label": cat.value.replace("_", " ").title()}
            for cat in QueryCategory
        ]
    }


@categories_router.get("/content")
async def get_content_types():
    """Get available content types"""
    return {
        "content_types": [
            {"value": ct.value, "label": ct.value.replace("_", " ").title()}
            for ct in ContentType
        ]
    }

