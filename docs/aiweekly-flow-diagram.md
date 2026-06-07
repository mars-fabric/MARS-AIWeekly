# AI Weekly Report Generator — Complete Flow Diagram

> Standalone AI Weekly Report Generator — all flow diagrams for the 4-stage pipeline.
> Last updated: June 2026

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
│                        BACKEND  (FastAPI / Python)                  [UPDATED]   │
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
│  Stage 1: LangGraph pipeline (NewsCollectionState TypedDict, 15 nodes)         │
│    OLD: direct Python tool calls in a flat helper function                     │
│                                                                                 │
│  Stage 4: PATCH MODE editor (copies highlights, only patches flagged items)    │
│    OLD: editor rewrote the full report from scratch                             │
│                                                                                 │
│  PDF generation: WeasyPrint (MD → HTML+CSS → PDF)                             │
│    OLD: fpdf2 library                                                           │
│                                                                                 │
│  _ConsoleCapture ── thread-safe stdout → REST console buffer                   │
└───────┬──────────────────────────────┬──────────────────────────────────────────┘
        │                              │
        ▼                              ▼
┌────────────────────────┐  ┌─────────────────────────────────────────────────────┐
│  FILE SYSTEM (JSON)    │  │   EXTERNAL APIs / LLM                   [UPDATED]   │
│                        │  │                                                     │
│  ~/Desktop/cmbdir/     │  │   Stage 1: LangGraph pipeline — 15 nodes            │
│  aiweekly/{id}/        │  │            RSS (26 feeds), company scrape,          │
│    task.json           │  │            DDGS.news(), NewsAPI, GNews, arxiv,      │
│    input_files/        │  │            web_surfer, perplexity, dedup            │
│                        │  │            (no LLM — pure Python tool calls)        │
│                        │  │                                                     │
│                        │  │   Stage 2: one_shot(researcher) per chunk + merge   │
│                        │  │   Stage 3: analysis pass + generation + merge       │
│                        │  │   Stage 4: critic pass + PATCH MODE editor          │
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

## 3. Stage 1 — Data Collection Pipeline (LangGraph)  [UPDATED]

> OLD implementation: a flat `helpers.run_data_collection()` function that called
> Python tools directly in sequence. No graph, no typed state, ~6 tool categories.
>
> NEW implementation: a LangGraph pipeline. State flows through a
> `NewsCollectionState` TypedDict across 15 nodes. The `company_ddg_news` node
> is new. RSS feed count increased from 18 to 26.

```
LangGraph pipeline — NewsCollectionState TypedDict, 15 nodes, no LLM calls

  broad_sweep
      │
      ▼
  curated_sources
      │
      ▼
  company_scrape
      │
      ▼
  company_ddg_news   ◄── NEW node (DDGS.news(), no API key required)
      │
      ▼
  newsapi_gnews
      │
      ▼
  rss_feeds
      │
      ▼
  custom_sources
      │
      ▼
  topic_arxiv_search
      │
      ▼
  topic_web_search
      │
      ▼
  web_surfer_agent
      │
      ▼
  perplexity_agent
      │
      ▼
  gap_fill
      │
      ▼
  date_validate
      │
      ▼
  semantic_dedup
      │
      ▼
  END
      │
      ▼
  Output: collection.json + collection.md
  Cost: $0.0000 (no LLM calls)
```

### Node Descriptions

```
  broad_sweep        cmbagent announcements_noauth(), full sweep

  curated_sources    cmbagent curated_ai_sources_search(), per topic

  company_scrape     cmbagent scrape_official_news_pages(), 15 companies

  company_ddg_news   DDGS.news() for each of 15 companies               [NEW]
  (NEW)              — OpenAI, NVIDIA, Google, Meta, Microsoft, etc.
                     — no API key required; reliable company news

  newsapi_gnews      NewsAPI + GNews (requires NEWSAPI_KEY / GNEWS_API_KEY)

  rss_feeds          26 global feeds (AI news + arXiv + company blogs)  [UPDATED]
                     OLD: 18 feeds
                     NEW additions: NVIDIA, Meta AI, Microsoft AI,
                       DeepMind, Apple ML, Mistral, AWS ML, IBM Research

  custom_sources     user-provided URLs / RSS feeds

  topic_arxiv_search arxiv.Client() direct API, 25 papers per topic

  topic_web_search   DDGS.news(): 2 queries/topic + 1 general sweep

  web_surfer_agent   cmbagent web_surfer (requires BING_API_KEY)

  perplexity_agent   cmbagent perplexity (requires PERPLEXITY_API_KEY)

  gap_fill           re-search topics with <5 items, max 2 rounds

  date_validate      strict date range filter

  semantic_dedup     difflib ratio >0.82 dedup
```

