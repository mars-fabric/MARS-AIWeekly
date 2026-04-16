"""
Structured Logging Configuration

Provides consistent logging across the application with:
- Context binding (task_id, session_id)
- JSON output for production
- Console output for development
- Integration with Python stdlib logging
"""

import logging
import sys
from contextvars import ContextVar
from typing import Optional

import structlog

# Context variables for request tracing
current_task_id: ContextVar[Optional[str]] = ContextVar('task_id', default=None)
current_session_id: ContextVar[Optional[str]] = ContextVar('session_id', default=None)
current_run_id: ContextVar[Optional[str]] = ContextVar('run_id', default=None)


def add_context_processor(logger, method_name, event_dict):
    """Add context variables to all log entries."""
    task_id = current_task_id.get()
    session_id = current_session_id.get()
    run_id = current_run_id.get()

    if task_id:
        event_dict['task_id'] = task_id
    if session_id:
        event_dict['session_id'] = session_id
    if run_id:
        event_dict['run_id'] = run_id

    return event_dict


_configured = False

# CRITICAL: Configure structlog immediately on module import to prevent
# incorrect default configuration from being used
# This is a minimal config that will be replaced by configure_logging()
structlog.configure(
    processors=[structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=False,
)


def configure_logging(
    log_level: str = "INFO",
    json_output: bool = False,
    log_file: Optional[str] = None
):
    """
    Configure structured logging for the application.

    Can be called multiple times (e.g., after uvicorn overrides logging).

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR)
        json_output: Use JSON format (for production)
        log_file: Optional file path for log output
    """
    global _configured

    print(f"[CONFIGURE_LOGGING] Called with log_file={log_file}, log_level={log_level}", file=sys.stderr)

    # Processors for structlog-native loggers
    structlog_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        add_context_processor,
    ]

    # Processors for foreign (stdlib) log records
    # NOTE: filter_by_level is excluded because it crashes on stdlib records
    # where the logger object is None in the ProcessorFormatter context
    foreign_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        add_context_processor,
    ]

    # Choose renderer based on environment
    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.plain_traceback
        )

    # Configure structlog
    structlog.configure(
        processors=structlog_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,  # Allow re-configuration
    )

    # Configure standard library logging
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=foreign_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    ))

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Add file handler if specified
    if log_file:
        print(f"[CONFIGURE_LOGGING] Adding file handler for {log_file}", file=sys.stderr)
        # Use mode 'a' (append) and delay=False to ensure immediate writes
        file_handler = logging.FileHandler(log_file, mode='a', delay=False)
        file_handler.setLevel(getattr(logging, log_level.upper()))  # Explicitly set level
        file_handler.setFormatter(structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=foreign_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),  # Always JSON for files
            ],
        ))
        root_logger.addHandler(file_handler)
        print(f"[CONFIGURE_LOGGING] File handler added successfully, total handlers: {len(root_logger.handlers)}", file=sys.stderr)

    # Reset any global logging disable (e.g. cmbagent's class-level
    # logging.disable(logging.CRITICAL) that runs at import time)
    logging.disable(logging.NOTSET)

    # Suppress noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Bound logger instance
    """
    if not _configured:
        configure_logging()

    # Ensure the stdlib logger has proper level set
    stdlib_logger = logging.getLogger(name)
    if stdlib_logger.level == logging.NOTSET:
        stdlib_logger.setLevel(logging.INFO)

    return structlog.get_logger(name)


def bind_context(
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None
):
    """
    Bind context for all subsequent log calls in this context.

    Args:
        task_id: Task identifier
        session_id: Session identifier
        run_id: Run identifier
    """
    if task_id:
        current_task_id.set(task_id)
    if session_id:
        current_session_id.set(session_id)
    if run_id:
        current_run_id.set(run_id)


def clear_context():
    """Clear all bound context."""
    current_task_id.set(None)
    current_session_id.set(None)
    current_run_id.set(None)


class LoggingContextManager:
    """
    Context manager for automatic context binding and cleanup.

    Usage:
        with LoggingContextManager(task_id="123"):
            logger.info("this includes task_id")
    """

    def __init__(
        self,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        run_id: Optional[str] = None
    ):
        self.task_id = task_id
        self.session_id = session_id
        self.run_id = run_id
        self._tokens = []

    def __enter__(self):
        if self.task_id:
            self._tokens.append(('task_id', current_task_id.set(self.task_id)))
        if self.session_id:
            self._tokens.append(('session_id', current_session_id.set(self.session_id)))
        if self.run_id:
            self._tokens.append(('run_id', current_run_id.set(self.run_id)))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for name, token in self._tokens:
            if name == 'task_id':
                current_task_id.reset(token)
            elif name == 'session_id':
                current_session_id.reset(token)
            elif name == 'run_id':
                current_run_id.reset(token)
        return False
