"""
Stream capture classes for intercepting stdout/stderr and AG2 events.

StreamCapture: Relay stdout to WebSocket and log file. Zero detection logic.
AG2IOStreamCapture: Intercept AG2 events and forward to WebSocket.
"""

import asyncio
import os
from io import StringIO
from typing import Any, Dict, Optional

from fastapi import WebSocket
from core.logging import get_logger

logger = get_logger(__name__)


class AG2IOStreamCapture:
    """
    Custom AG2 IOStream that intercepts all AG2 events and forwards them to WebSocket.
    This captures all agent messages, tool calls, function responses, etc.
    """

    def __init__(self, websocket: WebSocket, task_id: str, send_event_func, loop=None, session_id: str = None, session_logger=None):
        self.websocket = websocket
        self.task_id = task_id
        self.send_event = send_event_func
        self.loop = loop or asyncio.get_event_loop()
        self._original_print = print
        self.session_id = session_id
        self.session_logger = session_logger

        # Track writes for periodic flushing
        self._write_count = 0
        self._flush_interval = 10  # Flush every 10 writes

    def print(self, *objects: Any, sep: str = " ", end: str = "\n", flush: bool = False) -> None:
        """Capture print calls and send to WebSocket and log file (suppressed from terminal)"""
        message = sep.join(str(obj) for obj in objects)
        if message.strip():
            try:
                # Send to WebSocket for real-time UI display
                future = asyncio.run_coroutine_threadsafe(
                    self._send_output(message),
                    self.loop
                )
                # Write to session.log for persistence
                if self.session_logger:
                    asyncio.run_coroutine_threadsafe(
                        self.session_logger.write("agent.output", message.strip()),
                        self.loop
                    )
                    # Periodic flush
                    self._write_count += 1
                    if self._write_count >= self._flush_interval:
                        asyncio.run_coroutine_threadsafe(
                            self.session_logger.flush(),
                            self.loop
                        )
                        self._write_count = 0
            except Exception as e:
                logger.warning("ag2_iostream_print_error", error=str(e))
        # Do NOT print to terminal - output captured via WebSocket + log files only

    def send(self, message) -> None:
        """
        Capture AG2 events and forward to WebSocket.
        AG2 sends BaseEvent objects here with their own print() methods.
        """
        try:
            event_data = self._extract_event_data(message)
            if event_data:
                future = asyncio.run_coroutine_threadsafe(
                    self._send_structured_event(event_data),
                    self.loop
                )
            # Do NOT print to terminal - AG2 events captured via WebSocket only
        except AttributeError as e:
            # Silently ignore fileno-related errors - AG2 checking for terminal capabilities
            if 'fileno' not in str(e):
                logger.warning("ag2_iostream_send_error", error=str(e))
        except Exception as e:
            logger.warning("ag2_iostream_send_error", error=str(e))

    def _extract_event_data(self, event) -> Optional[Dict[str, Any]]:
        """Extract structured data from AG2 events - full content for complete audit trail"""
        try:
            event_type = type(event).__name__
            actual_event = getattr(event, 'content', event)

            data = {
                "event_type": event_type,
                "sender": getattr(actual_event, 'sender', None),
                "recipient": getattr(actual_event, 'recipient', None),
            }

            if hasattr(actual_event, 'content'):
                content = actual_event.content
                if content is not None:
                    data["content"] = str(content)  # Full content - no truncation

            if hasattr(actual_event, 'function_call'):
                fc = actual_event.function_call
                if fc:
                    data["function_name"] = getattr(fc, 'name', None)
                    data["function_arguments"] = getattr(fc, 'arguments', None)

            if hasattr(actual_event, 'tool_calls'):
                tool_calls = actual_event.tool_calls
                if tool_calls:
                    data["tool_calls"] = []
                    for tc in tool_calls:
                        tc_data = {
                            "id": getattr(tc, 'id', None),
                            "name": getattr(tc.function, 'name', None) if hasattr(tc, 'function') else None,
                            "arguments": getattr(tc.function, 'arguments', None) if hasattr(tc, 'function') else None,
                        }
                        data["tool_calls"].append(tc_data)

            if hasattr(actual_event, 'tool_responses'):
                tool_responses = actual_event.tool_responses
                if tool_responses:
                    data["tool_responses"] = []
                    for tr in tool_responses:
                        tr_data = {
                            "tool_call_id": getattr(tr, 'tool_call_id', None),
                            "content": str(getattr(tr, 'content', '')),  # Full content - no truncation
                        }
                        data["tool_responses"].append(tr_data)

            return data
        except Exception as e:
            return {"event_type": "unknown", "error": str(e)}

    async def _send_output(self, message: str):
        """Send output message to WebSocket"""
        try:
            await self.send_event(
                self.websocket,
                "output",
                {"message": message},
                run_id=self.task_id,
                session_id=self.session_id
            )
        except Exception as e:
            logger.warning("ws_output_send_failed", error=str(e))

    async def _send_structured_event(self, event_data: Dict[str, Any]):
        """Send structured AG2 event to WebSocket and log file"""
        try:
            event_type = event_data.get("event_type", "SYSTEM")
            sender = event_data.get("sender", "SYSTEM")
            content = event_data.get("content", "")

            if "ToolCall" in event_type or "FunctionCall" in event_type:
                ws_event_type = "tool_call"
                data = {
                    "agent": sender,
                    "tool_name": event_data.get("function_name") or "SYSTEM",
                    "arguments": event_data.get("function_arguments") or event_data.get("tool_calls", []),
                    "result": None
                }
                # Log to session.log (full content - no truncation for audit trail)
                if self.session_logger:
                    tool_name = event_data.get("function_name") or "SYSTEM"
                    await self.session_logger.write("tool.call", f"{sender}: {tool_name}",
                        arguments=str(event_data.get("function_arguments", "")))
            elif "ToolResponse" in event_type or "FunctionResponse" in event_type:
                ws_event_type = "tool_call"
                data = {
                    "agent": sender,
                    "tool_name": event_data.get("name", "SYSTEM"),
                    "arguments": {},
                    "result": content
                }
                # Log to session.log (full content - no truncation for audit trail)
                if self.session_logger:
                    await self.session_logger.write("tool.response", f"{sender}: result",
                        content=str(content))
            elif "Text" in event_type or "Received" in event_type:
                ws_event_type = "agent_message"
                data = {
                    "agent": sender,
                    "role": "assistant",
                    "message": content,
                    "metadata": {"recipient": event_data.get("recipient")}
                }
                # Log to session.log (full content - no truncation for audit trail)
                if self.session_logger:
                    await self.session_logger.write("agent.message", f"{sender}: {content}")
            else:
                ws_event_type = "agent_message"
                data = {
                    "agent": sender or "system",
                    "role": "system",
                    "message": f"[{event_type}] {content}" if content else f"[{event_type}]",
                    "metadata": event_data
                }
                # Log to session.log (full content - no truncation for audit trail)
                if self.session_logger:
                    msg = f"[{event_type}] {content}" if content else f"[{event_type}]"
                    await self.session_logger.write("agent.event", msg)

            await self.send_event(
                self.websocket,
                ws_event_type,
                data,
                run_id=self.task_id,
                session_id=self.session_id
            )
        except Exception as e:
            logger.warning("ws_structured_event_failed", error=str(e))

    def input(self, prompt: str = "", *, password: bool = False) -> str:
        """Handle input requests - not typically used in autonomous mode"""
        return ""


