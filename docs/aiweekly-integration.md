# AI Weekly Report Generator — End-to-End Integration Documentation

> Standalone AI Weekly Report Generator — complete integration docs.

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture Diagram](#2-architecture-diagram)
3. [Directory Structure](#3-directory-structure)
4. [The 4-Stage Pipeline](#4-the-4-stage-pipeline)
5. [Phase-Based Execution Engine](#5-phase-based-execution-engine)
6. [Shared State & Context Flow](#6-shared-state--context-flow)
7. [Backend API Reference](#7-backend-api-reference)
8. [Database Layer](#8-database-layer)
9. [Phase Classes & Prompts](#9-phase-classes--prompts)
10. [Frontend UI](#10-frontend-ui)
11. [Console Output & Real-Time Streaming](#11-console-output--real-time-streaming)
12. [Task Resumption](#12-task-resumption)
13. [Token Capacity Management](#13-token-capacity-management)
14. [Cost Tracking](#14-cost-tracking)
15. [End-to-End User Flow](#15-end-to-end-user-flow)
16. [Error Handling](#16-error-handling)
17. [Workflow Run Auto-Completion](#17-workflow-run-auto-completion)

---

## 1. Overview

The AI Weekly Report Generator is a **standalone, 4-stage, human-in-the-loop AI pipeline**. It transforms a date range + topic/source selection into a publication-ready AI weekly report through interactive stages:

1. **Data Collection** → 2. **Content Curation** → 3. **Report Generation** → 4. **Quality Review**

Stage 1 uses **direct Python tool calls** (no LLM). Stages 2–4 use a **3-agent LLM pipeline** (Primary → Specialist → Reviewer) via `AIWeeklyPhaseBase`.

**Key technologies:**
- **Backend:** Python, FastAPI, SQLAlchemy, asyncio
- **Phase System:** `AIWeeklyPhaseBase` → 4 phase subclasses
- **Data Collection:** `news_tools.py` — direct page scraping, RSS feeds, NewsAPI, GNews, DDG/Bing/Yahoo/Brave; 26 curated sources
- **Frontend:** React, TypeScript, Next.js (single-page app)
- **Real-time:** REST polling (console output)
- **Default LLM:** Dynamic from `WorkflowConfig.default_llm_model`; per-stage override via UI
- **Mode:** `"aiweekly"`

---

## 2. Architecture Diagram

```
┌───────────────────────────────────────────────────────────────────────┐
│                     FRONTEND (React/Next.js SPA)                      │
│                                                                       │
│  app/page.tsx ── SPA shell with right collapsible panel               │
│    └── AIWeeklyReportTask.tsx (5-step wizard)                         │
│         ├── AIWeeklySetupPanel.tsx       (Step 0)                     │
│         ├── AIWeeklyReviewPanel.tsx      (Steps 1–3)                  │
│         └── AIWeeklyReportPanel.tsx      (Step 4)                     │
│                                                                       │
│  useAIWeeklyTask.ts ── state management, API calls, polling           │
│                                                                       │
│  All navigation via React state — no page reloads                     │
└───────────┬───────────────────────────────────────────────────────────┘
            │ REST API
            ▼
┌───────────────────────────────────────────────────────────────────────┐
│                         BACKEND (FastAPI)                              │
│                                                                       │
│  routers/aiweekly.py ── REST endpoints + phase execution engine       │
│    _run_aiweekly_stage():                                            │
│      1. _load_phase_class(stage_num) ── importlib dynamic load        │
│      2. PhaseClass(config=...)                                         │
│      3. PhaseContext(task, work_dir, shared_state)                     │
│      4. await phase.execute(ctx)                                       │
│      5. Extract output, track cost, update DB                          │
│      6. On all-complete → _generate_cost_summary() → cost_summary.md │
│                                                                       │
│  _ConsoleCapture ── thread-safe stdout/stderr → REST console buffer   │
└───────────┬──────────────────────────────┬────────────────────────────┘
            │                              │
            ▼                              ▼
┌────────────────────────┐    ┌─────────────────────────────────────────┐
│   SQLite (SQLAlchemy)  │    │       cmbagent/phases/aiweekly/           │
│                        │    │                                         │
│  WorkflowRun (task)    │    │  collection_phase.py  (Stage 1, no LLM)│
│  TaskStage   (×4)      │    │  curation_phase.py    (Stage 2, LLM)   │
│  CostRecord            │    │  generation_phase.py  (Stage 3, LLM)   │
│  output_data.shared    │    │  review_phase.py      (Stage 4, LLM)   │
└────────────────────────┘    │  base.py              (shared base)     │
                              └─────────────────────────────────────────┘
```

---

## 3. Directory Structure

```
backend/
  models/aiweekly_schemas.py   # Pydantic request/response models
  routers/aiweekly.py          # 13 REST endpoints
  services/                    # session_manager, connection_manager, etc.
  core/                        # app factory, config, logging

mars-ui/
  app/
    page.tsx                   # SPA shell — main content + right panel
    layout.tsx                 # Root layout with AppShell
    providers.tsx              # ThemeProvider, WebSocketProvider, ToastProvider
  types/aiweekly.ts            # TypeScript interfaces + wizard constants
  hooks/useAIWeeklyTask.ts     # React hook — state, API calls, polling
  components/
    aiweekly/
      AIWeeklySetupPanel.tsx   # Date range, topics, sources, style
      AIWeeklyReviewPanel.tsx  # Edit/preview + refinement chat
      AIWeeklyReportPanel.tsx  # Final report + download artifacts
    tasks/
      AIWeeklyReportTask.tsx   # Main orchestrator (5-step wizard + stepper)
    layout/
      AppShell.tsx             # App shell (TopBar + main content)
      TopBar.tsx               # Centered "AI WEEKLY" header + theme toggle
    core/                      # Button, Stepper, Toast, etc.

cmbagent/phases/aiweekly/
  __init__.py
  base.py                      # AIWeeklyPhaseBase, AIWeeklyPhaseConfig
  collection_phase.py          # Stage 1: Direct tool calls (no LLM)
  curation_phase.py            # Stage 2: LLM content curation
  generation_phase.py          # Stage 3: LLM report writing
  review_phase.py              # Stage 4: LLM quality review

cmbagent/external_tools/
  news_tools.py                # RSS feeds, NewsAPI, GNews, web search
```

---

## 4. The 4-Stage Pipeline

| # | Stage | Class | Type | Specialist | Output Key |
|---|---|---|---|---|---|
| 1 | Data Collection | `AIWeeklyCollectionPhase` | Direct Python (no LLM) | N/A | `raw_collection` |
| 2 | Content Curation | `AIWeeklyCurationPhase` | LLM (3-agent) | Fact-checker | `curated_items` |
| 3 | Report Generation | `AIWeeklyGenerationPhase` | LLM (3-agent) | Business analyst | `draft_report` |
| 4 | Quality Review | `AIWeeklyReviewPhase` | LLM (generate+review) | None | `final_report` |

### Stage 1: Data Collection (Non-LLM)

Calls each tool sequentially, deduplicates by `(url, title[:80])`:

1. `announcements_noauth(limit=300)` — broad official news page sweep
2. `scrape_official_news_pages(company=X)` × 19 companies
3. `curated_ai_sources_search(limit=40)` — 26 curated AI news sources
4. `newsapi_search()` — NewsAPI (if key available)
5. `gnews_search()` — Google News (if key available)
6. `multi_engine_web_search()` — DDG SDK → Bing → Yahoo → Brave fallback

### Stages 2–4: LLM Pipeline

Each stage follows the `AIWeeklyPhaseBase.execute()` pattern:

```
1. Build user prompt (from shared state)
2. chunk_prompt_if_needed(user_prompt, system_prompt, model)
3. Generate primary output via safe_completion()
4. [If specialist] Run specialist review → merge improvements
5. Run reviewer pass → final polished output
6. Save to shared_state[output_key] and to file
```

---

## 5. Phase-Based Execution Engine

### `_run_aiweekly_stage()` in `backend/routers/aiweekly.py`

```python
async def _run_aiweekly_stage(task_id, stage_num, task_text, work_dir, task_config, model, n_reviews):
    # 1. Capture stdout/stderr for console streaming
    # 2. Load phase class via importlib
    # 3. Build shared state from prior completed stages
    # 4. Create phase context
    # 5. Execute with 900s timeout
    # 6. Update DB with output + status
```

### Phase Class Loading

```python
_PHASE_CLASSES = {
    1: "cmbagent.phases.aiweekly.collection_phase:AIWeeklyCollectionPhase",
    2: "cmbagent.phases.aiweekly.curation_phase:AIWeeklyCurationPhase",
    3: "cmbagent.phases.aiweekly.generation_phase:AIWeeklyGenerationPhase",
    4: "cmbagent.phases.aiweekly.review_phase:AIWeeklyReviewPhase",
}
```

---

## 6. Shared State & Context Flow

```
Stage 1 output:  shared_state["raw_collection"]
Stage 2 input:   {task_config, raw_collection}     → output: curated_items
Stage 3 input:   {task_config, raw_collection, curated_items} → output: draft_report
Stage 4 input:   {task_config, raw_collection, curated_items, draft_report} → output: final_report
```

---

## 7. Backend API Reference

All endpoints prefixed with `/api/aiweekly`.

| Method | Path | Description |
|---|---|---|
| POST | `/create` | Create task + 4 stage DB rows |
| POST | `/{id}/stages/{N}/execute` | Launch async stage execution |
| GET | `/{id}` | Full task state (all stages) |
| GET | `/{id}/stages/{N}/content` | Stage output markdown |
| PUT | `/{id}/stages/{N}/content` | Save user edits |
| POST | `/{id}/stages/{N}/refine` | LLM refinement of content |
| GET | `/{id}/stages/{N}/console` | Console output lines (polling) |
| POST | `/{id}/reset-from/{N}` | Reset stages N+ to pending |
| GET | `/recent` | List incomplete tasks for resume |
| POST | `/{id}/stop` | Cancel running stage |
| DELETE | `/{id}` | Delete task + work_dir |
| GET | `/{id}/download/{filename}` | Download artifact file |
| GET | `/{id}/download-pdf/{filename}` | Convert MD to PDF and download |

---

## 8. Database Layer

### WorkflowRun

| Column | Value |
|---|---|
| `mode` | `"aiweekly"` |
| `agent` | `"phase_orchestrator"` |
| `status` | `"executing"` → `"completed"` / `"failed"` |
| `meta.work_dir` | `~/Desktop/cmbdir/aiweekly/<id[:8]>` |
| `meta.task_config` | `{date_from, date_to, topics, sources, style}` |

### TaskStage (4 per task)

| Column | Description |
|---|---|
| `parent_run_id` | → WorkflowRun.id |
| `stage_number` | 1–4 |
| `status` | `pending` → `running` → `completed` / `failed` |
| `output_data` | `{"shared": {"<key>": "markdown content"}}` |

---

## 9. Phase Classes & Prompts

### Stage 2: AIWeeklyCurationPhase

**System prompt:** Senior AI news editor — curate, validate, deduplicate.
**Specialist:** Fact-checking specialist — date accuracy, credibility, diversity.

### Stage 3: AIWeeklyGenerationPhase

**System prompt:** Senior analyst writing enterprise-grade weekly report.
**Specialist:** Business analyst — completeness, balance, actionability.
**Report structure:** Executive Summary → Key Highlights → Trends → Quick Reference Table.

### Stage 4: AIWeeklyReviewPhase

**System prompt:** Quality editor — final polish for publication readiness.
**No specialist.** Uses generate + review only.

After the LLM pass, runs **programmatic verification** — 5 deterministic checks:
1. URL verification — marks inaccessible URLs
2. Date verification — flags out-of-range dates
3. Placeholder detection
4. Superlative detection
5. Synthesis text removal

---

## 10. Frontend UI

### SPA Architecture

The app is a **single-page application** — all navigation happens via React state changes, never full page reloads.

```
AppShell (layout)
  ├── TopBar — centered "AI WEEKLY" title + theme toggle
  └── Main content area
       └── page.tsx (SPA shell)
            ├── Main panel: AIWeeklyReportTask.tsx (5-step wizard)
            │    ├── Header + Stepper (5 steps)
            │    ├── Step 0: AIWeeklySetupPanel.tsx
            │    ├── Steps 1–3: AIWeeklyReviewPanel.tsx
            │    └── Step 4: AIWeeklyReportPanel.tsx
            │
            └── Right collapsible panel
                 ├── Recent Tasks (dropdown — fetches from /api/aiweekly/recent)
                 └── Start New Task (resets to setup view)
```

- **Default view:** Task setup panel (Step 0) loads immediately on app open
- **Task switching:** Clicking a recent task swaps the main content component via React state (`resumeTaskId`)
- **No router navigation:** The `key` prop on `AIWeeklyReportTask` forces React to remount with fresh state

### Hook: `useAIWeeklyTask.ts`

| Method | Purpose |
|---|---|
| `createTask()` | POST /create |
| `executeStage()` | POST /{id}/stages/{N}/execute |
| `fetchStageContent()` | GET /{id}/stages/{N}/content |
| `saveStageContent()` | PUT /{id}/stages/{N}/content |
| `refineContent()` | POST /{id}/stages/{N}/refine |
| `loadTaskState()` | GET /{id} |
| `resumeTask()` | GET /{id} + jump to latest step |
| `resetFromStage()` | POST /{id}/reset-from/{N} |
| `deleteTask()` | DELETE /{id} |

---

## 11. Console Output & Real-Time Streaming

During execution, `_ConsoleCapture` intercepts all `print()` / `sys.stdout` output from the phase class and buffers it in memory. Frontend polls `GET /console?since=N` every 2 seconds and appends new lines to `consoleOutput[]`.

Stage status is tracked via `GET /{id}` polling every 5 seconds.

---

## 12. Task Resumption

The right collapsible panel contains a **"Recent Tasks"** dropdown. When clicked, it fetches `GET /api/aiweekly/recent` and shows a list of incomplete tasks with their current stage and progress. Clicking a task sets `resumeTaskId` in React state, which triggers `AIWeeklyReportTask` to remount and load the task at the correct wizard step.

`resumeTask(id)` in `useAIWeeklyTask.ts` loads task state via `GET /{id}`, finds the latest completed stage, and sets `currentStep` to the next wizard step.

---

## 13. Token Capacity Management

Every LLM call in Stages 2–4 uses `chunk_prompt_if_needed()`:

1. Count tokens in system prompt + user prompt
2. If total > `model_context × 0.75`, split user prompt into chunks
3. Process each chunk separately, accumulate results
4. Dynamic `max_completion_tokens` = `context_limit - prompt_tokens - safety_buffer`

---

## 14. Cost Tracking

Each LLM call's token usage is tracked per-stage and recorded to the database via `CostRepository`.

- Stages 2–4 return token counts in `output_data["cost"]`
- Cost formula: `cost_usd = (prompt_tokens × 0.002 + completion_tokens × 0.008) / 1000`
- When all 4 stages complete, `cost_summary.md` is auto-generated

---

## 15. End-to-End User Flow

1. User opens app → sees setup panel (default view)
2. **Setup:** Configures date range, picks topics/sources, selects style
3. **Create + Execute Stage 1:** `POST /create` → `POST /stages/1/execute`
4. **Data Collection runs:** Console shows progress
5. **Stage 1 completes:** Wizard advances, shows collected data
6. User reviews, optionally edits, clicks **Next**
7. **Stages 2–4 auto-execute** and user reviews each
8. **Final report displayed** with download links + cost summary

---

## 16. Error Handling

| Error | Handling |
|---|---|
| Tool call failure (Stage 1) | Logged + skipped |
| Stage timeout (900s) | Stage marked `failed` |
| LLM API error | Stage marked `failed` with error |
| Token overflow | Auto-split via `chunk_prompt_if_needed` |
| Missing API keys | Stage 1 skips those steps silently |

---

## 17. Workflow Run Auto-Completion

When the last stage completes, `_run_aiweekly_stage()` automatically checks all `TaskStage` rows. If all 4 are `"completed"`, the parent `WorkflowRun` transitions to `"completed"` with a timestamp. Completed tasks no longer appear in `GET /api/aiweekly/recent`.
