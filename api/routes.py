"""
API Routes for Multi-Agent Pipeline (v2)
New endpoints using the multi-agent orchestrator for improved response quality.

Spec Reference: ProjectSpec.md v1.2, Section 5 (Orchestrator)
"""

import logging
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Header, Request as FastAPIRequest, Query
from fastapi.responses import JSONResponse

from models.schemas import (
    PipelineRequest,
    PipelineResponse,
    PipelineContext,
    Citation,
    AgentTrace,
    HealthCheckResponse,
    create_pipeline_context
)
from services.agents.orchestrator import PipelineOrchestrator, ENABLE_STAGE_AGENT
from services.conversation_logger import get_conversation_logger
from services.patient_chat_session_service import (
    get_patient_chat_session_service,
    SessionNotFoundError,
    SessionOwnershipError,
)
from config.pipeline_config import (
    IntentCategory,
    PatientStage,
    SPEC_VERSION,
    INTENT_CATEGORIES,
    PATIENT_STAGES
)
from config.agent_routing import KnowledgeBase
from config.settings import get_settings

logger = logging.getLogger(__name__)


# ================================
# Initialize Pipeline
# ================================

# Singleton orchestrator instance
_orchestrator: Optional[PipelineOrchestrator] = None


def get_orchestrator() -> PipelineOrchestrator:
    """Get or create the pipeline orchestrator singleton."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PipelineOrchestrator(enable_llm_validation=True)
        logger.info("Pipeline orchestrator initialized")
    return _orchestrator


# ================================
# Chat Router (v2 - Multi-Agent Pipeline)
# ================================

pipeline_router = APIRouter(prefix="/chat", tags=["Chat v2 (Multi-Agent Pipeline)"])


@pipeline_router.post("/", response_model=PipelineResponse)
async def chat_v2(
    request: PipelineRequest,
    raw_request: FastAPIRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    include_trace: bool = Query(False, description="Include detailed agent execution trace")
):
    """
    Chat with the AI companion using the multi-agent pipeline (v2).
    
    This endpoint uses a sophisticated multi-agent system that:
    1. **Profile Loading**: Loads patient stage from profile (if authenticated)
    2. **Intent Extraction**: Classifies query into 18 medical categories
    3. **Knowledge Retrieval**: Fetches relevant evidence from appropriate KB
    4. **Specialized Reasoning**: Generates stage-aware, empathetic responses
    5. **Safety Validation**: Ensures responses are safe and compliant
    
    Features over v1:
    - Personalized responses based on user-provided stage
    - More accurate intent classification (18 categories vs 9)
    - Better evidence retrieval with intent-based KB routing
    - Built-in safety guardrails
    - Sign-in prompts for guest users on stage-sensitive queries
    
    Headers (all optional for chat):
    - Authorization: Bearer <token> for signed-in users (loads profile)
    - X-User-ID: optional guest session id (no login required)
    
    Query Parameters:
    - include_trace: Set to true to include detailed agent execution trace
    """
    start_time = time.time()
    
    try:
        # Resolve signed-in user vs guest (guests never require OAuth; see resolve_chat_user_identity)
        user_id, is_guest = resolve_chat_user_identity(authorization, x_user_id)

        chat_session = None
        conversation_history = request.conversation_history

        if not is_guest and user_id:
            session_service = get_patient_chat_session_service()
            try:
                chat_session = await session_service.get_or_create_session(
                    user_id=user_id,
                    session_id=request.session_id,
                )
                conversation_history = await session_service.get_recent_messages(
                    chat_session.session_id
                )
            except SessionNotFoundError:
                raise HTTPException(
                    status_code=404,
                    detail="Chat session not found.",
                )
            except SessionOwnershipError:
                raise HTTPException(
                    status_code=403,
                    detail="You do not have access to this chat session.",
                )

        # Get orchestrator
        orchestrator = get_orchestrator()

        # Process through pipeline with user identity for profile loading
        response = await orchestrator.process(
            message=request.message,
            session_id=chat_session.session_id if chat_session else request.session_id,
            user_id=user_id,
            is_guest=is_guest,
            conversation_history=conversation_history,
            include_trace=include_trace or request.include_trace
        )

        if chat_session:
            session_service = get_patient_chat_session_service()
            intent_value = (
                response.intent.value
                if hasattr(response.intent, "value")
                else str(response.intent)
            )
            await session_service.append_turn(
                session_id=chat_session.session_id,
                user_message=request.message,
                assistant_message=response.response,
                metadata={
                    "intent": intent_value,
                    "request_id": response.request_id,
                },
            )
            response.session_id = chat_session.session_id
        
        # Calculate total latency
        total_latency = int((time.time() - start_time) * 1000)
        response.total_latency_ms = total_latency
        
        # Log conversation (async, non-blocking)
        await _log_conversation(
            request=request,
            response=response,
            user_id=user_id or "anonymous",
            latency_ms=total_latency
        )
        
        # Optionally strip trace info if not requested
        if not include_trace and not request.include_trace:
            response.trace = []
        
        logger.info(
            f"Pipeline completed: intent={response.intent}, "
            f"stage={response.stage}, latency={total_latency}ms, "
            f"abstained={response.abstained}, is_guest={is_guest}, "
            f"needs_onboarding={response.needs_onboarding}"
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing your request. Please try again."
        )


@pipeline_router.post("/stream")
async def chat_v2_stream(
    request: PipelineRequest,
    raw_request: FastAPIRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Stream chat responses from the multi-agent pipeline (v2).
    
    Note: Streaming is not yet implemented. Use the non-streaming endpoint.
    """
    raise HTTPException(
        status_code=501,
        detail="Streaming not yet implemented. Use POST /api/v2/chat/ instead."
    )


