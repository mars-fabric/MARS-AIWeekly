# CLAUDE.md — MARS AI Weekly

## Project Overview

**AI Weekly** is a 4-stage LangGraph + cmbagent pipeline that auto-generates a newsletter-style report on AI developments.

- **Backend**: FastAPI on port 8000 — `backend/routers/aiweekly.py`
- **Frontend**: Next.js on port 3000 — `mars-ui/components/aiweekly/`
- **Pipeline stages**:
  1. Data Collection — `backend/task_framework/news_collection_graph.py`
  2. Content Curation — cmbagent researcher
  3. Report Generation — cmbagent researcher → `report_draft.md`
  4. Quality Review — cmbagent researcher → `report_final.md`
- **Output files** per task live in `~/Desktop/cmbdir/aiweekly/{task_id[:8]}/input_files/`

---

## RSS / News Collection Rules

**File**: `backend/task_framework/news_collection_graph.py`

- `_GLOBAL_RSS_FEEDS` is a hardcoded list of RSS URLs that **always run** regardless of what source checkboxes the user selects in the UI. Do NOT gate this behind `if "curated-ai-websites" not in sources`. The `rss_feeds_node` must be unconditional.
- **Do not add arxiv links** to the hardcoded list — they were removed intentionally.
- **Do not add xai or mistral** entries to the `_news_tools._OFFICIAL_NEWS_PAGES.update()` block. Only cohere, perplexity, and similar non-mainstream sources belong there.
- **Custom URLs entered by the user in the UI always run** — they are not restricted by the hardcoded exclusions above. If a user enters an arxiv, xai, or mistral URL as a custom source, it must be fetched and included. Custom URLs are user intent and must not be filtered.
- URLs in `_GLOBAL_RSS_FEEDS` the user has confirmed they want:
  - `https://blogs.nvidia.com/blog/category/ai/` (added, was missing)
  - Standard feeds for OpenAI, Anthropic, Google, Meta, Microsoft, AWS, Hugging Face, DeepMind, etc.

---

## UI — Setup Panel Defaults

**File**: `mars-ui/components/aiweekly/AIWeeklySetupPanel.tsx`

- Default selected sources: `[]` — no sources selected by default
- `canSubmit` must NOT require `sources.length > 0` — sources are optional since RSS feeds always run anyway.
- Topics are required (`topics.length > 0` is still needed for `canSubmit`).

---

## Key Files

| File | Purpose |
|------|---------|
| `backend/task_framework/news_collection_graph.py` | Stage 1 data collection, RSS feeds, web search |
| `backend/task_framework/newsletter_renderer.py` | HTML newsletter renderer |
| `backend/routers/aiweekly.py` | All API endpoints, stage execution, file downloads |
| `mars-ui/components/aiweekly/AIWeeklySetupPanel.tsx` | Stage 1 config UI (dates, topics, sources, style) |
| `mars-ui/components/aiweekly/AIWeeklyReportPanel.tsx` | Stage 4 report view, artifact downloads |
| `mars-ui/hooks/useAIWeeklyTask.ts` | React hook — task state, stage execution |
| `headerimage.png` | Infosys SenseNext banner — embedded in HTML newsletter, do not delete |

---

## General Coding Rules

- No features beyond what was asked.
- Surgical changes only — don't touch adjacent code.
- Match existing style.
- No speculative abstractions.
- Remove imports/variables made unused by YOUR changes only.
