"""API module"""

# ================================
# v1 API Routes (Deprecated - Single Agent)
# ================================
# Still functional for backward compatibility
from .routes_deprecated import (
    chat_router,
    knowledge_router, 
    health_router,
    categories_router
)
from .forum_routes import forum_router

# ================================
# v2 API Routes (New - Multi-Agent Pipeline)
# ================================
from .routes import (
    pipeline_router,
    health_v2_router,
    debug_router
)

__all__ = [
    # v1 (deprecated)
    'chat_router',
    'knowledge_router', 
    'health_router',
    'categories_router',
    'forum_router',
    # v2 (new)
    'pipeline_router',
    'health_v2_router',
    'debug_router'
]

