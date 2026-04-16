# MARS-AIWeekly — Application Architecture

Technical architecture of the standalone AI Weekly Report Generator, extracted from Mars.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         MARS-AIWeekly                                   │
│                                                                         │
│  ┌──────────────┐     HTTP/WS      ┌──────────────┐    Python lib     │
│  │   Frontend    │ ◄──────────────► │   Backend    │ ◄──────────────► │
│  │  (Next.js)    │   localhost:3000  │  (FastAPI)   │   import         │
│  │               │     ──────►      │              │                   │
│  │  Port 3000    │   localhost:8000  │  Port 8000   │  ┌────────────┐ │
│  └──────────────┘                   └──────┬───────┘  │  cmbagent   │ │
│                                            │          │  (library)  │ │
│                                            ▼          └────────────┘ │
│                                     ┌──────────────┐                  │
│                                     │  PostgreSQL   │                  │
│                                     │  / SQLite     │                  │
│                                     └──────────────┘                  │
└─────────────────────────────────────────────────────────────────────────┘
```

**Three runtime components:**
1. **Frontend** — Next.js React app (port 3000)
2. **Backend** — FastAPI Python server (port 8000)
3. **cmbagent** — Installed Python library (not embedded), provides AI Weekly phase execution, database models, and news collection tools

---

## Data Flow: End-to-End

```
User (Browser)
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. SETUP                                                         │
│    AIWeeklySetupPanel → POST /api/aiweekly/create               │
│    User selects: date range, topics, sources, model, style       │
│    Backend creates: TaskStage records (stages 1-4, status=pending)│
│    Returns: task_id, work_dir, stages[]                          │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. STAGE EXECUTION (repeated for stages 1→4)                    │
│                                                                  │
│    Frontend: POST /api/aiweekly/{task_id}/stages/{N}/execute    │
│                                                                  │
│    Backend (routers/aiweekly.py):                               │
│      ├─ _load_phase_class(N) → importlib dynamic import         │
│      ├─ _build_shared_state() → merge outputs from prior stages │
│      ├─ PhaseClass(config=...).execute(ctx):                    │
│      │     Stage 1: news_tools → raw collection (no LLM)       │
│      │     Stage 2: 3-agent LLM pipeline → curated items       │
│      │     Stage 3: 3-agent LLM pipeline → draft report (MD)   │
│      │     Stage 4: review pipeline → final report (MD)         │
│      ├─ _ConsoleCapture → buffer stdout/stderr                  │
│      ├─ CostRepository.record() → track token usage             │
│      └─ TaskStage.status = "completed", save output_data        │
│                                                                  │
│    Frontend: polls GET /api/aiweekly/{id}/stages/{N}/console    │
│              every 2s for real-time console output               │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. REVIEW & REFINEMENT (optional, between stages)               │
│                                                                  │
│    AIWeeklyReviewPanel → user edits markdown in split pane      │
│    POST /api/aiweekly/{id}/stages/{N}/save → save edits        │
│    POST /api/aiweekly/{id}/stages/{N}/refine → LLM refinement  │
│    User can iterate, then advance to next stage                  │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. FINAL REPORT                                                  │
│                                                                  │
│    AIWeeklyReportPanel → renders final markdown                 │
│    GET /api/aiweekly/{id}/stages/4/content → final report       │
│    Download: markdown file, cost summary                         │
│    cost_summary.md written to work_dir on completion            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Backend Architecture

### Layer Diagram

