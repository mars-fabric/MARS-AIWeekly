"""
Connection Manager for CMBAgent Backend.

This module provides the single source of truth for WebSocket connection management.
All connection tracking should use this manager.
"""

import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from fastapi import WebSocket

from core.logging import get_logger

logger = get_logger(__name__)

# Import event types (with fallback)
try:
    from websocket_events import (
        WebSocketEvent,
        WebSocketEventType,
        create_workflow_started_event,
        create_workflow_state_changed_event,
        create_workflow_completed_event,
        create_dag_created_event,
        create_dag_node_status_changed_event,
        create_error_event,
    )
    from event_queue import event_queue
except ImportError:
    # Define minimal stubs if import fails
    class WebSocketEventType:
        WORKFLOW_STARTED = "workflow_started"
        WORKFLOW_STATE_CHANGED = "workflow_state_changed"
        WORKFLOW_COMPLETED = "workflow_completed"
        WORKFLOW_FAILED = "workflow_failed"
        WORKFLOW_PAUSED = "workflow_paused"
        WORKFLOW_RESUMED = "workflow_resumed"
        DAG_CREATED = "dag_created"
        DAG_NODE_STATUS_CHANGED = "dag_node_status_changed"
        OUTPUT = "output"
        PONG = "pong"
        ERROR = "error"
        STATUS = "status"
        AGENT_MESSAGE = "agent_message"

    class WebSocketEvent:
        def __init__(self, event_type=None, timestamp=None, run_id=None, session_id=None, data=None, **kwargs):
            self.event_type = event_type
            self.timestamp = timestamp or datetime.now(timezone.utc)
            self.run_id = run_id
            self.session_id = session_id
            self.data = data or {}

        def dict(self):
            return {
                "event_type": self.event_type.value if hasattr(self.event_type, 'value') else self.event_type,
                "timestamp": self.timestamp.isoformat() if hasattr(self.timestamp, 'isoformat') else str(self.timestamp),
                "run_id": self.run_id,
                "session_id": self.session_id,
                "data": self.data
            }

    def create_workflow_started_event(*args, **kwargs): return None
    def create_workflow_state_changed_event(*args, **kwargs): return None
    def create_workflow_completed_event(*args, **kwargs): return None
    def create_dag_created_event(*args, **kwargs): return None
    def create_dag_node_status_changed_event(*args, **kwargs): return None
    def create_error_event(*args, **kwargs): return None

    class _EventQueue:
        def push(self, *args, **kwargs): pass
        def get_since(self, *args, **kwargs): return []
        def get_all_events(self, *args, **kwargs): return []
        def get_events_since(self, *args, **kwargs): return []

    event_queue = _EventQueue()


