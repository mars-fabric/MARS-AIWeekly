# AIWeekly — Multi-Agent + LangGraph + Global News Collection
# Plan → Implementation Status (Updated June 2026)

> This document was originally the design plan. It has been updated to show
> implementation status: what was designed vs. what was actually built.
> Each item is marked ✅ DONE, ⚠️ PARTIAL, or ❌ NOT IMPLEMENTED.

---

## PART A — ALL 59 AGENTS IN MARS-CMBAGENT

mars-cmbagent v1.1.5 contains **59 agents** across 13 categories.
Agents are invoked via `cmbagent.one_shot(agent='agent_name', task='...')`.

---

### Category 1: Orchestration (5 agents)

| Agent Key | Role | Useful for AIWeekly? |
|---|---|---|
| `planner` | Creates multi-step plans from a task description | Yes — wrap full 4-stage pipeline in a plan |
| `plan_reviewer` | Critiques and improves a plan | Yes — review the collection/curation plan before running |
| `control` | Executes a plan step-by-step, records status after each step | Yes — drive Stages 2–4 sequentially with state tracking |
| `control_starter` | Initiates the control workflow | Yes — entry point for full pipeline execution |
| `copilot_control` | Intelligently routes tasks to the right agent based on complexity | Yes — ad-hoc routing for user queries about the report |

---

### Category 2: Research & Analysis (4 agents)

| Agent Key | Role | Useful for AIWeekly? |
|---|---|---|
| `researcher` | Generates reasoning, discussion, academic-style markdown; does NOT run code | ✅ Already used for Stages 2, 3, 4 — keep as-is |
| `researcher_executor` | Saves researcher output to disk | Internal — auto-called with researcher |
| `summarizer` | Summarizes documents: extracts title, authors, abstract, key findings | ✅ New: Stage 2 pre-pass to compress large collections |
| `session_summarizer` | Summarizes the entire workflow session | Optional: generate an executive log at pipeline end |

---

### Category 3: Web & Search (3 agents) ← MOST IMPORTANT FOR AIWEEKLY

| Agent Key | Role | Useful for AIWeekly? |
|---|---|---|
| `web_surfer` | **Autonomous web browser** — finds, visits, and extracts information from real web pages | ✅ NEW Stage 1: global topic-specific news not in cmbagent tools |
| `perplexity` | Scientific literature search using Perplexity; focuses on arXiv papers | ✅ NEW Stage 1: AI research paper coverage for the date window |
| `retrieve_assistant` | RAG document retrieval from indexed files | Optional: retrieve from past AIWeekly reports for comparison |

---

### Category 4: Engineering / Code Execution (7 agents)

| Agent Key | Role | Useful for AIWeekly? |
|---|---|---|
| `engineer` | Generates Python code for data processing, plots, statistics | Optional: generate data analysis scripts |
| `engineer_nest` | Nested chat coordinator for engineer | Internal |
| `engineer_response_formatter` | Validates and formats code output, fixes syntax errors | Internal |
| `executor` | Executes Python code blocks in a sandbox | Optional: run data processing scripts |
| `executor_bash` | Executes bash commands | Optional: install packages, file ops |
| `executor_response_formatter` | Processes and transfers execution results | Internal |
| `installer` | Manages pip installs | Optional: install missing dependencies |

---

### Category 5: Ideation (6 agents)

| Agent Key | Role | Useful for AIWeekly? |
|---|---|---|
| `idea_maker` | Generates research project ideas | ❌ Not relevant (designed for cosmology research) |
| `idea_maker_nest` | Nested chat for idea handling | ❌ Not relevant |
| `idea_maker_response_formatter` | Formats idea output | ❌ Not relevant |
| `idea_hater` | Critiques and stress-tests ideas | ❌ Not relevant |
| `idea_hater_response_formatter` | Formats critique output | ❌ Not relevant |
| `idea_saver` | Persists ideas to disk | ❌ Not relevant |

---

### Category 6: Task Management (2 agents)

