# AI Weekly Report Generator — Complete Feature Guide

> **Standalone AI Weekly Report Generator**
>
> A comprehensive guide covering the AI Weekly Report Generator: fundamentals, workflow stages, task lifecycle, AI techniques, and architecture.

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
| Raw Collection | Markdown | All items collected from RSS feeds, APIs, and web search |
| Curated Items | Markdown | Deduplicated, validated, and enriched master list |
| Draft Report | Markdown | 4-section report: Executive Summary, Key Highlights, Trends, Quick Reference |
| **Final Report** | Markdown | **Publication-ready report** polished for quality |
| Cost Summary | Markdown | Per-stage token usage and USD cost breakdown |

### 1.3 Key Design Principles

| Principle | Implementation |
|---|---|
| **Single-Page App** | All navigation via React state — only component swaps, no page reloads |
| **Phase-Based Execution** | 4 discrete stages, each using `one_shot(agent='researcher')` via cmbagent |
| **Hybrid Architecture** | Stage 1 = direct Python tool calls (no LLM). Stages 2–4 = one_shot LLM pipeline |
| **Human-in-the-loop** | Users review, edit, and refine output between every stage |
| **Token-safe** | Token-aware chunking via `_get_chunk_budget()` + `split_collection_items()` |
| **Dynamic model** | Model resolved from config; user can override per-stage via UI |
| **Multi-pass** | Stage 2-3: chunk + merge. Stage 4: critic + editor |
| **Agent enforcement** | Monkey-patch prevents cmbagent control agent from switching to engineer |
| **Auto-completing** | Task status transitions to `"completed"` when all stages finish |
| **Cost-transparent** | Per-stage cost tracking with aggregated USD totals |
| **Resumable** | Tasks persist as JSON files and can resume after browser reload |

### 1.4 Technology Stack

| Layer | Technology |
|---|---|
| **Backend** | Python, FastAPI, asyncio |
| **Execution Engine** | `cmbagent.one_shot(agent='researcher')` + helper functions |
| **Data Collection** | `news_tools.py` — RSS feeds, NewsAPI, GNews, web search |
| **Frontend** | React, TypeScript, Next.js (SPA) |
| **Real-time** | REST polling (console output) |
| **Storage** | JSON files (`task.json` per task in `~/Desktop/cmbdir/aiweekly/`) |

---

## 2. All Stages in the Pipeline

### Stage 1: Data Collection (Non-LLM)

**Function:** `helpers.run_data_collection()`

Runs all data collection tools directly in Python — no LLM involved:

| Step | Tool | Description |
|------|------|-------------|
| A | `announcements_noauth(limit=300)` | Broad official news page sweep |
| B | `scrape_official_news_pages(company=X)` × 19 | Direct HTML scraping + RSS per company |
| C | `curated_ai_sources_search(limit=40)` | 26 curated AI news sources |
| D | `newsapi_search()` | NewsAPI (if `NEWSAPI_KEY` set) |
| E | `gnews_search()` | Google News (if `GNEWS_API_KEY` set) |
| F | `multi_engine_web_search()` | DDG → Bing → Yahoo → Brave fallback |

**Output:** `raw_collection` — JSON + markdown summary.

### Stage 2: Content Curation (LLM)

**Function:** `helpers.build_curation_kwargs()` + `build_curation_merge_kwargs()`

Token-aware chunking splits collection into safe-size chunks. Each chunk is curated via `one_shot(agent='researcher')`. Multi-chunk results are merged via LLM merge pass.

Removes duplicates, validates dates, checks credibility, ensures diversity, groups by organization.

**Output:** `curated_items`.

### Stage 3: Report Generation (LLM)

**Function:** `helpers.build_generation_analysis_kwargs()` + `build_generation_kwargs()` + `build_generation_merge_kwargs()`

Two-pass architecture:
1. **Analysis pass:** Structural analysis of curated items
2. **Generation pass:** Per-chunk report writing (uses analysis as guidance)
3. **Merge pass:** If multi-chunk, LLM merges partial reports into unified draft

Writes the full 4-section report from curated items:
1. Executive Summary
2. Key Highlights & Developments
3. Trends & Strategic Implications
4. Quick Reference Table

**Output:** `draft_report`.

### Stage 4: Quality Review (LLM)

**Function:** `helpers.build_review_critique_kwargs()` + `helpers.build_review_kwargs()`

Two-pass architecture:
1. **Critic pass:** Editorial audit that identifies specific corrections needed
2. **Editor pass:** Applies all corrections + final polish for publication readiness

