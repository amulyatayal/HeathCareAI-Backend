"""API module"""

# ================================
# RAG / Chat Routes
# ================================
from .routes_chat import chat_router
from .routes_knowledge import knowledge_router, categories_router
from .routes_health import health_router
from .forum_routes import forum_router

# ================================
# Pipeline Routes (Multi-Agent)
# ================================
from .routes_pipeline import (
    pipeline_router,
    health_v2_router,
    debug_router
)
from .profile_routes import router as profile_router

__all__ = [
    # RAG / Chat
    'chat_router',
    'knowledge_router', 
    'health_router',
    'categories_router',
    'forum_router',
    # Pipeline
    'pipeline_router',
    'health_v2_router',
    'debug_router',
    'profile_router',
]

