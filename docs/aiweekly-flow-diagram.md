# AI Weekly Report Generator — Complete Flow Diagram

> Standalone AI Weekly Report Generator — all flow diagrams for the 4-stage pipeline.

---

## Master Flow Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              USER (Browser)                                     │
│                                                                                 │
│  1. Open AI Weekly app → default view is the task setup panel                  │
│  2. Pick date range, topics, sources, style → Click "Collect Data"             │
│  3. Review & edit each stage → Click "Next Stage"                              │
│  4. Download final report (MD / PDF) + cost summary                            │
│  5. Right panel: "Recent Tasks" dropdown to resume, "Start New Task" button    │
└───────┬─────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        FRONTEND  (React / Next.js — Single-Page App)            │
│                                                                                 │
│  app/page.tsx          ── SPA shell: main content + right collapsible panel     │
│  AIWeeklyReportTask.tsx── 5-step wizard (Step 0 = Setup, Steps 1–4 = Stages)   │
│  useAIWeeklyTask.ts    ── state management, REST calls, polling                │
│  AIWeeklySetupPanel    ── date range, topics, sources, style, model config     │
│  AIWeeklyReviewPanel   ── editor + refinement chat (Steps 1–3)                 │
│  AIWeeklyReportPanel   ── final report preview + download (Step 4)             │
│                                                                                 │
│  Navigation: All via React state — no page reloads, only component swaps       │
└───────┬─────────────────────────────────────────────────────────────────────────┘
        │ REST API (HTTP)
        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        BACKEND  (FastAPI / Python)                               │
│                                                                                 │
│  routers/aiweekly.py   ── 13 REST endpoints + execution engine                 │
│    _run_aiweekly_stage():                                                       │
│      1. _load_phase_class(stage_num) ── importlib dynamic load                 │
│      2. PhaseClass(config=...)       ── instantiate phase                      │
│      3. PhaseContext(task, work_dir, shared_state)                              │
│      4. await phase.execute(ctx)     ── tool calls / LLM pipeline              │
│      5. Extract output, track cost (CostRecord), update DB                     │
│      6. On all-complete → _generate_cost_summary() → cost_summary.md           │
│                                                                                 │
│  _ConsoleCapture ── thread-safe stdout → REST console buffer                   │
└───────┬──────────────────────────────┬──────────────────────────────────────────┘
        │                              │
        ▼                              ▼
┌────────────────────────┐  ┌─────────────────────────────────────────────────────┐
│   DATABASE  (SQLite)   │  │   EXTERNAL APIs / LLM                               │
│                        │  │                                                     │
│  Session               │  │   Stage 1: RSS feeds, NewsAPI, GNews, web search    │
│  WorkflowRun           │  │            (no LLM — direct Python tool calls)      │
│  TaskStage (×4)        │  │                                                     │
│  CostRecord            │  │   Stages 2–3: 3 LLM calls per stage                │
│                        │  │     (Primary → Specialist → Reviewer)               │
│                        │  │   Stage 4: 2 LLM calls (Primary → Reviewer)        │
│                        │  │     = 8 LLM calls total + refinement (on-demand)    │
└────────────────────────┘  └─────────────────────────────────────────────────────┘
```

---

## 1. Task Creation Flow

```
USER                          FRONTEND                         BACKEND                          DATABASE
 │                               │                               │                                │
 │  Configure date range,        │                               │                                │
 │  topics, sources, style       │                               │                                │
 │  Click "Collect Data"         │                               │                                │
 ├──────────────────────────────►│                               │                                │
 │                               │  POST /api/aiweekly/create    │                                │
 │                               │  { date_from, date_to,        │                                │
 │                               │    topics, sources, style }   │                                │
 │                               ├──────────────────────────────►│                                │
 │                               │                               │  uuid4() → task_id             │
 │                               │                               │  SessionManager.create_session()│
 │                               │                               ├───────────────────────────────►│
 │                               │                               │  INSERT Session + WorkflowRun  │
 │                               │                               │  ×4 INSERT TaskStage           │
 │                               │                               ├───────────────────────────────►│
 │                               │                               │                                │
 │                               │  ◄── { task_id, work_dir,     │                                │
 │                               │       stages: [4 pending] }   │                                │
 │                               │◄──────────────────────────────┤                                │
 │                               │                               │                                │
 │                               │  ─── TRIGGER STAGE 1 ──────► │                                │
