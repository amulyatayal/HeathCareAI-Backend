"""
Chat API Routes
Provides endpoints for chat, feedback, and session management
"""

import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Header, Request as FastAPIRequest
from fastapi.responses import JSONResponse

from models.schemas_rag import (
    ChatRequest, ChatResponse,
    FeedbackRequest, FeedbackResponse
)
from services.ai_agent import chat_with_agent, SessionManager
from services.conversation_logger import get_conversation_logger
from config import settings

logger = logging.getLogger(__name__)


# ================================
# Chat Router
# ================================

chat_router = APIRouter(prefix="/chat", tags=["Chat"])


@chat_router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    raw_request: FastAPIRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Chat with the breast cancer companion AI agent.
    
    Send a message and receive an empathetic, informative response
    backed by medical knowledge base.
    
    Authentication (via headers):
    - Authorization: Bearer <token> for Google OAuth users
    - X-User-ID: guest_xxx for guest users
    
    Options:
    - index_name: Get available indexes from GET /api/v1/knowledge/indexes
    - strict_mode: True = only knowledge base answers, False = general AI with KB context
    
    Returns conversation_id for feedback submission.
    """
    try:
        # Extract user_id from headers
        # Debug: Log ALL received headers
        all_headers = dict(raw_request.headers)
        logger.info(f"ALL Headers received: {all_headers}")
        logger.info(f"Parsed - Authorization: {authorization}, X-User-ID: {x_user_id}")
        
        user_id = None
        if authorization and authorization.startswith("Bearer "):
            # Google OAuth - decode JWT to get user info
            token = authorization.replace("Bearer ", "")
            try:
                import jwt
                # Decode without verification for user extraction (verification done by frontend)
                decoded = jwt.decode(token, options={"verify_signature": False})
                user_id = decoded.get("sub") or decoded.get("email") or decoded.get("user_id")
                logger.info(f"Authenticated user from JWT: {user_id}")
            except Exception as jwt_error:
                logger.warning(f"Could not decode JWT: {jwt_error}")
                user_id = "oauth_user"
        elif x_user_id:
            # Guest user with X-User-ID header
            user_id = x_user_id
            logger.info(f"Guest user from X-User-ID header: {user_id}")
        else:
            # Fallback to request body or anonymous
            user_id = request.user_id or "anonymous"
            logger.info(f"Fallback user_id: {user_id} (from request body: {request.user_id})")
        
        response = await chat_with_agent(
            message=request.message,
            session_id=request.session_id,
            user_id=user_id,
            include_sources=request.include_sources,
            index_name=request.index_name,
            use_strict_rag=request.strict_mode
        )
        
        # Log conversation to DynamoDB (async, non-blocking)
        try:
            conversation_logger = get_conversation_logger()
            log_result = await conversation_logger.log_conversation(
                session_id=response.session_id,
                user_id=user_id,
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