| Agent Key | Role | Useful for AIWeekly? |
|---|---|---|
| `task_improver` | Refines and improves task descriptions | Optional: improve user-provided topic/date inputs before Stage 1 |
| `task_recorder` | Persists improved task definition | Internal — used with task_improver |

---

### Category 7: Review & Recording (2 agents)

| Agent Key | Role | Useful for AIWeekly? |
|---|---|---|
| `review_recorder` | Records review recommendations | Internal — used with plan_reviewer |
| `reviewer_response_formatter` | Formats review output, removes spurious emojis | Internal |

---

### Category 8: Visualization (2 agents)

| Agent Key | Role | Useful for AIWeekly? |
|---|---|---|
| `plot_judge` | Analyzes plot quality using Vision Language Model | ❌ Not relevant |
| `plot_debugger` | Provides plot debugging assistance | ❌ Not relevant |

---

### Category 9: Keyword Extraction (3 agents)

| Agent Key | Role | Useful for AIWeekly? |
|---|---|---|
| `list_keywords_finder` | Extracts relevant keywords from a provided list | ✅ Optional: extract topic-specific search keywords from user's topic list |
| `aaai_keywords_finder` | Extracts keywords from AAAI-2025 keyword list | ❌ Not relevant |
| `aas_keyword_finder` | Extracts keywords from AAS paper keyword list | ❌ Not relevant |

---

### Category 10: Formatters (12 agents)

All formatter agents are **internal helpers** automatically used by their primary agents.
They should NOT be called directly in AIWeekly code.

`planner_response_formatter`, `engineer_response_formatter`, `executor_response_formatter`,
`researcher_response_formatter`, `summarizer_response_formatter`, `reviewer_response_formatter`,
`idea_maker_response_formatter`, `idea_hater_response_formatter`, `rag_software_formatter`,
`camb_response_formatter`, `classy_response_formatter`, `classy_sz_response_formatter`

---

### Category 11: Domain RAG Agents (10 agents)

These agents are specific to the cosmology domain and are **not relevant for AIWeekly**.

`camb_agent` (CAMB package), `camels_agent` (CAMELS simulations), `classy_agent` (CLASS package),
`classy_sz_agent` (CLASS-SZ ML solver), `cobaya_agent` (Cobaya inference), `cosmocnc_agent`,
`getdist_agent` (posterior analysis), `planck_agent` (Planck mission), `act_agent` (ACT telescope),
`memory_agent` (past task retrieval)

---

### Category 12: Context Agents (2 agents)

`camb_context`, `classy_context` — Cosmology domain RAG context. **Not relevant for AIWeekly.**

---

### Category 13: Utility (1 agent)

| Agent Key | Role | Useful for AIWeekly? |
|---|---|---|
| `terminator` | Ends a workflow session cleanly | Optional: clean shutdown of agent sessions |

---

## PART B — AGENTS SELECTED FOR AIWEEKLY

### Planned (7 agents selected from 59)

| Agent | Stage | Role in AIWeekly | Status |
|---|---|---|---|
| `web_surfer` | Stage 1 | Autonomous global web search for topic-specific news | ✅ DONE — gated on BING_API_KEY |
| `perplexity` | Stage 1 | arXiv research paper discovery for date window | ✅ DONE — gated on PERPLEXITY_API_KEY |
| `summarizer` | Stage 2 pre-pass | Compress 3,000+ raw items before curation | ⚠️ PARTIAL — logic implemented, needs testing with cmbagent summarizer |
| `researcher` | Stages 2, 3, 4 | Curation, generation (analyst + writer), review (critic + editor) — already in use | ✅ DONE — unchanged |
| `list_keywords_finder` | Stage 3 (optional) | Extract topic keywords to improve generation themes | ❌ NOT IMPLEMENTED |
| `task_improver` | Pre-Stage 1 (optional) | Refine user-provided topics/date range before collection | ❌ NOT IMPLEMENTED |
| `planner` + `control` | Full pipeline (optional) | Structured plan-driven pipeline execution | ❌ NOT IMPLEMENTED |

**Note on gating:** The plan called for `web_surfer` and `perplexity` to run unconditionally.
The implementation gates each behind its respective API key (`BING_API_KEY`, `PERPLEXITY_API_KEY`)
so the pipeline degrades gracefully when keys are absent.

