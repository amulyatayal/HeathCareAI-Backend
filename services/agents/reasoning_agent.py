"""
Reasoning Agent Factory
Creates specialized reasoning agents for each intent category.

Spec Reference: ProjectSpec.md v1.2, Section 8
"""

import logging
from typing import Optional, Dict, Any

from services.agents.base_agent import BaseAgent, AgentError
from services.agents.retrieval_agent import format_chunks_for_prompt, get_citations_from_chunks
from services.agents.stage_agent import get_stage_guidelines
from models.schemas import (
    PipelineContext,
    ReasoningResult,
    Citation
)
from config.pipeline_config import (
    IntentCategory,
    PatientStage,
    CertaintyLevel,
    ModelType,
    MEDICAL_DISCLAIMER,
    SAFE_FALLBACK_RESPONSE
)
from config.agent_routing import (
    get_route_for_intent,
    get_agent_prompt,
    is_medical_intent,
    is_strict_rag,
    is_citation_only,
    ReasoningAgentType
)

logger = logging.getLogger(__name__)


# ================================
# Response Generation Prompt
# ================================

# Template for STRICT RAG mode (KB evidence only)
REASONING_STRICT_TEMPLATE = """{agent_prompt}

RESPONSE GUIDELINES:
{stage_guidelines}

EVIDENCE CONTEXT:
{evidence_context}

IMPORTANT RULES (STRICT MODE - Evidence Only):
1. Base your response ONLY on the provided evidence. Do not make up information.
2. If the evidence is insufficient, acknowledge limitations and suggest consulting the care team.
3. Use clear, accessible language appropriate for patients.
4. Be empathetic and supportive in tone.
5. Include specific citations when referencing sources (e.g., "According to [Source 1]...").
6. For medical information, always recommend consulting healthcare providers for personalized advice.
{additional_rules}

{disclaimer_instruction}"""

# Template for FLEXIBLE mode (KB + LLM general knowledge)
REASONING_FLEXIBLE_TEMPLATE = """{agent_prompt}

RESPONSE GUIDELINES:
{stage_guidelines}

EVIDENCE CONTEXT (if available):
{evidence_context}

IMPORTANT RULES (FLEXIBLE MODE):
1. Use the provided evidence when available, citing sources appropriately.
2. You MAY supplement with your general knowledge for this topic category.
3. Clearly distinguish between sourced information and general advice.
4. Use clear, accessible language appropriate for patients.
5. Be empathetic and supportive in tone.
6. For any medical-adjacent advice, recommend consulting healthcare providers.
{additional_rules}

{disclaimer_instruction}"""


# Template for CITATION-ONLY mode (verbatim quotes only)
REASONING_CITATION_TEMPLATE = """{agent_prompt}

You are providing information using ONLY verbatim quotes from trusted medical sources.

PATIENT STAGE CONTEXT:
{stage_guidelines}

Use the patient's stage to personalize your intro and closing (but NOT the medical quotes).

SOURCE MATERIALS (use EXACT text from these):
{evidence_context}

CRITICAL RULES (CITATION-ONLY MODE):
1. You MUST use the EXACT wording from the sources. DO NOT paraphrase, summarize, or rewrite ANY medical content.
2. Select the 2-3 MOST RELEVANT source excerpts that answer the patient's question.
3. PERSONALIZE the intro based on patient stage:
   - Pre-diagnosis: "I know waiting for answers can be stressful..."
   - Newly diagnosed: "Being newly diagnosed can feel overwhelming..."
   - In treatment: "I understand treatment can bring many questions..."
   - Post-treatment: "As you're moving forward after treatment..."
4. PERSONALIZE the closing based on patient stage:
   - Pre-diagnosis: Reassure that many findings are benign, encourage follow-up
   - Newly diagnosed: Acknowledge emotions, encourage taking time to understand options
   - In treatment: Validate challenges, remind them their care team is there
   - Post-treatment: Celebrate progress, acknowledge ongoing concerns are normal
5. Your intro and closing should NOT contain any medical information or summary of the quotes.
6. After each quote, include the source reference: [📄 Source Name, p.XX]
7. Format quotes clearly using quotation marks.

RESPONSE FORMAT:
1. Stage-personalized empathetic intro (NO medical content)
2. Verbatim Quote 1 with source
3. Verbatim Quote 2 with source (if relevant)
4. Stage-personalized empathetic closing (NO medical summary) with 💜

{disclaimer_instruction}"""


REASONING_USER_TEMPLATE = """Patient Question: {question}

Patient Stage: {stage} ({stage_certainty})
{stage_context}

Please provide a helpful, evidence-based response."""


# ================================
# Reasoning Agent Base
# ================================

