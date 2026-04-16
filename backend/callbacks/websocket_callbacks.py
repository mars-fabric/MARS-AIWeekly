"""
WebSocket callback factory for workflow events.

Creates WorkflowCallbacks that emit events over WebSocket
for real-time UI updates.
"""

import logging
from datetime import datetime, timezone
from typing import Callable, Optional, Dict, Any

from cmbagent.callbacks import WorkflowCallbacks, PlanInfo, StepInfo

logger = logging.getLogger(__name__)


def create_websocket_callbacks(
    send_event_func: Callable[[str, Dict[str, Any]], None],
    run_id: str,
    total_steps: Optional[int] = None,
    hitl_mode: Optional[str] = None,
) -> WorkflowCallbacks:
    """
    Create WorkflowCallbacks that emit WebSocket events.

    Args:
        send_event_func: Function to send WebSocket events
            Signature: send(event_type: str, data: dict) -> None
        run_id: Workflow run ID for tagging events
        total_steps: Total number of steps (updated after planning)
        hitl_mode: HITL variant if applicable ("full_interactive", "planning_only", "error_recovery")

    Returns:
        WorkflowCallbacks configured for WebSocket emission
    """
    # Mutable container to track state
    state = {"total_steps": total_steps or 0, "steps_info": [], "hitl_mode": hitl_mode}

    # DAG node management is handled by DAGTracker, but we emit
    # timeline events so the frontend can show real-time progress.

    def on_planning_start(task: str, config: Dict[str, Any]) -> None:
        send_event_func("planning_start", {
            "run_id": run_id,
            "task": task[:200] if task else "",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def on_planning_complete(plan_info: PlanInfo) -> None:
        steps_summary = []
        for step in (plan_info.steps or []):
            if isinstance(step, dict):
                steps_summary.append({
                    k: v for k, v in step.items()
                    if k in ("sub_task", "sub_task_agent", "description", "goal")
                })
        send_event_func("planning_complete", {
            "run_id": run_id,
            "num_steps": plan_info.num_steps,
            "planning_time": plan_info.planning_time,
            "steps": steps_summary,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def on_step_start(step_info: StepInfo) -> None:
        send_event_func("step_start", {
            "run_id": run_id,
            "step_number": step_info.step_number,
            "goal": step_info.goal,
            "description": step_info.description,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def on_step_complete(step_info: StepInfo) -> None:
        send_event_func("step_complete", {
            "run_id": run_id,
            "step_number": step_info.step_number,
            "goal": step_info.goal,
            "execution_time": step_info.execution_time,
            "summary": step_info.summary,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def on_step_failed(step_info: StepInfo) -> None:
        send_event_func("step_failed", {
            "run_id": run_id,
            "step_number": step_info.step_number,
            "goal": step_info.goal,
            "error": step_info.error,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def on_workflow_complete(final_context: Dict[str, Any], total_time: float) -> None:
        send_event_func("workflow_complete", {
            "run_id": run_id,
            "total_time": total_time,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def on_workflow_failed(error: str, failed_step: Optional[int]) -> None:
        send_event_func("workflow_failed", {
            "run_id": run_id,
            "error": error,
            "failed_step": failed_step,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def on_cost_update(cost_data: Dict[str, Any]) -> None:
        # Emit summary cost event for frontend timeline
        # Detailed per-record emission is handled by CostCollector
        send_event_func("cost_summary", {
            "run_id": run_id,
            "total_cost": cost_data.get("total_cost", 0),
            "total_tokens": cost_data.get("total_tokens", 0),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def on_agent_message(agent: str, role: str, content: str, metadata: Dict[str, Any]) -> None:
        """Emit agent_message WebSocket event for comprehensive logging"""
        send_event_func("agent_message", {
            "run_id": run_id,
            "agent": agent,
            "role": role,
            "message": content,
            "metadata": metadata,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def on_code_execution(agent: str, code: str, language: str, result: Optional[str]) -> None:
        """Emit code_execution WebSocket event"""
        send_event_func("code_execution", {
            "run_id": run_id,
            "agent": agent,
            "code": code,
            "language": language,
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def on_tool_call(agent: str, tool_name: str, arguments: Dict[str, Any], result: Optional[Any]) -> None:
        """Emit tool_call WebSocket event"""
        send_event_func("tool_call", {
            "run_id": run_id,
            "agent": agent,
            "tool_name": tool_name,
            "arguments": arguments,
            "result": str(result) if result is not None else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def on_phase_change(phase: str, step_number: Optional[int]) -> None:
        """Emit phase_change WebSocket event"""
        send_event_func("phase_change", {
            "run_id": run_id,
            "phase": phase,
            "step_number": step_number,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    return WorkflowCallbacks(
        on_planning_start=on_planning_start,
        on_planning_complete=on_planning_complete,
        on_step_start=on_step_start,
        on_step_complete=on_step_complete,
        on_step_failed=on_step_failed,
        on_workflow_complete=on_workflow_complete,
        on_workflow_failed=on_workflow_failed,
        on_cost_update=on_cost_update,
        on_agent_message=on_agent_message,
        on_code_execution=on_code_execution,
        on_tool_call=on_tool_call,
        on_phase_change=on_phase_change
    )
