# MARS-AIWeekly — Application Structure

Standalone extraction of the AI Weekly feature from [Mars](https://github.com/UJ2202/MARS.git).  
Every file listed below maps 1:1 to a file in Mars. No additions, no rewrites.

---

## Directory Tree

```
mars-aiweekly/
├── backend/
│   ├── core/
│   │   ├── __init__.py              ← from backend/core/__init__.py
│   │   ├── app.py                   ← FastAPI app factory (create_app, CORS)
│   │   ├── config.py                ← Settings dataclass (env vars, work dirs)
│   │   └── logging.py               ← get_logger(), configure_logging()
│   │
│   ├── routers/
│   │   ├── __init__.py              ← register_routers() — only the 4 routers below
│   │   ├── aiweekly.py              ← /api/aiweekly/* — 13 endpoints, phase loader, console capture
│   │   ├── tasks.py                 ← /api/tasks/* — task submission (POST /tasks/ai-weekly/execute)
│   │   ├── sessions.py              ← /api/sessions/* — session CRUD, suspend/resume
│   │   ├── health.py                ← /api/health — liveness check
│   │   └── models.py                ← /api/models — LLM model listing for frontend selector
│   │
│   ├── models/
│   │   ├── __init__.py              ← from backend/models/__init__.py
│   │   ├── aiweekly_schemas.py      ← Pydantic: AIWeeklyCreateRequest/Response, stage schemas
│   │   └── schemas.py               ← Pydantic: TaskType, TaskRequest, TaskResponse (generic)
│   │
│   ├── services/
│   │   ├── __init__.py              ← from backend/services/__init__.py
│   │   ├── session_manager.py       ← SessionManager (create/save/load/suspend/resume)
│   │   ├── execution_service.py     ← Async task execution with pause/resume
│   │   ├── workflow_service.py      ← WorkflowRun record management
│   │   └── connection_manager.py    ← WebSocket connection pool
│   │
│   ├── execution/
│   │   ├── __init__.py              ← from backend/execution/__init__.py
│   │   ├── task_executor.py         ← execute_cmbagent_task(), work dir setup
│   │   ├── stream_capture.py        ← StreamCapture, AG2IOStreamCapture
│   │   ├── cost_collector.py        ← LLM token cost tracking
│   │   └── dag_tracker.py           ← Execution state/DAG tracking
│   │
│   ├── websocket/
│   │   ├── __init__.py              ← from backend/websocket/__init__.py
│   │   ├── handlers.py              ← websocket_endpoint() — session bind, task spawn
│   │   └── events.py                ← send_ws_event() with retry logic
│   │
│   ├── callbacks/
│   │   ├── __init__.py              ← from backend/callbacks/__init__.py
│   │   ├── websocket_callbacks.py   ← WS event emission callbacks
│   │   └── database_callbacks.py    ← DB persistence callbacks
│   │
│   ├── loggers/
│   │   ├── __init__.py              ← from backend/loggers/__init__.py
│   │   ├── logger_factory.py        ← LoggerFactory for structured logging
│   │   └── simple_logger.py         ← Lightweight logger fallback
│   │
│   ├── websocket_events.py          ← WebSocketEvent, WebSocketEventType models
│   ├── event_queue.py               ← EventQueue for WS message buffering
│   ├── credentials.py               ← Credential validation (API keys)
│   ├── main.py                      ← app instance, router registration, WS endpoint
│   └── run.py                       ← CLI entry: uvicorn server runner
│
├── mars-ui/
│   ├── app/
│   │   ├── layout.tsx               ← Root layout, provider wiring
│   │   ├── page.tsx                 ← Homepage — AI Weekly task (default screen)
│   │   ├── providers.tsx            ← Context providers (WebSocket, Theme)
│   │   ├── globals.css              ← Global stylesheet
│   │   ├── icon.tsx                 ← Favicon generator
│   │   ├── loading.tsx              ← Root loading skeleton
│   │   └── not-found.tsx            ← 404 page
│   │
│   ├── components/
│   │   ├── aiweekly/
│   │   │   ├── AIWeeklySetupPanel.tsx    ← Step 0: date range, topics, sources, model config
│   │   │   ├── AIWeeklyReviewPanel.tsx   ← Steps 1-3: edit/preview + refinement chat
│   │   │   └── AIWeeklyReportPanel.tsx   ← Step 4: final report + download
│   │   │
│   │   ├── tasks/
│   │   │   ├── AIWeeklyReportTask.tsx    ← Full wizard: stepper, recent tasks, stage flow
│   │   │   ├── TaskCard.tsx              ← Task card for task list display
│   │   │   ├── TaskList.tsx              ← Task gallery/list view
│   │   │   └── index.ts                 ← Barrel export
│   │   │
│   │   ├── core/
│   │   │   ├── Button.tsx
│   │   │   ├── IconButton.tsx
│   │   │   ├── Badge.tsx
│   │   │   ├── Tag.tsx
│   │   │   ├── Modal.tsx
│   │   │   ├── Tabs.tsx
│   │   │   ├── Toast.tsx
│   │   │   ├── ToastContainer.tsx
│   │   │   ├── InlineAlert.tsx
│   │   │   ├── Tooltip.tsx
│   │   │   ├── EmptyState.tsx
│   │   │   ├── ProgressIndicator.tsx
│   │   │   ├── Stepper.tsx               ← Wizard stepper used by AIWeeklyReportTask
│   │   │   ├── Skeleton.tsx
│   │   │   ├── Dropdown.tsx
│   │   │   ├── DataTable.tsx
│   │   │   ├── ResizableSplitPane.tsx    ← Split pane used in ReviewPanel
│   │   │   └── index.ts                 ← Barrel export
│   │   │
│   │   ├── deepresearch/
│   │   │   ├── RefinementChat.tsx        ← Chat UI reused by AI Weekly refinement
│   │   │   └── ExecutionProgress.tsx     ← Console progress bar during stage execution
│   │   │
│   │   ├── files/
│   │   │   ├── MarkdownRenderer.tsx      ← Renders markdown stage output
│   │   │   └── index.ts                 ← Barrel export
│   │   │
│   │   └── layout/
│   │       └── AppShell.tsx              ← App shell layout wrapper
│   │
│   ├── hooks/
│   │   ├── useAIWeeklyTask.ts            ← Core hook: task CRUD, stage execution, polling
│   │   ├── useModelConfig.ts             ← Fetch available LLM models
│   │   ├── useEventHandler.ts            ← WebSocket event routing
│   │   └── useSessionDetail.ts           ← Session detail loader
│   │
│   ├── contexts/
│   │   ├── WebSocketContext.tsx           ← Centralized WS connection, events, state
│   │   └── ThemeContext.tsx               ← Theme provider (dark/light)
│   │
│   ├── types/
│   │   ├── aiweekly.ts                   ← AI Weekly types, constants, stage config
│   │   ├── sessions.ts                   ← Session types
│   │   ├── websocket-events.ts           ← WS event type definitions
│   │   └── cost.ts                       ← Cost breakdown types
│   │
│   ├── lib/
│   │   ├── config.ts                     ← getApiUrl(), getWsUrl()
│   │   ├── fetchWithRetry.ts             ← Retry-enabled fetch wrapper
│   │   └── modes.ts                      ← Mode definitions (AI Weekly only)
│   │
│   ├── styles/
│   │   └── mars.css                      ← Component-level styles (.mars-markdown, layout)
│   │
│   ├── public/
│   │   └── mars-logo.svg                 ← Logo asset
│   │
│   ├── package.json
│   ├── package-lock.json
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── next-env.d.ts
│   └── server.js                         ← Dev server with browser auto-launch
│
├── pyproject.toml                        ← Python deps: cmbagent as library, FastAPI, etc.
├── alembic.ini                           ← DB migrations config (points to cmbagent DB)
├── docker-compose.yml                    ← Backend + frontend + DB services
├── Dockerfile                            ← Backend container image
├── Dockerfile.nextjs                     ← Frontend container image
└── README.md
```

---

## File Origin Map

| Standalone Path | Mars Source Path | Why Included |
|---|---|---|
| `backend/routers/aiweekly.py` | `backend/routers/aiweekly.py` | Primary API — 13 endpoints for the 4-stage pipeline |
| `backend/routers/tasks.py` | `backend/routers/tasks.py` | Task submission entry point (`POST /tasks/ai-weekly/execute`) |
| `backend/routers/sessions.py` | `backend/routers/sessions.py` | Session lifecycle (create/list/suspend/resume) |
| `backend/routers/health.py` | `backend/routers/health.py` | Container health probes |
| `backend/routers/models.py` | `backend/routers/models.py` | Model listing for frontend model selector |
| `backend/models/aiweekly_schemas.py` | `backend/models/aiweekly_schemas.py` | Request/response Pydantic models for AI Weekly |
| `backend/models/schemas.py` | `backend/models/schemas.py` | Shared TaskType, TaskRequest, TaskResponse |
| `backend/services/session_manager.py` | `backend/services/session_manager.py` | Session state persistence to DB |
| `backend/services/execution_service.py` | `backend/services/execution_service.py` | Async task execution with pause/resume |
| `backend/services/workflow_service.py` | `backend/services/workflow_service.py` | WorkflowRun record management |
| `backend/services/connection_manager.py` | `backend/services/connection_manager.py` | WebSocket connection pool |
| `backend/execution/task_executor.py` | `backend/execution/task_executor.py` | Core executor — invokes cmbagent, manages work dirs |
| `backend/execution/stream_capture.py` | `backend/execution/stream_capture.py` | Captures stdout/stderr for real-time console |
| `backend/execution/cost_collector.py` | `backend/execution/cost_collector.py` | LLM token cost aggregation |
| `backend/execution/dag_tracker.py` | `backend/execution/dag_tracker.py` | Execution state tracking |
| `backend/websocket/handlers.py` | `backend/websocket/handlers.py` | WS endpoint — session bind, task spawn, pause/resume |
| `backend/websocket/events.py` | `backend/websocket/events.py` | WS event send with retry |
| `backend/websocket_events.py` | `backend/websocket_events.py` | Event type definitions |
| `backend/event_queue.py` | `backend/event_queue.py` | Buffered event queue |
| `backend/callbacks/websocket_callbacks.py` | `backend/callbacks/websocket_callbacks.py` | WS emission callbacks |
| `backend/callbacks/database_callbacks.py` | `backend/callbacks/database_callbacks.py` | DB persistence callbacks |
| `backend/core/app.py` | `backend/core/app.py` | FastAPI factory |
| `backend/core/config.py` | `backend/core/config.py` | Settings (env vars, CORS, work dirs) |
| `backend/core/logging.py` | `backend/core/logging.py` | Structured logging setup |
| `backend/loggers/logger_factory.py` | `backend/loggers/logger_factory.py` | Logger factory |
| `backend/loggers/simple_logger.py` | `backend/loggers/simple_logger.py` | Fallback logger |
| `backend/credentials.py` | `backend/credentials.py` | API key validation |
| `backend/main.py` | `backend/main.py` | App instance + router registration |
| `backend/run.py` | `backend/run.py` | Uvicorn CLI runner |
| `mars-ui/components/aiweekly/*` | `mars-ui/components/aiweekly/*` | 3 AI Weekly panels |
| `mars-ui/components/tasks/AIWeeklyReportTask.tsx` | `mars-ui/components/tasks/AIWeeklyReportTask.tsx` | Full wizard orchestrator |
| `mars-ui/hooks/useAIWeeklyTask.ts` | `mars-ui/hooks/useAIWeeklyTask.ts` | Core state hook (task CRUD, stage exec, polling) |
| `mars-ui/types/aiweekly.ts` | `mars-ui/types/aiweekly.ts` | Type definitions and constants |
| `mars-ui/components/deepresearch/RefinementChat.tsx` | `mars-ui/components/deepresearch/RefinementChat.tsx` | Reused for AI Weekly refinement |
| `mars-ui/components/deepresearch/ExecutionProgress.tsx` | `mars-ui/components/deepresearch/ExecutionProgress.tsx` | Console progress during execution |
| `mars-ui/components/files/MarkdownRenderer.tsx` | `mars-ui/components/files/MarkdownRenderer.tsx` | Stage output rendering |
| `mars-ui/components/core/*` | `mars-ui/components/core/*` | Design system (Button, Stepper, ResizableSplitPane, etc.) |
| `mars-ui/contexts/WebSocketContext.tsx` | `mars-ui/contexts/WebSocketContext.tsx` | Centralized WS state |
| `mars-ui/contexts/ThemeContext.tsx` | `mars-ui/contexts/ThemeContext.tsx` | Theme provider |
| `mars-ui/lib/config.ts` | `mars-ui/lib/config.ts` | API/WS URL config |
| `mars-ui/lib/fetchWithRetry.ts` | `mars-ui/lib/fetchWithRetry.ts` | Retry-enabled fetch |
| `mars-ui/lib/modes.ts` | `mars-ui/lib/modes.ts` | Mode definitions |
| `mars-ui/styles/mars.css` | `mars-ui/styles/mars.css` | Component styles |

---

## What Is NOT Included (and why)

| Mars Path | Reason for Exclusion |
|---|---|
| `backend/routers/rfp.py` | RFP feature — not in AI Weekly chain |
| `backend/routers/deepresearch.py` | DeepResearch feature — not in chain |
| `backend/routers/copilot.py` | Copilot mode — not in chain |
| `backend/routers/newspulse.py` | NewsPulse feature — not in chain |
| `backend/routers/pda.py` | PDA feature — not in chain |
| `backend/routers/releasenotes.py` | Release Notes feature — not in chain |
| `backend/routers/files.py` | File browser — not used by AI Weekly |
| `backend/routers/arxiv.py` | Arxiv downloads — not used by AI Weekly |
| `backend/routers/enhance.py` | Enhancement router — not in chain |
| `backend/routers/branching.py` | Branch management — not in chain |
| `backend/routers/runs.py` | Run management — not in chain |
| `backend/routers/nodes.py` | Node management — not in chain |
| `backend/routers/phases.py` | Generic phases — AI Weekly uses its own router |
| `backend/models/rfp_schemas.py` | RFP schemas |
| `backend/models/deepresearch_schemas.py` | DeepResearch schemas |
| `backend/models/newspulse_schemas.py` | NewsPulse schemas |
| `backend/models/pda_schemas.py` | PDA schemas |
| `backend/models/copilot_schemas.py` | Copilot schemas |
| `backend/models/releasenotes_schemas.py` | Release Notes schemas |
| `backend/models/phase_schemas.py` | Generic phase schemas |
| `backend/services/pda_service.py` | PDA service |
| `backend/services/pdf_extractor.py` | PDF extraction — not in chain |
| `backend/execution/isolated_executor.py` | Process isolation — AI Weekly uses tracked mode |
| `backend/websocket_manager.py` | Deprecated — replaced by connection_manager.py |
| `cmbagent/` (directory) | Used as installed library, not embedded source |
| `mars-ui/components/rfp/` | RFP UI |
| `mars-ui/components/dag/` | DAG visualization |
| `mars-ui/components/branching/` | Branch UI |
| `mars-ui/components/console/` | Console panel — not used by AI Weekly directly |
| `mars-ui/components/newspulse/` | NewsPulse UI |
| `mars-ui/components/workflow/` | Workflow dashboard |
| `mars-ui/components/tables/` | Data tables |
| `mars-ui/components/metrics/` | Cost analytics dashboard |
| `mars-ui/components/modes/` | Mode gallery (multi-task selector) |
| `mars-ui/hooks/useRfpTask.ts` | RFP hook |
| `mars-ui/hooks/useDeepresearchTask.ts` | DeepResearch hook |
| `mars-ui/hooks/useNewsPulseTask.ts` | NewsPulse hook |
| `mars-ui/hooks/usePdaTask.ts` | PDA hook |
| `mars-ui/hooks/useReleaseNotesTask.ts` | Release Notes hook |
| `mars-ui/hooks/useCostData.ts` | Cost dashboard hook |
| `mars-ui/hooks/useWebSocket.ts` | Legacy WS hook (WebSocketContext replaces it) |
| `mars-ui/hooks/useResilientWebSocket.ts` | Not used by AI Weekly flow |
| `mars-ui/hooks/useCredentials.ts` | Credential modal — not core to AI Weekly |
| `mars-ui/types/deepresearch.ts` | DeepResearch types |
| `mars-ui/types/rfp.ts` | RFP types |
| `mars-ui/types/pda.ts` | PDA types |
| `mars-ui/types/newspulse.ts` | NewsPulse types |
| `mars-ui/types/releasenotes.ts` | Release Notes types |
| `mars-ui/types/branching.ts` | Branching types |
| `mars-ui/types/tables.ts` | Table types |
| `mars-ui/types/dag.ts` | DAG types |
| `mars-ui/types/retry.ts` | Retry types |
| `mars-ui/types/console.ts` | Console types |
| `mars-ui/types/mars-ui.ts` | Full app types |
| `mars-ui/lib/features.ts` | Feature flags for multi-feature app |
| `mars-ui/lib/telemetry.ts` | Telemetry — not in chain |
| `mars-ui/lib/pda-api.ts` | PDA API helpers |
| `tests/` | Test suite stays in Mars |
| `evals/` | Evaluation suite stays in Mars |
| `examples/` | Example scripts |
| `docs/` | Mars documentation |

---

## cmbagent — Used as Library

In Mars, `cmbagent/` is an embedded package. In MARS-AIWeekly, it is installed as a **Python library dependency** via `pyproject.toml`:

```toml
dependencies = [
    "cmbagent",  # installed from PyPI or git
    ...
]
```

The backend imports at runtime:
- `cmbagent.phases.aiweekly.collection_phase:AIWeeklyCollectionPhase`
- `cmbagent.phases.aiweekly.curation_phase:AIWeeklyCurationPhase`
- `cmbagent.phases.aiweekly.generation_phase:AIWeeklyGenerationPhase`
- `cmbagent.phases.aiweekly.review_phase:AIWeeklyReviewPhase`
- `cmbagent.database.models` (TaskStage, WorkflowRun, CostRecord)
- `cmbagent.database.repository` (CostRepository)
- `cmbagent.database.base` (get_db_session)
- `cmbagent.external_tools.news_tools` (data collection functions)

No cmbagent source files are copied into this repo.
