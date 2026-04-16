"""
API Routers for the MARS-AIWeekly backend.

Standalone extraction — only routers required by the AI Weekly feature.
"""

from routers.health import router as health_router
from routers.sessions import router as sessions_router
from routers.models import router as models_router
from routers.aiweekly import router as aiweekly_router


def register_routers(app):
    """Register all routers with the FastAPI application."""
    app.include_router(health_router)
    app.include_router(sessions_router)
    app.include_router(models_router)
    app.include_router(aiweekly_router)


__all__ = [
    "register_routers",
    "health_router",
    "sessions_router",
    "models_router",
    "aiweekly_router",
]
