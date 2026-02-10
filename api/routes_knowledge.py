"""
Knowledge Base API Routes
Provides endpoints for searching, managing documents, and listing indexes/categories
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException

from models.schemas_rag import (
    KnowledgeSearchRequest, KnowledgeSearchResponse,
    KnowledgeDocument, DocumentUploadResponse,
    QueryCategory, ContentType
)
from services.knowledge_base import get_knowledge_base

logger = logging.getLogger(__name__)


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