```

---

## 2. Stage Execution Flow (Stages 1–4)

```
FRONTEND (useAIWeeklyTask)        BACKEND (routers/aiweekly.py)      PHASE ENGINE              DATABASE
 │                                   │                                │                          │
 │  POST /{id}/stages/{N}/execute    │                                │                          │
 ├──────────────────────────────────►│                                │                          │
 │                                   │  UPDATE TaskStage → "running"  │                          │
 │                                   │  asyncio.create_task(          │                          │
 │                                   │    _run_aiweekly_stage(...))   │                          │
 │  ◄── { status: "started" }        │  ┌───────────────────────────►│                          │
 │◄──────────────────────────────────┤  │                             │                          │
 │                                   │  │  1. _build_shared_state()   │                          │
 │  Start console poll (2s)          │  │  2. Install console capture │                          │
 │  GET .../console?since=0          │  │  3. _load_phase_class(N)    │                          │
 ├──────────────────────────────────►│  │  4. await phase.execute(ctx)│                          │
 │                                   │  │     [PHASE PIPELINE]        │                          │
 │  ◄── console lines (polling)      │  │                             │                          │
 │◄──────────────────────────────────┤  │  5. Extract cost            │                          │
 │                                   │  │  6. INSERT CostRecord       │                          │
 │                                   │  │  7. UPDATE TaskStage →      │                          │
 │                                   │  │     "completed" + output    │                          │
 │                                   │  │  8. If ALL done → complete  │                          │
 │  Poll detects stage complete      │  │     WorkflowRun + cost file │                          │
 │  GET /{id}/stages/{N}/content     │  └─────────────────────────────┘                          │
 │  Display in editor panel          │                                │                          │
```

---

## 3. Stage 1 — Data Collection Pipeline (No LLM)

```
AIWeeklyCollectionPhase.execute(context)
 │
 │  TOOL CALLS (direct Python, no LLM):
 │    1. RSS feeds (30+ sources: OpenAI, Google, Meta, etc.)
 │    2. curated_ai_sources_search(limit=60)
 │    3. newsapi_search()        (if NEWSAPI_KEY set)
 │    4. gnews_search()          (if GNEWS_API_KEY set)
 │    5. multi_engine_web_search (DDG→Bing→Yahoo→Brave)
 │    6. Per-company web searches for 19 priority companies
 │
 │  Date filtering + Deduplication by (url, title[:80])
 │
 │  Output: raw_collection (markdown)
 │  Cost: $0.0000 (no LLM calls)
 │  Save to: input_files/collection.json + collection.md
```

---

## 4. Stages 2–4 — LLM Pipeline

```
AIWeeklyPhaseBase.execute(context)
 │
 │  A. BUILD PROMPTS (system + user from shared_state + style_rule)
 │  B. TOKEN CAPACITY CHECK (chunk_prompt_if_needed)
 │
 ▼
 PASS 1: PRIMARY AGENT → draft content
 PASS 2: SPECIALIST AGENT (Stages 2–3 only) → improved content
 PASS 3: REVIEWER AGENT (11-point checklist) → polished content
 │
 ▼
 Save to file + Return PhaseResult with output + cost
```

---

## 5. Shared State Accumulation

```
Stage 1 → raw_collection
Stage 2 reads {raw_collection, task_config} → curated_items
Stage 3 reads {raw_collection, curated_items, task_config} → draft_report
Stage 4 reads {all prior + task_config} → final_report
ALL done → WorkflowRun "completed" + cost_summary.md
```

---

## 6. Database Entity Relationship

```
Session 1:N → WorkflowRun 1:N → TaskStage (×4)
                          1:N → CostRecord
```

---

## 7. Task Resumption Flow

```
USER clicks "Recent Tasks" in right panel
  → GET /api/aiweekly/recent → dropdown list
  → Click task → component swap (no reload)
  → GET /api/aiweekly/{id} → wizard jumps to correct step
```

---

## 8. API Endpoint Quick Reference

| # | Method | Path | Description |
|---|--------|------|-------------|
| 1 | POST | `/api/aiweekly/create` | Create task + 4 stages |
| 2 | GET | `/api/aiweekly/recent` | List incomplete tasks |
| 3 | GET | `/api/aiweekly/{id}` | Full task state |
| 4 | POST | `/api/aiweekly/{id}/stages/{N}/execute` | Launch stage |
| 5 | GET | `/api/aiweekly/{id}/stages/{N}/content` | Stage output |
| 6 | PUT | `/api/aiweekly/{id}/stages/{N}/content` | Save edits |
| 7 | POST | `/api/aiweekly/{id}/stages/{N}/refine` | LLM refinement |
| 8 | GET | `/api/aiweekly/{id}/stages/{N}/console` | Console polling |
| 9 | POST | `/api/aiweekly/{id}/reset-from/{N}` | Reset stages N+ |
| 10 | POST | `/api/aiweekly/{id}/stop` | Cancel running stage |
| 11 | GET | `/api/aiweekly/{id}/download/{file}` | Download artifact |
| 12 | GET | `/api/aiweekly/{id}/download-pdf/{file}` | Download as PDF |
| 13 | DELETE | `/api/aiweekly/{id}` | Delete task + files |

---

## 9. Output Files

```
{work_dir}/input_files/
├── task_config.json       # User configuration
├── collection.json        # Stage 1: structured JSON
├── collection.md          # Stage 1: markdown summary
├── curated.md             # Stage 2: curated items
├── report_draft.md        # Stage 3: draft report
├── report_final.md        # Stage 4: final report
└── cost_summary.md        # Auto-generated cost breakdown
```