---

## 4. Stages 2–4 — LLM Pipeline (one_shot + multi-pass)  [UPDATED]

> Stage 4 editor is now in PATCH MODE.
> OLD: editor rewrote the full report, which risked output-token-limit truncation.
> NEW: editor copies all existing highlights exactly unless the critic flagged them,
>      then patches only the flagged items. report_final.md is always >= report_draft.md
>      in content length.

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

 STAGE 4 (Quality Review):  [UPDATED — PATCH MODE]
   A. Critic pass: one_shot → editorial audit (identifies flagged items)
   B. Editor pass (PATCH MODE):
        - Copy all existing highlights exactly unless critic flagged them
        - Patch only flagged items (no full rewrite)
        - Guarantees report_final.md >= report_draft.md in content
      OLD: editor rewrote the full report from scratch (caused truncation risk)
   C. Programmatic verification: URL check, date check,
      placeholder/superlative detection
 │
 ▼
 helpers.extract_stage_result() → markdown from chat history
 helpers.save_stage_file() → save to work_dir
```

---

## 5. Shared State Accumulation  [UPDATED]

> The state artifacts are the same as before. The flow diagram below now reflects
> the addition of review_critique.md in Stage 4 and cost_summary.md at completion.

```
Stage 1: raw_collection
            collection.json + collection.md
            │
            ▼
Stage 2: reads {raw_collection, task_config}
            → curated_items (curated.md)
            [+ report_outline.md if multi-chunk]
            │
            ▼
Stage 3: reads {raw_collection, curated_items, task_config}
            → draft_report (report_draft.md)
            [+ report_outline.md]
            │
            ▼
Stage 4: reads {all prior + task_config}
            → final_report (report_final.md)   [PATCH MODE — always >= draft]
            [+ review_critique.md]
            │
            ▼
ALL DONE: cost_summary.md
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

## 8. API Endpoint Quick Reference  [UPDATED]

> Endpoint 12 (download-pdf) now uses WeasyPrint (MD → HTML+CSS → PDF).
> OLD: fpdf2. The endpoint also applies a smart fallback: if report_final.md
> is less than 1.5× the size of report_draft.md (indicating possible truncation),
> the PDF is generated from report_draft.md instead.

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
| 12 | GET | `/api/aiweekly/{id}/download-pdf/{file}?inline=true` | Download as PDF (WeasyPrint) [UPDATED] |
| 13 | DELETE | `/api/aiweekly/{id}` | Delete task + files |

### PDF Download Detail  [UPDATED]

```
GET /api/aiweekly/{id}/download-pdf/{filename}?inline=true

  1. Read {filename} (e.g. report_final.md) from work_dir
  2. Smart fallback check:
       if report_final.md < 1.5× size of report_draft.md
           → use report_draft.md instead
             (guards against Stage 4 truncation)
  3. MD → HTML with CSS:
       - word-break: break-all on <pre> and <a> tags
         (handles long URLs and code blocks)
  4. WeasyPrint renders HTML+CSS → PDF bytes
  5. Return PDF with Content-Disposition: inline (or attachment)

  OLD: fpdf2 rendered plain text directly to PDF (no CSS, no HTML)
```

---

## 9. Output Files  [UPDATED]

> review_critique.md is now explicitly saved as a Stage 4 artifact.

```
{work_dir}/input_files/
├── task_config.json       # User configuration
├── collection.json        # Stage 1: structured JSON (LangGraph output)
├── collection.md          # Stage 1: markdown summary
├── curated.md             # Stage 2: curated items
├── report_outline.md      # Stage 2/3: outline (multi-chunk runs only)
├── report_draft.md        # Stage 3: draft report
├── review_critique.md     # Stage 4: critic pass output        [NEW artifact]
├── report_final.md        # Stage 4: final report (PATCH MODE — always >= draft)
└── cost_summary.md        # Auto-generated cost breakdown
```