---

## PART C — MULTI-AGENT PIPELINE ARCHITECTURE

### Original Plan

```
[Optional Pre-Stage]
  task_improver → refine user-provided topics + date range

Stage 1: DATA COLLECTION (LangGraph StateGraph)
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Node 1:  resolve_companies   → build dynamic company list           │
  │ Node 2:  broad_sweep         → cmbagent: announcements_noauth()     │
  │ Node 3:  company_scrape      → cmbagent: scrape_official_news_pages │
  │ Node 4:  curated_sources     → cmbagent: curated_ai_sources_search  │
  │ Node 5:  newsapi_gnews       → conditional on API keys              │
  │ Node 6:  rss_feeds           → feedparser: 20+ global RSS feeds     │
  │ Node 7:  custom_sources      → user-provided URLs + RSS             │
  │ Node 8:  arxiv_search        → arxiv.Client().results() directly    │
  │ Node 9:  ddg_web_search      → LangChain DuckDuckGoSearchRun        │
  │ Node 10: web_surfer_agent    → cmbagent one_shot('web_surfer')  NEW │
  │ Node 11: perplexity_agent    → cmbagent one_shot('perplexity')  NEW │
  │ Node 12: gap_fill            → re-search under-covered topics       │
  │ Node 13: date_validate       → strict date range filtering          │
  │ Node 14: semantic_dedup      → difflib similarity > 0.82            │
  │ Node 15: build_output        → writes collection.json + .md         │
  └─────────────────────────────────────────────────────────────────────┘
         ↓
Stage 2: CURATION
  [NEW] summarizer pre-pass → compress if collection > 200K chars
  researcher               → deduplicate, validate, enrich (existing)
         ↓
Stage 3: GENERATION
  researcher → analyst pass: outline + themes (existing)
  researcher → writer pass: full report (existing)
         ↓
Stage 4: QUALITY REVIEW
  researcher       → critic pass (existing)
  researcher       → editor pass (existing)
  Programmatic     → URL check, date range, placeholder detect (existing)
```

### Actual Implementation (June 2026) — `backend/task_framework/news_collection_graph.py`

```
Stage 1: DATA COLLECTION — LangGraph StateGraph, 15 nodes  ✅ DONE

  Node 1:  broad_sweep          ✅  cmbagent announcements_noauth()
  Node 2:  curated_sources      ✅  cmbagent curated_ai_sources_search() per topic
                                    (order differs from plan — no resolve_companies node)
  Node 3:  company_scrape       ✅  cmbagent scrape_official_news_pages() for 15 companies
  Node 4:  company_ddg_news     ✅  NEW (not in plan) — DDGS.news() per company
                                    Companies: openai, nvidia, google, meta, microsoft,
                                    anthropic, deepmind, apple, huggingface, amazon,
                                    ibm, mistral, xai, deepseek, cohere — no API key needed
  Node 5:  newsapi_gnews        ✅  NewsAPI + GNews (requires API keys)
  Node 6:  rss_feeds            ✅  26 RSS feeds (plan had 20; +6 added: NVIDIA, Meta AI,
                                    Microsoft AI, DeepMind, Apple ML, Mistral, AWS ML,
                                    IBM Research)
  Node 7:  custom_sources       ✅  user-provided URLs/RSS
  Node 8:  topic_arxiv_search   ✅  arxiv.Client() direct, 25 papers/topic
  Node 9:  topic_web_search     ✅  DDGS.news() structured output
                                    (plan specified DuckDuckGoSearchRun text blob — upgraded)
  Node 10: web_surfer_agent     ✅  cmbagent one_shot(agent='web_surfer')
                                    GATED on BING_API_KEY (plan: unconditional)
  Node 11: perplexity_agent     ✅  cmbagent one_shot(agent='perplexity')
                                    GATED on PERPLEXITY_API_KEY (plan: unconditional)
  Node 12: gap_fill             ✅  re-search topics with <5 items, max 2 rounds
                                    (plan: max 3 rounds)
  Node 13: date_validate        ✅  strict date range filter
  Node 14: semantic_dedup       ✅  difflib ratio > 0.82
  Node 15: build_output         ✅  writes collection.json + collection.md
                                    (implicit END node)

Stage 2: CURATION
  summarizer pre-pass           ⚠️  Logic present: triggers when collection > 200K chars.
                                    Needs testing with cmbagent summarizer agent.
                                    Currently falls through to direct researcher curation.
  researcher (chunked)          ✅  Chunking + merge for large collections

Stage 3: GENERATION
  analyst pass (researcher)     ✅  report_outline via analyst prompt
  writer pass (researcher)      ✅  report_draft via writer prompt
  merge pass                    ✅  merges partial reports for multi-chunk collections

Stage 4: QUALITY REVIEW         ✅  PATCH MODE added (not in original plan)
  critic pass (researcher)      ✅  identifies corrections list
  editor pass (researcher)      ✅  patches only flagged items (PATCH MODE)
  programmatic verification     ✅  URL/date/placeholder checks
```