After the LLM passes, runs **programmatic verification** — 5 deterministic checks:
1. URL verification — marks inaccessible URLs
2. Date verification — flags out-of-range dates
3. Placeholder detection
4. Superlative detection
5. Synthesis text removal

**Output:** `final_report`.

---

## 3. Task Flow — From App Open to Final Report

```
[User opens app → default view: AIWeeklySetupPanel]
    │
    └── Setup: selects date range, topics, sources, style, model settings
         ↓ POST /api/aiweekly/create + POST /{id}/stages/1/execute
[Step 1: Data Collection runs (console output polls via REST)]
    ↓ Auto-advances to Step 2 on completion
[Step 2: AIWeeklyReviewPanel — edit/preview curated items + refinement chat]
    ↓ Click "Next" → auto-executes Stage 3
[Step 3: AIWeeklyReviewPanel — edit/preview report draft + refinement chat]
    ↓ Click "Next" → auto-executes Stage 4
[Step 4: AIWeeklyReportPanel — final report preview + download artifacts]
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
| 4 | `AIWeeklyReportPanel` | Success banner, report preview, artifact downloads |

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
| `collection.json` | Stage 1: structured JSON |
| `collection.md` | Stage 1: markdown summary |
| `curated.md` | Stage 2 output |
| `report_draft.md` | Stage 3 output |
| `report_final.md` | Stage 4 output |
| `cost_summary.md` | Auto-generated cost breakdown |

---

## 5. AI Techniques Used

| Technique | Where |
|---|---|
| **Multi-source aggregation** | Stage 1 — RSS, APIs, web search across 35+ feeds |
| **Token-aware chunking** | Stages 2–4 — `_get_chunk_budget()` + `split_collection_items()` |
| **Multi-pass LLM** | Stage 2-3: chunk + merge. Stage 4: critic + editor |
| **Agent enforcement** | Monkey-patch forces `researcher` agent (prevents `engineer` code gen) |
| **Progressive context** | Each stage receives shared state from all prior stages |
| **Refinement chat** | Real-time LLM refinement on any editable stage |
| **Deduplication** | Python exact-match (Stage 1) + LLM semantic dedup (Stage 2) |

---

## 6. Architecture Deep Dive

### Phase Class Hierarchy

```
cmbagent.one_shot(agent='researcher')
  └── CMBAgent.solve (patched to enforce researcher)
       └── control agent → researcher agent → output
```

Helper functions in `backend/task_framework/aiweekly_helpers.py`:
- `build_curation_kwargs()` / `build_curation_merge_kwargs()`
- `build_generation_analysis_kwargs()` / `build_generation_kwargs()` / `build_generation_merge_kwargs()`
- `build_review_critique_kwargs()` / `build_review_kwargs()`
    └── AIWeeklyReviewPhase
```

### Shared State Flow

```
Stage 1: raw_collection → Stage 2: curated_items → Stage 3: draft_report → Stage 4: final_report
```

### Backend Router

`backend/routers/aiweekly.py` — 13 endpoints, prefix `/api/aiweekly`.

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
  "message": "Content refined successfully"
}
```

### GET `/api/aiweekly/recent`

Lists incomplete tasks for resume. Returns up to 10 tasks ordered by `started_at` descending.

### POST `/api/aiweekly/{task_id}/stop`

Stops a running task. Cancels background tasks, marks stages as `failed`.

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

### Model Selection — UI to Backend Flow

1. **UI:** Setup panel shows model dropdowns (Primary, Review, Specialist)
2. **Hook:** `executeStage()` copies model selections into `config_overrides`
3. **API:** `POST /{id}/stages/{N}/execute` accepts `{ config_overrides }`
4. **Backend:** Extracts overrides with fallback to defaults
5. **Phase:** Instantiated with the resolved config

---

## 9. Error Handling & Troubleshooting

| Scenario | Behavior |
|---|---|
| Tool call fails in Stage 1 | Error logged, continues to next tool |
| Stage times out (900s) | Marked as `failed`, user can retry |
| LLM call fails | Stage marked failed |
| Token overflow | `chunk_prompt_if_needed` splits large prompts |
| No API keys for NewsAPI/GNews | Those steps skipped silently |

---

## 10. Glossary

| Term | Definition |
|---|---|
| **Stage** | One of the 4 pipeline phases |
| **Phase class** | Python class implementing a stage's logic |
| **Shared state** | Accumulated outputs from all completed stages |
| **Refinement chat** | Real-time LLM editing of stage content |
| **Token chunking** | Splitting oversized prompts into safe-length chunks |
| **Specialist** | Secondary LLM agent that reviews primary output |
