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

## Newsletter HTML Feature (PENDING — needs implementation)

The user wants Stage 3 and Stage 4 to also generate an HTML newsletter alongside the existing `.md` and PDF outputs. This was implemented in commit `1959146` ("add design template") which was reverted by the user. It needs to be re-implemented cleanly.

### What to build

1. **`backend/task_framework/newsletter_renderer.py`** — Pure Python renderer, no extra LLM call.
   - Parses the Stage 3/4 markdown to extract articles from `## Key Highlights` and themes from `## Trends`.
   - Assigns articles to theme-based sections via keyword overlap scoring.
   - Generates an email-table HTML document matching the SenseNext AI Weekly Digest format.

2. **Inject rendering in `backend/routers/aiweekly.py`** — after Stage 3 and Stage 4 complete, call the renderer and save two files:
   - `report_draft_newsletter.html` (after Stage 3)
   - `report_final_newsletter.html` (after Stage 4)
   - Wrap in `try/except` so render failures never block the pipeline.

3. **UI access in `mars-ui/components/aiweekly/AIWeeklyReportPanel.tsx`**:
   - Add "View Newsletter" and "Download HTML" buttons at the top action bar pointing to `report_final_newsletter.html`.
   - Add both HTML files to the Generated Artifacts list with "Preview" (iframe modal), "Open" (new tab, `?inline=true`), and "Download HTML" buttons.

4. **Backend download endpoint** — add `inline: bool = False` to the `GET /{task_id}/download/{filename}` endpoint. When `inline=True`, serve `FileResponse` without a `filename` parameter so the browser renders HTML instead of downloading.

### HTML format requirements

- Email-table layout (nested `<table>` cells), `max-width: 600px`, centred.
- Banner image at the top: `headerimage.png` (lives at repo root `/home/ravi.khapra/Desktop/GitClones/MARS-AIWeekly/headerimage.png`). **Must be embedded as a base64 data URI** so the HTML is self-contained. Never delete this file.
- Date line ("28th Sep 2026") below the banner.
- Sections named dynamically from the AI-generated Trends section (uppercase, grey, small caps style).
- Each article: `<h2>` title, justified body paragraph, `<hr>` divider between articles within a section.
- **Source links must be the original collected URL for that article** — do not use any URL generated or guessed by the LLM. The only acceptable URL for an article is the one that was actually fetched in Stage 1 and carried through `collection.md` → `curated.md`.
  - The Stage 3 prompt must instruct the LLM to copy the exact source URL from the curated input for each article it writes about. No URL synthesis, no homepage links, no guessing.
  - If the original URL for an article is not available (was not collected or not passed through), show no link at all. A missing link is better than a wrong one.

### Parsing rules (avoid past bugs)

- Split articles only on **top-level bullet lines** — regex `\n(?=[-*]\s+\*\*)` with NO leading whitespace before `[-*]`. Indented sub-bullets are NOT new articles.
- **Deduplicate by normalized title** — same title under different date headers (`### YYYY-MM-DD`) should appear only once.
- Strip all `[text](url)` markdown from body text before rendering.
- Only include articles that have both a non-empty title AND non-empty body.

---

## Key Files

| File | Purpose |
|------|---------|
| `backend/task_framework/news_collection_graph.py` | Stage 1 data collection, RSS feeds, web search |
| `backend/task_framework/newsletter_renderer.py` | HTML newsletter renderer (PENDING re-implementation) |
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
