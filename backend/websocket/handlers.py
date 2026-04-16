"""
WebSocket endpoint and message handlers.

Uses the consolidated ConnectionManager as the single source of truth
for WebSocket connection management (Stage 4).

Session management (Stages 10-11):
- Every task execution creates a database-backed session via SessionManager
- Session state is persisted for pause/resume/continuation across all modes
- session_id is passed through config to the task executor
"""

import asyncio
from typing import Any, Dict

from fastapi import WebSocket, WebSocketDisconnect

from core.logging import get_logger
from websocket.events import send_ws_event

logger = get_logger(__name__)

# Active connections storage (fallback when services not available)
active_connections: Dict[str, WebSocket] = {}

# Services will be loaded at runtime
_services_available = None
_workflow_service = None
_connection_manager = None
_execution_service = None
_session_manager = None


def _check_services():
    """Check if services are available and load them."""
    global _services_available, _workflow_service, _connection_manager, _execution_service, _session_manager
    if _services_available is None:
        try:
            from services import workflow_service, connection_manager, execution_service
            from services.session_manager import get_session_manager
            _workflow_service = workflow_service
            _connection_manager = connection_manager
            _execution_service = execution_service
            _session_manager = get_session_manager()
            _services_available = True
        except ImportError:
            _services_available = False
    return _services_available


