"""
Video Retrieval Agent
Fetches relevant YouTube video transcripts based on user query.
Runs in parallel with RetrievalAgent to provide video suggestions.

Spec Reference: ProjectSpec.md v1.2, Section 13
"""

import logging
import asyncio
from typing import Optional, Dict, Any, List

from services.agents.base_agent import BaseAgent
from models.schemas import (
    PipelineContext,
    VideoRetrievalResult,
    VideoRetrievalChunk
)
from config.pipeline_config import ModelType
from services.knowledge_base import KnowledgeBaseService

logger = logging.getLogger(__name__)

# YouTube KB index name (matches the ingested index)
VIDEO_KB_INDEX = "youtube_transcripts"

# Retrieval thresholds for videos (more lenient than documents)
VIDEO_MIN_SCORE = 0.6
VIDEO_MIN_CHUNKS = 1
VIDEO_LIMIT = 10  # Get more to allow for deduplication


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
                require_keyword_match=False  # More lenient for videos
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
            
            videos = self._process_video_chunks(raw_chunks)
            
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
        
        # Return top 5 unique videos
        return videos[:5]
    
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
