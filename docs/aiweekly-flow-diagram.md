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
│  5. Right panel: collapsible sessions panel with search/filter + task cards    │
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
│    _run_aiweekly_one_shot_stage():                                              │
│      1. helpers.build_*_kwargs() ── build prompt + config                      │
│      2. _run_one_shot_sync(**kwargs) ── cmbagent.one_shot(agent='researcher')  │
│      3. Token-aware chunking + LLM merge for multi-chunk stages                │
│      4. helpers.extract_stage_result() ── extract markdown from chat history   │
│      5. Track cost, save file, update task.json                                │
│      6. On all-complete → _generate_cost_summary() → cost_summary.md           │
│                                                                                 │
│  _ConsoleCapture ── thread-safe stdout → REST console buffer                   │
└───────┬──────────────────────────────┬──────────────────────────────────────────┘
        │                              │
        ▼                              ▼
┌────────────────────────┐  ┌─────────────────────────────────────────────────────┐
│  FILE SYSTEM (JSON)    │  │   EXTERNAL APIs / LLM                               │
│                        │  │                                                     │
│  ~/Desktop/cmbdir/     │  │   Stage 1: RSS feeds, NewsAPI, GNews, web search    │
│  aiweekly/{id}/        │  │            (no LLM — direct Python tool calls)      │
│    task.json           │  │                                                     │
│    input_files/        │  │   Stage 2: one_shot(researcher) per chunk + merge   │
│                        │  │   Stage 3: analysis pass + generation + merge       │
│                        │  │   Stage 4: critic pass + editor pass                │
│                        │  │     All via cmbagent.one_shot(agent='researcher')   │
└────────────────────────┘  └─────────────────────────────────────────────────────┘
```

---

## 1. Task Creation Flow

```
USER                          FRONTEND                         BACKEND                          FILE SYSTEM
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
 │                               │                               │  file_task_store.create_task()  │
 │                               │                               ├───────────────────────────────►│
 │                               │                               │  Write task.json               │
 │                               │                               │  (4 stages, status=pending)    │
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
FRONTEND (useAIWeeklyTask)        BACKEND (routers/aiweekly.py)      PHASE ENGINE              FILE SYSTEM
 │                                   │                                │                          │
 │  POST /{id}/stages/{N}/execute    │                                │                          │
 ├──────────────────────────────────►│                                │                          │
 │                                   │  UPDATE task.json → "running"  │                          │
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
 │                                   │  │  6. Cost saved in task.json │                          │
 │                                   │  │  7. UPDATE task.json →       │                          │
 │                                   │  │     "completed" + output    │                          │
 │                                   │  │  8. If ALL done → complete  │                          │
 │  Poll detects stage complete      │  │     task + cost_summary.md  │                          │
 │  GET /{id}/stages/{N}/content     │  └─────────────────────────────┘                          │
 │  Display in editor panel          │                                │                          │
```

---

## 3. Stage 1 — Data Collection Pipeline (No LLM)

```
helpers.run_data_collection()
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

## 4. Stages 2–4 — LLM Pipeline (one_shot + multi-pass)

```
_run_aiweekly_one_shot_stage()
 │
 │  Uses cmbagent.one_shot(agent='researcher') for all LLM stages.
 │  Agent enforcement: CMBAgent.solve is monkey-patched to prevent the
 │  control agent from switching to 'engineer'.
 │
 ▼
 STAGE 2 (Content Curation):
   A. _compact_collection_for_prompt() — trim raw collection
   B. _get_chunk_budget(model) — token-aware chunk size (default ~60K chars)
   C. split_collection_items() → N chunks
   D. one_shot per chunk → partial curated outputs
   E. If multi-chunk: LLM merge pass (curation_merge_prompt) → unified output

 STAGE 3 (Report Generation):
   A. Analysis pass: one_shot on curated_items → structural analysis
   B. Generation pass: one_shot per chunk (analysis + curated) → partial reports
   C. If multi-chunk: LLM merge pass (merge_partials_prompt) → unified draft

 STAGE 4 (Quality Review):
   A. Critic pass: one_shot → editorial audit (identifies corrections)
   B. Editor pass: one_shot (draft + critique) → polished final report
   C. Programmatic verification: URL check, date check, placeholder/superlative detection
 │
 ▼
 helpers.extract_stage_result() → markdown from chat history
 helpers.save_stage_file() → save to work_dir
```

---

## 5. Shared State Accumulation

```
Stage 1 → raw_collection
Stage 2 reads {raw_collection, task_config} → curated_items
Stage 3 reads {raw_collection, curated_items, task_config} → draft_report
Stage 4 reads {all prior + task_config} → final_report
ALL done → task status "completed" + cost_summary.md
```

---

## 6. Data Storage

```
task.json contains: task metadata + 4 stages (with output_data and cost)
Cost data embedded in each stage's output_data["cost"]
```

---

## 7. Task Resumption Flow

```
USER sees right collapsible sessions panel (always visible)
  → Sessions fetched via relative URL: fetch('/api/aiweekly/recent')
    (goes through Next.js proxy to backend)
  → Panel shows task cards with:
    - Status icon (green check for completed, spinner for running)
    - Stage info ("Completed" for finished tasks, "Stage N: Name" otherwise)
    - Actual date/time started (e.g. "Apr 30, 10:52 AM")
    - Progress bar with percentage
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
