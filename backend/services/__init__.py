"""
Backend services for CMBAgent.

This module provides production-grade service layer that integrates
with the cmbagent database infrastructure (Stages 1-9).

Services:
- WorkflowService: Manages workflow lifecycle with database integration
- ConnectionManager: Manages WebSocket connections with event protocol (Stage 4)
- ExecutionService: Handles CMBAgent task execution
- SessionManager: Manages session state persistence and lifecycle (Stage 3)
"""

from services.workflow_service import WorkflowService, workflow_service
from services.connection_manager import ConnectionManager, connection_manager
from services.execution_service import ExecutionService, execution_service
from services.session_manager import (
    SessionManager,
    get_session_manager,
    create_session_manager
)

__all__ = [
    "WorkflowService",
    "workflow_service",
    "ConnectionManager",
    "connection_manager",
    "ExecutionService",
    "execution_service",
    "SessionManager",
    "get_session_manager",
    "create_session_manager",
]
