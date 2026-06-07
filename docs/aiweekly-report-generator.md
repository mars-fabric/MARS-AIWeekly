# AI Weekly Report Generator — Complete Feature Guide

> **Standalone AI Weekly Report Generator**
>
> A comprehensive guide covering the AI Weekly Report Generator: fundamentals, workflow stages, task lifecycle, AI techniques, and architecture. Updated June 2026 to reflect the LangGraph pipeline, PATCH MODE editor, and WeasyPrint PDF generation.

---

## Table of Contents

1. [Basics — What Is the AI Weekly Report Generator?](#1-basics--what-is-the-ai-weekly-report-generator)
2. [All Stages in the Pipeline](#2-all-stages-in-the-pipeline)
3. [Task Flow — From App Open to Final Report](#3-task-flow--from-app-open-to-final-report)
4. [Outcomes — Saved and Processed](#4-outcomes--saved-and-processed)
5. [AI Techniques Used](#5-ai-techniques-used)
6. [Architecture Deep Dive](#6-architecture-deep-dive)
7. [API Reference](#7-api-reference)
8. [Configuration & Model Defaults](#8-configuration--model-defaults)
9. [Error Handling & Troubleshooting](#9-error-handling--troubleshooting)
10. [Glossary](#10-glossary)

---

## 1. Basics — What Is the AI Weekly Report Generator?

### 1.1 Overview

The AI Weekly Report Generator is a **standalone, 4-stage, human-in-the-loop AI pipeline**. It transforms a date range, topic, and source selection into a **professional, publication-ready AI weekly news digest** — from raw data collection through content curation to a polished final report — while keeping the human in control at every stage.

The app runs as a **single-page application** (SPA) — all navigation happens via React state, with no full page reloads.

### 1.2 What It Produces

| Artifact | Format | Description |
|---|---|---|
| Raw Collection | Markdown + JSON | All items collected via the LangGraph 15-node pipeline |
| Curated Items | Markdown | Deduplicated, validated, and enriched master list |
| Draft Report | Markdown | 4-section report: Executive Summary, Key Highlights, Trends, Quick Reference |
| Report Outline | Markdown | Structural outline produced by the analyst pass in Stage 3 |
| **Final Report** | Markdown | **Publication-ready report** — PATCH MODE preserves all draft content |
| PDF Download | PDF | WeasyPrint-rendered PDF (tables, Unicode, code blocks; no crashes) |
| Cost Summary | Markdown | Per-stage token usage and USD cost breakdown |

### 1.3 Key Design Principles

| Principle | Implementation |
|---|---|
| **Single-Page App** | All navigation via React state — only component swaps, no page reloads |
| **Phase-Based Execution** | 4 discrete stages; Stage 1 = LangGraph pipeline (no LLM); Stages 2–4 = `one_shot(agent='researcher')` |
| **Hybrid Architecture** | Stage 1 = LangGraph 15-node graph (no LLM). Stages 2–4 = LLM pipeline |
| **Human-in-the-loop** | Users review, edit, and refine output between every stage |
| **Token-safe** | Token-aware chunking via `_get_chunk_budget()` + `split_collection_items()` |
| **Dynamic model** | Model resolved from config; user can override per-stage via UI |
| **Multi-pass** | Stage 2-3: chunk + merge. Stage 4: critic + PATCH MODE editor |
| **Agent enforcement** | Monkey-patch prevents cmbagent control agent from switching to engineer |
| **Auto-completing** | Task status transitions to `"completed"` when all stages finish |
| **Cost-transparent** | Per-stage cost tracking with aggregated USD totals |
| **Resumable** | Tasks persist as JSON files and can resume after browser reload |

### 1.4 Technology Stack

**Changed:** Technology stack updated to reflect LangGraph, DuckDuckGo company search, expanded RSS feeds, arxiv package, and WeasyPrint PDF.

| Layer | Technology |
|---|---|
| **Backend** | Python, FastAPI, asyncio |
| **Stage 1 orchestration** | LangGraph `StateGraph` (15 nodes) — `news_collection_graph.py` |
| **LLM stages 2–4** | `cmbagent.one_shot(agent='researcher')` |
| **Company news (no API)** | `duckduckgo_search` `DDGS.news()` per company |
| **RSS feeds** | `feedparser` (26 feeds including all major company blogs) |
| **Academic papers** | `arxiv` Python package (direct arXiv API) |
| **Web search** | `duckduckgo_search` `DDGS.news()` + `DuckDuckGoSearchRun` fallback |
| **Autonomous web** | cmbagent `web_surfer` agent (requires `BING_API_KEY`) |
| **PDF generation** | WeasyPrint 69.0 (markdown → HTML+CSS → PDF) |
| **Frontend** | React, TypeScript, Next.js 16 (SPA) |
| **Real-time** | REST polling (console output) |
| **Storage** | JSON files (`~/Desktop/cmbdir/aiweekly/`) |

---

## 2. All Stages in the Pipeline

### Stage 1: Data Collection — LangGraph 15-Node Pipeline (Non-LLM)

**Changed:** Stage 1 is no longer a flat sequence of 6 `helpers.run_data_collection()` tool calls. It is now a **LangGraph `StateGraph`** compiled from 15 nodes defined in `backend/task_framework/news_collection_graph.py`. Entry point: `run_data_collection()` → `run_news_collection_graph()` → compiled graph invocation.

**Old implementation (removed):**

| Step | Tool | Description |
|------|------|-------------|
| A | `announcements_noauth(limit=300)` | Broad sweep with a 300-item cap |
| B | `scrape_official_news_pages()` × 19 | Per-company scrape |
| C | `curated_ai_sources_search(limit=40)` | Curated AI sources, one query |
| D | `newsapi_search()` | NewsAPI |
| E | `gnews_search()` | GNews |
| F | `multi_engine_web_search()` | DDG → Bing → Yahoo → Brave fallback |

**New implementation — 15-node LangGraph pipeline:**

The graph runs sequentially. Each node is self-contained and handles its own exceptions — a node failure produces an error entry in `state["errors"]` but does not halt the pipeline.

#### Tier 1 — cmbagent Structured Tools

| # | Node | What it does |
|---|------|-------------|
| 1 | `broad_sweep` | `announcements_noauth()` — full sweep, no item limit |
| 2 | `curated_sources` | `curated_ai_sources_search()` — one query per user topic (not a single generic query) |
| 3 | `company_scrape` | `scrape_official_news_pages()` for 15 core companies: openai, anthropic, google, meta, microsoft, nvidia, huggingface, amazon, deepmind, apple, ibm, mistral, xai, deepseek, cohere |
| 4 | `company_ddg_news` | **NEW** — `DDGS.news()` per company (no API key required); guarantees company coverage even when cmbagent tools fail or return sparse results |
| 5 | `newsapi_gnews` | NewsAPI + GNews — one query per user topic; skipped silently if `NEWSAPI_KEY` / `GNEWS_API_KEY` are absent |

#### Common Feeds + User Sources

| # | Node | What it does |
|---|------|-------------|
| 6 | `rss_feeds` | 26 RSS feeds parsed by `feedparser`, date-filtered only — no topic constraint. Feeds include: TechCrunch AI, VentureBeat AI, The Verge, Synced Review, arXiv (cs.AI / cs.LG / cs.CL / cs.RO / cs.CV), HuggingFace blog, OpenAI blog, Google Research, Anthropic, NVIDIA blog, Meta AI, Microsoft AI, DeepMind, Apple ML, Mistral, AWS ML, IBM Research |
| 7 | `custom_sources` | User-provided URLs and RSS feeds; tries RSS parse first, falls back to HTML link scrape |

#### Tier 2 — Global Topic Search

| # | Node | What it does |
|---|------|-------------|
| 8 | `topic_arxiv_search` | Direct arXiv API — 25 papers per topic with expanded queries (e.g., `"llm"` → `"large language model transformer generation"`); works for any arbitrary topic string |
| 9 | `topic_web_search` | `DDGS.news()` — 2 queries per topic + 1 general AI sweep; falls back to `DuckDuckGoSearchRun` text parsing if package unavailable |
| 10 | `web_surfer_agent` | cmbagent `web_surfer` autonomous web browsing per topic — skipped if `BING_API_KEY` not set |
| 11 | `perplexity_agent` | cmbagent `perplexity` agent for academic paper discovery — skipped if `PERPLEXITY_API_KEY` not set |

#### Post-Processing

| # | Node | What it does |
|---|------|-------------|
| 12 | `gap_fill` | Re-searches any topic with fewer than 5 items using `multi_engine_web_search()`; max 2 rounds |
| 13 | `date_validate` | Strict date range filter; items with no parseable date are kept (flagged `_undated=True`) for Stage 4 verification |
| 14 | `semantic_dedup` | `difflib.SequenceMatcher` ratio > 0.82 on titles; uses prefix bucketing for O(n) average-case performance |
| 15 | `build_output` | Writes `collection.json` + `collection.md` to `input_files/` |

**State object `NewsCollectionState`:**

```python
date_from, date_to, topics, sources, custom_sources,
collected_items, seen_keys, errors, topic_coverage, gap_fill_round, work_dir
```

**Output:** `raw_collection` — `collection.json` + `collection.md`.

---

### Stage 2: Content Curation (LLM)

**Function:** `helpers.build_curation_kwargs()` + `build_curation_merge_kwargs()`

**Unchanged from previous version** except for one addition: if the raw collection exceeds ~200K characters, a compaction pre-pass (`_compact_collection_for_prompt()`) reduces it before passing it to the LLM.

Token-aware chunking splits the collection into safe-size chunks. Each chunk is curated via `one_shot(agent='researcher')`. Multi-chunk results are merged (programmatically by `merge_curated_chunks()` first; LLM merge only if needed).

Removes duplicates, validates dates, checks credibility, ensures diversity, groups by organization.

**Output:** `curated_items` → `curated.md`.

---

### Stage 3: Report Generation (LLM)

**Function:** `helpers.build_generation_analysis_kwargs()` + `build_generation_kwargs()` + `build_merge_kwargs()`

**Unchanged in structure.** Two-pass architecture:

1. **Analyst pass:** Structural outline — identifies key themes, groupings, and which items belong in each report section. Output saved as `report_outline.md`.
2. **Writer pass:** Full 4-section report written against the outline + curated items.
3. **Merge pass:** If curated items required chunking, partial reports are merged via LLM into a unified draft.

Report sections:

1. Executive Summary
2. Key Highlights & Developments
3. Trends & Strategic Implications
4. Quick Reference Table

**Output:** `report_draft.md` + `report_outline.md`.

---

### Stage 4: Quality Review — PATCH MODE (LLM)

**Changed:** The editor pass was redesigned to use PATCH MODE, eliminating the truncation problem of the old implementation.

**Old implementation (removed):**

- `build_review_kwargs()` instructed the editor to produce a **full rewrite** of the report.
- For large reports (~210K chars), the LLM hit its output token limit and returned only ~17K chars — discarding most of the content.
- Result: `report_final.md` was an incomplete stub.

**New implementation — PATCH MODE:**

| Pass | Function | What it does |
|------|----------|-------------|
| Critic | `build_review_critique_kwargs()` | Editorial audit — identifies specific corrections needed: missing items, wrong dates, bad URLs, duplicate entries, unsupported superlatives |
| Editor | `build_review_kwargs()` | **PATCH MODE** — copies all existing draft content verbatim; applies only the critic's flagged corrections. Never rewrites from scratch. |

Key instruction in the editor prompt (`review_editor_prompt`):

> "PATCH MODE — make the minimum changes needed. Copy every existing highlight from the draft EXACTLY unless the critic flagged it. Do NOT summarize, condense, or drop any item that was NOT flagged by the critic."

**Result:** `report_final.md` preserves the full content of `report_draft.md`, plus targeted corrections. The final report is never smaller than the draft due to LLM output limits.

**PDF safety fallback:** If `report_final.md` is more than 1.5× smaller than `report_draft.md` (indicating an unexpected truncation), the PDF download endpoint automatically uses `report_draft.md` as the source instead.

After both LLM passes, the pipeline runs **programmatic verification** — 7 deterministic checks:

1. URL verification — marks inaccessible URLs with `<!-- [LINK UNVERIFIED] -->`
2. Date verification — flags out-of-range dates
3. Placeholder detection
4. Superlative detection
5. Synthesis text removal
6. Truncation marker removal (safety net)
7. References section check

**Output:** `report_final.md`.

---

## 3. Task Flow — From App Open to Final Report

```
[User opens app → default view: AIWeeklySetupPanel]
    │
    └── Setup: selects date range, topics, sources, style, model settings
         ↓ POST /api/aiweekly/create + POST /{id}/stages/1/execute
[Step 1: LangGraph 15-node collection runs (console output polls via REST)]
    ↓ Auto-advances to Step 2 on completion
[Step 2: AIWeeklyReviewPanel — edit/preview curated items + refinement chat]
    ↓ Click "Next" → auto-executes Stage 3
[Step 3: AIWeeklyReviewPanel — edit/preview report draft + refinement chat]
    ↓ Click "Next" → auto-executes Stage 4
[Step 4: AIWeeklyReportPanel — final report preview + download artifacts (PDF)]
```

### Right Collapsible Sessions Panel

The right side of the app contains a collapsible sessions panel (320px open, 40px collapsed) with:
- **Search bar** — filter sessions by text
- **Filter tabs** — All / Running / Completed / Failed
- **Task cards** — status icon, stage info ("Completed" for finished tasks), date/time started, progress bar
- **Footer** — total session count

All API calls use relative URLs (`/api/aiweekly/recent`) through the Next.js proxy rewrite, enabling access from any hostname (not just localhost).

All transitions happen via React state — no page reloads.

### Key UI Components

| Wizard Step | Component | Purpose |
|---|---|---|
| 0 | `AIWeeklySetupPanel` | Date range, topics, sources, style, model settings |
| 1–3 | `AIWeeklyReviewPanel` | Resizable split-view editor + refinement chat |
| 4 | `AIWeeklyReportPanel` | Success banner, report preview, artifact downloads (including PDF) |

---

## 4. Outcomes — Saved and Processed

### File System (JSON)

- **`task.json`** — one file per task, contains all metadata, stage statuses, and output data
- Cost data embedded in each stage's `output_data["cost"]`

### Output Files

Files saved in `~/Desktop/cmbdir/aiweekly/{task_id[:8]}/input_files/`:

| File | Source |
|---|---|
| `task_config.json` | User selections from setup |
| `collection.json` | Stage 1: structured JSON with all collected items + errors + topic coverage |
| `collection.md` | Stage 1: markdown summary of all collected items |
| `curated.md` | Stage 2 output |
| `report_outline.md` | Stage 3 analyst pass: structural outline |
| `report_draft.md` | Stage 3 writer pass: full draft report |
| `report_final.md` | Stage 4 PATCH MODE editor output: polished final report |
| `cost_summary.md` | Auto-generated cost breakdown |

**Changed:** `report_outline.md` is a new artifact produced by the analyst pre-pass in Stage 3.

### PDF Download

**Changed:** PDF is now generated on demand via the `GET /api/aiweekly/{id}/download-pdf/{file}` endpoint using WeasyPrint (see Section 6). PDFs are not stored on disk — they are streamed per request.

---

## 5. AI Techniques Used

**Changed:** Deduplication now has two layers (LangGraph semantic dedup in Stage 1 + LLM dedup in Stage 2). Stage 4 uses PATCH MODE instead of full rewrite.

| Technique | Where |
|---|---|
| **LangGraph orchestration** | Stage 1 — 15-node StateGraph; sequential edges; each node self-contained |
| **Multi-source aggregation** | Stage 1 — cmbagent tools, DuckDuckGo, RSS (26 feeds), arXiv, NewsAPI/GNews, web_surfer, perplexity |
| **Two-tier collection** | Stage 1 — Tier 1 (structured cmbagent tools) + Tier 2 (global topic-driven search) |
| **Gap fill** | Stage 1 — re-searches under-covered topics (< 5 items), max 2 rounds |
| **Semantic dedup** | Stage 1 — `difflib.SequenceMatcher` ratio > 0.82 with prefix bucketing (O(n) average) |
| **Token-aware chunking** | Stages 2–4 — `_get_chunk_budget()` + `split_collection_items()` |
| **Multi-pass LLM** | Stage 2-3: chunk + merge. Stage 4: critic + PATCH MODE editor |
| **PATCH MODE editing** | Stage 4 — editor copies all draft content verbatim, applies only flagged corrections |
| **Agent enforcement** | Monkey-patch forces `researcher` agent (prevents `engineer` code gen) |
| **Progressive context** | Each stage receives shared state from all prior stages |
| **Refinement chat** | Real-time LLM refinement on any editable stage (diff patching with fallback) |
| **Programmatic verification** | Stage 4 post-LLM — 7 deterministic checks on the final report |

---

## 6. Architecture Deep Dive

### Stage 1 — LangGraph StateGraph

```
run_data_collection()
  └── run_news_collection_graph()   [news_collection_graph.py]
       └── compiled LangGraph StateGraph
            ├── broad_sweep → curated_sources → company_scrape → company_ddg_news
            ├── → newsapi_gnews → rss_feeds → custom_sources
            ├── → topic_arxiv_search → topic_web_search
            ├── → web_surfer_agent → perplexity_agent
            └── → gap_fill → date_validate → semantic_dedup → END
```

Node graph edges are strictly sequential. No conditional branching during traversal — the `gap_fill` node evaluates coverage internally and exits early if all topics are covered.

### Stages 2–4 — LLM Pipeline

```
cmbagent.one_shot(agent='researcher')
  └── CMBAgent.solve (monkey-patched to enforce researcher)
       └── control agent → researcher agent → output
```

Helper functions in `backend/task_framework/aiweekly_helpers.py`:
- `build_curation_kwargs()` / `build_curation_merge_kwargs()` — Stage 2
- `build_generation_analysis_kwargs()` / `build_generation_kwargs()` / `build_merge_kwargs()` — Stage 3
- `build_review_critique_kwargs()` / `build_review_kwargs()` — Stage 4 (PATCH MODE)

### PDF Generation — WeasyPrint

**Changed:** fpdf2 is replaced by WeasyPrint 69.0.

**Old implementation (removed — fpdf2):**
- `write_html()` raised `AssertionError` / `NotImplementedError` on malformed HTML tables
- `FPDFException: Not enough horizontal space` on certain content widths
- PDFs were frequently empty, partial, or crashed during generation

**New implementation — WeasyPrint:**

```
markdown → markdown2 HTML → CSS styling → WeasyPrint → PDF bytes → HTTP response
```

Key CSS rules that prevent crashes:

```css
/* Tables */
td, th { word-break: break-word; }

/* Code blocks */
pre, code { word-break: break-all; }
```

Full Unicode support (browser-grade font rendering). Tables, headings, bullets, and code blocks all render correctly. PDFs are streamed — not stored to disk.

**Endpoint:** `GET /api/aiweekly/{task_id}/download-pdf/{filename}?inline=true`

**Smart source selection:** If `report_final.md` is more than 1.5× smaller than `report_draft.md` (unexpected truncation detected), the endpoint automatically uses `report_draft.md` as the PDF source.

### Shared State Flow

```
Stage 1: raw_collection
  → Stage 2: curated_items
    → Stage 3: draft_report + report_outline
      → Stage 4: final_report (PATCH MODE — preserves full draft content)
```

### Backend Router

`backend/routers/aiweekly.py` — endpoints, prefix `/api/aiweekly`.

---

## 7. API Reference

### POST `/api/aiweekly/create`

Creates a new AI Weekly Report task.

**Request:**
```json
{
  "date_from": "2025-01-13",
  "date_to": "2025-01-19",
  "topics": ["llm", "cv"],
  "sources": ["github", "press-releases"],
  "style": "concise"
}
```

**Response:**
```json
{
  "task_id": "uuid",
  "work_dir": "/path/to/aiweekly/<id>",
  "stages": [
    {"stage_number": 1, "stage_name": "data_collection", "status": "pending"},
    {"stage_number": 2, "stage_name": "content_curation", "status": "pending"},
    {"stage_number": 3, "stage_name": "report_generation", "status": "pending"},
    {"stage_number": 4, "stage_name": "quality_review", "status": "pending"}
  ]
}
```

### POST `/api/aiweekly/{task_id}/stages/{stage_num}/execute`

Executes a stage asynchronously. Optional `config_overrides` for model and n_reviews.

### POST `/api/aiweekly/{task_id}/stages/{stage_num}/refine`

**Request:**
```json
{
  "message": "Add more detail about the OpenAI items",
  "content": "current markdown content..."
}
```

**Response:**
```json
{
  "refined_content": "improved markdown...",
  "message": "Applied 3 edit(s) via diff patching"
}
```

**Note:** Refinement uses diff patching (`services.diff_patcher.refine_with_diff`) with a full-document rewrite fallback.

### GET `/api/aiweekly/recent`

Lists incomplete tasks for resume. Returns up to 10 tasks ordered by `started_at` descending.

### POST `/api/aiweekly/{task_id}/stop`

Stops a running task. Cancels background tasks, marks stages as `failed`.

### GET `/api/aiweekly/{task_id}/download-pdf/{filename}`

**New endpoint.** Generates and streams a PDF of the requested markdown artifact.

**Query params:**
- `inline=true` — serves with `Content-Disposition: inline` (renders in browser tab)
- `inline=false` (default) — serves as attachment download

**Smart source fallback:** If `filename=report_final.md` but the final report is >1.5× smaller than the draft, uses `report_draft.md` automatically.

---

## 8. Configuration & Model Defaults

| Setting | Default | Source |
|---|---|---|
| Model | `WorkflowConfig.default_llm_model` | Overridable per-stage from UI |
| Fallback model | `gpt-4o` | If WorkflowConfig unavailable |
| Temperature | `0.7` | Overridable via UI |
| Max completion tokens | `16384` | Fixed |
| Reviews per stage | `1` | Overridable |
| Stage timeout | `900s` | Fixed |
| Token safety margin | `0.75` | Fixed |
| Chunk target | `60,000 chars` (~15K tokens) | `_CHUNK_TARGET_CHARS` in helpers |
| Gap fill threshold | `5 items per topic` | `MIN_COVERAGE_PER_TOPIC` in graph |
| Gap fill max rounds | `2` | `MAX_GAP_FILL_ROUNDS` in graph |
| Semantic dedup threshold | `0.82` similarity ratio | `SIM_THRESHOLD` in graph |
| PDF fallback ratio | `1.5×` | Router: if `draft_size > final_size * 1.5` |

### Optional Environment Variables (Stage 1)

| Variable | Effect if set |
|---|---|
| `NEWSAPI_KEY` | Enables NewsAPI search in `newsapi_gnews` node |
| `GNEWS_API_KEY` | Enables GNews search in `newsapi_gnews` node |
| `BING_API_KEY` | Enables cmbagent `web_surfer` autonomous browsing |
| `PERPLEXITY_API_KEY` | Enables cmbagent `perplexity` agent for paper discovery |

If none of `BING_API_KEY` / `PERPLEXITY_API_KEY` are set, nodes 10 and 11 skip silently — coverage is handled by arXiv, DuckDuckGo, and RSS feeds.

### Model Selection — UI to Backend Flow

1. **UI:** Setup panel shows model dropdowns (Primary, Review, Specialist)
2. **Hook:** `executeStage()` copies model selections into `config_overrides`
3. **API:** `POST /{id}/stages/{N}/execute` accepts `{ config_overrides }`
4. **Backend:** Extracts overrides with fallback to registry defaults
5. **Phase:** Instantiated with the resolved config

---

## 9. Error Handling & Troubleshooting

| Scenario | Behavior |
|---|---|
| A node fails in Stage 1 LangGraph | Error appended to `state["errors"]`; pipeline continues to next node |
| Stage 1 `company_ddg_news` fails | Error logged; company news still available from `company_scrape` node |
| `BING_API_KEY` / `PERPLEXITY_API_KEY` absent | Nodes 10/11 skip silently with a printed notice |
| `NEWSAPI_KEY` / `GNEWS_API_KEY` absent | `newsapi_gnews` node returns immediately without searching |
| Stage times out (900s) | Marked as `failed`; user can retry |
| LLM call fails (stages 2–4) | Stage marked failed |
| Token overflow | `_get_chunk_budget()` + `split_collection_items()` splits large prompts |
| Stage 4 editor produces small output | PDF endpoint falls back to `report_draft.md` automatically (1.5× threshold) |
| WeasyPrint rendering | CSS `word-break: break-word` on tables and `break-all` on code blocks prevents all known crash cases |
| Old fpdf2 crashes | Not applicable — fpdf2 removed; WeasyPrint used for all PDF generation |
| arXiv rate limits | `arxiv.Client` configured with `delay_seconds=1.0`, `num_retries=1` |
| DuckDuckGo rate limits | 1.0–1.5s sleep between company and topic queries |

---

## 10. Glossary

| Term | Definition |
|---|---|
| **Stage** | One of the 4 pipeline phases |
| **LangGraph StateGraph** | The 15-node directed graph that implements Stage 1 data collection; nodes are Python functions, state is a `TypedDict` |
| **Node** | One function in the LangGraph graph; self-contained, handles its own exceptions |
| **NewsCollectionState** | LangGraph state object passed between Stage 1 nodes: `date_from`, `date_to`, `topics`, `sources`, `custom_sources`, `collected_items`, `seen_keys`, `errors`, `topic_coverage`, `gap_fill_round`, `work_dir` |
| **Tier 1 (collection)** | cmbagent structured news tools — `broad_sweep`, `curated_sources`, `company_scrape`, `company_ddg_news`, `newsapi_gnews` |
| **Tier 2 (collection)** | Global topic-driven search — RSS feeds, arXiv, DuckDuckGo news, `web_surfer`, `perplexity`; works for any user-provided topic string |
| **company_ddg_news** | New Stage 1 node using `DDGS.news()` per core AI company — no API key, guarantees company coverage |
| **Prefix bucketing** | Semantic dedup optimization: groups items by their 2- and 3-word title prefixes so similarity is only computed within buckets, not across all pairs |
| **Phase class** | Python class implementing a stage's logic |
| **Shared state** | Accumulated outputs from all completed stages |
| **PATCH MODE** | Stage 4 editor behavior: copy all draft content verbatim, apply only corrections flagged by the critic — never rewrite from scratch |
| **Refinement chat** | Real-time LLM editing of stage content using diff patching |
| **Token chunking** | Splitting oversized prompts into safe-length chunks via `_get_chunk_budget()` + `split_collection_items()` |
| **WeasyPrint** | PDF rendering library used since June 2026; converts markdown → HTML+CSS → PDF; replaced fpdf2 |
| **Gap fill** | Stage 1 post-processing that re-searches under-covered topics (< 5 items); runs at most 2 rounds |
| **Semantic dedup** | Stage 1 post-processing that removes near-duplicate items using `difflib.SequenceMatcher` ratio > 0.82 |
| **Programmatic verification** | 7 deterministic post-LLM checks in Stage 4: URL accessibility, date range, placeholders, superlatives, synthesis text, truncation markers, references section |