class ConnectionManager:
    """
    Single source of truth for WebSocket connection management.

    Features:
    - Async-safe with lock protection
    - Connection limits to prevent exhaustion
    - Metadata tracking for debugging
    - Event queue integration for reliable delivery
    """

    def __init__(self, max_connections: int = 100, db_factory=None):
        """
        Initialize the connection manager.

        Args:
            max_connections: Maximum allowed simultaneous connections
            db_factory: Optional database factory for connection persistence
        """
        self._connections: Dict[str, WebSocket] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._max_connections = max_connections
        self._db_factory = db_factory

        logger.info("ConnectionManager initialized (max_connections=%d)", max_connections)

    async def connect(
        self,
        websocket: WebSocket,
        task_id: str,
        session_id: Optional[str] = None
    ) -> bool:
        """
        Register a WebSocket connection.

        NOTE: websocket.accept() must be called BEFORE calling this method.

        Args:
            websocket: FastAPI WebSocket instance (already accepted)
            task_id: Task identifier for this connection
            session_id: Optional session identifier

        Returns:
            True if connection registered, False if limit reached
        """
        async with self._lock:
            # Check connection limit
            if len(self._connections) >= self._max_connections:
                logger.warning(
                    "Connection limit reached (%d), rejecting task %s",
                    self._max_connections, task_id
                )
                return False

            # Handle reconnection - close existing connection for same task_id
            if task_id in self._connections:
                old_ws = self._connections[task_id]
                logger.info("Replacing existing connection for task %s", task_id)
                try:
                    await old_ws.close(code=1000, reason="Reconnection")
                except Exception:
                    pass  # Old connection might already be closed

            # Register new connection
            self._connections[task_id] = websocket
            self._metadata[task_id] = {
                "session_id": session_id,
                "connected_at": datetime.now(timezone.utc),
                "last_activity": datetime.now(timezone.utc),
            }

            logger.info(
                "Connection registered: task=%s, session=%s, total=%d",
                task_id, session_id, len(self._connections)
            )

            # Persist to database if available
            if self._db_factory:
                try:
                    self._persist_connection(task_id, session_id)
                except Exception as e:
                    logger.warning("Failed to persist connection: %s", e)

            return True

    async def disconnect(self, task_id: str):
        """
        Unregister a connection.

        Args:
            task_id: Task identifier
        """
        async with self._lock:
            if task_id in self._connections:
                del self._connections[task_id]
            if task_id in self._metadata:
                del self._metadata[task_id]

            logger.info(
                "Connection disconnected: task=%s, remaining=%d",
                task_id, len(self._connections)
            )

            # Remove from database if available
            if self._db_factory:
                try:
                    self._remove_connection(task_id)
                except Exception as e:
                    logger.warning("Failed to remove connection from DB: %s", e)

    def is_connected(self, task_id: str) -> bool:
        """Check if a task has an active connection."""
        return task_id in self._connections

    async def send_event(
        self,
        task_id: str,
        event_type_or_event,
        data: Dict[str, Any] = None,
        queue_if_disconnected: bool = True
    ) -> bool:
        """
        Send an event to a connected client.

        Supports both new-style (event_type + data) and legacy (WebSocketEvent object) calls.

        Args:
            task_id: Task identifier
            event_type_or_event: Event type string OR WebSocketEvent object
            data: Event data (only used if event_type_or_event is a string)
            queue_if_disconnected: Whether to queue if client disconnected

        Returns:
            True if sent or queued successfully
        """
        # Support both calling conventions:
        # New: send_event(task_id, "output", {"message": "hello"})
        # Legacy: send_event(task_id, WebSocketEvent(...))
        if isinstance(event_type_or_event, str):
            event_type = event_type_or_event
            event_data = data or {}
            event = WebSocketEvent(
                event_type=event_type,
                timestamp=datetime.now(timezone.utc),
                run_id=task_id,
                data=event_data
            )
        else:
            # Legacy WebSocketEvent object
            event = event_type_or_event
            event_type = event.event_type
            event_data = event.data if hasattr(event, 'data') else {}

        # Always queue for replay on reconnection
        if queue_if_disconnected:
            try:
                event_queue.push(task_id, event)
            except Exception:
                pass

        # Try to send to active connection
        async with self._lock:
            if task_id not in self._connections:
                return queue_if_disconnected

            websocket = self._connections[task_id]
            if task_id in self._metadata:
                self._metadata[task_id]["last_activity"] = datetime.now(timezone.utc)

        try:
            # Serialize event
            if hasattr(event, 'model_dump'):
                event_dict = event.model_dump()
            elif hasattr(event, 'dict'):
                event_dict = event.dict()
            else:
                event_dict = {
                    "event_type": event_type.value if hasattr(event_type, 'value') else event_type,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "run_id": task_id,
                    "data": event_data
                }

            # Convert datetime to ISO string
            if isinstance(event_dict.get("timestamp"), datetime):
                event_dict["timestamp"] = event_dict["timestamp"].isoformat() + "Z"

            await websocket.send_json(event_dict)
            return True

        except Exception as e:
            logger.warning("Failed to send event to %s: %s", task_id, e)
            await self.disconnect(task_id)
            return queue_if_disconnected

    async def send_json(self, task_id: str, data: Dict[str, Any]) -> bool:
        """
        Send raw JSON data to a client.

        Args:
            task_id: Task identifier
            data: JSON-serializable data

        Returns:
            True if sent successfully
        """
        async with self._lock:
            if task_id not in self._connections:
                return False
            websocket = self._connections[task_id]

        try:
            await websocket.send_json(data)
            return True
        except Exception as e:
            logger.warning("Failed to send JSON to %s: %s", task_id, e)
            await self.disconnect(task_id)
            return False

    # ==================== Convenience Methods ====================

    async def send_output(self, task_id: str, message: str):
        """Send output message"""
        event = WebSocketEvent(
            event_type=WebSocketEventType.OUTPUT,
            timestamp=datetime.now(timezone.utc),
            run_id=task_id,
            data={"message": message}
        )
        await self.send_event(task_id, event)

    async def send_status(self, task_id: str, status: str, message: str = None):
        """Send status update"""
        event = WebSocketEvent(
            event_type=WebSocketEventType.WORKFLOW_STATE_CHANGED,
            timestamp=datetime.now(timezone.utc),
            run_id=task_id,
            data={"status": status, "message": message or status}
        )
        await self.send_event(task_id, event)

    async def send_error(self, task_id: str, error_type: str, message: str, traceback: str = None):
        """Send error event"""
        error_event = create_error_event(
            run_id=task_id,
            error_type=error_type,
            message=message,
            traceback=traceback
        )
        if error_event:
            await self.send_event(task_id, error_event)
        else:
            await self.send_event(task_id, "error", {
                "error_type": error_type,
                "message": message,
                "traceback": traceback,
            })

    async def send_pong(self, task_id: str):
        """Send pong response (not queued)"""
        event = WebSocketEvent(
            event_type=WebSocketEventType.PONG,
            timestamp=datetime.now(timezone.utc),
            run_id=task_id,
            data={}
        )
        await self.send_event(task_id, event, queue_if_disconnected=False)

    async def send_workflow_started(
        self,
        task_id: str,
        task_description: str,
        agent: str,
        model: str
    ):
        """Send workflow started event."""
        event = create_workflow_started_event(
            run_id=task_id,
            task_description=task_description,
            agent=agent,
            model=model
        )
        if event:
            await self.send_event(task_id, event)
        else:
            await self.send_event(task_id, "workflow_started", {
                "task_description": task_description,
                "agent": agent,
                "model": model,
            })

    async def send_workflow_completed(self, task_id: str, results: Dict[str, Any] = None):
        """Send workflow completed event."""
        event = create_workflow_completed_event(
            run_id=task_id,
            results=results or {}
        )
        if event:
            await self.send_event(task_id, event)
        else:
            await self.send_event(task_id, "workflow_completed", {
                "results": results or {}
            })

    async def send_dag_created(
        self,
        task_id: str,
        nodes: list,
        edges: list,
        levels: int = 1
    ):
        """Send DAG created event."""
        event = create_dag_created_event(
            run_id=task_id,
            nodes=nodes,
            edges=edges,
            levels=levels
        )
        if event:
            await self.send_event(task_id, event)
        else:
            await self.send_event(task_id, "dag_created", {
                "nodes": nodes,
                "edges": edges,
                "levels": levels,
            })

    async def send_dag_node_status_changed(
        self,
        task_id: str,
        node_id: str,
        old_status: str,
        new_status: str
    ):
        """Send DAG node status change event."""
        event = create_dag_node_status_changed_event(
            run_id=task_id,
            node_id=node_id,
            old_status=old_status,
            new_status=new_status
        )
        if event:
            await self.send_event(task_id, event)
        else:
            await self.send_event(task_id, "dag_node_status_changed", {
                "node_id": node_id,
                "old_status": old_status,
                "new_status": new_status,
            })

    async def send_workflow_paused(self, task_id: str, message: str = "Workflow paused"):
        """Send workflow paused event."""
        event = WebSocketEvent(
            event_type=WebSocketEventType.WORKFLOW_PAUSED,
            timestamp=datetime.now(timezone.utc),
            run_id=task_id,
            data={"message": message, "status": "paused"}
        )
        await self.send_event(task_id, event)

    async def send_workflow_resumed(self, task_id: str, message: str = "Workflow resumed"):
        """Send workflow resumed event."""
        event = WebSocketEvent(
            event_type=WebSocketEventType.WORKFLOW_RESUMED,
            timestamp=datetime.now(timezone.utc),
            run_id=task_id,
            data={"message": message, "status": "executing"}
        )
        await self.send_event(task_id, event)

    async def send_workflow_cancelled(self, task_id: str, message: str = "Workflow cancelled"):
        """Send workflow cancelled event."""
        event = WebSocketEvent(
            event_type=WebSocketEventType.WORKFLOW_FAILED,
            timestamp=datetime.now(timezone.utc),
            run_id=task_id,
            data={"message": message, "status": "cancelled"}
        )
        await self.send_event(task_id, event)

    async def replay_missed_events(self, task_id: str, since_timestamp: float = None):
        """Replay events missed during disconnection"""
        try:
            if since_timestamp:
                events = event_queue.get_events_since(task_id, since_timestamp)
            else:
                events = event_queue.get_all_events(task_id)

            for event in events:
                await self.send_event(task_id, event, queue_if_disconnected=False)
        except Exception as e:
            logger.error("Failed to replay events for %s: %s", task_id, e)

    # ==================== Stats & Monitoring ====================

    async def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics"""
        async with self._lock:
            return {
                "active_connections": len(self._connections),
                "max_connections": self._max_connections,
                "connections": list(self._connections.keys())
            }

    def get_websocket(self, task_id: str) -> Optional[WebSocket]:
        """Get WebSocket for a task (for legacy compatibility)"""
        return self._connections.get(task_id)

    # ==================== Database Persistence ====================

    def _persist_connection(self, task_id: str, session_id: Optional[str]):
        """Persist connection to database"""
        if not self._db_factory:
            return

        from cmbagent.database.models import ActiveConnection
        import socket

        db = self._db_factory()
        try:
            # Upsert connection record
            existing = db.query(ActiveConnection).filter(
                ActiveConnection.task_id == task_id
            ).first()

            if existing:
                existing.session_id = session_id
                existing.last_heartbeat = datetime.now(timezone.utc)
                existing.server_instance = socket.gethostname()
            else:
                conn = ActiveConnection(
                    task_id=task_id,
                    session_id=session_id,
                    server_instance=socket.gethostname()
                )
                db.add(conn)

            db.commit()
        finally:
            db.close()

    def _remove_connection(self, task_id: str):
        """Remove connection from database"""
        if not self._db_factory:
            return

        from cmbagent.database.models import ActiveConnection

        db = self._db_factory()
        try:
            db.query(ActiveConnection).filter(
                ActiveConnection.task_id == task_id
            ).delete()
            db.commit()
        finally:
            db.close()


# Global connection manager instance
connection_manager = ConnectionManager(max_connections=100)
