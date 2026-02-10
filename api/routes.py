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
from services.agents.orchestrator import PipelineOrchestrator
from services.conversation_logger import get_conversation_logger
from config.pipeline_config import (
    IntentCategory,
    PatientStage,
    SPEC_VERSION,
    INTENT_CATEGORIES,
    PATIENT_STAGES
)
from config.agent_routing import KnowledgeBase

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
# V2.1 Verification Question Handler
# ================================

async def _handle_v2_1_verification(
    response: PipelineResponse,
    message: str,
    user_id: Optional[str]
) -> PipelineResponse:
    """
    Handle V2.1 verification questions and user confirmations/rejections.
    
    Features:
    - Inject verification questions when stage confirmation is detected
    - Handle user confirmations and update profile with granular stage data
    - Handle user rejections and allow re-classification
    - Loop prevention via metadata tracking
    """
    import re
    from services.patient_stage_service import get_patient_stage_service
    from services.patient_profile_service import get_patient_profile_service
    from services.profile_service_v2_1 import update_stage_with_metadata
    
    # PHASE 1: Check if user is responding to previous verification
    if hasattr(response, 'metadata') and response.metadata:
        pending_verification = response.metadata.get('verification_asked_for_stage')
        
        if pending_verification and message:
            message_lower = message.lower()
            
            # Check for CONFIRMATION keywords
            confirmation_keywords = ['yes', 'correct', 'confirmed', 'confirm', 'right', 
                                    'exactly', 'yep', 'yeah', "that's right", 'absolutely']
            is_confirmed = any(keyword in message_lower for keyword in confirmation_keywords)
            
            # Check for REJECTION keywords
            rejection_keywords = ['no', 'not right', 'incorrect', 'wrong', 'not correct', 
                                 "that's not", 'nope', 'negative']
            is_rejected = any(keyword in message_lower for keyword in rejection_keywords)
            
            if is_confirmed and user_id:
                logger.info(f"[V2.1] ✅ User CONFIRMED stage {pending_verification}")
                
                try:
                    profile_service = get_patient_profile_service()
                    stage_service = get_patient_stage_service()
                    
                    # Get stage details
                    stage_obj = stage_service.get_stage_by_id(pending_verification)
                    
                    if stage_obj:
                        # Get ROOT stage name
                        root_id = pending_verification.split('.')[0]
                        root_stage = stage_service.get_stage_by_id(root_id)
                        root_name = root_stage.name if root_stage else "Unknown Phase"
                        
                        # Map granular → broad enum
                        stage_map = {
                            '0': PatientStage.PRE_DIAGNOSIS,
                            '1': PatientStage.NEWLY_DIAGNOSED,
                            '2': PatientStage.ACTIVE_TREATMENT,
                            '3': PatientStage.ACTIVE_TREATMENT,
                            '4': PatientStage.ACTIVE_TREATMENT,
                            '5': PatientStage.SURVEILLANCE,
                            '6': PatientStage.ACTIVE_TREATMENT,
                            '7': PatientStage.ACTIVE_TREATMENT,
                            '8': PatientStage.ACTIVE_TREATMENT,
                            '9': PatientStage.ACTIVE_TREATMENT,
                            '10': PatientStage.ACTIVE_TREATMENT,
                        }
                        broad_stage = stage_map.get(root_id, PatientStage.ACTIVE_TREATMENT)
                        
                        # Update profile with existing V2.1 method
                        await update_stage_with_metadata(
                            profile_service=profile_service,
                            user_id=user_id,
                            new_stage=broad_stage,
                            new_detailed_stage_id=pending_verification,
                            metadata={
                                'source': 'verification',
                                'certainty': 'HIGH',
                                'user_confirmed': True,
                                'treatment_type': stage_obj.name,
                                'transition_notes': 'Confirmed via verification questions'
                            }
                        )
                        
                        # Also update label field
                        profile = await profile_service.get_profile(user_id)
                        profile.detailed_stage_label = stage_obj.name
                        await profile_service.update_profile(profile)
                        
                        logger.info(
                            f"[V2.1] ✅ Updated profile: broad={broad_stage.value}, "
                            f"detailed_id={pending_verification}, label={stage_obj.name}"
                        )
                        
                        # Update response
                        response.response = (
                            f"✅ Great! I've updated your profile to **{stage_obj.name}** "
                            f"({root_name}). {response.response}"
                        )
                
                except Exception as e:
                    logger.error(f"[V2.1] Profile update failed: {e}")
                
                # Clear verification state
                response.metadata['verification_asked_for_stage'] = None
            
            elif is_rejected:
                logger.info(f"[V2.1] ❌ User REJECTED stage {pending_verification}")
                
                # Clear verification state
                response.metadata['verification_asked_for_stage'] = None
                
                # Add acknowledgment
                response.response = "Thanks for letting me know! " + response.response
    
    # PHASE 2: Inject verification questions if stage confirmation detected
    if hasattr(response, 'response') and response.response:
        if "It sounds like you might be in the" in response.response and "Is that correct?" in response.response:
            try:
                logger.info("[V2.1] Pattern matched - stage confirmation detected!")
                
                # Extract granular_stage_id from metadata
                stage_id = None
                if hasattr(response, 'metadata') and isinstance(response.metadata, dict):
                    stage_id = response.metadata.get('granular_stage_id')
                    if stage_id:
                        logger.info(f"[V2.1] ✅ Found granular_stage_id: {stage_id}")
                
                if stage_id:
                    stage_service = get_patient_stage_service()
                    stage = stage_service.get_stage_by_id(stage_id)
                    
                    if stage and stage.verification_questions:
                        # Format ALL questions
                        if len(stage.verification_questions) > 1:
                            formatted_questions = "\n".join(
                                f"{i+1}. {q}" 
                                for i, q in enumerate(stage.verification_questions)
                            )
                            vq = f"To confirm, please answer:\n{formatted_questions}"
                            logger.info(f"[V2.1] Formatted {len(stage.verification_questions)} questions")
                        else:
                            vq = stage.verification_questions[0]
                            logger.info(f"[V2.1] Using single question")
                        
                        # Replace "Is that correct?" with verification questions
                        response.response = re.sub(
                            r'Is that correct\?',
                            vq,
                            response.response
                        )
                        
                        # Track that we asked
                        response.metadata['verification_asked_for_stage'] = stage_id
                        logger.info(f"[V2.1] ✅ Injected verification questions for stage {stage_id}")
                    
            except Exception as e:
                logger.error(f"[V2.1] Verification injection failed: {e}")
    
    return response


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
    
    Headers:
    - Authorization: Bearer <token> for authenticated users
    - X-User-ID: guest_xxx for guest users
    
    Query Parameters:
    - include_trace: Set to true to include detailed agent execution trace
    """
    start_time = time.time()
    
    try:
        # Extract user identity from headers
        user_id, is_guest = _extract_user_identity(authorization, x_user_id)
        
        # Get orchestrator
        orchestrator = get_orchestrator()
        
        # Process through pipeline with user identity for profile loading
        response = await orchestrator.process(
            message=request.message,
            session_id=request.session_id,
            user_id=user_id,
            is_guest=is_guest,
            conversation_history=request.conversation_history,
            include_trace=include_trace or request.include_trace
        )
        
        # ============================================================
        # V2.1: Inject verification questions and handle confirmations
        # ============================================================
        response = await _handle_v2_1_verification(
            response=response,
            message=request.message,
            user_id=user_id
        )
        
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
            "StageAgent", 
            "RetrievalAgent",
            "ReasoningAgent (18 variants)",
            "ValidatorAgent"
        ]
        
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

def _extract_user_identity(
    authorization: Optional[str],
    x_user_id: Optional[str]
) -> Tuple[Optional[str], bool]:
    """
    Extract user identity from request headers.
    
    Returns:
        (user_id, is_guest) tuple:
        - For authenticated users: (firebase_uid, False)
        - For guest users: (None, True)
    """
    logger.info(f"_extract_user_identity called: auth={authorization[:50] if authorization else None}...")
    
    if authorization and authorization.startswith("Bearer "):
        try:
            import jwt
            token = authorization.replace("Bearer ", "")
            logger.info(f"Attempting to decode JWT token (len={len(token)})")
            decoded = jwt.decode(token, options={"verify_signature": False})
            logger.info(f"JWT decoded successfully: {list(decoded.keys())}")
            user_id = decoded.get("sub") or decoded.get("user_id") or decoded.get("uid")
            logger.info(f"Extracted user_id: {user_id}")
            if user_id:
                logger.info(f"Authenticated user from JWT: {user_id}")
                return (user_id, False)
            else:
                logger.warning(f"No user_id found in JWT claims: {decoded}")
        except Exception as jwt_error:
            logger.warning(f"Could not decode JWT: {jwt_error}")
    else:
        logger.info(f"No valid Bearer token found (auth={authorization})")
    
    # Guest user (X-User-ID is for session tracking, not profile)
    if x_user_id:
        logger.debug(f"Guest user with session ID: {x_user_id}")
    
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
            import jwt
            token = authorization.replace("Bearer ", "")
            decoded = jwt.decode(token, options={"verify_signature": False})
            user_id = decoded.get("sub") or decoded.get("email") or decoded.get("user_id")
            logger.debug(f"Authenticated user from JWT: {user_id}")
            return user_id or "oauth_user"
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
