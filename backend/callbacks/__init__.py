"""
App-layer callback factories.

These functions create WorkflowCallbacks instances that are specific
to the backend application (WebSocket emission, database persistence).
They were moved here from cmbagent/callbacks.py to enforce the
library/app boundary: the library defines the callback contract,
the app provides concrete implementations.
"""

from cmbagent.callbacks import (
    WorkflowCallbacks,
    PlanInfo,
    StepInfo,
    StepStatus,
)

from .websocket_callbacks import create_websocket_callbacks
from .database_callbacks import create_database_callbacks

__all__ = [
    "create_websocket_callbacks",
    "create_database_callbacks",
]
