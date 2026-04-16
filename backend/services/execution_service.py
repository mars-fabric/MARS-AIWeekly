"""
Execution Service for CMBAgent Backend.

This service handles the actual execution of CMBAgent tasks,
integrating with all Stage 1-9 functionality.
"""

import asyncio
import sys
import os
import time
from typing import Dict, Any, Optional, Callable, TYPE_CHECKING
from datetime import datetime, timezone
from pathlib import Path

from core.config import settings

# Use forward references to avoid circular imports
if TYPE_CHECKING:
    from services.workflow_service import WorkflowService
    from services.connection_manager import ConnectionManager


import threading


class ExecutionService:
    """
    Service for executing CMBAgent tasks.
    
    This service provides:
    - Async task execution with output streaming
    - DAG tracking and status updates
    - Integration with workflow lifecycle
    - Pause/resume support
    """
    
    def __init__(self):
        """Initialize the execution service."""
        self._active_executions: Dict[str, Dict[str, Any]] = {}
        self._pause_flags: Dict[str, bool] = {}  # Track pause requests
        self._cancel_flags: Dict[str, bool] = {}  # Track cancel requests
        self._lock = threading.Lock()  # Thread-safe access to flags
    
    def is_paused(self, task_id: str) -> bool:
        """Check if a task is paused."""
        with self._lock:
            return self._pause_flags.get(task_id, False)
    
    def is_cancelled(self, task_id: str) -> bool:
        """Check if a task is cancelled."""
        with self._lock:
            return self._cancel_flags.get(task_id, False)
    
    def set_paused(self, task_id: str, paused: bool):
        """Set pause state for a task."""
        with self._lock:
            self._pause_flags[task_id] = paused
    
    def set_cancelled(self, task_id: str, cancelled: bool):
        """Set cancel state for a task."""
        with self._lock:
            self._cancel_flags[task_id] = cancelled
    
    async def wait_if_paused(self, task_id: str) -> bool:
        """
        Wait while task is paused.
        
        Args:
            task_id: Task identifier
            
        Returns:
            False if cancelled, True otherwise
        """
        while self.is_paused(task_id):
            if self.is_cancelled(task_id):
                return False
            await asyncio.sleep(0.5)
        return not self.is_cancelled(task_id)
    
    async def execute_task(
        self,
        task_id: str,
        task: str,
        config: Dict[str, Any],
        on_output: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Execute a CMBAgent task.
        
        Args:
            task_id: Task identifier
            task: Task description
            config: Configuration dictionary
            on_output: Optional callback for output
            
        Returns:
            Execution results dictionary
        """
        # Lazy import to avoid circular imports
        from services.workflow_service import workflow_service
        from services.connection_manager import connection_manager
        
        # Create workflow run in database
        run_info = workflow_service.create_workflow_run(
            task_id=task_id,
            task_description=task,
            mode=config.get("mode", "one-shot"),
            agent=config.get("agent", "engineer"),
            model=config.get("model", "gpt-4o"),
            config=config,
            session_id=config.get("session_id")
        )
        
        self._active_executions[task_id] = {
            "run_info": run_info,
            "started_at": datetime.now(timezone.utc),
            "config": config
        }
        
        # Reset pause/cancel flags
        self._pause_flags[task_id] = False
        self._cancel_flags[task_id] = False
        
        try:
            # Get work directory
            work_dir = config.get("workDir", settings.default_work_dir)
            if work_dir.startswith("~"):
                work_dir = os.path.expanduser(work_dir)

            # Get session_id from config (default to "default_session" if not provided)
            session_id = config.get("session_id", "default_session")

            # Create task directory nested under session
            # Structure: {work_dir}/sessions/{session_id}/tasks/{task_id}
            task_work_dir = os.path.join(work_dir, "sessions", session_id, "tasks", task_id)
            os.makedirs(task_work_dir, exist_ok=True)
            
            # Send workflow started event
            await connection_manager.send_workflow_started(
                task_id=task_id,
                task_description=task,
                agent=config.get("agent", "engineer"),
                model=config.get("model", "gpt-4o")
            )
            
            # Execute the actual CMBAgent task
            results = await self._run_cmbagent(
                task_id=task_id,
                task=task,
                config=config,
                work_dir=task_work_dir
            )
            
            # Complete the workflow
            workflow_service.complete_workflow(task_id, results)
            await connection_manager.send_workflow_completed(task_id, results)
            
            return results
            
        except Exception as e:
            error_msg = str(e)
            workflow_service.fail_workflow(task_id, error_msg)
            await connection_manager.send_error(
                task_id=task_id,
                error_type="ExecutionError",
                message=error_msg
            )
            return {"error": error_msg}
        
        finally:
            # Cleanup
            self._cleanup_execution(task_id)
    
    async def _run_cmbagent(
        self,
        task_id: str,
        task: str,
        config: Dict[str, Any],
        work_dir: str
    ) -> Dict[str, Any]:
        """
        Run CMBAgent in a thread with async output streaming.
        
        This method runs the actual CMBAgent execution in a separate thread
        while streaming output to the WebSocket connection.
        """
        # Lazy import to avoid circular imports
        from services.connection_manager import connection_manager
        
        import cmbagent
        from cmbagent.utils import get_api_keys_from_env
        
        # Get API keys
        api_keys = get_api_keys_from_env()
        
        # Extract config parameters
        mode = config.get("mode", "one-shot")
        agent = config.get("agent", "engineer")
        model = config.get("model", "gpt-4o")
        max_rounds = config.get("maxRounds", 25)
        max_attempts = config.get("maxAttempts", 6)
        default_llm_model = config.get("defaultModel", "gpt-4.1-2025-04-14")
        default_formatter_model = config.get("defaultFormatterModel", "o3-mini-2025-01-31")
        
        # Get event loop for async operations from sync context
        loop = asyncio.get_event_loop()
        
        # Create output streamer
        async def send_output(text: str):
            await connection_manager.send_output(task_id, text)
        
        def sync_send_output(text: str):
            """Synchronous wrapper for sending output."""
            asyncio.run_coroutine_threadsafe(send_output(text), loop)
        
        # Run CMBAgent in thread pool
        def run_agent():
            # Set environment variables
            os.environ["AIWEEKLY_DEBUG"] = "false"
            os.environ["AIWEEKLY_DISABLE_DISPLAY"] = "true"
            
            try:
                if mode == "planning-control":
                    planner_model = config.get("plannerModel", "gpt-4.1-2025-04-14")
                    plan_reviewer_model = config.get("planReviewerModel", "o3-mini-2025-01-31")
                    researcher_model = config.get("researcherModel", "gpt-4.1-2025-04-14")
                    engineer_model = config.get("model", "gpt-4o")
                    max_plan_steps = config.get("maxPlanSteps", 2)
                    n_plan_reviews = config.get("nPlanReviews", 1)
                    plan_instructions = config.get("planInstructions", "")
                    
                    results = cmbagent.planning_and_control_context_carryover(
                        task=task,
                        max_rounds_control=max_rounds,
                        max_n_attempts=max_attempts,
                        max_plan_steps=max_plan_steps,
                        n_plan_reviews=n_plan_reviews,
                        engineer_model=engineer_model,
                        researcher_model=researcher_model,
                        planner_model=planner_model,
                        plan_reviewer_model=plan_reviewer_model,
                        plan_instructions=plan_instructions if plan_instructions.strip() else None,
                        work_dir=work_dir,
                        api_keys=api_keys,
                        clear_work_dir=False,
                        default_formatter_model=default_formatter_model,
                        default_llm_model=default_llm_model,
                    )
                elif mode == "one-shot":
                    results = cmbagent.one_shot(
                        task=task,
                        agent=agent,
                        max_rounds=max_rounds,
                        max_n_attempts=max_attempts,
                        work_dir=work_dir,
                        api_keys=api_keys,
                        clear_work_dir=False,
                        model=model,
                        default_formatter_model=default_formatter_model,
                        default_llm_model=default_llm_model,
                    )
                else:
                    # Default to one-shot
                    results = cmbagent.one_shot(
                        task=task,
                        agent=agent,
                        max_rounds=max_rounds,
                        max_n_attempts=max_attempts,
                        work_dir=work_dir,
                        api_keys=api_keys,
                        clear_work_dir=False,
                        model=model,
                        default_formatter_model=default_formatter_model,
                        default_llm_model=default_llm_model,
                    )
                
                return results
                
            except Exception as e:
                return {"error": str(e)}
        
        # Run in thread pool
        results = await asyncio.get_event_loop().run_in_executor(None, run_agent)
        return results
    
    def _cleanup_execution(self, task_id: str):
        """Cleanup after execution."""
        # Lazy import to avoid circular imports
        from services.workflow_service import workflow_service
        
        if task_id in self._active_executions:
            del self._active_executions[task_id]
        if task_id in self._pause_flags:
            del self._pause_flags[task_id]
        if task_id in self._cancel_flags:
            del self._cancel_flags[task_id]
        workflow_service.cleanup_run(task_id)


# Global execution service instance
execution_service = ExecutionService()
