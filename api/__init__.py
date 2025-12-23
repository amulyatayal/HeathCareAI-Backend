"""API module"""
from .routes import chat_router, knowledge_router, health_router, categories_router
from .forum_routes import forum_router
from .user_routes import user_router

__all__ = ['chat_router', 'knowledge_router', 'health_router', 'categories_router', 'forum_router', 'user_router']