class ReasoningAgent(BaseAgent):
    """
    Base reasoning agent that generates responses using retrieved evidence.
    
    Uses the appropriate system prompt based on intent routing.
    Adapts response style based on patient stage.
    """
    
    def __init__(
        self,
        agent_type: ReasoningAgentType,
        model_type: ModelType = ModelType.ACCURATE
    ):
        super().__init__(
            name=agent_type.value,
            model_type=model_type,
            timeout_ms=30000  # 30 second timeout for generation
        )
        self.agent_type = agent_type
        self.base_prompt = get_agent_prompt(agent_type)
    
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Generate a response using retrieved evidence and patient context.
        
        Args:
            context: Pipeline context with intent, stage, and retrieval results
            
        Returns:
            Updated context with reasoning_result populated
        """
        logger.info(f"ReasoningAgent ({self.agent_type.value}) generating response...")
        
        # Get intent and check if strict RAG is required
        intent = context.intent_result.intent if context.intent_result else IntentCategory.UNKNOWN
        strict_mode = is_strict_rag(intent)
        citation_only_mode = is_citation_only(intent)
        
        # Check if we have sufficient evidence
        has_evidence = (
            context.retrieval_result and 
            context.retrieval_result.sufficient_evidence and
            len(context.retrieval_result.chunks) > 0
        )
        
        if not has_evidence and strict_mode:
            # Only abstain if strict RAG is required
            context.reasoning_result = self._create_abstention_result(context)
            logger.info(f"Abstaining due to insufficient evidence (strict_rag=True for {intent})")
            return context
        
        # CITATION-ONLY MODE: Use LLM for selection/presentation, but enforce verbatim quotes
        if citation_only_mode:
            logger.info(f"Citation-only mode for {intent}: LLM will select and present verbatim quotes")
        
        # If not strict mode and no evidence, we'll use LLM general knowledge
        if not has_evidence:
            logger.info(f"No KB evidence but strict_rag=False for {intent}, using LLM general knowledge")
        
        try:
            # Build the prompts
            system_prompt = self._build_system_prompt(context)
            user_prompt = self._build_user_prompt(context)
            
            # Generate response
            response_text = await self.invoke_llm(
                system_prompt=system_prompt,
                user_message=user_prompt,
                temperature=0.4,  # Balanced creativity/consistency
                max_tokens=1500
            )
            
            # Extract citations from chunks (if available)
            citations = []
            if context.retrieval_result and context.retrieval_result.chunks:
                citations = [
                    Citation(
                        source_file=c.get("source_file", "Unknown"),
                        section=c.get("section"),
                        page_start=c.get("page_start"),
                        page_end=c.get("page_end"),
                        relevance_score=c.get("relevance_score", 0.0)
                    )
                    for c in get_citations_from_chunks(context.retrieval_result.chunks)
                ]
            
            context.reasoning_result = ReasoningResult(
                response_text=response_text,
                citations=citations,
                abstained=False,
                confidence=self._calculate_confidence(context),
                agent_type=self.agent_type.value
            )
            
            logger.info(
                f"Response generated: {len(response_text)} chars, "
                f"{len(citations)} citations"
            )
            
        except Exception as e:
            logger.error(f"Reasoning failed: {e}")
            context.reasoning_result = ReasoningResult(
                response_text=SAFE_FALLBACK_RESPONSE,
                citations=[],
                abstained=True,
                abstention_reason=f"Generation error: {str(e)}",
                confidence=0.0,
                agent_type=self.agent_type.value
            )
        
        return context
    
    def _build_system_prompt(self, context: PipelineContext) -> str:
        """Build the system prompt with context."""
        # Get intent and mode settings
        intent = IntentCategory.UNKNOWN
        if context.intent_result:
            intent = context.intent_result.intent
        strict_mode = is_strict_rag(intent)
        citation_only_mode = is_citation_only(intent)
        
        # Get stage guidelines
        stage = PatientStage.UNKNOWN
        if context.stage_result:
            stage = context.stage_result.stage
        
        stage_info = get_stage_guidelines(stage)
        stage_guidelines = (
            f"- Tone: {stage_info.get('tone', 'warm and supportive')}\n"
            f"- Emphasize: {stage_info.get('emphasis', 'general support')}\n"
            f"- Avoid: {stage_info.get('avoid', 'making assumptions')}"
        )
        
        # Format evidence
        evidence_context = "No evidence retrieved from knowledge base."
        if context.retrieval_result and context.retrieval_result.chunks:
            evidence_context = format_chunks_for_prompt(
                context.retrieval_result.chunks,
                max_chars=6000  # Leave room for rest of prompt
            )
        
        # Add intent-specific rules
        additional_rules = self._get_additional_rules(context)
        
        # Determine if disclaimer needed
        disclaimer_instruction = ""
        if is_medical_intent(intent):
            disclaimer_instruction = (
                f"\nIMPORTANT: End your response with this disclaimer:\n"
                f'"{MEDICAL_DISCLAIMER}"'
            )
        
        # Choose template based on mode
        if citation_only_mode:
            template = REASONING_CITATION_TEMPLATE
            mode_name = "CITATION-ONLY"
        elif strict_mode:
            template = REASONING_STRICT_TEMPLATE
            mode_name = "STRICT"
        else:
            template = REASONING_FLEXIBLE_TEMPLATE
            mode_name = "FLEXIBLE"
        
        logger.debug(f"Using {mode_name} mode for intent: {intent}")
        
        # Citation template doesn't use additional_rules
        if citation_only_mode:
            return template.format(
                agent_prompt=self.base_prompt,
                stage_guidelines=stage_guidelines,
                evidence_context=evidence_context,
                disclaimer_instruction=disclaimer_instruction
            )
        
        return template.format(
            agent_prompt=self.base_prompt,
            stage_guidelines=stage_guidelines,
            evidence_context=evidence_context,
            additional_rules=additional_rules,
            disclaimer_instruction=disclaimer_instruction
        )
    
    def _build_user_prompt(self, context: PipelineContext) -> str:
        """Build the user prompt with question and context."""
        # Get stage info
        stage = PatientStage.UNKNOWN
        stage_certainty = "unknown"
        if context.stage_result:
            stage = context.stage_result.stage
            stage_certainty = context.stage_result.certainty
        
        # Build stage context
        stage_context = ""
        if context.stage_result and context.stage_result.signals:
            stage_context = f"Stage signals: {', '.join(context.stage_result.signals)}"
        
        return REASONING_USER_TEMPLATE.format(
            question=context.user_message,
            stage=stage,
            stage_certainty=stage_certainty,
            stage_context=stage_context
        )
    
    def _get_additional_rules(self, context: PipelineContext) -> str:
        """Get intent-specific additional rules."""
        intent = IntentCategory.UNKNOWN
        if context.intent_result:
            intent = context.intent_result.intent
        
        rules = {
            IntentCategory.SAFETY_RED_FLAGS: (
                "7. If describing emergency symptoms, ALWAYS advise seeking immediate medical care.\n"
                "8. Do not minimize potentially serious symptoms.\n"
                "9. Provide clear guidance on when to call emergency services."
            ),
            IntentCategory.MEDICATION_INFO: (
                "7. Never recommend specific medications or dosages.\n"
                "8. Always defer to the prescriber's instructions.\n"
                "9. Emphasize importance of taking medications as prescribed."
            ),
            IntentCategory.STATISTICS: (
                "7. Emphasize that statistics are population-level, not individual predictions.\n"
                "8. Present data with appropriate context about limitations.\n"
                "9. Be honest but not discouraging."
            ),
            IntentCategory.EMOTIONAL_SUPPORT: (
                "7. Lead with empathy and validation.\n"
                "8. Normalize the patient's feelings.\n"
                "9. Suggest professional support resources when appropriate."
            ),
            IntentCategory.NUTRITION: (
                "7. Provide practical, actionable food suggestions.\n"
                "8. Consider common treatment side effects (nausea, taste changes).\n"
                "9. Keep recipes and suggestions simple and accessible."
            ),
        }
        
        return rules.get(intent, "")
    
    def _calculate_confidence(self, context: PipelineContext) -> float:
        """Calculate response confidence based on evidence quality."""
        base_confidence = 0.7
        
        if context.retrieval_result:
            # Boost for more chunks above threshold
            above_threshold = context.retrieval_result.above_threshold
            if above_threshold >= 5:
                base_confidence += 0.15
            elif above_threshold >= 3:
                base_confidence += 0.1
            elif above_threshold >= 2:
                base_confidence += 0.05
        
        if context.intent_result:
            # Boost for high intent confidence
            if context.intent_result.confidence >= 0.85:
                base_confidence += 0.05
        
        if context.stage_result:
            # Boost for high stage certainty
            if context.stage_result.certainty == CertaintyLevel.HIGH:
                base_confidence += 0.05
        
        return min(base_confidence, 0.95)
    
    def _create_abstention_result(self, context: PipelineContext) -> ReasoningResult:
        """Create an abstention result when evidence is insufficient."""
        intent = IntentCategory.UNKNOWN
        if context.intent_result:
            intent = context.intent_result.intent
        
        # Customize abstention message based on intent
        abstention_messages = {
            IntentCategory.NUTRITION: (
                "I don't have enough specific nutrition information to answer your question confidently. "
                "For personalized dietary advice, please speak with your oncology dietitian or care team."
            ),
            IntentCategory.MEDICATION_INFO: (
                "I don't have sufficient information about this medication in my knowledge base. "
                "Please consult your pharmacist or prescribing doctor for accurate medication information."
            ),
            IntentCategory.SAFETY_RED_FLAGS: (
                "If you're experiencing concerning symptoms, please don't wait for my response. "
                "Contact your care team immediately or go to the emergency room if symptoms are severe."
            ),
        }
        
        default_message = (
            "I don't have enough reliable information to answer this question confidently. "
            "For accurate information about your specific situation, please consult your healthcare team."
        )
        
        return ReasoningResult(
            response_text=abstention_messages.get(intent, default_message),
            citations=[],
            abstained=True,
            abstention_reason="Insufficient evidence in knowledge base",
            confidence=0.0,
            agent_type=self.agent_type.value
        )
    
    def _build_citation_only_response(self, context: PipelineContext) -> ReasoningResult:
        """
        Build a response using ONLY verbatim text from sources.
        No LLM paraphrasing - returns exact quotes with source links.
        """
        chunks = context.retrieval_result.chunks if context.retrieval_result else []
        
        if not chunks:
            return self._create_abstention_result(context)
        
        # Build response with verbatim text and source citations
        response_parts = []
        citations = []
        seen_content = set()
        
        for i, chunk in enumerate(chunks[:5], 1):  # Limit to top 5 sources
            # Get the verbatim text (source_excerpt if available, else content)
            content = chunk.content.strip()
            
            # Skip duplicates
            content_key = content[:100]
            if content_key in seen_content:
                continue
            seen_content.add(content_key)
            
            # Extract just the answer part if it's a Q&A format
            answer_text = content
            if "Answer:" in content:
                parts = content.split("Answer:", 1)
                if len(parts) > 1:
                    answer_text = parts[1].strip()
            
            # Format source info for hyperlink
            source_file = chunk.source_file or "Source"
            source_name = source_file.replace(".pdf", "").replace("-", " ").replace("_", " ")
            if len(source_name) > 40:
                source_name = source_name[:37] + "..."
            
            page_info = ""
            if chunk.page_start:
                page_info = f" (p.{chunk.page_start}"
                if chunk.page_end and chunk.page_end != chunk.page_start:
                    page_info = f" (pp.{chunk.page_start}-{chunk.page_end}"
                page_info += ")"
            
            # Format: verbatim text with source link icon
            # Using markdown link format: [📄](source_url)
            source_link = f"[📄 {source_name}{page_info}]({source_file})"
            
            response_parts.append(f"{answer_text}\n\n*Source: {source_link}*")
            
            # Add citation
            citations.append(Citation(
                source_file=chunk.source_file or "Unknown",
                section=chunk.section,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                relevance_score=chunk.score
            ))
        
        # Join all verbatim quotes
        if len(response_parts) > 1:
            response_text = "\n\n---\n\n".join(response_parts)
        else:
            response_text = response_parts[0] if response_parts else "No information found."
        
        logger.info(f"Citation-only response: {len(response_parts)} sources, {len(response_text)} chars")
        
        return ReasoningResult(
            response_text=response_text,
            citations=citations,
            abstained=False,
            confidence=0.95,  # High confidence for verbatim quotes
            agent_type=self.agent_type.value
        )
    
    def _get_output_summary(self, context: PipelineContext) -> Optional[str]:
        """Generate output summary for logging."""
        if context.reasoning_result:
            r = context.reasoning_result
            return (
                f"abstained={r.abstained}, "
                f"confidence={r.confidence:.2f}, "
                f"chars={len(r.response_text)}"
            )
        return None


# ================================
# Agent Factory
# ================================

class ReasoningAgentFactory:
    """
    Factory for creating reasoning agents based on intent.
    
    Uses the routing configuration to determine which agent type
    and model to use for each intent.
    """
    
    _cache: Dict[ReasoningAgentType, ReasoningAgent] = {}
    
    @classmethod
    def get_agent(cls, intent: IntentCategory) -> ReasoningAgent:
        """
        Get or create a reasoning agent for the given intent.
        
        Args:
            intent: The classified intent category
            
        Returns:
            Appropriate ReasoningAgent instance
        """
        # Get routing config
        route = get_route_for_intent(intent)
        agent_type = route.agent_type
        model_type = route.model_type
        
        # Check cache
        if agent_type not in cls._cache:
            cls._cache[agent_type] = ReasoningAgent(
                agent_type=agent_type,
                model_type=model_type
            )
            logger.info(f"Created new ReasoningAgent: {agent_type.value}")
        
        return cls._cache[agent_type]
    
    @classmethod
    def clear_cache(cls):
        """Clear the agent cache."""
        cls._cache.clear()


# ================================
# Convenience Function
# ================================

def get_reasoning_agent(intent: IntentCategory) -> ReasoningAgent:
    """Get a reasoning agent for the given intent."""
    return ReasoningAgentFactory.get_agent(intent)