@pipeline_router.get("/intents")
async def list_intent_categories():
    """
    List all 18 intent categories the pipeline can classify.
    
    Useful for understanding what types of queries the system handles.
    """
    return {
        "categories": [
            {
                "value": cat.value,
                "label": cat.value.replace("_", " ").title(),
                "description": INTENT_CATEGORIES.get(cat, {}).get("description", "")
            }
            for cat in IntentCategory
        ],
        "count": len(IntentCategory),
        "spec_version": SPEC_VERSION
    }


@pipeline_router.get("/stages")
async def list_patient_stages():
    """
    List all patient stages the pipeline can identify.
    
    Useful for understanding how responses are tailored to patient journey.
    """
    return {
        "stages": [
            {
                "value": stage.value,
                "label": stage.value.replace("_", " ").title(),
                "description": PATIENT_STAGES.get(stage, {}).get("description", "")
            }
            for stage in PatientStage
        ],
        "count": len(PatientStage),
        "spec_version": SPEC_VERSION
    }


# ================================
# Health Router (v2 - Pipeline Health)
# ================================

health_v2_router = APIRouter(prefix="/health", tags=["Health v2"])


@health_v2_router.get("/", response_model=HealthCheckResponse)
async def health_check_v2():
    """
    Check health of the multi-agent pipeline.
    
    Returns status of all agents and knowledge bases.
    """
    try:
        orchestrator = get_orchestrator()
        
        # List available agents
        agents_available = [
            "IntentAgent",
        ]
        if ENABLE_STAGE_AGENT:
            agents_available.append("StageAgent")
        agents_available.extend([
            "RetrievalAgent",
            "ReasoningAgent (18 variants)",
            "ValidatorAgent",
        ])
        
        # List available knowledge bases
        kbs_available = [kb.value for kb in KnowledgeBase]
        
        return HealthCheckResponse(
            status="healthy",
            spec_version=SPEC_VERSION,
            agents_available=agents_available,
            knowledge_bases_available=kbs_available
        )
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return HealthCheckResponse(
            status="unhealthy",
            spec_version=SPEC_VERSION,
            agents_available=[],
            knowledge_bases_available=[]
        )


@health_v2_router.get("/ping")
async def ping_v2():
    """Simple ping endpoint for load balancer health checks."""
    return {
        "status": "ok",
        "api_version": "v2",
        "spec_version": SPEC_VERSION,
        "timestamp": datetime.utcnow().isoformat()
    }


@health_v2_router.get("/detailed")
async def detailed_health_check():
    """
    Detailed health check with individual component status.
    """
    health_status = {
        "overall": "healthy",
        "spec_version": SPEC_VERSION,
        "timestamp": datetime.utcnow().isoformat(),
        "components": {}
    }
    
    # Check Bedrock
    try:
        from config.aws import bedrock
        client = bedrock()
        health_status["components"]["bedrock"] = {
            "status": "healthy",
            "message": "Bedrock client initialized"
        }
    except Exception as e:
        health_status["components"]["bedrock"] = {
            "status": "unhealthy",
            "message": str(e)
        }
        health_status["overall"] = "degraded"
    
    # Check OpenSearch
    try:
        from config.aws import opensearch
        client = opensearch()
        cluster_health = client.cluster.health()
        health_status["components"]["opensearch"] = {
            "status": "healthy" if cluster_health.get("status") != "red" else "unhealthy",
            "message": f"Cluster status: {cluster_health.get('status', 'unknown')}"
        }
    except Exception as e:
        health_status["components"]["opensearch"] = {
            "status": "unhealthy", 
            "message": str(e)
        }
        health_status["overall"] = "degraded"
    
    # Check Pipeline Orchestrator
    try:
        orchestrator = get_orchestrator()
        health_status["components"]["orchestrator"] = {
            "status": "healthy",
            "message": "Pipeline orchestrator ready",
            "llm_validation_enabled": orchestrator.enable_llm_validation
        }
    except Exception as e:
        health_status["components"]["orchestrator"] = {
            "status": "unhealthy",
            "message": str(e)
        }
        health_status["overall"] = "degraded"
    
    return health_status