```
                        HTTP Requests / WebSocket
                              │
                ┌─────────────┴─────────────┐
                │         main.py            │
                │   (FastAPI app instance)   │
                │   register_routers(app)    │
                │   WS endpoint mounting     │
                └─────────────┬─────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
   ┌─────────────┐   ┌──────────────┐   ┌──────────────┐
   │   Routers    │   │  WebSocket   │   │    Core      │
   │              │   │  handlers.py │   │  app.py      │
   │ aiweekly.py  │   │  events.py   │   │  config.py   │
   │ tasks.py     │   │              │   │  logging.py  │
   │ sessions.py  │   └──────┬───────┘   └──────────────┘
   │ health.py    │          │
   │ models.py    │          │
   └──────┬───────┘          │
          │                  │
          ▼                  ▼
   ┌─────────────────────────────────┐
   │           Services              │
   │                                 │
   │  session_manager.py             │
   │  execution_service.py           │
   │  workflow_service.py            │
   │  connection_manager.py          │
   └──────────────┬──────────────────┘
                  │
                  ▼
   ┌─────────────────────────────────┐
   │         Execution               │
   │                                 │
   │  task_executor.py               │
   │  stream_capture.py              │
   │  cost_collector.py              │
   │  dag_tracker.py                 │
   └──────────────┬──────────────────┘
                  │
                  ▼
   ┌─────────────────────────────────┐
   │    cmbagent (installed lib)     │
   │                                 │
   │  phases/aiweekly/               │
   │    collection_phase.py          │
   │    curation_phase.py            │
   │    generation_phase.py          │
   │    review_phase.py              │
   │    base.py                      │
   │                                 │
   │  database/                      │
   │    models.py (TaskStage,        │
   │      WorkflowRun, CostRecord)   │
   │    repository.py                │
   │    base.py (get_db_session)     │
   │                                 │
   │  external_tools/                │
   │    news_tools.py                │
   └─────────────────────────────────┘
```

### Router Responsibilities

| Router | Prefix | Purpose |
|---|---|---|
| `aiweekly.py` | `/api/aiweekly` | 13 endpoints: create task, execute/poll/save/refine stages, get console, get state, list recent, delete, reset |
| `tasks.py` | `/api/tasks` | Generic task submission (`POST /tasks/ai-weekly/execute`) |
| `sessions.py` | `/api/sessions` | Session CRUD: create, list, get, suspend, resume, complete |
| `health.py` | `/api/health` | Liveness probe |
| `models.py` | `/api/models` | List available LLM models for frontend selector |

### Session Management Flow

```
   Create Session                    Execute Stages                    Complete
   ─────────────                    ──────────────                    ────────
                                                                      
   SessionManager                   task_executor.py                  SessionManager
   .create_session()                                                  .complete_session()
        │                                │                                 │
        ▼                                ▼                                 ▼
   ┌──────────┐                    ┌──────────┐                     ┌──────────┐
   │ Session   │                   │ Session   │                    │ Session   │
   │ record    │                   │ state     │                    │ status=   │
   │ mode=     │                   │ saved on  │                    │ completed │
   │ aiweekly  │                   │ each phase│                    │          │
   └──────────┘                    │ change    │                    └──────────┘
                                   └──────────┘
                                                                      
   DB: Session + SessionState      DB: Session state updated        DB: Final state
```

The backend in Mars uses `SessionManager` for all tasks. The same class is used here, scoped to the `aiweekly` mode. Sessions enable:
- **Pause/Resume** — user can close browser, come back later
- **State recovery** — stages track completion status in DB
- **Work directory isolation** — `sessions/{session_id}/tasks/{task_id}/`

### Phase Execution Pipeline (cmbagent)

```
routers/aiweekly.py
    │
    │  _run_aiweekly_stage(task_id, stage_num, config)
    │
    ├── _load_phase_class(stage_num)
    │       Uses importlib to load:
    │       Stage 1 → AIWeeklyCollectionPhase
    │       Stage 2 → AIWeeklyCurationPhase
    │       Stage 3 → AIWeeklyGenerationPhase
    │       Stage 4 → AIWeeklyReviewPhase
    │
    ├── _build_shared_state(task_id)
    │       Queries completed TaskStage records
    │       Merges output_data["shared"] from each
    │       Returns cumulative context dict
    │
    ├── PhaseClass(config).execute(ctx)
    │       │
    │       │  Stage 1 (Collection):
    │       │    news_tools.py → RSS, NewsAPI, Google News, web search
    │       │    Output: raw_collection (list of news items)
    │       │    Cost: $0 (no LLM)
    │       │
    │       │  Stage 2 (Curation):
    │       │    3-agent LLM pipeline (Primary → Specialist → Reviewer)
    │       │    Input: raw_collection
    │       │    Output: curated_items (deduplicated, filtered)
    │       │
    │       │  Stage 3 (Generation):
    │       │    3-agent LLM pipeline
    │       │    Input: curated_items
    │       │    Output: draft_report (markdown)
    │       │
    │       │  Stage 4 (Review):
    │       │    Review pipeline
    │       │    Input: draft_report
    │       │    Output: final_report (publication-ready markdown)
    │       │
    │       └── return result
    │
    ├── CostRepository.record(task_id, stage, tokens)
    │
    └── TaskStage.update(status="completed", output_data=result)
```

