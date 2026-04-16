"""
WebSocket Event Types and Data Models

This module defines the structured event protocol for WebSocket communication
between the backend and UI. All events are typed and validated using Pydantic.
"""

from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import datetime


class WebSocketEventType(str, Enum):
    """Types of WebSocket events"""

    # Connection events
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTED = "reconnected"

    # Workflow lifecycle events
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_STATE_CHANGED = "workflow_state_changed"
    WORKFLOW_PAUSED = "workflow_paused"
    WORKFLOW_RESUMED = "workflow_resumed"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"

    # Step execution events
    STEP_STARTED = "step_started"
    STEP_PROGRESS = "step_progress"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"

    # Retry events
    STEP_RETRY_STARTED = "step_retry_started"
    STEP_RETRY_BACKOFF = "step_retry_backoff"
    STEP_RETRY_SUCCEEDED = "step_retry_succeeded"
    STEP_RETRY_EXHAUSTED = "step_retry_exhausted"

    # DAG events
    DAG_CREATED = "dag_created"
    DAG_UPDATED = "dag_updated"
    DAG_NODE_STATUS_CHANGED = "dag_node_status_changed"

    # Agent events
    AGENT_MESSAGE = "agent_message"
    AGENT_THINKING = "agent_thinking"
    AGENT_TOOL_CALL = "agent_tool_call"

    # Approval events
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RECEIVED = "approval_received"

    # Cost and metrics
    COST_UPDATE = "cost_update"
    METRIC_UPDATE = "metric_update"

    # File events
    FILE_CREATED = "file_created"
    FILE_UPDATED = "file_updated"

    # Execution events
    EVENT_CAPTURED = "event_captured"

    # Error events
    ERROR_OCCURRED = "error_occurred"

    # Task stage events (Deepresearch integration)
    TASK_STAGE_STARTED = "task_stage_started"
    TASK_STAGE_COMPLETED = "task_stage_completed"
    TASK_STAGE_FAILED = "task_stage_failed"
    TASK_PROGRESS = "task_progress"

    # Heartbeat
    HEARTBEAT = "heartbeat"
    PONG = "pong"


class WebSocketEvent(BaseModel):
    """Base WebSocket event"""
    event_type: WebSocketEventType
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.utcnow())
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime.datetime: lambda v: v.isoformat()
        }


# Specific event data models

class WorkflowStartedData(BaseModel):
    """Data for workflow_started event"""
    run_id: str
    task_description: str
    agent: str
    model: str
    work_dir: Optional[str] = None


class WorkflowStateChangedData(BaseModel):
    """Data for workflow_state_changed event"""
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


class StepRetryStartedData(BaseModel):
    """Data for step_retry_started event"""
    step_id: str
    step_number: int
    attempt_number: int
    max_attempts: int
    error_category: str
    error_pattern: Optional[str] = None
    success_probability: Optional[float] = None
    strategy: str
    suggestions: List[str] = Field(default_factory=list)
    has_user_feedback: bool = False


class StepRetryBackoffData(BaseModel):
    """Data for step_retry_backoff event"""
    step_id: str
    step_number: int
    attempt_number: int
    backoff_seconds: int
    retry_strategy: str


class StepRetrySucceededData(BaseModel):
    """Data for step_retry_succeeded event"""
    step_id: str
    step_number: int
    attempt_number: int
    total_attempts: int


class StepRetryExhaustedData(BaseModel):
    """Data for step_retry_exhausted event"""
    step_id: str
    step_number: int
    total_attempts: int
    final_error: str


class DAGCreatedData(BaseModel):
    """Data for dag_created event"""
    run_id: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    levels: int


class DAGNodeStatusChangedData(BaseModel):
    """Data for dag_node_status_changed event"""
    node_id: str
    old_status: str
    new_status: str
    error: Optional[str] = None


class AgentMessageData(BaseModel):
    """Data for agent_message event"""
    agent: str
    message: str
    role: str = "assistant"


class AgentToolCallData(BaseModel):
    """Data for agent_tool_call event"""
    agent: str
    tool_name: str
    tool_args: Dict[str, Any]
    tool_result: Optional[str] = None


class ApprovalRequestedData(BaseModel):
    """Data for approval_requested event"""
    approval_id: str
    step_id: str
    action: str
    description: str
    context: Dict[str, Any]


class ApprovalReceivedData(BaseModel):
    """Data for approval_received event"""
    approval_id: str
    approved: bool
    feedback: Optional[str] = None


class CostUpdateData(BaseModel):
    """Data for cost_update event"""
    run_id: str
    step_id: Optional[str] = None
    model: str
    tokens: int
    input_tokens: Optional[int] = 0
    output_tokens: Optional[int] = 0
    cost_usd: float
    total_cost_usd: float


class MetricUpdateData(BaseModel):
    """Data for metric_update event"""
    metric_name: str
    value: float
    unit: str
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.utcnow())


class FileCreatedData(BaseModel):
    """Data for file_created event"""
    file_path: str
    file_type: str
    size_bytes: Optional[int] = None


class EventCapturedData(BaseModel):
    """Data for event_captured event"""
    event_id: str
    node_id: Optional[str] = None
    event_type: str
    event_subtype: Optional[str] = None
    agent_name: Optional[str] = None
    timestamp: str
    execution_order: int
    depth: int = 0


