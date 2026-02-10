"""
Health Check API Routes
Provides endpoints for service health monitoring
"""

import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException

from models.schemas_rag import HealthCheckResponse, ServiceHealth

logger = logging.getLogger(__name__)


# ================================
# Health Check Router
# ================================

health_router = APIRouter(prefix="/health", tags=["Health"])


@health_router.get("/", response_model=HealthCheckResponse)
async def health_check():
    """
    Check the health of all services.
    
    Returns status of Bedrock, OpenSearch, and other dependencies.
    """
    services = []
    overall_status = "healthy"
    
    # Check Bedrock
    try:
        from config.aws import bedrock
        client = bedrock()
        services.append(ServiceHealth(
            name="bedrock",
            status="healthy",
            message="Bedrock client initialized"
        ))
    except Exception as e:
        services.append(ServiceHealth(
            name="bedrock",
            status="unhealthy",
            message=str(e)
        ))
        overall_status = "degraded"
    
    # Check OpenSearch
    try:
        from config.aws import opensearch
        client = opensearch()
        # Try a simple health check
        health = client.cluster.health()
        services.append(ServiceHealth(
            name="opensearch",
            status="healthy" if health.get("status") != "red" else "unhealthy",
            message=f"Cluster status: {health.get('status', 'unknown')}"
        ))
    except Exception as e:
        services.append(ServiceHealth(
            name="opensearch",
            status="unhealthy",
            message=str(e)
        ))
        overall_status = "degraded"
    
    # Check S3
    try:
        from config.aws import s3
        client = s3()
        services.append(ServiceHealth(
            name="s3",
            status="healthy",
            message="S3 client initialized"
        ))
    except Exception as e:
        services.append(ServiceHealth(
            name="s3",
            status="unhealthy",
            message=str(e)
        ))
        overall_status = "degraded"
    
    return HealthCheckResponse(
        status=overall_status,
        version="1.0.0",
        services=services,
        timestamp=datetime.utcnow()
    )


@health_router.get("/ping")
async def ping():
    """Simple ping endpoint for load balancer health checks"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