---

## Frontend Architecture

### Component Hierarchy

```
app/layout.tsx
  └── providers.tsx
        ├── ThemeContext
        └── WebSocketContext
              └── app/page.tsx (AI Weekly = default homepage)
                    └── AIWeeklyReportTask
                          │
                          ├── Stepper (wizard navigation)
                          │
                          ├── Step 0: AIWeeklySetupPanel
                          │     ├── Date range picker
                          │     ├── Topic/source selectors
                          │     ├── Model config (via useModelConfig)
                          │     └── Style selection
                          │
                          ├── Steps 1-3: AIWeeklyReviewPanel
                          │     ├── ResizableSplitPane
                          │     │     ├── Left: MarkdownRenderer (preview)
                          │     │     │         or textarea (edit mode)
                          │     │     └── Right: RefinementChat
                          │     └── ExecutionProgress (during stage run)
                          │
                          └── Step 4: AIWeeklyReportPanel
                                ├── MarkdownRenderer (final report)
                                ├── ExecutionProgress (during stage run)
                                └── Download buttons (MD, cost summary)
```

### State Management

```
┌──────────────────────────────────────────────┐
│          useAIWeeklyTask() hook               │
│                                                │
│  State:                                        │
│    taskId          — current task ID           │
│    taskState       — stages[], status, costs   │
│    currentStep     — wizard step (0-4)         │
│    editableContent — per-stage edited markdown │
│    consoleOutput   — real-time console lines   │
│    isExecuting     — stage running flag        │
│    error           — latest error              │
│                                                │
│  Actions:                                      │
│    createTask(config)    → POST /create        │
│    executeStage(N)       → POST /stages/N/exec │
│    saveContent(N, text)  → POST /stages/N/save │
│    refineContent(N, msg) → POST /stages/N/refine│
│    resumeTask(id)        → GET /{id}           │
│    deleteTask(id)        → DELETE /{id}        │
│    resetFromStage(N)     → POST /{id}/reset/N  │
│                                                │
│  Polling:                                      │
│    Console: GET /stages/N/console?since=X      │
│             every 2 seconds during execution   │
│    State:   GET /{task_id} every 5 seconds     │
│             during execution                   │
└──────────────────────────────────────────────┘
```

### API Communication Pattern

```
Frontend (hooks)                        Backend (routers)
──────────────────                      ─────────────────

useAIWeeklyTask
  │
  ├── REST (fetch + retry) ────────────► aiweekly.py
  │     POST /api/aiweekly/create           13 endpoints
  │     POST /api/aiweekly/{id}/stages/{N}/execute
  │     GET  /api/aiweekly/{id}/stages/{N}/console
  │     GET  /api/aiweekly/{id}/stages/{N}/content
  │     POST /api/aiweekly/{id}/stages/{N}/save
  │     POST /api/aiweekly/{id}/stages/{N}/refine
  │     GET  /api/aiweekly/{id}
  │     GET  /api/aiweekly/recent
  │     DELETE /api/aiweekly/{id}
  │     POST /api/aiweekly/{id}/reset/{N}
  │
  ├── REST ─────────────────────────────► tasks.py
  │     POST /api/tasks/ai-weekly/execute
  │
useModelConfig
  │
  └── REST ─────────────────────────────► models.py
        GET /api/models

WebSocketContext
  │
  └── WebSocket ────────────────────────► websocket/handlers.py
        ws://localhost:8000/ws              session bind
                                           task spawn
                                           pause/resume/cancel

useSessionDetail
  │
  └── REST ─────────────────────────────► sessions.py
        GET /api/sessions/{id}
        POST /api/sessions
```

---

## Database Schema (via cmbagent)

All models come from `cmbagent.database.models`. The backend does not define its own ORM — it uses the library's tables.

