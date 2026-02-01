"""
Application Settings and Configuration
Loads from environment variables with sensible defaults
"""

import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from functools import lru_cache
from dotenv import load_dotenv

# Load environment variables from .env file
# This ensures boto3 and other AWS SDKs can find credentials
load_dotenv()


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

