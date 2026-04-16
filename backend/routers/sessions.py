"""
Session Management API

REST endpoints for managing workflow sessions:
- List sessions with filters (by mode, status)
- Get session details and history
- Suspend/resume sessions
- Delete sessions
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.logging import get_logger
from services.session_manager import get_session_manager

router = APIRouter(prefix="/api/sessions", tags=["sessions"], redirect_slashes=False)
logger = get_logger(__name__)


# ==================== Request/Response Models ====================

class SessionCreateRequest(BaseModel):
    """Request to create a new session"""
    mode: str = Field(..., description="Workflow mode (copilot, planning-control, etc.)")
    config: dict = Field(default_factory=dict, description="Session configuration")
    name: Optional[str] = Field(None, description="Optional session name")


class SessionResponse(BaseModel):
    """Session summary response"""
    session_id: str
    name: str
    mode: str
    status: str
    current_phase: Optional[str] = None
    current_step: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SessionDetailResponse(SessionResponse):
    """Detailed session response including history"""
    conversation_history: List[dict] = []
    context_variables: dict = {}
    plan_data: Optional[dict] = None
    config: dict = {}


class SessionListResponse(BaseModel):
    """List of sessions"""
    sessions: List[SessionResponse]
    total: int


class SessionActionResponse(BaseModel):
    """Response for session actions"""
    success: bool
    session_id: str
    message: str


# ==================== Endpoints ====================

@router.post("", response_model=SessionResponse)
async def create_session(request: SessionCreateRequest):
    """
    Create a new session.

    This creates an empty session that can be used for a workflow execution.
    Generally, sessions are created automatically when starting a workflow,
    but this endpoint allows pre-creating sessions.
    """
    try:
        session_manager = get_session_manager()
        session_id = session_manager.create_session(
            mode=request.mode,
            config=request.config,
            name=request.name
        )

        info = session_manager.get_session_info(session_id)
        if not info:
            raise HTTPException(status_code=500, detail="Failed to retrieve created session")

        logger.info("session_created_via_api", session_id=session_id, mode=request.mode)

        return SessionResponse(
            session_id=session_id,
            name=info.get("name", ""),
            mode=info.get("mode", request.mode),
            status=info.get("status", "active"),
            current_phase=info.get("current_phase"),
            current_step=info.get("current_step"),
            created_at=info.get("created_at"),
            updated_at=info.get("updated_at")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("session_create_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    status: Optional[str] = Query(None, description="Filter by status (active, suspended, completed)"),
    mode: Optional[str] = Query(None, description="Filter by workflow mode"),
    limit: int = Query(50, ge=1, le=200, description="Maximum sessions to return"),
):
    """
    List sessions with optional filters.

    Returns sessions ordered by most recently updated first.
    """
    try:
        session_manager = get_session_manager()
        sessions = session_manager.list_sessions(
            status=status,
            mode=mode,
            limit=limit
        )

        return SessionListResponse(
            sessions=[SessionResponse(**s) for s in sessions],
            total=len(sessions)
        )

    except Exception as e:
        logger.error("session_list_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str):
    """
    Get detailed session information including conversation history.
    """
    try:
        session_manager = get_session_manager()
        state = session_manager.load_session_state(session_id, include_completed=True)
        if not state:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        info = session_manager.get_session_info(session_id)

        created_at = state.get("created_at")
        updated_at = state.get("updated_at")

        return SessionDetailResponse(
            session_id=session_id,
            name=info.get("name", "") if info else "",
            mode=state.get("mode", ""),
            status=state.get("status", ""),
            current_phase=state.get("current_phase"),
            current_step=state.get("current_step"),
            created_at=created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at) if created_at else None,
            updated_at=updated_at.isoformat() if hasattr(updated_at, 'isoformat') else str(updated_at) if updated_at else None,
            conversation_history=state.get("conversation_history", []),
            context_variables=state.get("context_variables", {}),
            plan_data=state.get("plan_data"),
            config=state.get("config", {})
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("session_get_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/history")
async def get_session_history(
    session_id: str,
    limit: int = Query(100, ge=1, le=1000, description="Max messages to return"),
):
    """
    Get conversation history for a session.

    Returns the last N messages from the session.
    """
    try:
        session_manager = get_session_manager()
        state = session_manager.load_session_state(session_id, include_completed=True)
        if not state:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        history = state.get("conversation_history", [])

        return {
            "session_id": session_id,
            "total_messages": len(history),
            "messages": history[-limit:]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("session_history_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/suspend", response_model=SessionActionResponse)
async def suspend_session(session_id: str):
    """
    Suspend an active session for later resumption.

    Suspended sessions retain their state and can be resumed.
    """
    try:
        session_manager = get_session_manager()
        success = session_manager.suspend_session(session_id)

        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot suspend session {session_id} - not active or not found"
            )

        logger.info("session_suspended_via_api", session_id=session_id)

        return SessionActionResponse(
            success=True,
            session_id=session_id,
            message="Session suspended successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("session_suspend_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/resume", response_model=SessionActionResponse)
async def resume_session(session_id: str):
    """
    Resume a suspended session.

    The session state is preserved and execution can continue.
    """
    try:
        session_manager = get_session_manager()
        success = session_manager.resume_session(session_id)

        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot resume session {session_id} - not suspended or not found"
            )

        logger.info("session_resumed_via_api", session_id=session_id)

        return SessionActionResponse(
            success=True,
            session_id=session_id,
            message="Session resumed successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("session_resume_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}", response_model=SessionActionResponse)
async def delete_session(session_id: str):
    """
    Delete a session and all associated data.

    This action is irreversible. All session history and state will be lost.
    """
    try:
        session_manager = get_session_manager()
        success = session_manager.delete_session(session_id)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found"
            )

        logger.info("session_deleted_via_api", session_id=session_id)

        return SessionActionResponse(
            success=True,
            session_id=session_id,
            message="Session deleted successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("session_delete_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/runs")
async def get_session_runs(session_id: str):
    """
    Get all workflow runs associated with a session.

    Returns runs ordered by most recently started first.
    Useful for mapping session_id to run_id(s) for fetching
    costs, files, events, and console logs.
    """
    try:
        from cmbagent.database import get_db_session
        from cmbagent.database.models import WorkflowRun

        db = get_db_session()
        try:
            runs = db.query(WorkflowRun).filter(
                WorkflowRun.session_id == session_id
            ).order_by(WorkflowRun.started_at.desc()).all()

            return {
                "session_id": session_id,
                "total_runs": len(runs),
                "runs": [
                    {
                        "id": r.id,
                        "mode": r.mode,
                        "agent": r.agent,
                        "model": r.model,
                        "status": r.status,
                        "task_description": r.task_description,
                        "started_at": r.started_at.isoformat() if r.started_at else None,
                        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                        "is_branch": r.is_branch,
                        "meta": r.meta,
                    }
                    for r in runs
                ]
            }
        finally:
            db.close()

    except Exception as e:
        logger.error("session_runs_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
