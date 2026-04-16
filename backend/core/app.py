"""
FastAPI application factory and configuration.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.logging import configure_logging

# Global app instance
_app: FastAPI = None

# Store log config for re-application after uvicorn overrides
_log_config = {}


def _get_default_log_file() -> str:
    """Get default log file path in work directory."""
    work_dir = os.getenv("AIWEEKLY_DEFAULT_WORK_DIR", "~/Desktop/cmbdir/aiweekly")
    work_dir = os.path.expanduser(work_dir)
    log_dir = Path(work_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return str(log_dir / "backend.log")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan: re-apply logging after uvicorn overrides it."""
    configure_logging(**_log_config)
    import logging
    logging.getLogger(__name__).info("Backend started, logs writing to %s", _log_config.get("log_file", "console"))
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    global _app, _log_config

    # Build log config
    log_file = os.getenv("LOG_FILE") or _get_default_log_file()
    _log_config = {
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "json_output": os.getenv("LOG_JSON", "false").lower() == "true",
        "log_file": log_file,
    }

    # Initial configure (may be overridden by uvicorn, re-applied in lifespan)
    configure_logging(**_log_config)

    app = FastAPI(
        title=settings.app_title,
        version=settings.app_version,
        lifespan=lifespan,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _app = app
    return app


def get_app() -> FastAPI:
    """Get the current FastAPI application instance."""
    global _app
    if _app is None:
        _app = create_app()
    return _app