class StreamCapture:
    """Relay stdout to WebSocket and segregated log files (run.log and session.log)."""

    def __init__(self, websocket: WebSocket, task_id: str, send_event_func,
                 loop=None, work_dir=None, session_id: str = None,
                 run_logger=None, session_logger=None):
        self.websocket = websocket
        self.task_id = task_id
        self.send_event = send_event_func
        self.buffer = StringIO()
        self.loop = loop
        self.session_id = session_id

        # Simplified logging with segregated loggers
        self.run_logger = run_logger
        self.session_logger = session_logger

        # Track writes for periodic flushing
        self._write_count = 0
        self._flush_interval = 10  # Flush every 10 writes

    async def write(self, text: str):
        """Write text to buffer, WebSocket, and session.log."""
        if text.strip():
            # Send to WebSocket (keep existing behavior)
            try:
                await self.send_event(
                    self.websocket,
                    "output",
                    {"message": text.strip()},
                    run_id=self.task_id,
                    session_id=self.session_id
                )
            except Exception as e:
                logger.warning("ws_stream_send_failed", error=str(e))

            # Write to session.log (ALL agent output goes here)
            if self.session_logger:
                try:
                    await self.session_logger.write("agent.output", text.strip())

                    # Periodic flush to ensure logs are written
                    self._write_count += 1
                    if self._write_count >= self._flush_interval:
                        await self.session_logger.flush()
                        self._write_count = 0
                except Exception as e:
                    logger.warning("session_log_write_failed", error=str(e))

        # Keep in-memory buffer for getvalue()
        self.buffer.write(text)

        return len(text)

    async def flush(self):
        """Flush all loggers."""
        try:
            if self.run_logger:
                await self.run_logger.flush()
            if self.session_logger:
                await self.session_logger.flush()
        except Exception as e:
            logger.warning("logger_flush_failed", error=str(e))

    def getvalue(self):
        return self.buffer.getvalue()

    async def close(self):
        """Close loggers and flush buffers."""
        if self.run_logger:
            try:
                await self.run_logger.close()
            except Exception as e:
                logger.warning("run_logger_close_failed", error=str(e))

        if self.session_logger:
            try:
                await self.session_logger.close()
            except Exception as e:
                logger.warning("session_logger_close_failed", error=str(e))