### Key Architecture Differences: Plan vs. Implementation

| Item | Plan | Implemented |
|---|---|---|
| Node 1 | `resolve_companies` (dynamic list builder) | Eliminated — company list is hardcoded in `company_ddg_news` |
| Node 4 | Not in plan | `company_ddg_news` added — DDGS.news() per company |
| Node 9 | `ddg_web_search` via `DuckDuckGoSearchRun` (text blob) | `topic_web_search` via `DDGS.news()` (structured output) |
| RSS feeds | 20 feeds | 26 feeds |
| `web_surfer` gating | Unconditional | Gated on `BING_API_KEY` |
| `perplexity` gating | Unconditional | Gated on `PERPLEXITY_API_KEY` |
| `gap_fill` max rounds | 3 | 2 |
| Stage 4 mode | Full rewrite by editor | PATCH MODE — copy all highlights unless flagged by critic |
| PDF generation | fpdf2 write_html() | WeasyPrint 69.0 (markdown → HTML+CSS → PDF) |

---

## PART D — LANGGRAPH DESIGN (Technical Detail)

### Why LangGraph?

LangGraph is a graph execution framework built on top of LangChain. It provides:
- **Shared state** that flows through all nodes — one `collected_items` list built up incrementally
- **Sequential execution** with clear node dependencies
- **Conditional edges** — gap_fill can loop back if coverage is insufficient
- **Error isolation** — each node's errors are captured without stopping the full pipeline
- **Extensibility** — add/remove/reorder nodes without restructuring the code

### State Object (TypedDict) — As Implemented

```python
class NewsCollectionState(TypedDict):
    date_from: str                    # "2025-05-28"
    date_to: str                      # "2025-06-04"
    topics: List[str]                 # ["llm", "robotics"]
    sources: List[str]                # user-selected source categories
    custom_sources: Optional[List[str]]    # user-provided URLs/RSS feeds
    companies: List[str]              # resolved from topics dynamically
    collected_items: List[Dict]       # growing list of news items
    seen_keys: List[str]              # dedup keys: "title_lower:domain"
    errors: List[str]                 # non-fatal errors per node
    company_coverage: Dict[str, int]  # items per company
    gap_fill_round: int               # current gap-fill iteration (max 2)
    work_dir: str                     # output directory
```

Each item in `collected_items` has shape:
```python
{
    "title": "GPT-5 Released with Extended Context",
    "url": "https://openai.com/blog/gpt-5",
    "summary": "OpenAI released GPT-5 with 2M token context...",
    "source": "openai",              # or "rss", "arxiv", "web_surfer", etc.
    "published_at": "2025-05-30"     # YYYY-MM-DD or "" if unknown
}
```

### LangGraph Graph Topology — As Implemented

