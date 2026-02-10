"""
Pipeline Orchestrator
Coordinates all agents with maximum parallelization for optimal latency.

Spec Reference: ProjectSpec.md v1.2, Section 5
"""

import asyncio
import time
import logging
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime

from services.agents.base_agent import BaseAgent
from services.agents.intent_agent import IntentAgent
from services.agents.stage_agent_v2 import StageAgentV2
from services.agents.retrieval_agent import RetrievalAgent
from services.agents.video_retrieval_agent import VideoRetrievalAgent
from services.agents.reasoning_agent import get_reasoning_agent
from services.agents.validator_agent import ValidatorAgent
from services.patient_profile_service import get_patient_profile_service
from services.patient_stage_service import get_patient_stage_service
from models.schemas import (
    PipelineContext,
    PipelineResponse,
    AgentTrace,
    AgentStatus,
    SuggestedVideo,
    StageResult,
    ModificationProposal,
    create_pipeline_context
)
from config.pipeline_config import IntentCategory, PatientStage, CertaintyLevel, SPEC_VERSION
from config.agent_routing import is_citation_only
from config.settings import settings
from services.metrics import record_latency, record_count

logger = logging.getLogger(__name__)


# Stage-sensitive intents that benefit from personalization
STAGE_SENSITIVE_INTENTS = [
    IntentCategory.SURGERY_PROCEDURES,
    IntentCategory.SIDE_EFFECTS,
    IntentCategory.MEDICATION_INFO,
    IntentCategory.POST_SURGERY_RECOVERY,
    IntentCategory.CANCER_TREATMENT,
    IntentCategory.EMOTIONAL_SUPPORT,
    IntentCategory.STATISTICS,
]

# Sign-in suggestion message (Option C - in-response)
SIGN_IN_SUGGESTION = (
    "\n\n---\n"
    "*💡 For more personalized guidance based on your treatment stage, "
    "[sign in to your account](/login).*"
)


