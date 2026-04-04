"""
Document API Routes
Endpoints for patient medical document upload, download, and deletion.

All endpoints require authentication — guest users cannot manage documents.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import RedirectResponse

from config.settings import settings
from models.document_schemas import (
    DocumentListResponse,
    DocumentMetaResponse,
    UploadDocumentResponse,
)
from services.document_service import get_document_service
from api.auth import get_authenticated_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Patient Documents"])

ACCEPTED_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_FILE_BYTES = settings.patient_document_max_file_bytes


@router.get("", response_model=DocumentListResponse)
async def list_documents(user_id: str = Depends(get_authenticated_user_id)):
    """Return all active documents for the authenticated patient."""
    service = get_document_service()
    docs, total_bytes = await service.list_documents(user_id)

    return DocumentListResponse(
        documents=[
            DocumentMetaResponse(
                id=d.document_id,
                name=d.name,
                type=d.type,
                date=d.uploaded_at.isoformat(),
                size=d.size,
                size_bytes=d.size_bytes,
            )
            for d in docs
        ],
        total_count=len(docs),
        total_size_bytes=total_bytes,
        storage_limit_bytes=settings.patient_document_storage_limit_bytes,
        max_file_size_bytes=settings.patient_document_max_file_bytes,
    )


@router.post("/upload", response_model=UploadDocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    name: str = Query(None, description="Optional display name override"),
    user_id: str = Depends(get_authenticated_user_id),
):
    """Upload a medical document (PDF, JPG, PNG)."""
    content_type = file.content_type or ""
    if content_type not in ACCEPTED_CONTENT_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported file type: {content_type}. Accepted: PDF, JPG, PNG.")

    content = await file.read()
    if len(content) > MAX_FILE_BYTES:
        limit_mb = MAX_FILE_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {limit_mb} MB.")

    display_name = name or file.filename or "Untitled"

    service = get_document_service()
    try:
        doc = await service.upload_document(user_id, content, display_name, content_type)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except OverflowError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return UploadDocumentResponse(
        id=doc.document_id,
        name=doc.name,
        type=doc.type,
        size=doc.size,
        uploaded_at=doc.uploaded_at.isoformat(),
    )


@router.get("/{document_id}/download")
async def download_document(
    document_id: str,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Redirect to a short-lived presigned S3 URL for the document."""
    service = get_document_service()
    try:
        url = await service.get_download_url(user_id, document_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found")

    return RedirectResponse(url=url, status_code=307)


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    user_id: str = Depends(get_authenticated_user_id),
):
    """Soft-delete a document and remove the file from S3."""
    service = get_document_service()
    try:
        await service.delete_document(user_id, document_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found")

    return {"message": "Document deleted successfully"}
