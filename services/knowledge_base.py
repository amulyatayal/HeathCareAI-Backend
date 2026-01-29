"""
Knowledge Base Service
Manages medical knowledge for breast cancer patient queries
Uses OpenSearch for hybrid search (vector + keyword)
"""

import json
import time
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from config import settings, bedrock, opensearch
from models.schemas_deprecated import (
    KnowledgeDocument, KnowledgeSearchRequest, KnowledgeSearchResponse,
    KnowledgeSearchResult, QueryCategory, ContentType
)

logger = logging.getLogger(__name__)

# Hybrid search weights (tune these for best results)
VECTOR_WEIGHT = 0.7  # Weight for semantic/vector similarity
KEYWORD_WEIGHT = 0.3  # Weight for keyword matching

# Evidence gating configuration for RAG
MIN_CHUNKS_REQUIRED = 3  # Minimum chunks needed to generate answer
MIN_SCORE_THRESHOLD = 5.0  # Minimum relevance score for a chunk
KEYWORD_MATCH_REQUIRED = True  # Require at least one chunk with keyword match


# ================================
# Embedding Service
# ================================

class EmbeddingService:
    """Generate embeddings using AWS Bedrock Titan"""
    
    def __init__(self):
        self.model_id = settings.bedrock_embedding_model
        self.dimension = settings.kb_embedding_dimension
        self._client = None
    
    def _get_client(self):
        """Lazy load Bedrock client"""
        if self._client is None:
            self._client = bedrock()
        return self._client
    
    def create_embedding(self, text: str) -> Optional[List[float]]:
        """Create embedding for text using Titan"""
        try:
            client = self._get_client()
            
            body = json.dumps({
                "inputText": text[:8000]  # Titan limit
            })
            
            response = client.invoke_model(
                modelId=self.model_id,
                body=body
            )
            
            response_body = json.loads(response['body'].read())
            embedding = response_body.get('embedding', [])
            
            logger.debug(f"Created embedding with {len(embedding)} dimensions")
            return embedding
            
        except Exception as e:
            logger.error(f"Error creating embedding: {e}")
            return None


# ================================
# OpenSearch Index Management
# ================================

def get_index_mapping(use_vectors: bool = True) -> Dict[str, Any]:
    """Get OpenSearch index mapping for knowledge base"""
    mappings = {
        "properties": {
            "document_id": {"type": "keyword"},
            "title": {"type": "text", "analyzer": "standard"},
            "content": {"type": "text", "analyzer": "standard"},
            "content_type": {"type": "keyword"},
            "category": {"type": "keyword"},
            "source_url": {"type": "keyword"},
            "author": {"type": "text"},
            "published_date": {"type": "date"},
            "tags": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"}
        }
    }
    
    # Add vector field only if using vector search
    if use_vectors:
        mappings["properties"]["embedding"] = {
            "type": "knn_vector",
            "dimension": settings.kb_embedding_dimension,
            "method": {
                "name": "hnsw",
                "space_type": "cosinesimil",
                "engine": "faiss",
                "parameters": {
                    "ef_construction": 512,
                    "m": 16
                }
            }
        }
    
    settings_dict = {
        "index": {
            "number_of_shards": 2,
            "number_of_replicas": 1
        }
    }
    
    # Add KNN setting only if using vectors
    if use_vectors:
        settings_dict["index"]["knn"] = True
    
    return {
        "settings": settings_dict,
        "mappings": mappings
    }


def create_index_if_not_exists(index_name: str = None, use_vectors: bool = True) -> bool:
    """Create OpenSearch index if it doesn't exist
    
    Args:
        index_name: Name of the index to create
        use_vectors: Whether to include vector/KNN fields (requires VECTOR SEARCH collection)
    """
    index_name = index_name or settings.opensearch_index
    
    try:
        client = opensearch()
        
        if not client.indices.exists(index=index_name):
            mapping = get_index_mapping(use_vectors=use_vectors)
            client.indices.create(index=index_name, body=mapping)
            logger.info(f"Created index: {index_name} (vectors={'enabled' if use_vectors else 'disabled'})")
            return True
        else:
            logger.info(f"Index already exists: {index_name}")
            return True
            
    except Exception as e:
        logger.error(f"Error creating index: {e}")
        return False


# ================================
# Knowledge Base Service
# ================================

