"""
WebSocket module for handling real-time communication.
"""

from websocket.events import send_ws_event
from websocket.handlers import websocket_endpoint, handle_client_message

__all__ = [
    "send_ws_event",
    "websocket_endpoint",
    "handle_client_message",
]