```
broad_sweep
      ↓
curated_sources
      ↓
company_scrape
      ↓
company_ddg_news  ← NEW (not in plan): DDGS.news() per company, no API key
      ↓
newsapi_gnews
      ↓
rss_feeds
      ↓
custom_sources
      ↓
topic_arxiv_search
      ↓
topic_web_search  ← uses DDGS.news() structured output (not DuckDuckGoSearchRun)
      ↓
web_surfer_agent  ← cmbagent.one_shot(agent='web_surfer'), gated on BING_API_KEY
      ↓
perplexity_agent  ← cmbagent.one_shot(agent='perplexity'), gated on PERPLEXITY_API_KEY
      ↓
gap_fill  ←────────── loops back here if any topic has <5 items (max 2 rounds)
      ↓ (if OK)
date_validate
      ↓
semantic_dedup
      ↓
build_output  (END)
```

### Tools Used in Stage 1

| Tool | Source | Purpose | API Key? |
|---|---|---|---|
| `DDGS.news()` | `duckduckgo_search` package | Per-company news + topic web search | None — free |
| `arxiv.Client()` | `arxiv` package (direct) | arXiv papers by topic + date range | None — free |
| `feedparser.parse(url)` | `feedparser` package | Parse any RSS/Atom feed | None — free |
| `newsapi_search()` | NewsAPI | General news | `NEWSAPI_KEY` |
| `gnews_search()` | GNews | Google News | `GNEWS_KEY` |
| `cmbagent.one_shot('web_surfer')` | cmbagent | Autonomous web browsing | `BING_API_KEY` |
| `cmbagent.one_shot('perplexity')` | cmbagent | Academic/arXiv literature | `PERPLEXITY_API_KEY` |

**Note:** The original plan listed `DuckDuckGoSearchRun` from `langchain_community.tools`. The
implementation uses `DDGS.news()` from the `duckduckgo_search` package directly. This returns
structured dicts (title, url, body, date) rather than a raw text blob, enabling proper item
parsing.

---

## PART E — WEB_SURFER AGENT (Stage 1, Node 10) — ✅ IMPLEMENTED

### What web_surfer does

The `web_surfer` agent autonomously browses the web. It:
1. Formulates search queries based on the task
2. Opens real web pages (not just search snippets)
3. Extracts article titles, URLs, and summaries
4. Returns structured markdown

**Gating:** Only runs when `BING_API_KEY` is set in environment. Returns state unchanged if key absent.

### How we call it in Stage 1

```python
def web_surfer_agent_node(state: NewsCollectionState) -> NewsCollectionState:
    """Node 10: Use web_surfer agent for global topic-specific news discovery."""
    try:
        from cmbagent import one_shot
    except ImportError:
        return state  # gracefully skip if unavailable

    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])

    for topic in state["topics"]:
        task = (
            f"Search the web for major AI news, product announcements, and releases about "
            f"'{topic}' published between {state['date_from']} and {state['date_to']}. "
            f"For each item found, return:\n"
            f"- Title\n- URL\n- One-sentence summary\n- Publication date\n\n"
            f"Focus on global sources: tech blogs, company blogs, news sites, research labs."
        )
        try:
            result = one_shot(agent='web_surfer', task=task)
            # Parse the agent's markdown response into structured items
            items = _parse_agent_markdown_to_items(result, source="web_surfer")
            collected, seen = _merge_items(items, collected, seen)
            print(f"[Collection] web_surfer/{topic}: {len(items)} items")
        except Exception as exc:
            errors.append(f"web_surfer/{topic}: {exc}")

    return {**state, "collected_items": collected, "seen_keys": seen, "errors": errors}
```

---

## PART F — PERPLEXITY AGENT (Stage 1, Node 11) — ✅ IMPLEMENTED

### What perplexity does

The `perplexity` agent searches academic literature, primarily arXiv. It returns:
- Paper titles, arXiv IDs
- Author lists
- Abstract summaries
- Publication dates

**Gating:** Only runs when `PERPLEXITY_API_KEY` is set in environment.

### How we call it in Stage 1

