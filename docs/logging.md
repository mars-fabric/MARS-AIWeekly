# Logging

> Logging patterns, configuration, and conventions for the AI Weekly standalone app.

---

## Overview

| Layer | Language | Library | Pattern |
|---|---|---|---|
| Backend | Python | `structlog` + stdlib `logging` | `get_logger(__name__)` |
| Frontend | TypeScript | Browser `console` API | `console.log/error/warn` |

The backend uses **structured logging** via `structlog` for machine-parseable output with context binding. The frontend uses the native browser console API.

---

## Backend Logging

### Configuration Module

**File:** `backend/core/logging.py`

Key exports:

| Function | Purpose |
|---|---|
| `configure_logging(log_level, json_output, log_file)` | Initialize logging |
| `get_logger(name)` | Return a `structlog.stdlib.BoundLogger` |
| `bind_context(task_id, session_id, run_id)` | Bind tracing context |
| `clear_context()` | Clear all bound context |

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CMBAGENT_DEFAULT_WORK_DIR` | `"~/Desktop/cmbdir"` | Root directory for all data |
| `LOG_LEVEL` | `"INFO"` | Minimum log level |
| `LOG_JSON` | `"false"` | JSON-formatted output |
| `LOG_FILE` | `"{work_dir}/logs/backend.log"` | Backend log file path |
| `CMBAGENT_DATABASE_URL` | — | Not used (file-based storage) |

### Logger Usage

Backend services and routers use:

```python
from core.logging import get_logger
logger = get_logger(__name__)

# Structured key-value pairs
logger.info("task_created", task_id=task_id, mode="aiweekly")
logger.error("stage_execution_failed", task_id=task_id, error=str(e))
```

### Structured Logging with structlog

Log calls accept keyword arguments as structured fields:

```
2024-01-15T10:30:45Z [info] task_created  task_id=abc123  mode=aiweekly
```

### Context Binding

Uses `contextvars` to attach tracing IDs to all log entries:

```python
from core.logging import bind_context, clear_context

bind_context(task_id="task_123", session_id="sess_456")
logger.info("processing")  # Automatically includes task_id and session_id
clear_context()
```

### Log Processors

The structlog pipeline:
1. `merge_contextvars` — Merge async context variables
2. `filter_by_level` — Filter below configured level
3. `add_logger_name` — Add module path
4. `add_log_level` — Add level string
5. `TimeStamper(fmt="iso")` — ISO 8601 timestamp
6. `StackInfoRenderer()` — Stack info if present
7. `format_exc_info` — Format tracebacks
8. `UnicodeDecoder()` — Unicode handling
9. `add_context_processor` — Inject task_id, session_id, run_id

### Output Formats

- **Development:** Colorized console via `ConsoleRenderer(colors=True)`
- **Production:** JSON via `JSONRenderer()` (set `LOG_JSON=true`)

### Suppressed Loggers

```python
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
```

### Log File Location

Default: `~/Desktop/cmbdir/logs/backend.log`

---

## Console Capture for AI Weekly Stages

During stage execution, `_ConsoleCapture` in `routers/aiweekly.py` intercepts `sys.stdout` to buffer console output. Frontend polls `GET /{id}/stages/{N}/console?since=idx` every 2 seconds to display real-time progress.

This is a lightweight, thread-safe capture mechanism specific to the AI Weekly pipeline — simpler than the full AG2 stdio capture used in the parent MARS project.

---

## Frontend Logging

### Console Methods

The frontend uses native browser `console` API:

```typescript
console.log('[WebSocket] Connecting...');
console.error('Error:', error);
console.warn('[WebSocket] Not connected');
```

### Debug Configuration

**File:** `mars-ui/lib/config.ts`

```typescript
debug: process.env.NEXT_PUBLIC_DEBUG === 'true',
```

---

## Log Levels

| Level | Usage |
|---|---|
| `DEBUG` | Detailed diagnostics: config dumps, state checks |
| `INFO` | Normal operations: task creation, stage execution |
| `WARNING` | Recoverable issues: missing state, failed sends |
| `ERROR` | Failures: database errors, execution failures |

Default level is `INFO`. Set `LOG_LEVEL=DEBUG` for verbose output.

---

## Best Practices

- Use `get_logger(__name__)` in all backend modules
- Add structured key-value pairs to log calls
- Bind `task_id` context before processing
- Don't log sensitive data (API keys, tokens)
- Use `LOG_JSON=true` in production for machine parsing
