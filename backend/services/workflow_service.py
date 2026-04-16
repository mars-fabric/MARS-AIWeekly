"""
Workflow Service for CMBAgent Backend.

This service integrates with the cmbagent database layer to provide
proper workflow lifecycle management including:
- Creating WorkflowRun records in the database
- Managing session lifecycle
- State machine transitions for pause/resume/cancel
- DAG integration
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import uuid

from core.logging import get_logger

logger = get_logger(__name__)

# Import cmbagent database components
try:
    from cmbagent.database import (
        get_db_session,
        init_database,
        SessionManager,
        WorkflowRepository,
        DAGRepository,
        WorkflowState,
        StepState,
        StateMachine,
        WorkflowController,
    )
    from cmbagent.database.models import WorkflowRun, WorkflowStep, Session
    DATABASE_AVAILABLE = True
except ImportError as e:
    logger.warning("Database components not available: %s", e)
    DATABASE_AVAILABLE = False


class WorkflowService:
    """
    Service for managing workflow lifecycle with database integration.
    
    This service provides a clean interface for:
    - Creating and managing sessions
    - Creating workflow runs in the database
    - Managing workflow state transitions
    - Pause/resume/cancel functionality
    """
    
    def __init__(self):
        """Initialize the workflow service."""
        self._db_initialized = False
        self._session_manager: Optional[SessionManager] = None
        self._default_session_id: Optional[str] = None
        
        # Track active runs: {task_id: {"run_id": str, "session_id": str, "db_run_id": str}}
        self._active_runs: Dict[str, Dict[str, Any]] = {}
        
        if DATABASE_AVAILABLE:
            self._initialize_database()
    
    def _initialize_database(self):
        """Initialize database connection and session manager."""
        try:
            init_database()
            self._session_manager = SessionManager()
            self._default_session_id = self._session_manager.get_or_create_default_session()
            self._db_initialized = True
            logger.info("[WorkflowService] Database initialized with session: %s", self._default_session_id)
        except Exception as e:
            logger.error("[WorkflowService] Failed to initialize database: %s", e)
            self._db_initialized = False
    
    @property
    def is_database_available(self) -> bool:
        """Check if database is available and initialized."""
        return DATABASE_AVAILABLE and self._db_initialized
    
    def create_workflow_run(
        self,
        task_id: str,
        task_description: str,
        mode: str = "one-shot",
        agent: str = "engineer",
        model: str = "gpt-4o",
        config: Dict[str, Any] = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Create a new workflow run in the database.

        Args:
            task_id: External task identifier (from WebSocket)
            task_description: The task to execute
            mode: Execution mode (one-shot, planning-control, etc.)
            agent: Primary agent to use
            model: LLM model to use
            config: Full configuration dictionary
            session_id: Session ID to associate with this run (uses default if None)

        Returns:
            Dict with run_id, session_id, and db_run_id
        """
        if not self.is_database_available:
            # Fallback: just track the task_id
            run_info = {
                "task_id": task_id,
                "run_id": task_id,  # Use task_id as run_id when no DB
                "session_id": "default",
                "db_run_id": None,
                "status": "executing"
            }
            self._active_runs[task_id] = run_info
            return run_info
        
        try:
            db = get_db_session()
            try:
                # Use provided session_id or fall back to default
                effective_session_id = session_id or self._default_session_id

                # Create workflow repository with session isolation
                repo = WorkflowRepository(db, effective_session_id)

                # Create the workflow run
                run = repo.create_run(
                    task_description=task_description,
                    mode=mode,
                    agent=agent,
                    model=model,
                    status=WorkflowState.EXECUTING.value,
                    started_at=datetime.now(timezone.utc),
                    meta={**(config or {}), "task_id": task_id}  # Store config + task_id in meta
                )

                run_info = {
                    "task_id": task_id,
                    "run_id": str(run.id),
                    "session_id": effective_session_id,
                    "db_run_id": str(run.id),
                    "status": run.status
                }
                self._active_runs[task_id] = run_info

                logger.info("[WorkflowService] Created workflow run: %s for task: %s", run.id, task_id)
                return run_info
                
            finally:
                db.close()

        except Exception as e:
            logger.error("[WorkflowService] Error creating workflow run: %s", e)
            # Fallback to non-DB mode
            run_info = {
                "task_id": task_id,
                "run_id": task_id,
                "session_id": "default",
                "db_run_id": None,
                "status": "executing"
            }
            self._active_runs[task_id] = run_info
            return run_info
    
    def get_run_info(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get run info for a task."""
        return self._active_runs.get(task_id)
    
    def pause_workflow(self, task_id: str) -> Dict[str, Any]:
        """
        Pause a running workflow.
        
        Args:
            task_id: The task identifier
            
        Returns:
            Dict with status and message
        """
        run_info = self._active_runs.get(task_id)
        if not run_info:
            return {"success": False, "message": f"Task {task_id} not found"}
        
        if not self.is_database_available or not run_info.get("db_run_id"):
            # Fallback: just update local state
            run_info["status"] = "paused"
            return {"success": True, "message": "Workflow paused (local only)", "status": "paused"}
        
        try:
            db = get_db_session()
            try:
                controller = WorkflowController(db, run_info["session_id"])
                controller.pause_workflow(run_info["db_run_id"])
                
                run_info["status"] = "paused"
                return {"success": True, "message": "Workflow paused", "status": "paused"}
                
            finally:
                db.close()

        except Exception as e:
            logger.error("[WorkflowService] Error pausing workflow: %s", e)
            # Still update local state
            run_info["status"] = "paused"
            return {"success": True, "message": f"Workflow paused (with warning: {e})", "status": "paused"}
    
    def resume_workflow(self, task_id: str) -> Dict[str, Any]:
        """
        Resume a paused workflow.
        
        Args:
            task_id: The task identifier
            
        Returns:
            Dict with status and message
        """
        run_info = self._active_runs.get(task_id)
        if not run_info:
            return {"success": False, "message": f"Task {task_id} not found"}
        
        if not self.is_database_available or not run_info.get("db_run_id"):
            # Fallback: just update local state
            run_info["status"] = "executing"
            return {"success": True, "message": "Workflow resumed (local only)", "status": "executing"}
        
        try:
            db = get_db_session()
            try:
                controller = WorkflowController(db, run_info["session_id"])
                controller.resume_workflow(run_info["db_run_id"])
                
                run_info["status"] = "executing"
                return {"success": True, "message": "Workflow resumed", "status": "executing"}
                
            finally:
                db.close()

        except Exception as e:
            logger.error("[WorkflowService] Error resuming workflow: %s", e)
            # Still update local state
            run_info["status"] = "executing"
            return {"success": True, "message": f"Workflow resumed (with warning: {e})", "status": "executing"}
    
    def cancel_workflow(self, task_id: str) -> Dict[str, Any]:
        """
        Cancel a workflow.
        
        Args:
            task_id: The task identifier
            
        Returns:
            Dict with status and message
        """
        run_info = self._active_runs.get(task_id)
        if not run_info:
            return {"success": False, "message": f"Task {task_id} not found"}
        
        if not self.is_database_available or not run_info.get("db_run_id"):
            # Fallback: just update local state
            run_info["status"] = "cancelled"
            return {"success": True, "message": "Workflow cancelled (local only)", "status": "cancelled"}
        
        try:
            db = get_db_session()
            try:
                controller = WorkflowController(db, run_info["session_id"])
                controller.cancel_workflow(run_info["db_run_id"])
                
                run_info["status"] = "cancelled"
                return {"success": True, "message": "Workflow cancelled", "status": "cancelled"}
                
            finally:
                db.close()

        except Exception as e:
            logger.error("[WorkflowService] Error cancelling workflow: %s", e)
            # Still update local state
            run_info["status"] = "cancelled"
            return {"success": True, "message": f"Workflow cancelled (with warning: {e})", "status": "cancelled"}
    
    def complete_workflow(self, task_id: str, results: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Mark a workflow as complete.
        
        Args:
            task_id: The task identifier
            results: Optional results to store
            
        Returns:
            Dict with status and message
        """
        run_info = self._active_runs.get(task_id)
        if not run_info:
            return {"success": False, "message": f"Task {task_id} not found"}
        
        if self.is_database_available and run_info.get("db_run_id"):
            try:
                db = get_db_session()
                try:
                    repo = WorkflowRepository(db, run_info["session_id"])
                    repo.update_run_status(
                        run_info["db_run_id"],
                        WorkflowState.COMPLETED.value,
                        completed_at=datetime.now(timezone.utc)
                    )
                finally:
                    db.close()
            except Exception as e:
                logger.error("[WorkflowService] Error completing workflow in DB: %s", e)

        run_info["status"] = "completed"
        return {"success": True, "message": "Workflow completed", "status": "completed"}
    
    def fail_workflow(self, task_id: str, error: str = None) -> Dict[str, Any]:
        """
        Mark a workflow as failed.
        
        Args:
            task_id: The task identifier
            error: Optional error message
            
        Returns:
            Dict with status and message
        """
        run_info = self._active_runs.get(task_id)
        if not run_info:
            return {"success": False, "message": f"Task {task_id} not found"}
        
        if self.is_database_available and run_info.get("db_run_id"):
            try:
                db = get_db_session()
                try:
                    repo = WorkflowRepository(db, run_info["session_id"])
                    repo.update_run_status(
                        run_info["db_run_id"],
                        WorkflowState.FAILED.value,
                        completed_at=datetime.now(timezone.utc),
                        error=error
                    )
                finally:
                    db.close()
            except Exception as e:
                logger.error("[WorkflowService] Error failing workflow in DB: %s", e)

        run_info["status"] = "failed"
        return {"success": True, "message": "Workflow failed", "status": "failed"}
    
    def cleanup_run(self, task_id: str):
        """Remove a run from active tracking."""
        if task_id in self._active_runs:
            del self._active_runs[task_id]


# Global workflow service instance
workflow_service = WorkflowService()