class ErrorOccurredData(BaseModel):
    """Data for error_occurred event"""
    error_type: str
    message: str
    step_id: Optional[str] = None
    traceback: Optional[str] = None


class TaskStageStartedData(BaseModel):
    """Data for task_stage_started event"""
    stage_number: int
    stage_name: str
    total_stages: int


class TaskStageCompletedData(BaseModel):
    """Data for task_stage_completed event"""
    stage_number: int
    stage_name: str
    output_summary: Dict[str, Any] = Field(default_factory=dict)


class TaskProgressData(BaseModel):
    """Data for task_progress event"""
    completed: int
    total: int
    percent: int = 0


# Helper functions for creating events

def create_workflow_started_event(run_id: str, task_description: str, agent: str, model: str, work_dir: Optional[str] = None) -> WebSocketEvent:
    """Create a workflow_started event"""
    return WebSocketEvent(
        event_type=WebSocketEventType.WORKFLOW_STARTED,
        run_id=run_id,
        data=WorkflowStartedData(
            run_id=run_id,
            task_description=task_description,
            agent=agent,
            model=model,
            work_dir=work_dir
        ).dict()
    )


def create_workflow_state_changed_event(run_id: str, status: str, started_at: Optional[datetime] = None, completed_at: Optional[datetime] = None, error: Optional[str] = None) -> WebSocketEvent:
    """Create a workflow_state_changed event"""
    return WebSocketEvent(
        event_type=WebSocketEventType.WORKFLOW_STATE_CHANGED,
        run_id=run_id,
        data=WorkflowStateChangedData(
            status=status,
            started_at=started_at.isoformat() if started_at else None,
            completed_at=completed_at.isoformat() if completed_at else None,
            error=error
        ).dict()
    )


def create_dag_created_event(run_id: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], levels: int) -> WebSocketEvent:
    """Create a dag_created event"""
    return WebSocketEvent(
        event_type=WebSocketEventType.DAG_CREATED,
        run_id=run_id,
        data=DAGCreatedData(
            run_id=run_id,
            nodes=nodes,
            edges=edges,
            levels=levels
        ).dict()
    )


def create_dag_node_status_changed_event(run_id: str, node_id: str, old_status: str, new_status: str, error: Optional[str] = None) -> WebSocketEvent:
    """Create a dag_node_status_changed event"""
    return WebSocketEvent(
        event_type=WebSocketEventType.DAG_NODE_STATUS_CHANGED,
        run_id=run_id,
        data=DAGNodeStatusChangedData(
            node_id=node_id,
            old_status=old_status,
            new_status=new_status,
            error=error
        ).dict()
    )


def create_error_event(run_id: str, error_type: str, message: str, step_id: Optional[str] = None, traceback: Optional[str] = None) -> WebSocketEvent:
    """Create an error_occurred event"""
    return WebSocketEvent(
        event_type=WebSocketEventType.ERROR_OCCURRED,
        run_id=run_id,
        data=ErrorOccurredData(
            error_type=error_type,
            message=message,
            step_id=step_id,
            traceback=traceback
        ).dict()
    )


def create_event_captured_event(
    run_id: str,
    event_id: str,
    event_type: str,
    execution_order: int,
    timestamp: str,
    node_id: Optional[str] = None,
    event_subtype: Optional[str] = None,
    agent_name: Optional[str] = None,
    depth: int = 0
) -> WebSocketEvent:
    """Create an event_captured event"""
    return WebSocketEvent(
        event_type=WebSocketEventType.EVENT_CAPTURED,
        run_id=run_id,
        data=EventCapturedData(
            event_id=event_id,
            node_id=node_id,
            event_type=event_type,
            event_subtype=event_subtype,
            agent_name=agent_name,
            timestamp=timestamp,
            execution_order=execution_order,
            depth=depth
        ).dict()
    )


def create_task_stage_started_event(
    run_id: str, stage_number: int, stage_name: str, total_stages: int
) -> WebSocketEvent:
    """Create a task_stage_started event"""
    return WebSocketEvent(
        event_type=WebSocketEventType.TASK_STAGE_STARTED,
        run_id=run_id,
        data=TaskStageStartedData(
            stage_number=stage_number,
            stage_name=stage_name,
            total_stages=total_stages,
        ).dict()
    )


def create_task_stage_completed_event(
    run_id: str, stage_number: int, stage_name: str, output_summary: Dict[str, Any] = None
) -> WebSocketEvent:
    """Create a task_stage_completed event"""
    return WebSocketEvent(
        event_type=WebSocketEventType.TASK_STAGE_COMPLETED,
        run_id=run_id,
        data=TaskStageCompletedData(
            stage_number=stage_number,
            stage_name=stage_name,
            output_summary=output_summary or {},
        ).dict()
    )


def create_task_progress_event(
    run_id: str, completed: int, total: int
) -> WebSocketEvent:
    """Create a task_progress event"""
    return WebSocketEvent(
        event_type=WebSocketEventType.TASK_PROGRESS,
        run_id=run_id,
        data=TaskProgressData(
            completed=completed,
            total=total,
            percent=round(completed / total * 100) if total else 0,
        ).dict()
    )
