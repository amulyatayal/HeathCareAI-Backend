"""
Video Retrieval Agent
Fetches relevant YouTube video transcripts based on user query.
Runs in parallel with RetrievalAgent to provide video suggestions.

Uses intent-based topic keywords to ensure videos match the query subject
(e.g. nutrition vs meditation) not just context (e.g. "chemotherapy").

Spec Reference: ProjectSpec.md v1.2, Section 13
"""

import logging
import asyncio
from typing import Optional, Dict, Any, List, Set

from services.agents.base_agent import BaseAgent
from models.schemas_pipeline import (
    PipelineContext,
    VideoRetrievalResult,
    VideoRetrievalChunk
)
from config.pipeline_config import ModelType, IntentCategory
from services.knowledge_base import KnowledgeBaseService

logger = logging.getLogger(__name__)

# YouTube KB index name (matches the ingested index)
VIDEO_KB_INDEX = "youtube_transcripts"

# Retrieval thresholds for videos
VIDEO_MIN_SCORE = 1.5  # Higher threshold for better relevance
VIDEO_MIN_CHUNKS = 1
VIDEO_LIMIT = 10  # Get more to allow for deduplication

# Intent-specific topic keywords: video must contain at least one to be relevant.
# Prevents e.g. meditation videos that mention "chemotherapy" from matching nutrition queries.
INTENT_TOPIC_KEYWORDS: Dict[IntentCategory, List[str]] = {
    IntentCategory.NUTRITION: [
        # Core diet/food terms - require in TITLE for strictness
        "food", "foods", "eat", "eating", "nutrition", "diet", "dietary", "dietitian",
        "recipe", "recipes", "meal", "meals", "cooking", "snack", "snacks",
        "drink", "drinks", "fluid", "fluids", "fruit", "fruits", "vegetable", "vegetables",
        "protein", "calorie", "calories", "appetite",
    ],
    IntentCategory.EXERCISE: [
        "exercise", "exercises", "movement", "physical", "activity", "workout",
        "fitness", "stretching", "walking", "yoga", "strength", "lymphedema",
    ],
    IntentCategory.SIDE_EFFECTS: [
        "side effect", "side effects", "nausea", "fatigue", "hair", "neuropathy",
        "mouth", "taste", "constipation", "diarrhea", "hot flush", "joint",
    ],
    IntentCategory.EMOTIONAL_SUPPORT: [
        "emotional", "anxiety", "stress", "cope", "coping", "support", "mental",
        "meditation", "mindfulness", "journaling", "gratitude", "counseling",
    ],
    IntentCategory.SURGERY_PROCEDURES: [
        "surgery", "surgical", "lumpectomy", "mastectomy", "reconstruction",
        "lymph node", "biopsy", "operation",
    ],
    IntentCategory.DRAINS_WOUND_CARE: [
        "drain", "drains", "wound", "incision", "healing", "scar", "infection",
    ],
    IntentCategory.CANCER_TREATMENT: [
        "chemotherapy", "chemo", "radiation", "radiotherapy", "hormone therapy",
        "targeted therapy", "immunotherapy", "treatment",
    ],
    IntentCategory.MEDICATION_INFO: [
        "medication", "medicine", "drug", "tamoxifen", "herceptin", "dose",
        "pill", "tablet", "prescription",
    ],
    IntentCategory.CLOTHING: [
        "clothing", "bra", "bras", "prosthetic", "prosthesis", "comfort",
        "dressing", "garment", "mastectomy",
    ],
}