```
┌─────────────────┐     ┌──────────────────┐     ┌───────────────┐
│   Session        │     │   WorkflowRun    │     │  TaskStage     │
├─────────────────┤     ├──────────────────┤     ├───────────────┤
│ id              │◄────│ session_id       │     │ id            │
│ mode (aiweekly) │     │ id               │◄────│ workflow_run_id│
│ status          │     │ task_id          │     │ stage_number  │
│ created_at      │     │ status           │     │ stage_name    │
│ updated_at      │     │ config (JSON)    │     │ status        │
└─────────────────┘     │ created_at       │     │ output_data   │
                        │ completed_at     │     │ error         │
      ┌─────────────────┤                  │     │ started_at    │
      │                 └──────────────────┘     │ completed_at  │
      ▼                                          └───────────────┘
┌─────────────────┐
│  SessionState    │     ┌───────────────┐
├─────────────────┤     │  CostRecord    │
│ id              │     ├───────────────┤
│ session_id      │     │ id            │
│ state_data (JSON│     │ task_id       │
│ saved_at        │     │ stage_number  │
└─────────────────┘     │ prompt_tokens │
                        │ completion_tkn│
                        │ cost_usd      │
                        │ model         │
                        └───────────────┘
```

---

## Deployment Architecture

### Docker Compose (3 services)

```yaml
services:
  backend:
    build: .                    # Dockerfile
    ports: ["8000:8000"]
    environment:
      - DATABASE_URL=postgresql://...
      - AZURE_OPENAI_API_KEY=...
      - NEWSAPI_KEY=...
    depends_on: [db]

  frontend:
    build:
      context: mars-ui
      dockerfile: ../Dockerfile.nextjs
    ports: ["3000:3000"]
    environment:
      - NEXT_PUBLIC_API_URL=http://backend:8000
    depends_on: [backend]

  db:
    image: postgres:16-alpine
    volumes: [pgdata:/var/lib/postgresql/data]
    environment:
      - POSTGRES_DB=mars_aiweekly
      - POSTGRES_USER=mars
      - POSTGRES_PASSWORD=...
```

### Development Mode

```
Terminal 1:  cd backend && python run.py        # uvicorn on :8000
Terminal 2:  cd mars-ui && npm run dev           # next dev on :3000
```

---

## Key Design Decisions (inherited from Mars)

| Decision | Rationale |
|---|---|
| REST polling over WebSocket for stage execution | AI Weekly stages are long-running (minutes). Polling every 2s for console + 5s for state is simpler and more resilient than maintaining a persistent WS for the duration. |
| cmbagent as library, not embedded | Avoids code duplication. Phase classes, database models, and tools are maintained in one place. Mars-AIWeekly installs it as a pip dependency. |
| 4-stage pipeline with shared state | Each stage builds on the previous one's `output_data["shared"]`. State is persisted in DB between stages, enabling pause/resume and per-stage review. |
| importlib phase loading | `_load_phase_class(N)` uses importlib to dynamically load `cmbagent.phases.aiweekly.*`. This decouples the backend from specific phase implementations. |
| Console capture via `_ConsoleCapture` | Intercepts stdout/stderr during phase execution. Buffered per task+stage, served via polling endpoint. No extra logging framework needed. |
| SessionManager singleton | `get_session_manager()` returns a single instance per process. All session operations go through it. Avoids connection pool exhaustion. |
| Frontend wizard pattern | 5-step wizard (Setup → Collection Review → Curation Review → Generation Review → Final Report) gives users control at each stage versus a fire-and-forget approach. |
| Shared deepresearch components | `RefinementChat` and `ExecutionProgress` are reused from deepresearch. They are generic enough — no AI-Weekly-specific logic was added to them. |

---

## External Dependencies

### Backend (Python)
| Package | Purpose |
|---|---|
| `cmbagent` | Phase execution, DB models, news tools |
| `fastapi` | Web framework |
| `uvicorn` | ASGI server |
| `sqlalchemy` | ORM / DB access |
| `alembic` | DB migrations |
| `pydantic` | Request/response validation |
| `websockets` | WS protocol support |
| `python-dotenv` | Environment variable loading |

### Frontend (Node.js)
| Package | Purpose |
|---|---|
| `next` | React framework |
| `react` | UI library |
| `tailwindcss` | Utility-first CSS |
| `lucide-react` | Icon library |
| `html2pdf.js` | PDF export of reports |

### External APIs (runtime)
| API | Used By | Stage |
|---|---|---|
| Azure OpenAI / OpenAI | cmbagent phases 2-4 | LLM calls |
| NewsAPI | cmbagent news_tools | Stage 1 collection |
| Google News | cmbagent news_tools | Stage 1 collection |
| DuckDuckGo Search | cmbagent news_tools | Stage 1 collection |
| RSS feeds (26 sources) | cmbagent news_tools | Stage 1 collection |
