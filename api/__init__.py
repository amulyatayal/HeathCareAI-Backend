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
from .profile_routes import router as profile_router

# ================================
# v2 Admin Portal & Patient Resources
# ================================
from .admin_routes import router as admin_router
from .resource_routes import router as resource_router

# ================================
# v2 Patient Tracking & Dashboard
# ================================
from .mood_routes import router as mood_router
from .symptom_routes import router as symptom_router
from .appointment_routes import router as appointment_router
from .dashboard_routes import router as dashboard_router

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
    'debug_router',
    'profile_router',
    # v2 admin & resources
    'admin_router',
    'resource_router',
    # v2 patient tracking & dashboard
    'mood_router',
    'symptom_router',
    'appointment_router',
    'dashboard_router',
]