class KnowledgeBaseService:
    """Service for managing and searching the knowledge base with hybrid search"""
    
    def __init__(self, index_name: str = None, use_vectors: bool = True):
        self.index_name = index_name or settings.opensearch_index
        self.use_vectors = use_vectors
        self.embedding_service = EmbeddingService()  # Always initialize for hybrid search
        self._client = None
    
    def _get_client(self):
        """Lazy load OpenSearch client"""
        if self._client is None:
            self._client = opensearch()
        return self._client
    
    async def add_document(self, document: KnowledgeDocument) -> str:
        """Add a document to the knowledge base with vector embedding"""
        try:
            # Prepare document for indexing
            doc_id = document.id or str(hash(document.title + document.content))
            doc_body = {
                "document_id": doc_id,
                "title": document.title,
                "content": document.content,
                "content_type": document.content_type.value,
                "category": document.category.value,
                "source_url": document.source_url,
                "author": document.author,
                "published_date": document.published_date.isoformat() if document.published_date else None,
                "tags": document.tags,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            
            # Always create embedding for hybrid search
            text_for_embedding = f"{document.title}. {document.content}"
            embedding = self.embedding_service.create_embedding(text_for_embedding)
            
            if embedding:
                doc_body["embedding"] = embedding
                logger.debug(f"Created embedding for document {doc_id}")
            else:
                raise ValueError(f"Failed to create embedding for document {doc_id}")
            
            # Index document
            # Note: OpenSearch Serverless doesn't support custom IDs or refresh parameter
            client = self._get_client()
            response = client.index(
                index=self.index_name,
                body=doc_body
            )
            
            # Get the auto-generated ID from response
            generated_id = response.get('_id', doc_id)
            logger.info(f"Indexed document: {doc_body['document_id']} (ID: {generated_id})")
            return generated_id
            
        except Exception as e:
            logger.error(f"Error adding document: {e}")
            raise
    
    async def search(
        self,
        query: str,
        category: Optional[QueryCategory] = None,
        content_type: Optional[ContentType] = None,
        limit: int = 10
    ) -> KnowledgeSearchResponse:
        """
        Search the knowledge base using HYBRID search (vector + keyword).
        
        Combines semantic similarity (understanding meaning) with keyword matching
        (exact terms) for best results.
        """
        start_time = time.time()
        
        try:
            # Build filters
            filters = []
            if category:
                filters.append({"term": {"category": category.value}})
            if content_type:
                filters.append({"term": {"content_type": content_type.value}})
            
            # Create query embedding for vector search
            query_embedding = self.embedding_service.create_embedding(query)
            
            if not query_embedding:
                raise ValueError("Failed to create query embedding")
            
            # Build hybrid search query combining vector + keyword
            # Using script_score to combine KNN with keyword matching
            hybrid_query = {
                "size": limit * 2,  # Get more results to re-rank
                "query": {
                    "bool": {
                        "should": [
                            # Vector search component (semantic similarity)
                            {
                                "knn": {
                                    "embedding": {
                                        "vector": query_embedding,
                                        "k": limit * 2
                                    }
                                }
                            },
                            # Keyword search component (exact matching)
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": ["title^3", "content"],
                                    "type": "best_fields",
                                    "boost": KEYWORD_WEIGHT / VECTOR_WEIGHT  # Relative weight
                                }
                            }
                        ],
                        "minimum_should_match": 1
                    }
                }
            }
            
            # Add filters if present
            if filters:
                hybrid_query["query"]["bool"]["filter"] = filters
            
            # Execute hybrid search
            client = self._get_client()
            response = client.search(
                index=self.index_name,
                body=hybrid_query
            )
            
            # Parse and deduplicate results
            hits = response.get("hits", {}).get("hits", [])
            seen_docs = set()
            results = []
            
            for hit in hits:
                source = hit["_source"]
                doc_id = source.get("document_id", hit["_id"])
                
                # Skip duplicates (can happen with hybrid search)
                if doc_id in seen_docs:
                    continue
                seen_docs.add(doc_id)
                
                results.append(KnowledgeSearchResult(
                    document_id=doc_id,
                    title=source.get("title", ""),
                    content_excerpt=source.get("content", "")[:500],  # Longer excerpts
                    relevance_score=hit.get("_score", 0.0),
                    content_type=ContentType(source.get("content_type", "faq")),
                    category=QueryCategory(source.get("category", "general")),
                    source_url=source.get("source_url")
                ))
                
                if len(results) >= limit:
                    break
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            logger.info(f"Hybrid search completed: {len(results)} results in {elapsed_ms:.1f}ms")
            
            return KnowledgeSearchResponse(
                results=results,
                total_results=len(results),
                search_time_ms=elapsed_ms
            )
            
        except Exception as e:
            logger.error(f"Error in hybrid search: {e}")
            raise
    
    async def search_chunks_for_rag(
        self,
        query: str,
        limit: int = 15,
        min_chunks: int = MIN_CHUNKS_REQUIRED,
        min_score: float = MIN_SCORE_THRESHOLD,
        require_keyword_match: bool = KEYWORD_MATCH_REQUIRED
    ) -> Dict[str, Any]:
        """
        Search for chunks optimized for RAG retrieval with evidence gating.
        
        This method:
        1. Retrieves top K chunks using hybrid search (BM25 + vector)
        2. Applies evidence gating to ensure quality
        3. Returns chunks with full metadata for citations
        
        Args:
            query: User question
            limit: Max chunks to retrieve (default 15)
            min_chunks: Minimum chunks above threshold required (default 3)
            min_score: Minimum relevance score threshold (default 5.0)
            require_keyword_match: Require at least one chunk with keyword match
        
        Returns:
            Dict with:
            - chunks: List of chunk dicts with content and metadata
            - has_sufficient_evidence: Boolean indicating if evidence is sufficient
            - evidence_stats: Statistics about the retrieved evidence
        """
        start_time = time.time()
        
        try:
            # Create query embedding for vector search
            query_embedding = self.embedding_service.create_embedding(query)
            
            if not query_embedding:
                raise ValueError("Failed to create query embedding")
            
            # Extract keywords from query for keyword match check
            query_keywords = set(query.lower().split())
            # Remove common stop words
            stop_words = {'what', 'how', 'when', 'where', 'why', 'who', 'is', 'are', 
                          'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'of', 'and',
                          'or', 'but', 'with', 'my', 'i', 'me', 'can', 'do', 'does',
                          'should', 'would', 'could', 'will', 'be', 'have', 'has'}
            query_keywords = query_keywords - stop_words
            
            # Keyword search fields: include video_title for YouTube index to improve relevance
            is_video_index = "youtube" in (self.index_name or "").lower()
            mm_fields = ["content^2", "video_title^2"] if is_video_index else ["content^2", "section"]
            
            # Build hybrid search query for chunks
            hybrid_query = {
                "size": limit * 2,  # Get extra for filtering
                "query": {
                    "bool": {
                        "should": [
                            # Vector search component
                            {
                                "knn": {
                                    "embedding": {
                                        "vector": query_embedding,
                                        "k": limit * 2
                                    }
                                }
                            },
                            # Keyword search component
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": mm_fields,
                                    "type": "best_fields",
                                    "boost": KEYWORD_WEIGHT / VECTOR_WEIGHT
                                }
                            }
                        ],
                        "minimum_should_match": 1
                    }
                }
            }
            
            # Execute search
            client = self._get_client()
            response = client.search(
                index=self.index_name,
                body=hybrid_query
            )
            
            # Process results
            hits = response.get("hits", {}).get("hits", [])
            chunks = []
            chunks_above_threshold = 0
            keyword_match_found = False
            
            for hit in hits:
                source = hit["_source"]
                score = hit.get("_score", 0.0)
                content = source.get("content", "")
                
                # Check for keyword match (content; for video index also check title)
                content_lower = content.lower()
                has_keyword_match = any(kw in content_lower for kw in query_keywords)
                if not has_keyword_match and is_video_index:
                    title_lower = (source.get("video_title") or "").lower()
                    has_keyword_match = any(kw in title_lower for kw in query_keywords)
                
                if has_keyword_match:
                    keyword_match_found = True
                
                if score >= min_score:
                    chunks_above_threshold += 1
                
                # Handle both PDF chunks (source_file) and Q&A pairs (source_url)
                source_file = source.get("source_file") or source.get("source_url") or "Unknown"
                
                # Check if this is a video index (youtube_transcripts)
                is_video_index = "youtube" in self.index_name.lower() or "video" in self.index_name.lower()
                
                chunk = {
                    "chunk_id": source.get("chunk_id", hit["_id"]),
                    "document_id": source.get("document_id", hit["_id"]),
                    "content": content,
                    "source_file": source_file,
                    "title": source.get("title") or source.get("video_title"),  # Q&A pairs or videos have title
                    "page_start": source.get("page_start", 1),
                    "page_end": source.get("page_end", 1),
                    "section": source.get("section"),
                    "content_type": source.get("content_type", "medical_article"),
                    "relevance_score": score,
                    "score": score,  # Alias for compatibility
                    "has_keyword_match": has_keyword_match,
                    "answer_type": source.get("answer_type"),  # For per-intent KBs
                    "source_excerpt": source.get("source_excerpt"),  # Verbatim text
                    "metadata": {}  # Store all source fields for video-specific data
                }
                
                # For video indices, include video-specific fields in metadata and top-level
                if is_video_index:
                    chunk["video_id"] = source.get("video_id")
                    chunk["video_title"] = source.get("video_title")
                    chunk["video_url"] = source.get("video_url")
                    chunk["channel"] = source.get("channel")
                    chunk["channel_name"] = source.get("channel")  # Alias
                    chunk["timestamped_url"] = source.get("timestamped_url")
                    chunk["start_seconds"] = source.get("start_seconds")
                    chunk["end_seconds"] = source.get("end_seconds")
                    chunk["start_timestamp"] = source.get("start_timestamp")
                    chunk["end_timestamp"] = source.get("end_timestamp")
                    chunk["chunk_index"] = source.get("chunk_index")
                    # Also store in metadata for compatibility
                    chunk["metadata"] = {
                        "video_id": source.get("video_id"),
                        "video_title": source.get("video_title"),
                        "video_url": source.get("video_url"),
                        "channel": source.get("channel"),
                        "channel_name": source.get("channel"),
                        "timestamped_url": source.get("timestamped_url"),
                        "start_seconds": source.get("start_seconds"),
                        "end_seconds": source.get("end_seconds"),
                        "start_timestamp": source.get("start_timestamp"),
                        "end_timestamp": source.get("end_timestamp"),
                        "chunk_index": source.get("chunk_index")
                    }
                else:
                    # For non-video indices, store all source fields in metadata
                    # Flatten nested metadata from indexed documents (citation_only, derived_answer etc.)
                    base_metadata = {k: v for k, v in source.items() if k not in ["content", "embedding", "metadata"]}
                    nested_metadata = source.get("metadata", {})
                    if isinstance(nested_metadata, dict):
                        base_metadata.update(nested_metadata)
                    chunk["metadata"] = base_metadata
                
                chunks.append(chunk)
                
                if len(chunks) >= limit:
                    break
            
            # Evidence gating check
            has_sufficient_evidence = (
                chunks_above_threshold >= min_chunks and
                (not require_keyword_match or keyword_match_found)
            )
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            evidence_stats = {
                "total_chunks": len(chunks),
                "chunks_above_threshold": chunks_above_threshold,
                "keyword_match_found": keyword_match_found,
                "min_chunks_required": min_chunks,
                "min_score_threshold": min_score,
                "search_time_ms": elapsed_ms
            }
            
            logger.info(
                f"RAG chunk search: {len(chunks)} chunks, "
                f"{chunks_above_threshold} above threshold, "
                f"keyword_match={keyword_match_found}, "
                f"sufficient_evidence={has_sufficient_evidence}"
            )
            
            return {
                "chunks": chunks,
                "has_sufficient_evidence": has_sufficient_evidence,
                "evidence_stats": evidence_stats
            }
            
        except Exception as e:
            logger.error(f"Error in RAG chunk search: {e}")
            raise
    
    async def get_relevant_context(
        self,
        query: str,
        category: Optional[QueryCategory] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get relevant context from knowledge base for AI agent
        Returns simplified format for prompt injection
        """
        try:
            search_response = await self.search(
                query=query,
                category=category,
                limit=limit
            )
            
            context = []
            for result in search_response.results:
                context.append({
                    "title": result.title,
                    "content": result.content_excerpt,
                    "content_type": result.content_type.value,
                    "category": result.category.value,
                    "score": result.relevance_score,
                    "url": result.source_url
                })
            
            return context
            
        except Exception as e:
            logger.error(f"Error getting context: {e}")
            return []
    
    async def delete_document(self, document_id: str) -> bool:
        """Delete a document from the knowledge base"""
        try:
            client = self._get_client()
            client.delete(
                index=self.index_name,
                id=document_id,
                refresh=True
            )
            logger.info(f"Deleted document: {document_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting document: {e}")
            return False
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get knowledge base statistics"""
        try:
            client = self._get_client()
            response = client.indices.stats(index=self.index_name)
            
            total_docs = response["_all"]["primaries"]["docs"]["count"]
            size_bytes = response["_all"]["primaries"]["store"]["size_in_bytes"]
            
            return {
                "index_name": self.index_name,
                "total_documents": total_docs,
                "size_mb": round(size_bytes / (1024 * 1024), 2),
                "status": "healthy"
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "index_name": self.index_name,
                "status": "error",
                "error": str(e)
            }


# ================================
# Singleton Instance
# ================================

_knowledge_base: Optional[KnowledgeBaseService] = None


def get_knowledge_base(use_vectors: bool = True, index_name: str = None) -> KnowledgeBaseService:
    """Get knowledge base service singleton with hybrid search enabled
    
    Args:
        use_vectors: Whether to use vector/hybrid search (default: True)
                    Requires VECTOR SEARCH collection type in OpenSearch Serverless
        index_name: Custom index name (default: from settings)
    """
    global _knowledge_base
    
    # Create a unique key for this instance
    cache_key = f"{index_name or settings.opensearch_index}_{use_vectors}"
    
    if _knowledge_base is None:
        _knowledge_base = {}
    
    if cache_key not in _knowledge_base:
        _knowledge_base[cache_key] = KnowledgeBaseService(
            use_vectors=use_vectors,
            index_name=index_name
        )
        logger.info(f"Initialized KnowledgeBaseService (index={index_name or 'default'}, vectors={use_vectors})")
    
    return _knowledge_base[cache_key]

