"""
Request/response models for patient privacy APIs (export, erasure).
"""

from pydantic import BaseModel, Field


class AccountDeletionRequest(BaseModel):
    confirmation: str = Field(
        ...,
        description='Must be exactly: DELETE MY ACCOUNT',
    )


class AccountDeletionResponse(BaseModel):
    message: str


DELETE_ACCOUNT_CONFIRMATION = "DELETE MY ACCOUNT"