class PipelineOrchestrator:
    """
    Orchestrates the multi-agent pipeline with maximum parallelization.
    
    Pipeline Flow (optimized):
    
    ┌─────────────────────────────────────────────────────────┐
    │  PHASE 1: Classification (PARALLEL)                     │
    │  ┌──────────┐   ┌──────────┐                           │
    │  │  Intent  │   │  Stage   │  ← Run simultaneously     │
    │  │  Agent   │   │  Agent   │                           │
    │  └────┬─────┘   └────┬─────┘                           │
    │       └──────┬───────┘                                  │
    └──────────────┼──────────────────────────────────────────┘
                   ▼
    ┌─────────────────────────────────────────────────────────┐
    │  PHASE 2: Retrieval (PARALLEL)                          │
    │  ┌──────────────┐   ┌─────────────────┐                │
    │  │  Retrieval   │   │ VideoRetrieval  │                │
    │  │    Agent     │   │     Agent       │ ← YouTube KB   │
    │  └──────┬───────┘   └────────┬────────┘                │
    │         └────────┬───────────┘                          │
    └──────────────────┼──────────────────────────────────────┘
              ▼
    ┌─────────────────────────────────────────────────────────┐
    │  PHASE 3: Reasoning                                     │
    │  ┌──────────────┐                                       │
    │  │  Reasoning   │  ← Dynamically selected based on      │
    │  │    Agent     │    intent (18 specialized agents)     │
    │  └──────┬───────┘                                       │
    └─────────┼───────────────────────────────────────────────┘
              ▼
    ┌─────────────────────────────────────────────────────────┐
    │  PHASE 4: Validation (Future)                           │
    │  ┌──────────────┐                                       │
    │  │  Validator   │  ← Safety checks and guardrails       │
    │  │    Agent     │                                       │
    │  └──────────────┘                                       │
    └─────────────────────────────────────────────────────────┘
    """
    
    def __init__(self, enable_llm_validation: bool = True):  # LLM validation ON by default (uses Haiku)
        # Initialize reusable agents
        self.intent_agent = IntentAgent()
        self.stage_agent = StageAgentV2()
        self.retrieval_agent = RetrievalAgent()
        self.video_retrieval_agent = VideoRetrievalAgent()  # YouTube video retrieval
        self.validator_agent = ValidatorAgent(use_llm_validation=enable_llm_validation)
        # Reasoning agents are created on-demand via factory
        
        self._traces: List[AgentTrace] = []
        self._current_request_id: Optional[str] = None
    
    async def process(
        self,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        is_guest: bool = True,
        conversation_history: Optional[List[dict]] = None,
        include_trace: bool = False
    ) -> PipelineResponse:
        """
        Process a user message through the full pipeline.
        
        Args:
            message: User's question/message
            session_id: Optional session ID for tracking
            user_id: Firebase UID if authenticated (None for guests)
            is_guest: Whether user is a guest (no profile features)
            conversation_history: Previous conversation messages
            include_trace: Whether to include debug trace in response
            
        Returns:
            PipelineResponse with final answer and metadata
        """
        start_time = time.time()
        self._traces = []
        
        # Create pipeline context
        ctx = create_pipeline_context(
            message=message,
            session_id=session_id,
            conversation_history=conversation_history or []
        )
        self._current_request_id = ctx.request_id
        
        logger.info(f"Pipeline started: request_id={ctx.request_id}")
        self._log_step(
            step_name="pipeline_start",
            agent_name="orchestrator",
            input_summary=message[:200],
            output_summary="",
            latency_ms=0,
            model_used=None,
            safety_flags=[],
        )
        
        try:
            # ============================================
            # PHASE 0: Load Profile (if authenticated)
            # ============================================
            needs_onboarding = False
            profile = None
            
            if user_id and not is_guest:
                # Authenticated user - load profile for stage
                profile_service = get_patient_profile_service()
                profile = await profile_service.get_profile(user_id)
                
                if profile and profile.onboarding_completed:
                    # Use user-provided stage (HIGH certainty)
                    ctx.stage_result = StageResult(
                        stage=profile.current_stage,
                        certainty=CertaintyLevel.HIGH,
                        certainty_score=1.0,
                        signals=["User-provided via onboarding"]
                    )
                    logger.info(f"Loaded stage from profile: {profile.current_stage}")
                else:
                    # Authenticated but no profile - prompt for onboarding
                    ctx.stage_result = StageResult(
                        stage=PatientStage.UNKNOWN,
                        certainty=CertaintyLevel.LOW,
                        certainty_score=0.0,
                        signals=["Onboarding not completed"]
                    )
                    needs_onboarding = True
                    logger.info(f"User {user_id} needs onboarding")
            else:
                # Guest user - using UNKNOWN stage
                ctx.stage_result = StageResult(
                    stage=PatientStage.UNKNOWN,
                    certainty=CertaintyLevel.LOW,
                    certainty_score=0.0,
                    signals=["Guest user"]
                )
                logger.debug("Guest user - using UNKNOWN stage")
            
            # ============================================
            # PHASE 1: Classification (Parallel)
            # Intent + Stage (Inferred)
            # ============================================
            ctx = await self._run_classification_phase(ctx)
            
            # ============================================
            # PHASE 1.5: Pathway Proposals (Chat-Based)
            # ============================================
            modification_proposal = None
            stage_update_message = None
            
            if user_id and not is_guest and profile:
                inferred = ctx.stage_result
                inferred_stage_id = ctx.metadata.get("granular_stage_id")
                
                # Check for High Certainty Mismatch
                if (inferred and inferred.stage != PatientStage.UNKNOWN and 
                    inferred.stage != profile.current_stage and 
                    inferred.certainty == CertaintyLevel.HIGH):
                    
                    # 1. Loop Prevention: Did we just ask about this?
                    # Check last system message in history
                    last_was_proposal = False
                    if conversation_history:
                        last_msg = conversation_history[-1]
                        if last_msg.get("role") == "assistant" and "Is that correct?" in last_msg.get("content", ""):
                            last_was_proposal = True
                    
                    # 2. Logic
                    if last_was_proposal:
                        # We asked -> User responded.
                        # Check if response is positive confirmation
                        # Allow "yes" at the beginning of longer messages like "yes, I am asking about..."
                        clean_msg = message.strip().lower()
                        confirmation_words = ['yes', 'yeah', 'yep', 'correct', 'that\'s right', 'sure', 'right']
                        is_confirmation = any(clean_msg.startswith(word) for word in confirmation_words)
                        
                        if is_confirmation:
                            # EXECUTE UPDATE
                            logger.info(f"User confirmed stage change to {inferred.stage}. Updating profile.")
                            profile_service = get_patient_profile_service()
                            
                            # Use granular ID if available, else broad
                            target_id = inferred_stage_id if inferred_stage_id else "0" # Fallback? 
                            # If inferred.stage is broad enum, we can't map back easily without granular ID.
                            # StageAgentV2 metadata has granular_id.
                            
                            if inferred_stage_id:
                                # Look up granular stage name from hierarchy
                                stage_service = get_patient_stage_service()
                                stage_obj = stage_service.get_stage_by_id(inferred_stage_id)
                                friendly_name = stage_obj.name if stage_obj else str(inferred.stage)
                                
                                # Update BOTH fields in database to prevent repeated prompts
                                # 1. Update broad stage (current_stage) - this is what users see
                                await profile_service.update_stage(user_id, inferred.stage)
                                
                                # 2. Update detailed stage (detailed_stage_id) - for internal granular tracking and RAG
                                await profile_service.update_stage_detailed(user_id, inferred_stage_id)
                                
                                stage_update_message = f"Thanks, I've updated your stage to **{friendly_name}**."
                                logger.info(f"Setting stage_update_message: {stage_update_message}")
                                
                                # To preserve context, use the PREVIOUS user message for RAG
                                # Extract the last user message from conversation history (before "yes")
                                if conversation_history and len(conversation_history) >= 2:
                                    # Find the last user message before the current one
                                    for i in range(len(conversation_history) - 1, -1, -1):
                                        if conversation_history[i].get("role") == "user":
                                            original_question = conversation_history[i].get("content", "")
                                            if original_question and original_question.strip().lower() not in confirmation_words:
                                                logger.info(f"Using original question for context: {original_question}")
                                                # Update the context to use the original question
                                                ctx = PipelineContext(
                                                    request_id=ctx.request_id,
                                                    user_message=original_question,
                                                    conversation_history=conversation_history,
                                                    session_id=ctx.session_id,
                                                    user_id=ctx.user_id,
                                                    metadata=ctx.metadata
                                                )
                                                # Re-run classification with the original question
                                                ctx = await self._run_classification_phase(ctx)
                                                break
                                
                                # Continue processing strictly with NEW stage (which is already in ctx)
                            else:
                                logger.warning("Granular ID missing for update")
                                # Skip update if no ID
                        else:
                            # User ignored or negated.
                            # REVERT to Profile Stage to respect user choice.
                            logger.info("User ignored/negated stage proposal. Reverting context to Profile Stage.")
                            ctx.stage_result = StageResult(
                                stage=profile.current_stage,
                                certainty=CertaintyLevel.HIGH,
                                certainty_score=1.0,
                                signals=["User ignored proposal"]
                            )
                            # Do NOT ask again.
                    else:
                        # We haven't asked yet.
                        # STOP PIPELINE. Ask Confirmation.
                        # Look up granular stage name from hierarchy for specific, patient-friendly prompt
                        proposed_name = None
                        if inferred_stage_id:
                            stage_service = get_patient_stage_service()
                            stage_obj = stage_service.get_stage_by_id(inferred_stage_id)
                            if stage_obj:
                                proposed_name = stage_obj.name
                        
                        # Fallback to broad category if granular lookup fails
                        if not proposed_name:
                            stage_display_names = {
                                PatientStage.PRE_DIAGNOSIS: "Pre-Diagnosis",
                                PatientStage.AWAITING_RESULTS: "Awaiting Results",
                                PatientStage.NEWLY_DIAGNOSED: "Newly Diagnosed",
                                PatientStage.ACTIVE_TREATMENT: "Active Treatment",
                                PatientStage.POST_TREATMENT: "Post-Treatment",
                                PatientStage.SURVEILLANCE: "Surveillance",
                                PatientStage.PALLIATIVE_SUPPORT: "Palliative Support",
                                PatientStage.UNKNOWN: "Unknown"
                            }
                            proposed_name = stage_display_names.get(inferred.stage, str(inferred.stage))
                        
                        logger.info(f"Proposing stage change: {profile.current_stage} -> {proposed_name}")
                        
                        # Return clarifications-style response
                        total_latency = int((time.time() - start_time) * 1000)
                        return PipelineResponse(
                            request_id=ctx.request_id,
                            response=f"It sounds like you might be in the **{proposed_name}** stage based on what you said. Is that correct?",
                            intent=ctx.intent_result.intent,
                            stage=ctx.stage_result.stage,
                            citations=[],
                            confidence=1.0, # High confidence in question
                            abstained=False, # We are engaging
                            disclaimer_included=False,
                            trace=self._traces if include_trace else [],
                            total_latency_ms=total_latency,
                            needs_onboarding=needs_onboarding,
                            sign_in_suggestion=None,
                            metadata=ctx.metadata
                        )
            
            # Check for early abort (e.g., clarification needed)
            if ctx.should_abort:
                return self._create_clarification_response(ctx, start_time, stage_update_message)
            
            # ============================================
            # PHASE 2: Retrieval
            # ============================================
            ctx = await self._run_retrieval_phase(ctx)
            
            # ============================================
            # PHASE 3: Reasoning
            # ============================================
            ctx = await self._run_reasoning_phase(ctx)
            
            # ============================================
            # PHASE 4: Validation
            # ============================================
            ctx = await self._run_validation_phase(ctx)
            
            # Prepend update message if any
            response = self._build_response(
                ctx, start_time, include_trace, 
                needs_onboarding=needs_onboarding,
                is_guest=is_guest,
                modification_proposal=None # No longer using cards
            )
            
            if stage_update_message:
                logger.info(f"Prepending stage_update_message to response: {stage_update_message}")
                response.response = stage_update_message + "\n\n" + response.response
            else:
                logger.info("No stage_update_message to prepend")
                
            return response
            
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            return self._create_error_response(ctx, str(e), start_time)
    
    async def _run_intent_phase(
        self,
        ctx: PipelineContext
    ) -> PipelineContext:
        """Run intent classification only (stage comes from profile)."""
        logger.info("Phase 1: Running intent classification...")
        
        ctx, intent_trace = await self.intent_agent.run(ctx)
        self._traces.append(intent_trace)
        
        self._log_step(
            step_name="intent_classification",
            agent_name="intent_agent",
            input_summary="",
            output_summary=f"intent={ctx.intent_result.intent}, stage={ctx.stage_result.stage}",
            latency_ms=intent_trace.latency_ms,
            model_used=None,
            safety_flags=[],
        )
        
        logger.info(
            f"Intent classified: {ctx.intent_result.intent}, "
            f"Stage (from profile): {ctx.stage_result.stage}"
        )
        
        # Check if clarification is needed
        if ctx.intent_result and ctx.intent_result.clarification_needed:
            ctx.should_abort = True
            ctx.abort_reason = "Clarification needed"
        
        return ctx
    
    async def _run_classification_phase(
        self,
        ctx: PipelineContext
    ) -> PipelineContext:
        """Run intent and stage classification in parallel."""
        logger.info("Phase 1: Running classification (parallel)...")
        
        # Create tasks for parallel execution
        intent_task = asyncio.create_task(self.intent_agent.run(ctx))
        # Pass intent=None as they are parallel; StageAgentV2 handles this
        stage_task = asyncio.create_task(self.stage_agent.run(ctx))
        
        # Wait for both to complete
        (ctx_intent, intent_trace), (ctx_stage, stage_trace) = await asyncio.gather(
            intent_task, stage_task
        )
        
        # Merge results into main context
        # Note: ctx objects are copies or same ref? usually copies in async if not careful, 
        # but here 'run' returns (updated_ctx, trace).
        
        ctx.intent_result = ctx_intent.intent_result
        # Logic to prioritize Profile Stage vs Inferred Stage?
        # Spec 7.5 says "Stage inferred per request".
        # But for 'Context' passed to Reasoning Agent, we might prefer the Profile if it exists.
        # However, StageAgentV2 is the authority on "Where does the user appear to be NOW".
        # We will store the INFERRED result in stage_result as per spec.
        # If we want to keep Profile stage, we should have stored it elsewhere or make a decision here.
        
        # Currently, Phase 0 loaded Profile Stage. Phase 1 (StageAgent) overwrites it.
        # This is correct for "Session Context" adaptation (e.g. user says "I just had surgery" but profile says "Pre-op" -> we should answer as if they had surgery).
        # AND we trigger a proposal.
        
        ctx.stage_result = ctx_stage.stage_result
        # Merge metadata (granular id)
        if ctx_stage.metadata.get("granular_stage_id"):
            ctx.metadata["granular_stage_id"] = ctx_stage.metadata["granular_stage_id"]
        
        # Store traces
        self._traces.extend([intent_trace, stage_trace])
        self._log_step(
            step_name="classification",
            agent_name="intent_stage_parallel",
            input_summary="",
            output_summary=f"intent={ctx.intent_result.intent}, stage={ctx.stage_result.stage}",
            latency_ms=max(intent_trace.latency_ms, stage_trace.latency_ms),
            model_used=None,
            safety_flags=[],
        )
        
        logger.info(
            f"Classification complete: intent={ctx.intent_result.intent}, "
            f"stage={ctx.stage_result.stage}"
        )
        
        # Check if clarification is needed
        if ctx.intent_result and ctx.intent_result.clarification_needed:
            ctx.should_abort = True
            ctx.abort_reason = "Clarification needed"
        
        return ctx
    
    async def _run_retrieval_phase(
        self,
        ctx: PipelineContext
    ) -> PipelineContext:
        """Run document and video retrieval in PARALLEL."""
        logger.info("Phase 2: Running retrieval (parallel - docs + videos)...")
        
        # Create tasks for parallel execution
        doc_retrieval_task = asyncio.create_task(self.retrieval_agent.run(ctx))
        video_retrieval_task = asyncio.create_task(self.video_retrieval_agent.run(ctx))
        
        # Wait for both to complete
        (ctx_docs, doc_trace), (ctx_videos, video_trace) = await asyncio.gather(
            doc_retrieval_task, video_retrieval_task
        )
        
        # Merge results into context
        ctx.retrieval_result = ctx_docs.retrieval_result
        ctx.video_retrieval_result = ctx_videos.video_retrieval_result
        
        # Store traces
        self._traces.extend([doc_trace, video_trace])
        
        # Calculate combined latency (max of both since parallel)
        combined_latency = max(doc_trace.latency_ms, video_trace.latency_ms)
        
        # Build output summary
        doc_count = ctx.retrieval_result.total_retrieved if ctx.retrieval_result else 0
        video_count = ctx.video_retrieval_result.total_retrieved if ctx.video_retrieval_result else 0
        doc_sufficient = ctx.retrieval_result.sufficient_evidence if ctx.retrieval_result else False
        
        self._log_step(
            step_name="retrieval",
            agent_name="retrieval_parallel",
            input_summary="",
            output_summary=f"doc_chunks={doc_count}, videos={video_count}, sufficient={doc_sufficient}",
            latency_ms=combined_latency,
            model_used=None,
            safety_flags=[],
        )
        
        logger.info(
            f"Retrieval complete: {doc_count} doc chunks, {video_count} videos, "
            f"sufficient={doc_sufficient}"
        )
        
        return ctx
    
    async def _run_reasoning_phase(
        self,
        ctx: PipelineContext
    ) -> PipelineContext:
        """Run reasoning with appropriate specialized agent."""
        logger.info("Phase 3: Running reasoning...")
        
        # Get the right reasoning agent for this intent
        intent = ctx.intent_result.intent if ctx.intent_result else IntentCategory.UNKNOWN
        reasoning_agent = get_reasoning_agent(intent)
        
        ctx, reasoning_trace = await reasoning_agent.run(ctx)
        self._traces.append(reasoning_trace)
        
        if ctx.reasoning_result:
            logger.info(
                f"Reasoning complete: abstained={ctx.reasoning_result.abstained}, "
                f"confidence={ctx.reasoning_result.confidence:.2f}"
            )
            self._log_step(
                step_name="reasoning",
                agent_name=reasoning_trace.agent_name if reasoning_trace else "reasoning_agent",
                input_summary="",
                output_summary=f"abstained={ctx.reasoning_result.abstained}, confidence={ctx.reasoning_result.confidence:.2f}",
                latency_ms=reasoning_trace.latency_ms if reasoning_trace else 0,
                model_used=None,
                safety_flags=[],
            )
        
        return ctx
    
    async def _run_validation_phase(
        self,
        ctx: PipelineContext
    ) -> PipelineContext:
        """Run safety validation on the response."""
        logger.info("Phase 4: Running validation...")
        
        ctx, validation_trace = await self.validator_agent.run(ctx)
        self._traces.append(validation_trace)
        
        if ctx.validation_result:
            logger.info(
                f"Validation complete: safe={ctx.validation_result.is_safe}, "
                f"flags={len(ctx.validation_result.flags)}"
            )
            self._log_step(
                step_name="validation",
                agent_name=validation_trace.agent_name if validation_trace else "validator_agent",
                input_summary="",
                output_summary=f"safe={ctx.validation_result.is_safe}, flags={len(ctx.validation_result.flags)}",
                latency_ms=validation_trace.latency_ms if validation_trace else 0,
                model_used=None,
                safety_flags=[f.rule_id for f in ctx.validation_result.flags] if ctx.validation_result else [],
            )
        
        return ctx
    
    def _build_response(
        self,
        ctx: PipelineContext,
        start_time: float,
        include_trace: bool,
        needs_onboarding: bool = False,
        is_guest: bool = True,
        modification_proposal: Optional['ModificationProposal'] = None
    ) -> PipelineResponse:
        """Build the final pipeline response."""
        total_latency = int((time.time() - start_time) * 1000)
        
        response_text = ""
        if ctx.reasoning_result:
            response_text = ctx.reasoning_result.response_text
        
        citations = []
        if ctx.reasoning_result and ctx.reasoning_result.citations:
            citations = ctx.reasoning_result.citations
        
        # Extract suggested videos from video retrieval result
        suggested_videos = self._extract_suggested_videos(ctx)
        logger.info(
            f"Orchestrator: Extracted {len(suggested_videos)} suggested videos. "
            f"video_retrieval_result exists: {ctx.video_retrieval_result is not None}, "
            f"videos count: {len(ctx.video_retrieval_result.videos) if ctx.video_retrieval_result else 0}"
        )
        
        if suggested_videos:
            logger.info(f"Orchestrator: First suggested video: {suggested_videos[0].title} ({suggested_videos[0].video_id})")
        
        # Determine if we should show sources section (hide for citation-only intents)
        intent = ctx.intent_result.intent if ctx.intent_result else IntentCategory.UNKNOWN
        show_sources = not is_citation_only(intent)
        
        response = PipelineResponse(
            request_id=ctx.request_id,
            response=response_text,
            intent=intent,
            stage=ctx.stage_result.stage if ctx.stage_result else "unknown",
            citations=citations,
            confidence=ctx.reasoning_result.confidence if ctx.reasoning_result else 0.0,
            abstained=ctx.reasoning_result.abstained if ctx.reasoning_result else True,
            disclaimer_included=True,  # We always add disclaimers for medical content
            suggested_videos=suggested_videos,
            show_sources=show_sources,
            trace=self._traces if include_trace else [],
            total_latency_ms=total_latency,
            needs_onboarding=needs_onboarding,
            sign_in_suggestion=self._get_sign_in_suggestion(ctx, is_guest),
            modification_proposal=modification_proposal,
            metadata=ctx.metadata
        )
        
        logger.info(f"Orchestrator: PipelineResponse created with {len(response.suggested_videos)} suggested_videos")
        # Emit metrics
        record_latency(
            "pipeline.total_latency_ms",
            total_latency,
            dimensions={
                "intent": str(response.intent),
                "stage": str(response.stage),
            },
        )
        record_count(
            "pipeline.requests",
            1,
            dimensions={
                "intent": str(response.intent),
                "status": "success" if not response.abstained else "abstained",
            },
        )
        self._log_step(
            step_name="pipeline_complete",
            agent_name="orchestrator",
            input_summary="",
            output_summary=f"intent={response.intent}, stage={response.stage}, abstained={response.abstained}",
            latency_ms=total_latency,
            model_used=None,
            safety_flags=[],
        )
        return response
    
    def _extract_suggested_videos(
        self,
        ctx: PipelineContext
    ) -> List[SuggestedVideo]:
        """Extract suggested videos from video retrieval result."""
        suggested_videos = []
        
        if ctx.video_retrieval_result and ctx.video_retrieval_result.videos:
            for video in ctx.video_retrieval_result.videos[:3]:  # Top 3 videos
                # Use timestamped URL if available, otherwise regular URL
                url = video.timestamped_url or video.video_url
                
                # Create relevance note from transcript excerpt
                relevance_note = None
                if video.transcript_excerpt:
                    excerpt = video.transcript_excerpt[:150]
                    if len(video.transcript_excerpt) > 150:
                        excerpt += "..."
                    relevance_note = excerpt
                
                suggested_videos.append(SuggestedVideo(
                    video_id=video.video_id,
                    title=video.video_title,
                    url=url,
                    channel_name=video.channel_name,
                    relevance_note=relevance_note,
                    timestamp_seconds=video.timestamp_start
                ))
        
        return suggested_videos
    
    def _create_clarification_response(
        self,
        ctx: PipelineContext,
        start_time: float,
        stage_update_message: Optional[str] = None
    ) -> PipelineResponse:
        """Create a response requesting clarification."""
        total_latency = int((time.time() - start_time) * 1000)
        
        clarification_text = (
            ctx.intent_result.suggested_clarification
            if ctx.intent_result and ctx.intent_result.suggested_clarification
            else "Could you please tell me more about what you'd like to know?"
        )
        
        # Prepend stage update message if present
        if stage_update_message:
            logger.info(f"Prepending stage_update_message to clarification: {stage_update_message}")
            clarification_text = stage_update_message + "\n\n" + clarification_text
        
        return PipelineResponse(
            request_id=ctx.request_id,
            response=clarification_text,
            intent=ctx.intent_result.intent if ctx.intent_result else IntentCategory.UNKNOWN,
            stage=ctx.stage_result.stage if ctx.stage_result else "unknown",
            citations=[],
            confidence=0.5,
            abstained=False,
            disclaimer_included=False,
            suggested_videos=[],
            trace=self._traces,
            total_latency_ms=total_latency
        )
    
    def _create_error_response(
        self,
        ctx: PipelineContext,
        error_message: str,
        start_time: float
    ) -> PipelineResponse:
        """Create an error response."""
        total_latency = int((time.time() - start_time) * 1000)
        
        return PipelineResponse(
            request_id=ctx.request_id,
            response=(
                "I'm sorry, I encountered an issue processing your question. "
                "Please try again, or contact support if the problem persists."
            ),
            intent=IntentCategory.UNKNOWN,
            stage="unknown",
            citations=[],
            confidence=0.0,
            abstained=True,
            disclaimer_included=False,
            suggested_videos=[],
            trace=self._traces,
            total_latency_ms=total_latency
        )

    def _get_sign_in_suggestion(
        self,
        ctx: PipelineContext,
        is_guest: bool
    ) -> Optional[str]:
        """
        Get sign-in suggestion for guest users on stage-sensitive queries.
        
        Returns the suggestion message if:
        - User is a guest
        - Query intent is stage-sensitive (medical/treatment related)
        
        Option C: Response-integrated sign-in suggestion
        """
        if not is_guest:
            return None
        
        # Check if intent is stage-sensitive
        intent = ctx.intent_result.intent if ctx.intent_result else IntentCategory.UNKNOWN
        
        if intent in STAGE_SENSITIVE_INTENTS:
            return SIGN_IN_SUGGESTION
        
        return None

    def _log_step(
        self,
        step_name: str,
        agent_name: str,
        input_summary: str,
        output_summary: str,
        latency_ms: int,
        model_used: Optional[str],
        safety_flags: List[str],
    ) -> None:
        """Emit structured log for a pipeline step."""
        payload: Dict[str, Any] = {
            "event": "pipeline_step",
            "request_id": self._current_request_id,
            "step_name": step_name,
            "agent_name": agent_name,
            "latency_ms": latency_ms,
            "model_used": model_used,
            "safety_flags": safety_flags,
            "spec_version": SPEC_VERSION,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if settings.enable_structured_logging:
            logger.info(payload)
        else:
            logger.info(
                f"[{step_name}] agent={agent_name} latency={latency_ms}ms flags={safety_flags} output={output_summary}"
            )


# ================================
# Convenience Function
# ================================

async def process_message(
    message: str,
    session_id: Optional[str] = None,
    conversation_history: Optional[List[dict]] = None
) -> PipelineResponse:
    """
    Process a message through the multi-agent pipeline.
    
    This is the main entry point for the pipeline.
    """
    orchestrator = PipelineOrchestrator()
    return await orchestrator.process(
        message=message,
        session_id=session_id,
        conversation_history=conversation_history
    )

