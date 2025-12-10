"""
Healthcare Companion AI Backend
A supportive AI assistant for breast cancer patients

Features:
- AI-powered chat with medical knowledge
- Knowledge base with semantic search
- Multi-platform support (iOS, Android, Web)
- AWS-hosted (Bedrock, OpenSearch, S3)
"""

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from api import chat_router, knowledge_router, health_router, categories_router

# ================================
# Logging Configuration
# ================================

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


# ================================
# Application Lifespan
# ================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events"""
    # Startup
    logger.info("=" * 60)
    logger.info("🏥 Healthcare Companion AI Backend Starting...")
    logger.info(f"   Environment: {settings.app_env}")
    logger.info(f"   Debug Mode: {settings.debug}")
    logger.info(f"   API Prefix: {settings.api_prefix}")
    logger.info("=" * 60)
    
    yield
    
    # Shutdown
    logger.info("Healthcare Companion AI Backend shutting down...")


# ================================
# FastAPI Application
# ================================

app = FastAPI(
    title="Healthcare Companion AI",
    description="""
    ## 🏥 AI-Powered Healthcare Companion for Breast Cancer Patients
    
    This API provides:
    
    - **💬 Intelligent Chat**: Empathetic AI assistant specialized in breast cancer support
    - **📚 Knowledge Base**: Medical information search with semantic understanding
    - **🔒 Safe & Reliable**: Evidence-based responses with appropriate disclaimers
    
    ### Supported Platforms
    - iOS (Swift/SwiftUI)
    - Android (Kotlin)
    - Web (React/Next.js)
    
    ### Query Categories
    - Symptoms & Diagnosis
    - Treatment Options
    - Side Effects Management
    - Lifestyle & Nutrition
    - Emotional Support
    - Follow-up Care
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)


# ================================
# CORS Middleware
# ================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================================
# Exception Handlers
# ================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": "An unexpected error occurred. Please try again.",
            "timestamp": datetime.utcnow().isoformat()
        }
    )


# ================================
# Request Logging Middleware
# ================================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests"""
    start_time = datetime.utcnow()
    
    # Process request
    response = await call_next(request)
    
    # Calculate duration
    duration = (datetime.utcnow() - start_time).total_seconds() * 1000
    
    # Log request (skip health checks for cleaner logs)
    if "/health" not in request.url.path:
        logger.info(
            f"{request.method} {request.url.path} - "
            f"Status: {response.status_code} - "
            f"Duration: {duration:.0f}ms"
        )
    
    return response


# ================================
# Include Routers
# ================================

# API v1 routes
app.include_router(chat_router, prefix=settings.api_prefix)
app.include_router(knowledge_router, prefix=settings.api_prefix)
app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(categories_router, prefix=settings.api_prefix)


# ================================
# Root Endpoints
# ================================

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Healthcare Companion AI",
        "version": "1.0.0",
        "description": "AI-powered support for breast cancer patients",
        "documentation": "/docs",
        "health": f"{settings.api_prefix}/health",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/favicon.ico")
async def favicon():
    """Return empty favicon to prevent 404s"""
    return JSONResponse(content={}, status_code=204)


# ================================
# Run Application
# ================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        reload_dirs=["api", "config", "models", "services", "utils"] if settings.debug else None,
        log_level=settings.log_level.lower()
    )