# ================================
# Debug Router (v2)
# ================================

debug_router = APIRouter(prefix="/debug", tags=["Debug v2"])


@debug_router.post("/analyze")
async def analyze_query(
    request: PipelineRequest,
    raw_request: FastAPIRequest
):
    """
    Analyze a query without generating a full response.
    
    Useful for debugging intent classification and stage identification.
    Returns intent, stage, and retrieval info without full reasoning.
    """
    try:
        from services.agents import IntentAgent
        import asyncio
        
        # Create context
        context = create_pipeline_context(
            message=request.message,
            session_id=request.session_id,
            conversation_history=request.conversation_history
        )
        
        intent_agent = IntentAgent()
        # StageAgent removed - stage comes from profile, not LLM inference
        
        # Run intent agent
        intent_result = await intent_agent.run(context)
        
        analysis = {
            "request_id": context.request_id,
            "message": request.message,
            "timestamp": datetime.utcnow().isoformat(),
            "intent": None,
            "stage": "from_profile",  # Stage now comes from user profile
            "errors": []
        }
        
        # Process intent result
        if isinstance(intent_result, Exception):
            analysis["errors"].append(f"Intent error: {str(intent_result)}")
        else:
            intent_ctx, intent_trace = intent_result
            if intent_ctx.intent_result:
                analysis["intent"] = {
                    "category": intent_ctx.intent_result.intent.value if hasattr(intent_ctx.intent_result.intent, 'value') else str(intent_ctx.intent_result.intent),
                    "confidence": intent_ctx.intent_result.confidence,
                    "reasoning": intent_ctx.intent_result.reasoning,
                    "clarification_needed": intent_ctx.intent_result.clarification_needed,
                    "latency_ms": intent_trace.latency_ms
                }
        
        return analysis
        
    except Exception as e:
        logger.error(f"Analysis error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@debug_router.get("/routing/{intent}")
async def get_intent_routing(intent: str):
    """
    Get routing configuration for a specific intent.
    
    Shows which knowledge bases and model are used for this intent.
    """
    try:
        from config.agent_routing import (
            get_route_for_intent,
            get_knowledge_bases_for_intent,
            get_model_for_intent,
            is_strict_rag
        )
        
        # Parse intent
        try:
            intent_category = IntentCategory(intent.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid intent. Valid intents: {[i.value for i in IntentCategory]}"
            )
        
        route = get_route_for_intent(intent_category)
        
        return {
            "intent": intent_category.value,
            "agent_type": route.agent_type.value,
            "knowledge_bases": [kb.value for kb in route.knowledge_bases],
            "model_type": route.model_type.value,
            "requires_stage": route.requires_stage,
            "strict_rag": route.strict_rag,
            "allow_parallel_kb": route.allow_parallel_kb
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Routing lookup error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ================================
# Helper Functions
# ================================

from typing import Tuple

def resolve_chat_user_identity(
    authorization: Optional[str],
    x_user_id: Optional[str],
) -> Tuple[Optional[str], bool]:
    """
    Resolve user id + guest flag for chat.

    - **Guests** never require OAuth: no Bearer is fine. Optional ``X-User-ID`` for session
      tracking. Fully anonymous requests (no headers) are still allowed as guest.
    - **Signed-in users**: ``Authorization: Bearer <JWT>`` yields ``(uid, is_guest=False)``.
    - **Test bypass** (``IS_AUTHENTICATION_REQUIRED=N``): when there is no Bearer and no
      ``X-User-ID``, assign ``unauthenticated_test_user_id`` so automated tests get a stable id.

    Chat never returns 401 solely for missing auth headers.
    """
    settings = get_settings()
    user_id, is_guest = _extract_user_identity(authorization, x_user_id)

    # Test / integration bypass: synthetic id only when flag is N and request is fully anonymous
    if not settings.chat_authentication_required:
        if user_id is None and not (x_user_id and str(x_user_id).strip()):
            return settings.unauthenticated_test_user_id, True
    return user_id, is_guest


def _extract_user_identity(
    authorization: Optional[str],
    x_user_id: Optional[str]
) -> Tuple[Optional[str], bool]:
    """
    Extract user identity from request headers.
    
    Returns:
        (user_id, is_guest) tuple:
        - For authenticated users: (uid from JWT, False)
        - For guest users with X-User-ID: (guest session id, True)
        - For fully anonymous guest: (None, True)
    """
    logger.info(f"_extract_user_identity called: auth={authorization[:50] if authorization else None}...")
    
    if authorization and authorization.startswith("Bearer "):
        try:
            from config import settings as app_settings

            token = authorization.replace("Bearer ", "")
            logger.info(f"Attempting to decode JWT token (len={len(token)})")
            if app_settings.patient_bearer_legacy_jwt_decode:
                import jwt

                decoded = jwt.decode(token, options={"verify_signature": False})
                logger.info(f"JWT decoded successfully: {list(decoded.keys())}")
                user_id = decoded.get("sub") or decoded.get("user_id") or decoded.get("uid")
                logger.info(f"Extracted user_id: {user_id}")
                if user_id:
                    logger.info(f"Authenticated user from JWT: {user_id}")
                    return (user_id, False)
                logger.warning(f"No user_id found in JWT claims: {decoded}")
            else:
                from services.patient_jwt import get_patient_token_identity

                ident = get_patient_token_identity(token, app_settings)
                if ident:
                    user_id, decoded = ident[0], ident[1]
                    logger.info(f"JWT decoded successfully: {list(decoded.keys())}")
                    logger.info(f"Authenticated user from JWT: {user_id}")
                    return (user_id, False)
                logger.warning("No user_id found or token not accepted")
        except Exception as jwt_error:
            logger.warning(f"Could not decode JWT: {jwt_error}")
    else:
        logger.info(f"No valid Bearer token found (auth={authorization})")
    
    # Guest: optional X-User-ID for session tracking (no OAuth required)
    if x_user_id and str(x_user_id).strip():
        gid = str(x_user_id).strip()
        logger.debug(f"Guest user with session ID: {gid}")
        return (gid, True)

    return (None, True)


def _extract_user_id(
    raw_request: FastAPIRequest,
    authorization: Optional[str],
    x_user_id: Optional[str],
    request: PipelineRequest
) -> str:
    """Extract user ID from request headers (legacy - for logging)."""
    if authorization and authorization.startswith("Bearer "):
        try:
            from config import settings as app_settings

            token = authorization.replace("Bearer ", "")
            if app_settings.patient_bearer_legacy_jwt_decode:
                import jwt

                decoded = jwt.decode(token, options={"verify_signature": False})
                user_id = decoded.get("sub") or decoded.get("email") or decoded.get("user_id")
                logger.debug(f"Authenticated user from JWT: {user_id}")
                return user_id or "oauth_user"
            else:
                from services.patient_jwt import get_patient_token_identity

                ident = get_patient_token_identity(token, app_settings)
                if ident:
                    user_id = ident[0]
                    logger.debug(f"Authenticated user from JWT: {user_id}")
                    return user_id
        except Exception as jwt_error:
            logger.warning(f"Could not decode JWT: {jwt_error}")
        return "oauth_user"
    elif x_user_id:
        logger.debug(f"Guest user from X-User-ID header: {x_user_id}")
        return x_user_id
    else:
        return "anonymous"



async def _log_conversation(
    request: PipelineRequest,
    response: PipelineResponse,
    user_id: str,
    latency_ms: int
):
    """Log conversation to DynamoDB (non-blocking)."""
    try:
        conversation_logger = get_conversation_logger()
        
        # Map intent to query category for backward compatibility
        query_category = response.intent if isinstance(response.intent, str) else response.intent.value
        
        log_result = await conversation_logger.log_conversation(
            session_id=request.session_id or response.request_id,
            user_id=user_id,
            question=request.message,
            answer=response.response,
            query_category=query_category,
            index_name="multi_agent_pipeline",
            strict_mode=True,  # Pipeline always uses evidence
            has_sufficient_evidence=not response.abstained,
            confidence_score=response.confidence,
            response_time_ms=latency_ms,
            sources=[
                {"title": c.source_file, "score": c.relevance_score}
                for c in response.citations
            ]
        )
        
        if log_result:
            logger.debug(f"Conversation logged: {log_result.get('conversation_id')}")
            
    except Exception as log_error:
        logger.warning(f"Failed to log conversation (non-fatal): {log_error}")
