# AI Weekly Report Generator — End-to-End Integration Documentation

> Standalone AI Weekly Report Generator — complete integration docs.
> Last updated: June 2026 — reflects current implementation.

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
18. [Recent Changes (June 2026)](#18-recent-changes-june-2026)

---

## 1. Overview

The AI Weekly Report Generator is a **standalone, 4-stage, human-in-the-loop AI pipeline**. It transforms a date range + topic/source selection into a publication-ready AI weekly report through interactive stages:

1. **Data Collection** → 2. **Content Curation** → 3. **Report Generation** → 4. **Quality Review**

Stage 1 uses a **LangGraph StateGraph 15-node pipeline** (no LLM). Stages 2–4 use **`cmbagent.one_shot(agent='researcher')`** with token-aware chunking and multi-pass LLM execution.

**Key technologies:**
- **Backend:** Python, FastAPI, asyncio
- **Execution Engine:** `one_shot(agent='researcher')` via `cmbagent` + helper functions in `aiweekly_helpers.py`
- **Data Collection:** LangGraph 15-node pipeline in `news_collection_graph.py` — cmbagent tools, DDGS.news(), RSS feeds (26), NewsAPI, GNews, arxiv.Client(), cmbagent web_surfer + perplexity agents
- **Frontend:** React, TypeScript, Next.js (single-page app)
- **Real-time:** REST polling (console output)
- **Storage:** JSON file-based (`task.json` per task in `~/Desktop/cmbdir/aiweekly/`)
- **Default LLM:** Dynamic from `WorkflowConfig.default_llm_model`; per-stage override via UI
- **Agent Enforcement:** Monkey-patch on `CMBAgent.solve` prevents control agent from switching to `engineer`
- **PDF Generation:** WeasyPrint 69.0 (markdown → HTML+CSS → PDF)
- **Mode:** `"aiweekly"`

**cmbagent agents used by stage:**

| Agent | Stage | Role | API Key Required |
|---|---|---|---|
| `web_surfer` | Stage 1 (Node 10) | Autonomous global web browsing for topic news | `BING_API_KEY` |
| `perplexity` | Stage 1 (Node 11) | arXiv / academic literature discovery | `PERPLEXITY_API_KEY` |
| `summarizer` | Stage 2 pre-pass | Compress collections >200K chars before curation | None (not yet active) |
| `researcher` | Stages 2, 3, 4 | Curation, generation (analyst + writer), review (critic + editor) | None |

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
│  routers/aiweekly.py ── REST endpoints + one_shot execution engine      │
│    _run_aiweekly_one_shot_stage():                                     │
│      1. helpers.build_*_kwargs() ── build prompt + config               │
│      2. _run_one_shot_sync(**kwargs) ── cmbagent.one_shot(researcher)   │
│      3. Token-aware chunking + LLM merge for multi-chunk stages        │
│      4. helpers.extract_stage_result() + save_stage_file()              │
│      5. On all-complete → _generate_cost_summary() → cost_summary.md  │
│                                                                       │
│  _patch_solve_once() ── agent enforcement (prevents engineer override)  │
│  _ConsoleCapture ── thread-safe stdout/stderr → REST console buffer    │
└───────────┬──────────────────────────────┬────────────────────────────┘
            │                              │
            ▼                              ▼
┌────────────────────────┐    ┌─────────────────────────────────────────┐
│  File System (JSON)    │    │  backend/task_framework/                │
│                        │    │                                         │
│  task.json (per task)  │    │  news_collection_graph.py (Stage 1,    │
│  Stages + output_data  │    │    LangGraph 15-node pipeline, no LLM) │
│  Cost in output_data   │    │  aiweekly_helpers.py (Stages 2–4,      │
└────────────────────────┘    │    prompts, chunking, merge, PATCH MODE)│
                              └─────────────────────────────────────────┘
```

---

## 3. Directory Structure

```
backend/
  models/aiweekly_schemas.py   # Pydantic request/response models
  routers/aiweekly.py          # 13 REST endpoints + PDF via WeasyPrint
  task_framework/
    news_collection_graph.py   # Stage 1: LangGraph 15-node collection pipeline
    aiweekly_helpers.py        # Stage 2–4: prompts, chunking, merge, PATCH MODE
  services/
    file_task_store.py         # JSON file-based task/stage persistence
    session_manager.py         # Session lifecycle (legacy)
    connection_manager.py      # WebSocket connections
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
```

---

## 4. The 4-Stage Pipeline

| # | Stage | Implementation | Type | Specialist | Output Key |
|---|---|---|---|---|---|
| 1 | Data Collection | LangGraph 15-node pipeline | No LLM | N/A | `raw_collection` |
| 2 | Content Curation | `researcher` (chunked + merge) | LLM | Fact-checker | `curated_items` |
| 3 | Report Generation | `researcher` × 2 passes | LLM | Business analyst | `draft_report` |
| 4 | Quality Review | `researcher` × 2 passes (PATCH MODE) | LLM | None | `final_report` |

### Stage 1: Data Collection — LangGraph StateGraph (15 Nodes)

`backend/task_framework/news_collection_graph.py`

The collection runs as a LangGraph StateGraph. All nodes share a `NewsCollectionState` TypedDict
that accumulates `collected_items` incrementally. Each node's errors are captured without
stopping the pipeline.

**Node sequence:**

| Node | Method | Source | API Key? |
|---|---|---|---|
| 1. `broad_sweep` | `announcements_noauth()` | cmbagent | None |
| 2. `curated_sources` | `curated_ai_sources_search()` per topic | cmbagent | None |
| 3. `company_scrape` | `scrape_official_news_pages()` × 15 companies | cmbagent | None |
| 4. `company_ddg_news` | `DDGS.news()` × 15 companies | duckduckgo_search | None |
| 5. `newsapi_gnews` | NewsAPI + GNews | External APIs | `NEWSAPI_KEY`, `GNEWS_KEY` |
| 6. `rss_feeds` | feedparser × 26 RSS feeds | feedparser | None |
| 7. `custom_sources` | user-provided URLs/RSS | feedparser | None |
| 8. `topic_arxiv_search` | `arxiv.Client()`, 25 papers/topic | arxiv | None |
| 9. `topic_web_search` | `DDGS.news()` structured output | duckduckgo_search | None |
| 10. `web_surfer_agent` | `cmbagent.one_shot(agent='web_surfer')` | cmbagent | `BING_API_KEY` |
| 11. `perplexity_agent` | `cmbagent.one_shot(agent='perplexity')` | cmbagent | `PERPLEXITY_API_KEY` |
| 12. `gap_fill` | re-search topics with <5 items, max 2 rounds | mixed | varies |
| 13. `date_validate` | strict date range filter | — | None |
| 14. `semantic_dedup` | difflib ratio > 0.82 | — | None |
| 15. `build_output` (END) | writes `collection.json` + `collection.md` | — | None |

**Company list for `company_ddg_news` and `company_scrape`:**
openai, nvidia, google, meta, microsoft, anthropic, deepmind, apple, huggingface, amazon, ibm, mistral, xai, deepseek, cohere

**RSS feeds (26):** Includes NVIDIA, Meta AI, Microsoft AI, DeepMind, Apple ML, Mistral, AWS ML, IBM Research, and 18 others.

Nodes 10 and 11 are **silently skipped** when their respective API keys are absent.

### Stages 2–4: LLM Pipeline

Each stage follows the pattern in `aiweekly_helpers.py`:

```
Stage 2 (Curation):
  [Optional] summarizer pre-pass if collection > 200K chars
  researcher (chunked) → per-chunk curation → LLM merge

Stage 3 (Generation):
  researcher → analyst pass: report_outline
  researcher → writer pass: report_draft
  [If multi-chunk] merge pass: partial reports → single report_draft.md

Stage 4 (Quality Review — PATCH MODE):
  researcher → critic pass: identifies corrections list
  researcher → editor pass: patches only flagged items
                            ("copy all existing highlights exactly unless flagged")
  Programmatic → URL check, date range, placeholder detect
```

---

## 5. Phase-Based Execution Engine

### `_run_aiweekly_one_shot_stage()` in `backend/routers/aiweekly.py`

```python
async def _run_aiweekly_one_shot_stage(
    task_id, stage_num, stage_def, task_config, work_dir, shared_state,
    config_overrides, buf_key, callbacks
):
    # Stage 1: LangGraph 15-node collection pipeline (no LLM)
    # Stages 2-4: Build kwargs via helpers, run one_shot(agent='researcher')
    #   Stage 2: Token-aware chunking + per-chunk curation + LLM merge
    #   Stage 3: Analysis pass + generation per chunk + LLM merge
    #   Stage 4: Critic pass (PATCH MODE) + Editor pass + programmatic verification
    # All stages: extract_stage_result() + save_stage_file() + update task.json
```

### Agent Enforcement

```python
# _patch_solve_once() in routers/aiweekly.py
# Monkey-patches CMBAgent.solve to inject:
#   current_instructions = "Use ONLY the researcher agent. Do NOT use the engineer."
# This prevents cmbagent's control agent LLM from overriding agent_for_sub_task.
```

### Helper Functions (`backend/task_framework/aiweekly_helpers.py`)

| Function | Purpose |
|---|---|
| `build_curation_kwargs()` | Stage 2: build one_shot kwargs for curation |
| `build_curation_merge_kwargs()` | Stage 2: merge multi-chunk curation results |
| `build_generation_analysis_kwargs()` | Stage 3: structural analysis pass |
| `build_generation_kwargs()` | Stage 3: report generation per chunk |
| `build_generation_merge_kwargs()` | Stage 3: merge multi-chunk reports |
| `build_review_critique_kwargs()` | Stage 4: critic pass (editorial audit, PATCH MODE) |
| `build_review_kwargs()` | Stage 4: editor pass (apply patches only) |
| `_get_chunk_budget(model)` | Token-aware chunk size calculation |
| `split_collection_items()` | Split text into chunks at item boundaries |
| `extract_stage_result()` | Extract markdown from one_shot chat history |
| `programmatic_verification()` | URL/date/placeholder checks (Stage 4) |

---

## 6. Shared State & Context Flow

```
Stage 1 output:  shared_state["raw_collection"]   (collection.json + collection.md)
Stage 2 input:   {task_config, raw_collection}     → output: curated_items
Stage 3 input:   {task_config, raw_collection, curated_items} → output: draft_report
Stage 4 input:   {task_config, raw_collection, curated_items, draft_report} → output: final_report
```

**Smart fallback in PDF generation:** If `report_final.md` is less than 1.5× smaller than
`report_draft.md` (indicating truncation), WeasyPrint uses `report_draft.md` as the PDF source.

---

## 7. Backend API Reference

All endpoints prefixed with `/api/aiweekly`.

| Method | Path | Description |
|---|---|---|
| POST | `/create` | Create task + 4 stages in task.json |
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
| GET | `/{id}/download-pdf/{filename}` | Convert MD to PDF via WeasyPrint and download |

---

## 8. Data Storage

All task data is stored as JSON files on the file system. No database is required.

### task.json (one per task)

| Field | Value |
|---|---|
| `mode` | `"aiweekly"` |
| `status` | `"executing"` → `"completed"` / `"failed"` |
| `work_dir` | `~/Desktop/cmbdir/aiweekly/<id[:8]>` |
| `task_config` | `{date_from, date_to, topics, sources, style}` |

### Stage Data (4 stages per task, embedded in task.json)

| Field | Description |
|---|---|
| `stage_number` | 1–4 |
| `status` | `pending` → `running` → `completed` / `failed` |
| `output_data` | `{"shared": {"<key>": "markdown content"}, "cost": {...}}` |

### Stage 1 output files (in work_dir)

| File | Description |
|---|---|
| `collection.json` | All collected items as structured JSON |
| `collection.md` | All collected items as formatted markdown |

---

## 9. Phase Classes & Prompts

### Stage 2: Curation

**System prompt:** Senior AI news editor — curate, validate, deduplicate.
**Specialist:** Fact-checking specialist — date accuracy, credibility, diversity.
**Pre-pass:** summarizer agent triggered when collection exceeds 200K chars (pending full testing).

### Stage 3: Generation

**System prompt:** Senior analyst writing enterprise-grade weekly report.
**Specialist:** Business analyst — completeness, balance, actionability.
**Report structure:** Executive Summary → Key Highlights → Trends → Quick Reference Table.

### Stage 4: Quality Review (PATCH MODE)

**System prompt:** Quality editor — final polish for publication readiness.
**No specialist.** Two researcher passes:
1. **Critic pass** — identifies specific corrections (not a full rewrite)
2. **Editor pass** — copies all content unchanged; patches only flagged items

**Rationale for PATCH MODE:** The original full-rewrite approach hit the output token limit,
truncating `report_final.md` from 210K chars to ~17K chars. PATCH MODE preserves full content
by only modifying flagged items.

After the LLM passes, runs **programmatic verification** — 5 deterministic checks:
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
            └── Right collapsible sessions panel (320px open, 40px collapsed)
                 ├── Search bar + filter tabs (All/Running/Completed/Failed)
                 ├── Task cards: status icon, stage info, date/time, progress bar
                 │   • Completed tasks show "Completed" (not stage name)
                 │   • Date/time shows actual timestamp (e.g. "Apr 30, 10:52 AM")
                 └── Footer: total session count
```

- **Default view:** Task setup panel (Step 0) loads immediately on app open
- **Task switching:** Clicking a task swaps the main content component via React state (`resumeTaskId`)
- **No router navigation:** The `key` prop on `AIWeeklyReportTask` forces React to remount with fresh state
- **API calls use relative URLs:** `fetch('/api/aiweekly/recent')` goes through Next.js proxy rewrite to backend

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

The right collapsible sessions panel is always visible. It fetches `GET /api/aiweekly/recent` (via relative URL through Next.js proxy) and shows task cards with status, stage info, date/time, and progress. Clicking a task sets `resumeTaskId` in React state, which triggers `AIWeeklyReportTask` to remount and load the task at the correct wizard step.

`resumeTask(id)` in `useAIWeeklyTask.ts` loads task state via `GET /{id}`, finds the latest completed stage, and sets `currentStep` to the next wizard step.

---

## 13. Token Capacity Management

Stages 2–4 use token-aware chunking via `aiweekly_helpers.py`:

1. `_get_chunk_budget(model)` — calculates safe chunk size based on model context window
2. `split_collection_items(text, target_chars)` — splits at item boundaries (not mid-item)
3. Each chunk processed via separate `one_shot()` call
4. Multi-chunk results merged via LLM merge pass (`curation_merge_prompt` or `merge_partials_prompt`)
5. Default chunk target: ~60K chars (`_CHUNK_TARGET_CHARS`)

---

## 14. Cost Tracking

Each LLM call's token usage is tracked per-stage in the `output_data["cost"]` field of task.json.

- Stages 2–4 return token counts in `output_data["cost"]`
- Cost formula: `cost_usd = (prompt_tokens × 0.002 + completion_tokens × 0.008) / 1000`
- When all 4 stages complete, `cost_summary.md` is auto-generated in the work directory

---

## 15. End-to-End User Flow

1. User opens app → sees setup panel (default view)
2. **Setup:** Configures date range, picks topics/sources, selects style
3. **Create + Execute Stage 1:** `POST /create` → `POST /stages/1/execute`
4. **Data Collection runs:** LangGraph 15-node pipeline; console shows node-by-node progress
5. **Stage 1 completes:** Wizard advances, shows collected data
6. User reviews, optionally edits, clicks **Next**
7. **Stages 2–4 auto-execute** and user reviews each
8. **Final report displayed** with download links (MD + PDF) + cost summary

---

## 16. Error Handling

| Error | Handling |
|---|---|
| Node failure in Stage 1 | Error appended to `state["errors"]`; pipeline continues |
| Missing API keys (Stage 1) | Nodes 10 and 11 silently skipped; other nodes unaffected |
| Tool call failure (Stage 1) | Logged + skipped |
| Stage timeout (900s) | Stage marked `failed` |
| LLM API error | Stage marked `failed` with error |
| Token overflow | Auto-split via `chunk_prompt_if_needed` |
| report_final.md truncated | Smart fallback: PDF uses report_draft.md if final < 1.5× draft size |

---

## 17. Workflow Run Auto-Completion

When the last stage completes, `_run_aiweekly_one_shot_stage()` reloads the task from task.json and checks all stages. If all 4 are `"completed"`, the task status transitions to `"completed"` with a timestamp. Completed tasks appear in `GET /api/aiweekly/recent` (the sessions panel shows all tasks with search/filter).

---

## 18. Recent Changes (June 2026)

### Stage 1: LangGraph 15-node pipeline (replaces direct Python tool calls)

The previous Stage 1 was a flat sequence of 6 direct Python function calls. It has been
replaced with a **LangGraph StateGraph** with 15 nodes. Key benefits:

- Shared `NewsCollectionState` TypedDict flows through all nodes
- Each node's errors are isolated — one failure does not stop the pipeline
- `gap_fill` node can loop back to re-search topics with insufficient coverage
- New nodes can be added or reordered without restructuring

### New data source: `company_ddg_news` (Node 4)

Added `DDGS.news()` per company as a dedicated node. Covers 15 companies (openai, nvidia,
google, meta, microsoft, anthropic, deepmind, apple, huggingface, amazon, ibm, mistral, xai,
deepseek, cohere) with no API key required. Fills coverage gaps when cmbagent tools
rate-limit or fail.

### `topic_web_search` upgraded from `DuckDuckGoSearchRun` to `DDGS.news()`

The original plan used `DuckDuckGoSearchRun` from `langchain_community.tools`, which returns
a raw text blob. The implementation uses `DDGS.news()` from the `duckduckgo_search` package
directly, returning structured dicts (title, url, body, date) for reliable item parsing.

### RSS feed count increased from 20 to 26

Six feeds added: NVIDIA, Meta AI, Microsoft AI, DeepMind, Apple ML, Mistral, AWS ML,
IBM Research.

### cmbagent agents added to Stage 1

- `web_surfer` (Node 10) — autonomous web browsing; gated on `BING_API_KEY`
- `perplexity` (Node 11) — academic/arXiv literature; gated on `PERPLEXITY_API_KEY`

Both nodes silently skip when their keys are absent.

### Stage 4: PATCH MODE

The original Stage 4 editor did a full rewrite, which hit the output token limit and produced
a truncated `report_final.md` (~17K chars from a 210K char draft). PATCH MODE changes the
editor to copy all content unchanged and patch only items flagged by the critic pass.

### PDF generation: WeasyPrint replaces fpdf2

`fpdf2`'s `write_html()` crashed on malformed HTML tables, long URLs, and Unicode.
WeasyPrint 69.0 handles all of these. It was already present in `Requirements.txt`.

Smart fallback: if `report_final.md` is less than 1.5× smaller than `report_draft.md`,
WeasyPrint uses the draft as source (detects and recovers from truncation).

### Stage 2: summarizer pre-pass (partial)

Logic is in place to invoke `cmbagent.one_shot(agent='summarizer')` when the collection
exceeds 200K chars, compressing to ~500 items before curation. Needs end-to-end testing —
currently falls through to the researcher directly.