async def websocket_endpoint(websocket: WebSocket, task_id: str, execute_task_func):
    """Main WebSocket endpoint handler.

    Args:
        websocket: The WebSocket connection
        task_id: The task identifier
        execute_task_func: Function to execute CMBAgent task
    """
    await websocket.accept()

    # Register connection
    services_available = _check_services()
    if services_available:
        await _connection_manager.connect(websocket, task_id)
    else:
        active_connections[task_id] = websocket

    try:
        # Wait for task data
        data = await websocket.receive_json()
        task = data.get("task", "")
        config = data.get("config", {})

        # Debug logging
        logger.debug("WebSocket received data for task %s", task_id)
        logger.debug("Task: %s...", task[:100])
        logger.debug("Config mode: %s", config.get('mode', 'NOT SET'))
        logger.debug("Config keys: %s", list(config.keys()))

        if not task:
            await send_ws_event(websocket, "error", {"message": "No task provided"}, run_id=task_id)
            return

        mode = config.get("mode", "one-shot")

        # Create or reuse session for ALL modes (Stages 10-11)
        session_id = config.get("copilotSessionId") or config.get("session_id")
        if services_available and _session_manager and not session_id:
            try:
                session_id = _session_manager.create_session(
                    mode=mode,
                    config=config,
                    name=config.get("sessionName") or f"{mode}_{task_id[:8]}"
                )
                logger.info("Created session %s for task %s (mode=%s)", session_id, task_id, mode)
            except Exception as e:
                logger.warning("Failed to create session for task %s: %s", task_id, e)

        # Inject session_id into config so task executor can use it
        if session_id:
            config["session_id"] = session_id

        # Create workflow run in database if services available
        if services_available:
            # Extract mode-specific primary agent and model
            if mode == "planning-control":
                agent = "planner"
                model = config.get("plannerModel", config.get("model", "gpt-4o"))
            elif mode == "idea-generation":
                agent = "idea_maker"
                model = config.get("ideaMakerModel", config.get("model", "gpt-4o"))
            elif mode == "ocr":
                agent = "ocr"
                model = "mistral-ocr"
            elif mode == "arxiv":
                agent = "arxiv"
                model = "none"
            elif mode == "enhance-input":
                agent = "enhancer"
                model = config.get("defaultModel", "gpt-4o")
            else:  # one-shot
                agent = config.get("agent", "engineer")
                model = config.get("model", "gpt-4o")

            run_result = _workflow_service.create_workflow_run(
                task_id=task_id,
                task_description=task,
                mode=mode,
                agent=agent,
                model=model,
                config=config,
                session_id=session_id
            )
            logger.info("Created workflow run: %s", run_result)

        # Send initial status with session_id so frontend can track it
        await send_ws_event(
            websocket, "status",
            {"message": "Starting CMBAgent execution...", "session_id": session_id},
            run_id=task_id,
            session_id=session_id
        )

        # Create background task for execution
        execution_task = asyncio.create_task(
            execute_task_func(websocket, task_id, task, config)
        )

        # Handle both execution and client messages
        # Use a single persistent receive task to avoid resource leaks
        receive_task = asyncio.create_task(websocket.receive_json())

        try:
            while True:
                done, pending = await asyncio.wait(
                    [execution_task, receive_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Check if execution completed
                if execution_task in done:
                    # Cancel pending receive task to avoid resource leak
                    if receive_task in pending:
                        receive_task.cancel()
                        try:
                            await receive_task
                        except asyncio.CancelledError:
                            pass

                    # Check if execution_task had an exception
                    try:
                        result = execution_task.result()
                        logger.info("Execution completed successfully for task %s", task_id)
                    except Exception as exec_error:
                        logger.error("Execution failed for task %s: %s", task_id, exec_error)
                        # Try to send error to client
                        try:
                            await send_ws_event(
                                websocket, "error",
                                {"message": f"Task execution failed: {str(exec_error)}"},
                                run_id=task_id
                            )
                        except Exception:
                            pass  # WebSocket might already be closed
                    break

                # Handle client message
                if receive_task in done:
                    try:
                        client_msg = receive_task.result()
                        await handle_client_message(websocket, task_id, client_msg)
                    except WebSocketDisconnect:
                        logger.info("WebSocket disconnected while receiving for task %s", task_id)
                        break
                    except Exception as e:
                        logger.error("Error handling client message: %s", e)

                    # Create new receive task for next iteration
                    receive_task = asyncio.create_task(websocket.receive_json())

        except asyncio.CancelledError:
            # Clean up on cancellation
            if not execution_task.done():
                execution_task.cancel()
            if not receive_task.done():
                receive_task.cancel()
            raise

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for task %s", task_id)
    except Exception as e:
        logger.error("Error in WebSocket endpoint: %s", e)
        try:
            await send_ws_event(
                websocket, "error",
                {"message": f"Execution error: {str(e)}"},
                run_id=task_id
            )
        except:
            pass
    finally:
        # Disconnect
        if _check_services():
            await _connection_manager.disconnect(task_id)
        elif task_id in active_connections:
            del active_connections[task_id]


async def handle_client_message(websocket: WebSocket, task_id: str, message: dict):
    """Handle messages from client (e.g., approval responses, pause, resume).

    Integrates with Stage 3 (State Machine), Stage 5 (WebSocket Protocol),
    and Stage 6 (HITL Approval System).
    """
    msg_type = message.get("type")
    services_available = _check_services()

    if msg_type == "ping":
        if services_available:
            await _connection_manager.send_pong(task_id)
        else:
            await send_ws_event(websocket, "pong", {}, run_id=task_id)

    elif msg_type in ["resolve_approval", "approval_response"]:
        # Handle approval resolution (Stage 5: Robust Approvals)
        approval_id = message.get("approval_id")

        # Support both 'resolution' and 'approved' formats
        if "approved" in message:
            resolution = "approved" if message.get("approved") else "rejected"
        else:
            resolution = message.get("resolution", "rejected")

        feedback = message.get("feedback", "")
        modifications = message.get("modifications", "")

        # Parse modifications into dict
        modifications_dict = {}
        if modifications:
            try:
                import json
                modifications_dict = json.loads(modifications) if isinstance(modifications, str) else modifications
            except (json.JSONDecodeError, TypeError):
                modifications_dict = {"raw": modifications}

        # Combine feedback and modifications for legacy compatibility
        full_feedback = f"{feedback}\n\nModifications: {modifications}" if modifications else feedback

        # Single resolution path (Stage 11C)
        try:
            from cmbagent.database.websocket_approval_manager import WebSocketApprovalManager

            success = WebSocketApprovalManager.resolve_from_db(
                approval_id=approval_id,
                resolution=resolution,
                user_feedback=full_feedback,
                modifications=modifications_dict,
            )

            if success:
                logger.info("Approval %s resolved as %s", approval_id, resolution)
                await send_ws_event(
                    websocket, "approval_received",
                    {
                        "approval_id": approval_id,
                        "approved": resolution in ("approved", "modified"),
                        "resolution": resolution,
                        "feedback": full_feedback,
                    },
                    run_id=task_id,
                )
            else:
                logger.warning("Approval %s not found or already resolved", approval_id)
                await send_ws_event(
                    websocket, "error",
                    {"message": f"Approval {approval_id} not found or already resolved"},
                    run_id=task_id,
                )

        except Exception as e:
            logger.error("Error resolving approval: %s", e)
            await send_ws_event(
                websocket, "error",
                {"message": f"Failed to resolve approval: {str(e)}"},
                run_id=task_id,
            )

    elif msg_type == "pause":
        logger.info("Pause requested for task %s", task_id)

        if services_available:
            result = _workflow_service.pause_workflow(task_id)
            _execution_service.set_paused(task_id, True)
            await _connection_manager.send_workflow_paused(
                task_id, result.get("message", "Workflow paused")
            )
        else:
            await send_ws_event(
                websocket,
                "workflow_paused",
                {"message": "Workflow paused", "status": "paused"},
                run_id=task_id
            )

    elif msg_type == "resume":
        logger.info("Resume requested for task %s", task_id)

        if services_available:
            result = _workflow_service.resume_workflow(task_id)
            _execution_service.set_paused(task_id, False)
            await _connection_manager.send_workflow_resumed(
                task_id, result.get("message", "Workflow resumed")
            )
        else:
            await send_ws_event(
                websocket,
                "workflow_resumed",
                {"message": "Workflow resumed", "status": "executing"},
                run_id=task_id
            )

    elif msg_type == "cancel":
        logger.info("Cancel requested for task %s", task_id)

        if services_available:
            result = _workflow_service.cancel_workflow(task_id)
            _execution_service.set_cancelled(task_id, True)
            await _connection_manager.send_workflow_cancelled(
                task_id, result.get("message", "Workflow cancelled")
            )
        else:
            await send_ws_event(
                websocket,
                "workflow_cancelled",
                {"message": "Workflow cancelled", "status": "cancelled"},
                run_id=task_id
            )

    elif msg_type == "request_state":
        logger.debug("State request for task %s", task_id)
        if services_available:
            run_info = _workflow_service.get_run_info(task_id)
            if run_info:
                await _connection_manager.send_status(
                    task_id, run_info.get("status", "unknown")
                )
            # Replay missed events
            since_timestamp = message.get("since")
            await _connection_manager.replay_missed_events(task_id, since_timestamp)

    else:
        logger.warning("Unknown message type: %s", msg_type)