class VideoRetrievalAgent(BaseAgent):
    """
    Agent that retrieves relevant YouTube video transcripts.
    
    Searches the youtube_transcripts index and returns video suggestions
    with deduplication (one chunk per video_id).
    """
    
    def __init__(self):
        super().__init__(
            name="video_retrieval_agent",
            model_type=ModelType.FAST,  # No LLM needed, just retrieval
            timeout_ms=10000  # 10 second timeout
        )
        self._kb_service: Optional[KnowledgeBaseService] = None
    
    def _get_kb_service(self) -> KnowledgeBaseService:
        """Get or create KnowledgeBaseService for YouTube KB."""
        if self._kb_service is None:
            self._kb_service = KnowledgeBaseService(
                use_vectors=True,
                index_name=VIDEO_KB_INDEX
            )
        return self._kb_service
    
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Retrieve relevant video transcripts from YouTube KB.
        
        Args:
            context: Pipeline context with user message
            
        Returns:
            Updated context with video_retrieval_result populated
        """
        logger.info(f"VideoRetrievalAgent processing: {context.user_message[:50]}...")
        
        try:
            kb_service = self._get_kb_service()
            
            # Search is async, so we can await it directly
            logger.info(f"VideoRetrievalAgent: Searching '{VIDEO_KB_INDEX}' for: {context.user_message[:50]}...")
            rag_result = await kb_service.search_chunks_for_rag(
                query=context.user_message,
                limit=VIDEO_LIMIT,
                min_chunks=VIDEO_MIN_CHUNKS,
                min_score=VIDEO_MIN_SCORE,
                require_keyword_match=True  # Require keyword match for better relevance
            )
            
            # Convert to VideoRetrievalChunk format with deduplication
            raw_chunks = rag_result.get("chunks", [])
            logger.info(
                f"VideoRetrievalAgent: Found {len(raw_chunks)} raw chunks from search. "
                f"sufficient_evidence={rag_result.get('has_sufficient_evidence', False)}"
            )
            
            if raw_chunks:
                logger.info(f"VideoRetrievalAgent: First chunk keys: {list(raw_chunks[0].keys())}")
                if raw_chunks[0].get("video_id"):
                    logger.info(f"VideoRetrievalAgent: First chunk video_id: {raw_chunks[0].get('video_id')}")
                else:
                    logger.warning(f"VideoRetrievalAgent: First chunk missing video_id! document_id={raw_chunks[0].get('document_id')}")
            
            # Filter for relevance before processing (use intent for topic-specific matching)
            # Note: intent_result.intent may be a string (due to use_enum_values=True) or enum
            intent_raw = context.intent_result.intent if context.intent_result else IntentCategory.UNKNOWN
            # Convert string to IntentCategory enum if needed
            if isinstance(intent_raw, str):
                try:
                    intent = IntentCategory(intent_raw)
                except ValueError:
                    intent = IntentCategory.UNKNOWN
            else:
                intent = intent_raw
            filtered_chunks = self._filter_relevant_chunks(raw_chunks, context.user_message, intent)
            logger.info(f"VideoRetrievalAgent: Filtered to {len(filtered_chunks)} relevant chunks (from {len(raw_chunks)})")
            
            videos = self._process_video_chunks(filtered_chunks)
            
            context.video_retrieval_result = VideoRetrievalResult(
                videos=videos,
                total_retrieved=len(videos),
                sufficient_videos=len(videos) >= 1,
                knowledge_base_used=VIDEO_KB_INDEX
            )
            
            logger.info(
                f"Video retrieval complete: {len(videos)} unique videos found "
                f"(from {len(rag_result.get('chunks', []))} chunks)"
            )
            
        except Exception as e:
            logger.error(f"Video retrieval failed: {e}")
            # Return empty result on failure - don't break the pipeline
            context.video_retrieval_result = VideoRetrievalResult(
                videos=[],
                total_retrieved=0,
                sufficient_videos=False,
                knowledge_base_used=VIDEO_KB_INDEX
            )
        
        return context
    
    def _filter_relevant_chunks(
        self,
        chunks: List[Dict[str, Any]],
        query: str,
        intent: IntentCategory = IntentCategory.UNKNOWN,
    ) -> List[Dict[str, Any]]:
        """
        Filter chunks to ensure they're relevant to the query and intent.
        
        - For NUTRITION intent: require topic keyword in VIDEO TITLE (not just content)
          to avoid meditation/emotional videos that mention food in passing.
        - Other intents with topic keywords: check title+content.
        - Otherwise: require core keyword match or 2+ general query-term matches.
        """
        if not chunks:
            return []
        
        topic_keywords: Optional[List[str]] = None
        if intent in INTENT_TOPIC_KEYWORDS:
            topic_keywords = [kw.lower() for kw in INTENT_TOPIC_KEYWORDS[intent]]
        
        # Negative keywords by intent - if title contains these, likely wrong topic
        # Medical/physical intents should NOT match emotional/mindfulness videos
        emotional_negative = [
            "meditation", "meditate", "journaling", "journal", "gratitude",
            "mindfulness", "anxiety", "stress relief", "emotional", "cope", "coping",
            "mental health", "well-being", "wellbeing",
        ]
        general_negative = ["q&a", "question", "ask me"]
        
        negative_keywords_by_intent: Dict[IntentCategory, List[str]] = {
            IntentCategory.NUTRITION: emotional_negative + general_negative,
            IntentCategory.SIDE_EFFECTS: emotional_negative + general_negative,
            IntentCategory.CANCER_TREATMENT: emotional_negative + general_negative,
            IntentCategory.SURGERY_PROCEDURES: emotional_negative + general_negative,
            IntentCategory.MEDICATION_INFO: emotional_negative + general_negative,
            IntentCategory.EXERCISE: emotional_negative + general_negative,
            IntentCategory.DRAINS_WOUND_CARE: emotional_negative + general_negative,
            IntentCategory.EMOTIONAL_SUPPORT: [
                "recipe", "recipes", "cooking", "calorie", "protein",
                "exercise", "workout", "fitness",
            ],
        }
        negative_keywords = negative_keywords_by_intent.get(intent, [])
        
        # Extract key terms from query (remove common words)
        query_lower = query.lower()
        stop_words = {'what', 'is', 'the', 'a', 'an', 'can', 'help', 'with', 'for', 'in', 'on', 'at', 'to', 'of', 'and', 'or', 'but', 'are', 'do', 'does', 'how', 'should', 'i', 'my', 'during'}
        query_terms = [t for t in query_lower.split() if t not in stop_words and len(t) > 2]
        core_keywords = [t for t in query_terms if len(t) > 5]
        if not core_keywords:
            core_keywords = query_terms[:2] if len(query_terms) >= 2 else query_terms
        
        relevant_chunks = []
        for chunk in chunks:
            title = (chunk.get("video_title") or chunk.get("title") or "").lower()
            content = (chunk.get("content") or "").lower()
            combined = f"{title} {content}"
            
            # Check for strong title match FIRST - if video title directly matches query topic, include it
            # This handles cases where intent classification doesn't perfectly match
            strong_match_terms = {
                "pregnant": ["pregnancy", "pregnant", "baby", "fertility", "conceive"],
                "hair": ["hair loss", "lose my hair", "hair fall"],
                "exercise": ["exercise", "workout", "physical activity", "fitness"],
                "recurrence": ["recurrence", "come back", "return"],
                "mastectomy": ["mastectomy"],
                "lumpectomy": ["lumpectomy"],
                "reconstruction": ["reconstruction"],
            }
            
            has_strong_title_match = False
            for query_term, title_terms in strong_match_terms.items():
                if query_term in query_lower:
                    if any(tt in title for tt in title_terms):
                        has_strong_title_match = True
                        logger.info(f"Strong title match for '{query_term}': {chunk.get('video_title', 'Unknown')[:60]}...")
                        break
            
            if has_strong_title_match:
                relevant_chunks.append(chunk)
                continue
            
            # Check negative keywords (in title only)
            if negative_keywords and any(neg in title for neg in negative_keywords):
                logger.info(
                    f"Filtered out video (negative keyword in title): {chunk.get('video_title', 'Unknown')[:60]}..."
                )
                continue
            
            if topic_keywords:
                # For specific medical intents: require topic keyword in TITLE
                # This prevents irrelevant videos that mention keywords in passing
                title_strict_intents = {
                    IntentCategory.NUTRITION,
                    IntentCategory.SIDE_EFFECTS,
                    IntentCategory.EXERCISE,
                    IntentCategory.MEDICATION_INFO,
                }
                
                if intent in title_strict_intents:
                    has_topic_in_title = any(kw in title for kw in topic_keywords)
                    if not has_topic_in_title:
                        logger.info(
                            f"Filtered out video (no {intent.value} keyword in TITLE): {chunk.get('video_title', 'Unknown')[:60]}..."
                        )
                        continue
                else:
                    # Other intents: check combined title+content
                    has_topic = any(kw in combined for kw in topic_keywords)
                    if not has_topic:
                        logger.debug(
                            f"Filtered out video (no topic match): {chunk.get('video_title', 'Unknown')[:60]}..."
                        )
                        continue
                relevant_chunks.append(chunk)
                continue
            
            # No topic map: use query-term relevance with fuzzy matching
            if not query_terms:
                relevant_chunks.append(chunk)
                continue
            
            # Check for matches including partial/stem matches
            def has_match(term: str, text: str) -> bool:
                """Check if term matches in text, including common variations."""
                if term in text:
                    return True
                # Handle common word stems (e.g., pregnant/pregnancy, exercise/exercising)
                stem_map = {
                    "pregnant": ["pregnan", "fertility", "baby", "conceive"],
                    "exercise": ["exercis", "workout", "fitness", "physical activity"],
                    "hair": ["hair loss", "losing hair", "bald"],
                    "food": ["eat", "diet", "nutrition", "meal"],
                    "treatment": ["therap", "chemo", "radiation"],
                }
                if term in stem_map:
                    return any(stem in text for stem in stem_map[term])
                # Check if term stem (first 5+ chars) appears
                if len(term) >= 5 and term[:5] in text:
                    return True
                return False
            
            matching = sum(1 for t in query_terms if has_match(t, combined))
            core_matches = sum(1 for k in core_keywords if has_match(k, combined))
            
            # Prioritize title matches
            title_matches = sum(1 for t in query_terms if has_match(t, title))
            
            if title_matches >= 2 or core_matches >= 1 or matching >= 2:
                relevant_chunks.append(chunk)
            else:
                logger.debug(
                    f"Filtered out video: {chunk.get('video_title', 'Unknown')} "
                    f"(title: {title_matches}, core: {core_matches}/{len(core_keywords)}, general: {matching}/{len(query_terms)})"
                )
        
        return relevant_chunks
    
    def _process_video_chunks(
        self,
        chunks: List[Dict[str, Any]]
    ) -> List[VideoRetrievalChunk]:
        """
        Process raw chunks into VideoRetrievalChunk objects with deduplication.
        
        Keeps only the highest-scoring chunk per video_id to avoid
        suggesting the same video multiple times.
        
        Args:
            chunks: Raw chunk data from search_chunks_for_rag
            
        Returns:
            List of deduplicated VideoRetrievalChunk objects
        """
        # Track best chunk per video_id
        best_by_video: Dict[str, Dict[str, Any]] = {}
        
        for chunk in chunks:
            # Extract video_id from chunk data
            # Fields are at top level in youtube_transcripts index (after our fix)
            video_id = chunk.get("video_id") or chunk.get("metadata", {}).get("video_id", "")
            
            if not video_id:
                # Try to extract from document_id (format: youtube_{video_id}_{chunk_index})
                doc_id = chunk.get("document_id", chunk.get("chunk_id", ""))
                if doc_id and doc_id.startswith("youtube_"):
                    parts = doc_id.split("_")
                    if len(parts) >= 2:
                        video_id = parts[1]
            
            if not video_id:
                logger.warning(
                    f"Skipping chunk without video_id. "
                    f"chunk_id={chunk.get('chunk_id', 'unknown')}, "
                    f"document_id={chunk.get('document_id', 'unknown')}, "
                    f"keys={list(chunk.keys())}"
                )
                continue
            
            score = chunk.get("relevance_score", chunk.get("score", 0.0))
            
            # Keep only the highest-scoring chunk per video
            if video_id not in best_by_video or score > best_by_video[video_id].get("score", 0):
                best_by_video[video_id] = {
                    "chunk": chunk,
                    "score": score,
                    "video_id": video_id
                }
        
        # Convert to VideoRetrievalChunk objects
        videos = []
        for video_id, data in best_by_video.items():
            chunk = data["chunk"]
            
            # Extract fields from chunk (top-level in youtube_transcripts index)
            video_title = (
                chunk.get("video_title") or 
                chunk.get("title") or 
                chunk.get("metadata", {}).get("video_title", "Unknown Video")
            )
            video_url = (
                chunk.get("video_url") or 
                chunk.get("metadata", {}).get("video_url", f"https://www.youtube.com/watch?v={video_id}")
            )
            channel_name = (
                chunk.get("channel") or 
                chunk.get("channel_name") or 
                chunk.get("metadata", {}).get("channel")
            )
            timestamped_url = (
                chunk.get("timestamped_url") or 
                chunk.get("metadata", {}).get("timestamped_url")
            )
            
            # Extract timestamps (stored as floats, convert to int)
            start_seconds = chunk.get("start_seconds") or chunk.get("metadata", {}).get("start_seconds")
            end_seconds = chunk.get("end_seconds") or chunk.get("metadata", {}).get("end_seconds")
            
            timestamp_start = int(start_seconds) if start_seconds else None
            timestamp_end = int(end_seconds) if end_seconds else None
            
            # Get transcript content
            transcript_excerpt = chunk.get("content", "")
            
            video_chunk = VideoRetrievalChunk(
                chunk_id=chunk.get("chunk_id", chunk.get("document_id", f"youtube_{video_id}")),
                video_id=video_id,
                video_title=video_title,
                video_url=video_url,
                channel_name=channel_name,
                transcript_excerpt=transcript_excerpt,
                timestamp_start=timestamp_start,
                timestamp_end=timestamp_end,
                timestamped_url=timestamped_url,
                score=data["score"],
                metadata={
                    "start_timestamp": chunk.get("start_timestamp"),
                    "end_timestamp": chunk.get("end_timestamp"),
                    "chunk_index": chunk.get("chunk_index"),
                    **chunk.get("metadata", {})
                }
            )
            videos.append(video_chunk)
        
        # Sort by score descending
        videos.sort(key=lambda v: v.score, reverse=True)
        
        # Deduplicate similar titles (keep highest scoring)
        # Two titles are "similar" if they share significant words
        def normalize_title(title: str) -> set:
            """Extract significant words from title for comparison."""
            stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                         'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
                         'dr', 'tasha', 'episode', 'part', 'video'}
            words = set(w.lower() for w in title.split() if len(w) > 2 and w.lower() not in stop_words)
            # Remove numbers and special chars
            words = {w.strip('0123456789-:()[]') for w in words}
            words = {w for w in words if len(w) > 2}
            return words
        
        def titles_are_similar(title1: str, title2: str) -> bool:
            """Check if two titles are similar enough to be duplicates."""
            words1 = normalize_title(title1)
            words2 = normalize_title(title2)
            if not words1 or not words2:
                return False
            # Calculate Jaccard similarity
            intersection = len(words1 & words2)
            union = len(words1 | words2)
            similarity = intersection / union if union > 0 else 0
            return similarity > 0.6  # 60% word overlap = similar
        
        unique_videos = []
        for video in videos:
            is_duplicate = False
            for existing in unique_videos:
                if video.video_id == existing.video_id:
                    is_duplicate = True
                    break
                if titles_are_similar(video.video_title, existing.video_title):
                    logger.info(f"Filtered similar title: '{video.video_title[:50]}' ~ '{existing.video_title[:50]}'")
                    is_duplicate = True
                    break
            if not is_duplicate:
                unique_videos.append(video)
        
        # Return max 3 unique videos
        return unique_videos[:3]
    
    def _get_output_summary(self, context: PipelineContext) -> Optional[str]:
        """Generate output summary for logging."""
        if context.video_retrieval_result:
            r = context.video_retrieval_result
            return (
                f"kb={r.knowledge_base_used}, "
                f"videos={r.total_retrieved}, "
                f"sufficient={r.sufficient_videos}"
            )
        return None
