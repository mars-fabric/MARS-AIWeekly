"""
Event Queue for WebSocket Messages

This module provides a thread-safe event queue for storing and retrieving
WebSocket events. Events are retained for a configurable time period to support
reliable delivery across reconnections.
"""

from collections import deque
from threading import Lock
from typing import Dict, List, Optional, Any
import time
from datetime import datetime

from websocket_events import WebSocketEvent


class QueuedEvent:
    """Wrapper for events with queue metadata"""

    def __init__(self, event: WebSocketEvent, queued_at: float):
        self.event = event
        self.queued_at = queued_at


class EventQueue:
    """Thread-safe event queue for WebSocket messages"""

    def __init__(self, max_size: int = 1000, retention_seconds: int = 300):
        """
        Initialize event queue

        Args:
            max_size: Maximum events to keep per run_id (default 1000)
            retention_seconds: How long to keep events in seconds (default 5 minutes)
        """
        self.max_size = max_size
        self.retention_seconds = retention_seconds
        self.queues: Dict[str, deque] = {}  # run_id -> deque of events
        self.lock = Lock()

    def push(self, run_id: str, event: WebSocketEvent):
        """
        Add event to queue for run_id

        Args:
            run_id: Workflow run ID
            event: WebSocket event to queue
        """
        with self.lock:
            if run_id not in self.queues:
                self.queues[run_id] = deque(maxlen=self.max_size)

            # Wrap event with queue metadata
            queued_event = QueuedEvent(event, time.time())

            self.queues[run_id].append(queued_event)

            # Cleanup old events
            self._cleanup_old_events(run_id)

    def get_events_since(self, run_id: str, since_timestamp: float) -> List[WebSocketEvent]:
        """
        Get all events since timestamp

        Args:
            run_id: Workflow run ID
            since_timestamp: Unix timestamp (seconds since epoch)

        Returns:
            List of events that occurred after the timestamp
        """
        with self.lock:
            if run_id not in self.queues:
                return []

            events = []
            for queued_event in self.queues[run_id]:
                if queued_event.queued_at > since_timestamp:
                    events.append(queued_event.event)

            return events

    def get_all_events(self, run_id: str) -> List[WebSocketEvent]:
        """
        Get all queued events for run_id

        Args:
            run_id: Workflow run ID

        Returns:
            List of all events in queue for this run_id
        """
        with self.lock:
            if run_id not in self.queues:
                return []
            return [queued_event.event for queued_event in self.queues[run_id]]

    def clear(self, run_id: str):
        """
        Clear queue for run_id

        Args:
            run_id: Workflow run ID
        """
        with self.lock:
            if run_id in self.queues:
                del self.queues[run_id]

    def clear_all(self):
        """Clear all queues"""
        with self.lock:
            self.queues.clear()

    def get_queue_size(self, run_id: str) -> int:
        """
        Get number of events in queue for run_id

        Args:
            run_id: Workflow run ID

        Returns:
            Number of events in queue
        """
        with self.lock:
            if run_id not in self.queues:
                return 0
            return len(self.queues[run_id])

    def get_all_run_ids(self) -> List[str]:
        """
        Get list of all run_ids with queued events

        Returns:
            List of run_ids
        """
        with self.lock:
            return list(self.queues.keys())

    def _cleanup_old_events(self, run_id: str):
        """
        Remove events older than retention period

        Args:
            run_id: Workflow run ID
        """
        now = time.time()
        cutoff = now - self.retention_seconds

        queue = self.queues[run_id]

        # Remove old events from the left of the deque
        while queue:
            queued_event = queue[0]

            if queued_event.queued_at < cutoff:
                queue.popleft()
            else:
                # Events are ordered by time, so we can stop here
                break

    def cleanup_all_old_events(self):
        """Cleanup old events from all queues"""
        with self.lock:
            for run_id in list(self.queues.keys()):
                self._cleanup_old_events(run_id)

                # Remove empty queues
                if len(self.queues[run_id]) == 0:
                    del self.queues[run_id]


# Global event queue instance
event_queue = EventQueue()