```python
def perplexity_agent_node(state: NewsCollectionState) -> NewsCollectionState:
    """Node 11: Use perplexity agent for academic paper coverage."""
    try:
        from cmbagent import one_shot
    except ImportError:
        return state

    task = (
        f"Find the most important AI research papers published on arXiv "
        f"between {state['date_from']} and {state['date_to']} covering: "
        f"{', '.join(state['topics'])}.\n\n"
        f"For each paper return:\n"
        f"- Title\n- arXiv URL (https://arxiv.org/abs/XXXX.XXXXX)\n"
        f"- Authors\n- Two-sentence abstract summary\n"
        f"Focus on papers with significant practical impact."
    )
    try:
        result = one_shot(agent='perplexity', task=task)
        items = _parse_agent_markdown_to_items(result, source="perplexity")
        collected, seen = _merge_items(items, state["collected_items"], state["seen_keys"])
        print(f"[Collection] perplexity: {len(items)} papers")
    except Exception as exc:
        errors = list(state["errors"]) + [f"perplexity: {exc}"]
        return {**state, "errors": errors}

    return {**state, "collected_items": collected, "seen_keys": seen}
```

---

## PART G — SUMMARIZER AGENT (Stage 2 Pre-pass) — ⚠️ PARTIAL

### Problem it solves

After Stage 1, the collection often has 3,000+ items (~700K chars of text). Sending all of
this directly to the `researcher` curation agent risks hitting token limits and degrades
quality (model gets overwhelmed by volume).

### Solution: summarizer pre-pass

```python
def run_stage2_curation(collected_md: str, date_from: str, date_to: str, topics: list, ...):
    from cmbagent import one_shot

    # If collection is large, use summarizer agent to pre-compress it
    if len(collected_md) > 200_000:
        item_count = collected_md.count("**[")  # rough count
        compress_task = (
            f"You are given {item_count} raw AI news items collected for a weekly report "
            f"covering {', '.join(topics)} from {date_from} to {date_to}.\n\n"
            f"Your job:\n"
            f"1. Remove clear duplicates (same story from multiple sources)\n"
            f"2. Remove items clearly outside the topics: {', '.join(topics)}\n"
            f"3. Remove very low-quality items (no URL, no content, marketing fluff)\n"
            f"4. Keep the most important and interesting items\n"
            f"5. Return the condensed list in the same format as input.\n\n"
            f"Target: reduce to the top 500 most relevant items.\n\n"
            + collected_md
        )
        collected_md = one_shot(agent='summarizer', task=compress_task)
        print(f"[Stage 2] Summarizer compressed collection to {len(collected_md)} chars")

    # Now run existing researcher curation on the compressed collection
    return one_shot(agent='researcher', task=curation_prompt + "\n\n" + collected_md, ...)
```

**Implementation status:** The 200K char threshold and logic are in place. The `summarizer`
agent call itself needs end-to-end testing — the current pipeline falls through to the
researcher directly for all collection sizes.

---

## PART H — STAGE 4 PATCH MODE — ✅ IMPLEMENTED (NEW — not in original plan)

### Problem with original approach

The original plan had the editor agent do a full rewrite of the report. In practice this caused
the output token limit to be hit — `report_final.md` was truncated to ~17K chars from a 210K
char draft.

### Patch Mode solution

Instead of rewriting, the editor only patches items flagged by the critic:

```
Critic pass:   identifies a corrections list (specific items to fix)
Editor pass:   "copy all existing highlights exactly unless flagged by critic"
               → patches only the flagged items, preserves full content
```

This ensures `report_final.md` retains the full length of `report_draft.md`.

### Smart fallback

WeasyPrint PDF generation uses `report_draft.md` when `report_final.md` is less than 1.5×
smaller than the draft — detecting truncation and falling back to the fuller source.

---

## PART I — PDF GENERATION — ✅ IMPLEMENTED (WeasyPrint, not fpdf2)

### Original plan

`fpdf2` write_html() was the specified PDF library.

### What was built

**WeasyPrint 69.0** — markdown → HTML+CSS → PDF.

| Issue with fpdf2 | WeasyPrint solution |
|---|---|
| Crashed on malformed HTML tables | No crash — handles complex tables |
| Failed on long URLs | Handles long URLs gracefully |
| Unicode issues | Full Unicode support |

WeasyPrint was already listed in `Requirements.txt`. The switch required no new dependency.

