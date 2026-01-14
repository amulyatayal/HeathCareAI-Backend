"""
Retrieval Agent
Fetches relevant evidence from knowledge bases based on intent routing.

Spec Reference: ProjectSpec.md v1.2, Section 13
"""

import logging
import asyncio
from typing import Optional, List, Dict, Any

from services.agents.base_agent import BaseAgent
from models.schemas import (
    PipelineContext,
    RetrievalResult,
    RetrievalChunk
)
from config.pipeline_config import (
    IntentCategory,
    ModelType,
    RetrievalConfig
)
from config.agent_routing import (
    get_route_for_intent,
    get_knowledge_bases_for_intent,
    KnowledgeBase,
    is_medical_intent
)
from services.knowledge_base import KnowledgeBaseService

logger = logging.getLogger(__name__)


class RetrievalAgent(BaseAgent):
    """
    Agent that retrieves relevant evidence from knowledge bases.
    
    Uses intent-based routing to select the appropriate KB(s).
    Applies different thresholds for medical vs. non-medical queries.
    """
    
    def __init__(self):
        super().__init__(
            name="retrieval_agent",
            model_type=ModelType.FAST,  # No LLM needed, just retrieval
            timeout_ms=15000  # 15 second timeout for search
        )
        self._kb_services: Dict[str, KnowledgeBaseService] = {}
    
    def _get_kb_service(self, kb_name: str) -> KnowledgeBaseService:
        """Get or create a KnowledgeBaseService for the given index."""
        if kb_name not in self._kb_services:
            self._kb_services[kb_name] = KnowledgeBaseService(index_name=kb_name)
        return self._kb_services[kb_name]
    
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Retrieve evidence from knowledge bases based on classified intent.
        
        Args:
            context: Pipeline context with intent_result populated
            
        Returns:
            Updated context with retrieval_result populated
        """
        logger.info(f"RetrievalAgent processing query: {context.user_message[:50]}...")
        
        # Get intent from context (default to UNKNOWN if not classified)
        intent = IntentCategory.UNKNOWN
        if context.intent_result:
            intent = context.intent_result.intent
        
        # Get KB routing for this intent
        knowledge_bases = get_knowledge_bases_for_intent(intent)
        
        logger.info(f"Intent '{intent}' routes to KBs: {[kb.value for kb in knowledge_bases]}")
        
        # Determine retrieval thresholds based on intent type
        if is_medical_intent(intent):
            min_chunks = RetrievalConfig.MEDICAL_MIN_CHUNKS
            min_score = RetrievalConfig.MEDICAL_MIN_SCORE
            require_keyword = RetrievalConfig.MEDICAL_REQUIRE_KEYWORD
        elif intent == IntentCategory.NUTRITION:
            min_chunks = RetrievalConfig.NUTRITION_MIN_CHUNKS
            min_score = RetrievalConfig.NUTRITION_MIN_SCORE
            require_keyword = RetrievalConfig.NUTRITION_REQUIRE_KEYWORD
        else:
            min_chunks = RetrievalConfig.GENERAL_MIN_CHUNKS
            min_score = RetrievalConfig.GENERAL_MIN_SCORE
            require_keyword = RetrievalConfig.GENERAL_REQUIRE_KEYWORD
        
        # Search primary KB first
        primary_kb = knowledge_bases[0] if knowledge_bases else KnowledgeBase.MEDICAL
        
        try:
            result = await self._search_kb(
                kb_name=primary_kb.value,
                query=context.user_message,
                min_chunks=min_chunks,
                min_score=min_score,
                require_keyword=require_keyword
            )
            
            # If insufficient evidence from primary KB, try secondary KBs
            if not result.sufficient_evidence and len(knowledge_bases) > 1:
                logger.info("Primary KB insufficient, searching secondary KBs...")
                
                for secondary_kb in knowledge_bases[1:]:
                    secondary_result = await self._search_kb(
                        kb_name=secondary_kb.value,
                        query=context.user_message,
                        min_chunks=min_chunks,
                        min_score=min_score,
                        require_keyword=require_keyword
                    )
                    
                    # Merge results
                    result = self._merge_results(result, secondary_result)
                    
                    if result.sufficient_evidence:
                        break
            
            context.retrieval_result = result
            
            logger.info(
                f"Retrieval complete: {result.total_retrieved} chunks, "
                f"{result.above_threshold} above threshold, "
                f"sufficient={result.sufficient_evidence}"
            )
            
        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            # Return empty result on failure
            context.retrieval_result = RetrievalResult(
                chunks=[],
                total_retrieved=0,
                above_threshold=0,
                sufficient_evidence=False,
                knowledge_base_used=primary_kb.value
            )
        
        return context
    
    async def _search_kb(
        self,
        kb_name: str,
        query: str,
        min_chunks: int,
        min_score: float,
        require_keyword: bool
    ) -> RetrievalResult:
        """Search a specific knowledge base."""
        logger.info(f"Searching KB '{kb_name}' with min_chunks={min_chunks}, min_score={min_score}")
        
        kb_service = self._get_kb_service(kb_name)
        
        # Run the synchronous search in an executor
        loop = asyncio.get_event_loop()
        rag_result = await loop.run_in_executor(
            None,
            lambda: asyncio.run(kb_service.search_chunks_for_rag(
                query=query,
                limit=RetrievalConfig.MAX_CHUNKS,
                min_chunks=min_chunks,
                min_score=min_score,
                require_keyword_match=require_keyword
            ))
        )
        
        # Convert to RetrievalResult format
        chunks = []
        for chunk_data in rag_result.get("chunks", []):
            chunk = RetrievalChunk(
                chunk_id=chunk_data.get("document_id", ""),
                content=chunk_data.get("content", ""),
                score=chunk_data.get("score", 0.0),
                source_file=chunk_data.get("source_file"),
                section=chunk_data.get("section"),
                page_start=chunk_data.get("page_start"),
                page_end=chunk_data.get("page_end"),
                metadata={
                    "title": chunk_data.get("title"),
                    "category": chunk_data.get("category"),
                    "content_type": chunk_data.get("content_type"),
                    "tags": chunk_data.get("tags", []),
                    "keyword_match": chunk_data.get("keyword_match", False)
                }
            )
            chunks.append(chunk)
        
        evidence_stats = rag_result.get("evidence_stats", {})
        
        return RetrievalResult(
            chunks=chunks,
            total_retrieved=evidence_stats.get("total_retrieved", len(chunks)),
            above_threshold=evidence_stats.get("above_threshold", 0),
            sufficient_evidence=rag_result.get("has_sufficient_evidence", False),
            knowledge_base_used=kb_name
        )
    
    def _merge_results(
        self,
        primary: RetrievalResult,
        secondary: RetrievalResult
    ) -> RetrievalResult:
        """Merge results from multiple knowledge bases."""
        # Combine chunks, avoiding duplicates by chunk_id
        seen_ids = {c.chunk_id for c in primary.chunks}
        merged_chunks = list(primary.chunks)
        
        for chunk in secondary.chunks:
            if chunk.chunk_id not in seen_ids:
                merged_chunks.append(chunk)
                seen_ids.add(chunk.chunk_id)
        
        # Sort by score (descending)
        merged_chunks.sort(key=lambda c: c.score, reverse=True)
        
        # Recalculate statistics
        total = len(merged_chunks)
        # Count chunks above minimum threshold (use general threshold for merged)
        above = sum(1 for c in merged_chunks if c.score >= RetrievalConfig.GENERAL_MIN_SCORE)
        
        # Sufficient if we have enough above-threshold chunks
        sufficient = above >= RetrievalConfig.GENERAL_MIN_CHUNKS
        
        return RetrievalResult(
            chunks=merged_chunks[:RetrievalConfig.MAX_CHUNKS],  # Cap at max
            total_retrieved=total,
            above_threshold=above,
            sufficient_evidence=sufficient,
            knowledge_base_used=f"{primary.knowledge_base_used}+{secondary.knowledge_base_used}"
        )
    
    def _get_output_summary(self, context: PipelineContext) -> Optional[str]:
        """Generate output summary for logging."""
        if context.retrieval_result:
            r = context.retrieval_result
            return (
                f"kb={r.knowledge_base_used}, "
                f"chunks={r.total_retrieved}, "
                f"above_threshold={r.above_threshold}, "
                f"sufficient={r.sufficient_evidence}"
            )
        return None


# ================================
# Helper Functions
# ================================

def format_chunks_for_prompt(chunks: List[RetrievalChunk], max_chars: int = 8000) -> str:
    """
    Format retrieved chunks into a context string for LLM prompts.
    
    Args:
        chunks: List of retrieved chunks
        max_chars: Maximum character limit for combined context
        
    Returns:
        Formatted context string with source citations
    """
    if not chunks:
        return "No relevant information found in the knowledge base."
    
    context_parts = []
    total_chars = 0
    
    for i, chunk in enumerate(chunks, 1):
        # Format source citation
        source = chunk.source_file or "Unknown source"
        section = f", {chunk.section}" if chunk.section else ""
        pages = ""
        if chunk.page_start:
            pages = f", p.{chunk.page_start}"
            if chunk.page_end and chunk.page_end != chunk.page_start:
                pages = f", pp.{chunk.page_start}-{chunk.page_end}"
        
        citation = f"[Source {i}: {source}{section}{pages}]"
        
        # Format chunk content
        content = chunk.content.strip()
        chunk_text = f"{citation}\n{content}\n"
        
        # Check character limit
        if total_chars + len(chunk_text) > max_chars:
            break
        
        context_parts.append(chunk_text)
        total_chars += len(chunk_text)
    
    return "\n---\n".join(context_parts)


def get_citations_from_chunks(chunks: List[RetrievalChunk]) -> List[Dict[str, Any]]:
    """Extract citation information from chunks."""
    citations = []
    seen_sources = set()
    
    for chunk in chunks:
        source_key = f"{chunk.source_file}:{chunk.section}:{chunk.page_start}"
        if source_key not in seen_sources:
            citations.append({
                "source_file": chunk.source_file or "Unknown",
                "section": chunk.section,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "relevance_score": chunk.score
            })
            seen_sources.add(source_key)
    
    return citations

