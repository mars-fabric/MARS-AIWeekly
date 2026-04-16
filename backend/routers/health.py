"""
Health check and root endpoints.
"""

import time
from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/")
async def root():
    """Root endpoint - API status check."""
    return {"message": "CMBAgent API is running"}


@router.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": time.time()}
