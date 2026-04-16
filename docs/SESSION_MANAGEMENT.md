# Session Management — AI Weekly

> Session and task lifecycle management for the standalone AI Weekly app.

---

## Overview

The AI Weekly app uses a simplified session management system focused on task persistence and resumption. Unlike a multi-mode workflow platform, the session layer here serves a single purpose: **persist AI Weekly tasks so they survive browser reloads and can be resumed**.

Key capabilities:
- **Task persistence:** Tasks stored in SQLite via SQLAlchemy
- **Resumable:** Incomplete tasks appear in the right-panel "Recent Tasks" dropdown
- **Cost tracking:** Per-task resource usage via CostRecord
- **Auto-cleanup:** Completed tasks auto-transition and are removed from the recent list

---

## Project Structure

### Backend (Python/FastAPI)

```
backend/
├── routers/
│   ├── aiweekly.py            # AI Weekly REST endpoints (13 endpoints)
│   ├── sessions.py            # Session REST API endpoints
│   ├── health.py              # Health check endpoint
│   └── models.py              # Model configuration endpoints
├── services/
│   ├── session_manager.py     # Session lifecycle management
│   ├── connection_manager.py  # WebSocket connection management
│   ├── workflow_service.py    # Workflow execution service
│   └── execution_service.py   # Task execution service
├── core/
│   ├── app.py                 # FastAPI app factory
│   ├── config.py              # Configuration
│   └── logging.py             # Logging setup
└── main.py                    # Application entry point
```

### Frontend (Next.js/React/TypeScript — SPA)

```
mars-ui/
├── app/
│   ├── page.tsx               # SPA shell — main content + right panel
│   ├── layout.tsx             # Root layout with AppShell
│   └── providers.tsx          # Theme, WebSocket, Toast providers
├── components/
│   ├── aiweekly/              # Setup, Review, Report panels
│   ├── tasks/
│   │   └── AIWeeklyReportTask.tsx  # 5-step wizard orchestrator
│   ├── layout/
│   │   ├── AppShell.tsx       # App shell (TopBar + content)
│   │   └── TopBar.tsx         # Centered "AI WEEKLY" + theme toggle
│   └── core/                  # Button, Stepper, Toast, etc.
├── hooks/
│   └── useAIWeeklyTask.ts     # State management, API calls, polling
├── contexts/
│   ├── WebSocketContext.tsx    # WebSocket state
│   └── ThemeContext.tsx        # Dark/light theme
└── types/
    └── aiweekly.ts            # TypeScript interfaces
```

---

## Task Lifecycle

### States

```
┌─────────────┐
│   Created    │  (POST /api/aiweekly/create)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Executing   │  (stages running sequentially)
└──────┬──────┘
       │
       ├──────────────────┐
       ▼                  ▼
┌─────────────┐    ┌─────────────┐
│  Completed   │    │   Failed    │
└─────────────┘    └─────────────┘
```

### Task Status Values

| Status | Description |
|--------|-------------|
| `executing` | Task is active — at least one stage pending or running |
| `completed` | All 4 stages completed (auto-transition) |
| `failed` | A stage failed or task was stopped by user |

---

## Session Manager

**File:** `backend/services/session_manager.py`

The `SessionManager` handles session creation for AI Weekly tasks.

### Key Methods

| Method | Purpose |
|---|---|
| `create_session(mode, config)` | Create session for a new task |
| `list_sessions(status, limit)` | List sessions with filters |
| `delete_session(session_id)` | Soft-delete session |

### Task-Specific Endpoints

The AI Weekly router (`routers/aiweekly.py`) provides task-specific lifecycle management:

| Endpoint | Purpose |
|---|---|
| `POST /api/aiweekly/create` | Create task (auto-creates session) |
| `GET /api/aiweekly/recent` | List incomplete tasks for resume |
| `GET /api/aiweekly/{id}` | Full task state with all stages |
| `POST /api/aiweekly/{id}/stop` | Cancel running task |
| `DELETE /api/aiweekly/{id}` | Delete task and all files |

---

## Task Resume Flow

### How Resumption Works

```
User clicks "Recent Tasks" in right panel
    │
    ▼
GET /api/aiweekly/recent
    → Returns incomplete tasks with stage/progress info
    │
    ▼
User clicks a task in the dropdown
    │
    ▼
React state update: resumeTaskId = task.task_id
    → AIWeeklyReportTask remounts with new key
    │
    ▼
useAIWeeklyTask.resumeTask(id)
    → GET /api/aiweekly/{id}
    → Finds latest completed stage
    → Sets currentStep to next wizard step
    │
    ▼
Wizard displays at correct step
    → User can continue from where they left off
```

Key points:
- **No page reload** — component swap via React state
- **URL deep-link support** — `?resume=<task_id>` query param sets initial state
- **Running stages reconnect** — if a stage is still running, console polling resumes

---

## Database Schema

### WorkflowRun

```sql
CREATE TABLE workflow_runs (
    id TEXT PRIMARY KEY,           -- task_id (UUID)
    session_id TEXT,               -- FK → sessions.id
    mode TEXT DEFAULT 'aiweekly',
    agent TEXT DEFAULT 'phase_orchestrator',
    status TEXT DEFAULT 'executing',
    task_description TEXT,
    meta JSON,                     -- {work_dir, task_config, orchestration}
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);
```

### TaskStage

```sql
CREATE TABLE task_stages (
    id TEXT PRIMARY KEY,
    parent_run_id TEXT,            -- FK → workflow_runs.id
    stage_number INTEGER,          -- 1–4
    stage_name TEXT,               -- data_collection, content_curation, etc.
    status TEXT DEFAULT 'pending', -- pending, running, completed, failed
    output_data JSON,             -- {shared: {key: content}, cost: {tokens}}
    error_message TEXT
);
```

### CostRecord

```sql
CREATE TABLE cost_records (
    id TEXT PRIMARY KEY,
    run_id TEXT,                   -- FK → workflow_runs.id
    model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    cost_usd REAL,
    timestamp TIMESTAMP
);
```

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key for LLM stages 2–4 |
| `NEWSAPI_KEY` | No | — | NewsAPI key for expanded data collection |
| `DATABASE_URL` | No | SQLite | PostgreSQL URL |
| `CMBAGENT_DEFAULT_WORK_DIR` | No | `~/Desktop/cmbdir` | Root data directory |
| `LOG_LEVEL` | No | `INFO` | Logging level |

### Ports

| Service | Port |
|---|---|
| Backend (FastAPI) | 8000 |
| Frontend (Next.js) | 3000 |
