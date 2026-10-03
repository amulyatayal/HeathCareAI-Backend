"""
Patient Document Service
DynamoDB metadata + S3 file storage for patient-uploaded medical documents.

Table: PatientDocuments
  PK = user_id   (links to PatientProfiles)
  SK = document_id
"""

import logging
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from config.settings import settings
from config.aws import get_dynamodb_resource, s3 as get_s3
from models.document_schemas import PatientDocument

logger = logging.getLogger(__name__)

ACCEPTED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}

MAX_FILE_BYTES = settings.patient_document_max_file_bytes
STORAGE_LIMIT_BYTES = settings.patient_document_storage_limit_bytes


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


class DocumentService:
    """CRUD for patient documents backed by DynamoDB (metadata) and S3 (files)."""

    TABLE_NAME = "PatientDocuments"

    def __init__(self):
        self.dynamodb = get_dynamodb_resource()
        self.table = self.dynamodb.Table(self.TABLE_NAME)
        self.bucket = settings.s3_bucket_name
        self.prefix = settings.s3_document_prefix

    def _s3_key(self, user_id: str, document_id: str, extension: str) -> str:
        return f"{self.prefix}/{user_id}/{document_id}.{extension}"

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    async def list_documents(self, user_id: str) -> Tuple[List[PatientDocument], int]:
        """Return (active_docs, total_size_bytes) for a user."""
        try:
            response = self.table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key("user_id").eq(user_id),
                ScanIndexForward=False,
            )
            items = response.get("Items", [])
            docs = [PatientDocument.from_dynamodb_item(i) for i in items if i.get("status", "active") == "active"]
            docs.sort(key=lambda d: d.uploaded_at, reverse=True)
            total_bytes = sum(d.size_bytes for d in docs)
            return docs, total_bytes
        except ClientError as e:
            logger.error(f"Error listing documents for {user_id}: {e}")
            raise

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    async def upload_document(
        self,
        user_id: str,
        file_content: bytes,
        filename: str,
        content_type: str,
    ) -> PatientDocument:
        """
        Upload file to S3 and write metadata to DynamoDB.

        Raises ValueError for validation failures,
        and generic Exception for AWS errors.
        """
        short_type = ACCEPTED_CONTENT_TYPES.get(content_type)
        if not short_type:
            raise ValueError(f"Unsupported file type: {content_type}. Accepted: PDF, JPG, PNG.")

        size_bytes = len(file_content)
        if size_bytes > MAX_FILE_BYTES:
            raise ValueError(f"File too large ({_format_size(size_bytes)}). Maximum is {_format_size(MAX_FILE_BYTES)}.")

        _, total_used = await self.list_documents(user_id)
        if total_used + size_bytes > STORAGE_LIMIT_BYTES:
            raise OverflowError("Storage limit reached. Delete some documents to free up space.")

        document_id = str(uuid.uuid4())
        s3_key = self._s3_key(user_id, document_id, short_type)
        now = datetime.utcnow()

        try:
            get_s3().put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=file_content,
                ContentType=content_type,
                Metadata={"user_id": user_id, "original_filename": filename},
            )
        except ClientError as e:
            logger.error(f"S3 upload failed for {user_id}/{document_id}: {e}")
            raise

        doc = PatientDocument(
            user_id=user_id,
            document_id=document_id,
            name=filename,
            content_type=content_type,
            type=short_type,
            size_bytes=size_bytes,
            size=_format_size(size_bytes),
            s3_key=s3_key,
            uploaded_at=now,
        )

        try:
            self.table.put_item(Item=doc.to_dynamodb_item())
            logger.info(f"Document uploaded: user={user_id}, doc={document_id}, size={doc.size}")
        except ClientError as e:
            # Best-effort rollback: delete S3 object
            try:
                get_s3().delete_object(Bucket=self.bucket, Key=s3_key)
            except Exception:
                logger.warning(f"S3 rollback failed for {s3_key}")
            raise

        return doc

    # ------------------------------------------------------------------
    # Download (presigned URL)
    # ------------------------------------------------------------------

    async def get_download_url(self, user_id: str, document_id: str, expires_in: int = 300) -> str:
        """
        Generate a presigned S3 GET URL valid for ``expires_in`` seconds.

        Raises ValueError if the document doesn't exist or belong to the user.
        """
        doc = await self._get_document(user_id, document_id)

        try:
            url = get_s3().generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": doc.s3_key,
                    "ResponseContentDisposition": f'attachment; filename="{doc.name}"',
                },
                ExpiresIn=expires_in,
            )
            return url
        except ClientError as e:
            logger.error(f"Presigned URL failed for {doc.s3_key}: {e}")
            raise

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_document(self, user_id: str, document_id: str) -> None:
        """Soft-delete by marking status='deleted' and removing S3 object."""
        doc = await self._get_document(user_id, document_id)

        try:
            get_s3().delete_object(Bucket=self.bucket, Key=doc.s3_key)
        except ClientError as e:
            logger.warning(f"S3 delete failed for {doc.s3_key}: {e}")

        try:
            self.table.update_item(
                Key={"user_id": user_id, "document_id": document_id},
                UpdateExpression="SET #s = :s",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "deleted"},
            )
            logger.info(f"Document deleted: user={user_id}, doc={document_id}")
        except ClientError as e:
            logger.error(f"DynamoDB delete failed for {user_id}/{document_id}: {e}")
            raise

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_document(self, user_id: str, document_id: str) -> PatientDocument:
        """Fetch a single active document; raises ValueError if not found."""
        try:
            resp = self.table.get_item(Key={"user_id": user_id, "document_id": document_id})
            item = resp.get("Item")
            if not item or item.get("status") == "deleted":
                raise ValueError(f"Document {document_id} not found")
            return PatientDocument.from_dynamodb_item(item)
        except ClientError as e:
            logger.error(f"Error fetching document {document_id}: {e}")
            raise


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_service_instance: Optional[DocumentService] = None


def get_document_service() -> DocumentService:
    global _service_instance
    if _service_instance is None:
        _service_instance = DocumentService()
    return _service_instance
