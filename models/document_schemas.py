"""
Patient Document Models
Pydantic schemas for medical document storage and retrieval.

Documents are stored in S3 and metadata is persisted in DynamoDB.
Each document is linked to a PatientProfile via user_id.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
import uuid


def _generate_document_id() -> str:
    return str(uuid.uuid4())


class PatientDocument(BaseModel):
    """Metadata record stored in the PatientDocuments DynamoDB table."""

    user_id: str = Field(..., description="Firebase UID (partition key, links to PatientProfiles)")
    document_id: str = Field(default_factory=_generate_document_id, description="Unique document ID (sort key)")
    name: str = Field(..., description="Display name (original filename)")
    content_type: str = Field(..., description="MIME type, e.g. application/pdf")
    type: str = Field(..., description="Short type label: pdf, jpg, png")
    size_bytes: int = Field(..., description="File size in bytes")
    size: str = Field(..., description="Human-readable size, e.g. '1.2 MB'")
    s3_key: str = Field(..., description="S3 object key for the stored file")
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = Field(default="active", description="active | deleted")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None,
        }

    def to_dynamodb_item(self) -> dict:
        data = self.dict()
        if isinstance(data.get("uploaded_at"), datetime):
            data["uploaded_at"] = data["uploaded_at"].isoformat()
        return data

    @classmethod
    def from_dynamodb_item(cls, item: dict) -> "PatientDocument":
        if item.get("uploaded_at") and isinstance(item["uploaded_at"], str):
            try:
                item["uploaded_at"] = datetime.fromisoformat(item["uploaded_at"].replace("Z", "+00:00"))
            except ValueError:
                item["uploaded_at"] = datetime.utcnow()
        if "size_bytes" in item:
            item["size_bytes"] = int(item["size_bytes"])
        return cls(**item)


class DocumentMetaResponse(BaseModel):
    id: str
    name: str
    type: str
    date: str
    size: str
    size_bytes: int


class DocumentListResponse(BaseModel):
    documents: List[DocumentMetaResponse]
    total_count: int
    total_size_bytes: int
    storage_limit_bytes: int
    max_file_size_bytes: int


class UploadDocumentResponse(BaseModel):
    id: str
    name: str
    type: str
    size: str
    uploaded_at: str
    message: str = "Document uploaded successfully"
