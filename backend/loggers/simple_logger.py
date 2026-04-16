"""
Simple plain-text file logger with timestamps and buffering.

This module provides lightweight loggers for segregating logs into:
- run.log: Infrastructure events (connections, lifecycle, DAG operations)
- session.log: ALL events including agent output, tool calls, conversations
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import aiofiles
except ImportError:
    aiofiles = None


class SimpleFileLogger:
    """
    Simple plain-text logger with timestamps.

    Features:
    - Plain text format: [timestamp] [event_type] message key=value
    - Async I/O with buffering for performance
    - Thread-safe with asyncio.Lock
    - Graceful error handling
    """

    def __init__(self, log_path: Path, buffer_size: int = 10):
        """
        Initialize logger.

        Args:
            log_path: Path to log file
            buffer_size: Number of lines to buffer before flushing (default: 10)
        """
        self.log_path = Path(log_path)
        self.buffer = []
        self.buffer_size = buffer_size
        self.lock = asyncio.Lock()
        self._closed = False

        # Ensure parent directory exists
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    async def write(self, event_type: str, message: str = "", **kwargs):
        """
        Write a log entry.

        Format: [timestamp] [event_type] message key1=val1 key2=val2

        Args:
            event_type: Type of event (e.g., "run.started", "agent.output")
            message: Optional message text
            **kwargs: Additional key-value pairs to log
        """
        if self._closed:
            return

        try:
            # Generate timestamp in UTC
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            # Build log line
            parts = [f"[{timestamp}]", f"[{event_type}]"]

            if message:
                parts.append(message)

            # Add key-value pairs
            for key, val in kwargs.items():
                # Handle multiline values by replacing newlines
                val_str = str(val).replace("\n", "\\n")
                parts.append(f"{key}={val_str}")

            line = " ".join(parts) + "\n"

            # Buffer the line
            async with self.lock:
                self.buffer.append(line)
                if len(self.buffer) >= self.buffer_size:
                    await self._flush_unlocked()

        except Exception as e:
            # Graceful degradation - don't crash if logging fails
            print(f"[SimpleFileLogger] Failed to write log: {e}")

    async def flush(self):
        """Flush buffer to file (public, acquires lock)."""
        async with self.lock:
            await self._flush_unlocked()

    async def _flush_unlocked(self):
        """Flush buffer to file (private, assumes lock is held)."""
        if not self.buffer:
            return

        try:
            if aiofiles:
                # Use async file I/O if available
                async with aiofiles.open(self.log_path, "a", encoding="utf-8") as f:
                    await f.writelines(self.buffer)
            else:
                # Fallback to sync I/O
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.writelines(self.buffer)

            self.buffer.clear()

        except Exception as e:
            print(f"[SimpleFileLogger] Failed to flush buffer to {self.log_path}: {e}")

    async def close(self):
        """Flush and close the logger."""
        if self._closed:
            return

        self._closed = True
        await self.flush()

    def __repr__(self):
        return f"{self.__class__.__name__}(log_path={self.log_path})"


class RunLogger(SimpleFileLogger):
    """
    Logs infrastructure events to run.log.

    Events logged:
    - WebSocket connections/disconnections
    - Run lifecycle (started, paused, resumed, completed, failed)
    - DAG operations (created, updated, node status changes)
    - System info (work directory, config, resource limits)
    - Heartbeats (sampled)
    """

    pass


class SessionLogger(SimpleFileLogger):
    """
    Logs ALL events to session.log.

    Events logged (complete audit trail):
    - All AG2 stdio output (conversations, messages, thinking, print() calls)
    - Tool calls (function calls, arguments, results)
    - Code execution output (code blocks, execution results, errors)
    - Agent handoffs (speaker selection, agent transitions)
    - All events (file creation, approvals, cost updates, errors)
    - All run.log events too (for cross-run audit trail)
    """

    pass
