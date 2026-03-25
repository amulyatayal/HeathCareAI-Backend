"""
Application Settings and Configuration
Loads from environment variables with sensible defaults
"""

import os
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # AWS Configuration
    aws_region: str = "us-east-1"
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    
    # OpenSearch Configuration (Managed Cluster)
    opensearch_endpoint: str = ""
    opensearch_index: str = "breast_cancer_knowledge"
    opensearch_username: Optional[str] = None
    opensearch_password: Optional[str] = None
    
    # Bedrock Configuration
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    bedrock_embedding_model: str = "amazon.titan-embed-text-v2:0"
    
    # S3 Configuration
    s3_bucket_name: str = "healthcare-ai-documents"
    s3_region: str = "us-east-1"
    
    # Application Configuration
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"
    enable_structured_logging: bool = True
    enable_metrics: bool = False
    metrics_namespace: str = "healthcare_ai_backend"
    
    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    
    # Chat (POST /api/v2/chat/) — guests never require OAuth; optional X-User-ID for sessions.
    # Y (default): normal behavior (anonymous guests use user_id=None unless X-User-ID is sent).
    # N: when neither Bearer nor X-User-ID is sent, use unauthenticated_test_user_id (CI/tests).
    is_authentication_required: str = Field(
        default="Y",
        description="Y=default guest handling; N=synthetic test user id when no headers (tests)",
    )
    unauthenticated_test_user_id: str = Field(
        default="anonymous_test",
        description="Guest user id when IS_AUTHENTICATION_REQUIRED=N and request has no Bearer/X-User-ID",
    )
    
    # CORS
    allowed_origins: str = "http://localhost:3000,http://localhost:8080"
    
    # Rate Limiting
    rate_limit_requests: int = 100
    rate_limit_window: int = 60
    
    # Knowledge Base
    kb_chunk_size: int = 500
    kb_chunk_overlap: int = 50
    kb_embedding_dimension: int = 1024
    
    @property
    def cors_origins(self) -> List[str]:
        """Parse CORS origins from comma-separated string"""
        return [origin.strip() for origin in self.allowed_origins.split(",")]
    
    @property
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.app_env.lower() == "production"
    
    @property
    def chat_authentication_required(self) -> bool:
        """
        True (default): normal chat — guests do not need OAuth.
        False (N): use synthetic test user id for fully anonymous requests (tests only).
        """
        v = (self.is_authentication_required or "Y").strip().upper()
        return v not in ("N", "NO", "0", "FALSE")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Convenience access
settings = get_settings()