---

## PART J — EXPECTED ITEM COUNTS (As Implemented)

Example: 7-day window, topics = ["llm", "robotics"], all sources enabled

| Source Node | Tool/Method | Estimated Items |
|---|---|---|
| broad_sweep | `announcements_noauth()` | ~30 |
| curated_sources | `curated_ai_sources_search()` | ~350 |
| company_scrape | `scrape_official_news_pages()` × 15 companies | ~300 |
| company_ddg_news | `DDGS.news()` × 15 companies (NEW) | ~200 |
| newsapi_gnews | `newsapi_search()` (if key set) | ~100 |
| rss_feeds | feedparser × 26 feeds | ~650 |
| topic_arxiv_search | `arxiv.Client().results()` | ~150 |
| topic_web_search | `DDGS.news()` structured output | ~80 |
| web_surfer_agent | `cmbagent one_shot('web_surfer')` | ~100 |
| perplexity_agent | `cmbagent one_shot('perplexity')` | ~50 |
| gap_fill | re-search topics with <5 items | ~30 |
| **Total before dedup** | | **~2,040** |
| **After semantic dedup (0.82)** | | **~1,200–1,400 unique** |

vs old approach (no agent search, caps applied): ~500 items

---

## PART K — WHAT CHANGED FROM THE ORIGINAL PLAN

### Changes to Stage 1 nodes

1. **`resolve_companies` node eliminated** — the company list is hardcoded directly in `company_ddg_news_node`. No dynamic resolver needed.
2. **`company_ddg_news` node added (Node 4)** — not in original plan. Fills coverage gap when cmbagent tools fail or rate-limit. Uses `DDGS.news()` per company with no API key.
3. **Node ordering changed** — plan had `broad_sweep → company_scrape → curated_sources`. Implementation runs `broad_sweep → curated_sources → company_scrape → company_ddg_news`.
4. **`topic_web_search` (Node 9) upgraded** — plan specified `DuckDuckGoSearchRun` from `langchain_community.tools` which returns a text blob. Implementation uses `DDGS.news()` from `duckduckgo_search` which returns structured dicts — better for item parsing.
5. **RSS feed count increased from 20 to 26** — added NVIDIA, Meta AI, Microsoft AI, DeepMind, Apple ML, Mistral, AWS ML, IBM Research feeds.
6. **`web_surfer` gated on `BING_API_KEY`** — plan said unconditional.
7. **`perplexity` gated on `PERPLEXITY_API_KEY`** — plan said unconditional.
8. **`gap_fill` max rounds reduced from 3 to 2** — 3 rounds was too slow in practice.

### Changes to Stage 4

9. **PATCH MODE added** — original plan had editor do a full rewrite. Full rewrite hit output token limit and truncated `report_final.md` to ~17K chars. Patch mode fixes this by having the editor copy all content and patch only flagged items.

### Changes to PDF generation

10. **WeasyPrint 69.0 replaces fpdf2** — fpdf2's `write_html()` crashed on malformed HTML tables, long URLs, and Unicode. WeasyPrint handles all of these. It was already in `Requirements.txt`.

### Agents not yet implemented

11. **`summarizer` pre-pass** — logic is in place but needs end-to-end testing.
12. **`list_keywords_finder`** — not implemented.
13. **`plan_reviewer`** — not implemented.
14. **`task_improver`** — not implemented.

---

## PART L — FILES MODIFIED (Implementation Record)

| File | Change Made |
|---|---|
| `backend/task_framework/news_collection_graph.py` | 15-node LangGraph pipeline; added `company_ddg_news_node`, `topic_web_search_node` (DDGS), `web_surfer_agent_node`, `perplexity_agent_node`, `gap_fill_node`, `semantic_dedup_node` |
| `backend/task_framework/aiweekly_helpers.py` | PATCH MODE in Stage 4 (critic + editor passes); summarizer pre-pass stub in Stage 2; chunking + merge logic |
| `backend/routers/aiweekly.py` | WeasyPrint PDF generation replacing fpdf2; smart fallback to report_draft when report_final is <1.5× smaller |

---

