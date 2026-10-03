"""
AWS Client Configuration
Initializes Bedrock, OpenSearch, and S3 clients
"""

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
from .settings import settings


def get_bedrock_client():
    """Get Bedrock Runtime client for AI model invocation"""
    return boto3.client(
        service_name='bedrock-runtime',
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key
    )


def get_opensearch_client():
    """Get OpenSearch client for knowledge base queries
    
    Supports two authentication methods:
    1. Username/Password - for managed OpenSearch clusters
    2. AWS SigV4 - for OpenSearch Serverless (aoss)
    """
    if not settings.opensearch_endpoint:
        raise ValueError("OpenSearch endpoint not configured")
    
    # Strip protocol from endpoint if present
    endpoint = settings.opensearch_endpoint
    endpoint = endpoint.replace('https://', '').replace('http://', '')
    
    # Use username/password if provided (managed cluster)
    if settings.opensearch_username and settings.opensearch_password:
        http_auth = (settings.opensearch_username, settings.opensearch_password)
    else:
        # Fall back to AWS SigV4 for Serverless
        service = 'aoss' if 'aoss.amazonaws.com' in endpoint else 'es'
        
        credentials = boto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region
        ).get_credentials()
        
        http_auth = AWS4Auth(
            credentials.access_key,
            credentials.secret_key,
            settings.aws_region,
            service,
            session_token=credentials.token
        )
    
    return OpenSearch(
        hosts=[{'host': endpoint, 'port': 443}],
        http_auth=http_auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30
    )


def get_s3_client():
    """Get S3 client for document storage"""
    return boto3.client(
        service_name='s3',
        region_name=settings.s3_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key
    )


# Lazy-loaded clients
_bedrock_client = None
_opensearch_client = None
_s3_client = None


def bedrock():
    """Get or create Bedrock client"""
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = get_bedrock_client()
    return _bedrock_client


def opensearch():
    """Get or create OpenSearch client"""
    global _opensearch_client
    if _opensearch_client is None:
        _opensearch_client = get_opensearch_client()
    return _opensearch_client


def s3():
    """Get or create S3 client"""
    global _s3_client
    if _s3_client is None:
        _s3_client = get_s3_client()
    return _s3_client


def reset_opensearch_client():
    """Reset OpenSearch client (useful when switching between environments)"""
    global _opensearch_client
    _opensearch_client = None


# ================================
# DynamoDB Client
# ================================

_dynamodb_client = None
_dynamodb_table = None


def _optional_boto3_credentials() -> dict:
    """
    Credentials from Settings (.env loaded by pydantic-settings) are NOT visible to boto3
    unless passed explicitly or exported to os.environ. When both are set, pass them so local
    .env matches Bedrock/S3 behavior in this project.
    """
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        return {
            "aws_access_key_id": settings.aws_access_key_id,
            "aws_secret_access_key": settings.aws_secret_access_key,
        }
    return {}


def get_dynamodb_resource():
    """DynamoDB resource using region + optional Settings credentials."""
    return boto3.resource(
        "dynamodb",
        region_name=settings.aws_region,
        **_optional_boto3_credentials(),
    )


def get_dynamodb_client():
    """Get DynamoDB client"""
    return boto3.client(
        service_name="dynamodb",
        region_name=settings.aws_region,
        **_optional_boto3_credentials(),
    )


def get_dynamodb_table(table_name: str = "ChatConversations"):
    """Get DynamoDB table resource"""
    return get_dynamodb_resource().Table(table_name)


def dynamodb():
    """Get or create DynamoDB client (cached)"""
    global _dynamodb_client
    if _dynamodb_client is None:
        _dynamodb_client = get_dynamodb_client()
    return _dynamodb_client

