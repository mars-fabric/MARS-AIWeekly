# Session Management — AI Weekly

> Session and task lifecycle management for the standalone AI Weekly app.

---

## Overview

The AI Weekly app uses a simplified session management system focused on task persistence and resumption. Unlike a multi-mode workflow platform, the session layer here serves a single purpose: **persist AI Weekly tasks so they survive browser reloads and can be resumed**.

Key capabilities:
- **Task persistence:** Tasks stored as JSON files in `~/Desktop/cmbdir/aiweekly/`
- **Resumable:** All tasks (including completed) appear in the right sessions panel
- **Cost tracking:** Per-stage cost tracked in task.json output_data
- **Sessions panel:** Collapsible right panel with search, filter tabs, and task cards
- **Relative URLs:** Frontend uses `/api/aiweekly/recent` through Next.js proxy (works from any hostname)

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
│   ├── file_task_store.py     # JSON file-based task/stage persistence
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

## Task Persistence

**File:** `backend/services/file_task_store.py`

The `file_task_store` module handles all task data persistence using JSON files stored under `~/Desktop/cmbdir/aiweekly/`.

### Key Functions

| Function | Purpose |
|---|---|
| `create_task(task_id, work_dir, ...)` | Create task with stage definitions |
| `get_task(task_id)` | Load task data by scanning directories |
| `update_task(task_id, updates)` | Update top-level task fields |
| `update_stage(task_id, stage_num, updates)` | Update a specific stage |
| `list_recent_tasks(limit)` | List recent tasks for resume flow |
| `delete_task(task_id)` | Delete task directory and all files |

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
Right collapsible sessions panel (always visible, 320px open / 40px collapsed)
    │
    ▼
fetch('/api/aiweekly/recent')  (relative URL through Next.js proxy)
    → Returns all tasks with stage/progress info
    │
    ▼
Sessions panel shows task cards:
    • Status icon (green check / spinner / red X)
    • Stage info: "Completed" for finished, "Stage N: Name" otherwise
    • Actual date/time started (e.g. "Apr 30, 10:52 AM")
    • Progress bar with percentage
    • Delete button (hover)
    │
    ▼
User clicks a task card
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
- **Search & filter** — sessions panel has search bar + filter tabs (All/Running/Completed/Failed)
- **Running stages reconnect** — if a stage is still running, console polling resumes

---

## Data Storage

### File Structure

Each task is stored in its own directory under `~/Desktop/cmbdir/aiweekly/`:

```
~/Desktop/cmbdir/aiweekly/
├── {task_id[:8]}/
│   ├── task.json                  # Complete task state + all stage data
│   └── input_files/
│       ├── task_config.json       # User configuration
│       ├── collection.md          # Stage 1 output
│       ├── curated.md             # Stage 2 output
│       ├── report_draft.md        # Stage 3 output
│       ├── report_final.md        # Stage 4 output
│       └── cost_summary.md        # Auto-generated on completion
```

### task.json Schema

| Field | Type | Description |
|---|---|---|
| `id` | string | Task UUID |
| `status` | string | `executing`, `completed`, `failed` |
| `task_description` | string | Human-readable description |
| `mode` | string | Always `"aiweekly"` |
| `model` | string | Default LLM model |
| `work_dir` | string | Absolute path to task directory |
| `task_config` | object | `{date_from, date_to, topics, sources, style}` |
| `created_at` | string | ISO timestamp |
| `completed_at` | string | ISO timestamp or null |
| `stages` | array | Array of 4 stage objects |

### Stage Object

| Field | Type | Description |
|---|---|---|
| `stage_number` | int | 1–4 |
| `stage_name` | string | `data_collection`, `content_curation`, etc. |
| `status` | string | `pending`, `running`, `completed`, `failed` |
| `output_data` | object | `{"shared": {"<key>": "content"}, "cost": {...}}` |
| `error_message` | string | Error details if failed |
| `started_at` | string | ISO timestamp |
| `completed_at` | string | ISO timestamp |

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key for LLM stages 2–4 |
| `NEWSAPI_KEY` | No | — | NewsAPI key for expanded data collection |
| `CMBAGENT_DEFAULT_WORK_DIR` | No | `~/Desktop/cmbdir` | Root data directory |
| `LOG_LEVEL` | No | `INFO` | Logging level |

### Ports

| Service | Port |
|---|---|
| Backend (FastAPI) | 8000 |
| Frontend (Next.js) | 3000 |