## PART M — WHAT IS NOT CHANGING

The following are working correctly and were NOT modified:

- Stage 3 report generation (researcher agent, analyst + writer passes)
- Programmatic URL verification in Stage 4
- Token-aware chunking and merging logic
- UI model selector
- LangGraph graph structure (nodes only added, not restructured)

---

## PART N — HOW TO VERIFY

```bash
# 1. Check graph has correct nodes
cd /home/ravi.khapra/Desktop/GitClones/MARS-AIWeekly
python -c "
from backend.task_framework.news_collection_graph import build_news_graph
g = build_news_graph()
g.get_graph().print_ascii()
"
# Should show all 15 nodes including company_ddg_news, web_surfer_agent, perplexity_agent

# 2. Quick collection test
python -c "
from backend.task_framework.news_collection_graph import run_news_collection_graph
state = run_news_collection_graph(
    date_from='2025-05-28', date_to='2025-06-04',
    topics=['llm'], sources=['official', 'rss']
)
print('Total items:', len(state['collected_items']))
sources = {}
for item in state['collected_items']:
    s = item.get('source','unknown')
    sources[s] = sources.get(s, 0) + 1
for s, c in sorted(sources.items(), key=lambda x: -x[1]):
    print(f'  {s}: {c}')
print('Errors:', state['errors'])
"
# company_ddg_news, web_surfer (if BING_API_KEY set), perplexity (if key set) should appear

# 3. Full Stage 1 + Stage 2 test (checks summarizer pre-pass)
# Run via the FastAPI endpoint: POST /api/aiweekly/{task_id}/stages/1/execute
# Then POST /api/aiweekly/{task_id}/stages/2/execute
# Watch logs for "[Stage 2] Summarizer compressed collection..."
```

---

## Summary — Plan vs. Implementation Status

| Item | Planned | Status |
|---|---|---|
| 15-node LangGraph pipeline | Yes | ✅ DONE |
| `resolve_companies` node | Yes | ❌ Eliminated — hardcoded in company_ddg_news |
| `broad_sweep` node | Yes | ✅ DONE |
| `curated_sources` node | Yes | ✅ DONE |
| `company_scrape` node | Yes | ✅ DONE |
| `company_ddg_news` node | No (new) | ✅ DONE — added to fill coverage gap |
| `newsapi_gnews` node | Yes | ✅ DONE |
| `rss_feeds` node (26 feeds) | 20 feeds planned | ✅ DONE (26 feeds) |
| `custom_sources` node | Yes | ✅ DONE |
| `topic_arxiv_search` node | Yes | ✅ DONE |
| `topic_web_search` via DDGS.news() | DuckDuckGoSearchRun planned | ✅ DONE (upgraded) |
| `web_surfer_agent` (gated BING_API_KEY) | Unconditional | ✅ DONE (gated) |
| `perplexity_agent` (gated PERPLEXITY_API_KEY) | Unconditional | ✅ DONE (gated) |
| `gap_fill` (max 2 rounds) | 3 rounds planned | ✅ DONE (2 rounds) |
| `date_validate` node | Yes | ✅ DONE |
| `semantic_dedup` node | Yes | ✅ DONE |
| `build_output` node | Yes | ✅ DONE |
| Stage 2 `summarizer` pre-pass | Yes | ⚠️ PARTIAL — needs testing |
| Stage 2 researcher (chunked + merge) | Yes | ✅ DONE |
| Stage 3 analyst + writer passes | Yes | ✅ DONE |
| Stage 4 PATCH MODE | No (new) | ✅ DONE — prevents truncation |
| Stage 4 critic + editor passes | Yes | ✅ DONE |
| Stage 4 programmatic verification | Yes | ✅ DONE |
| WeasyPrint PDF (replaces fpdf2) | fpdf2 planned | ✅ DONE |
| `list_keywords_finder` in Stage 3 | Optional | ❌ NOT IMPLEMENTED |
| `plan_reviewer` | Optional | ❌ NOT IMPLEMENTED |
| `task_improver` pre-stage | Optional | ❌ NOT IMPLEMENTED |
