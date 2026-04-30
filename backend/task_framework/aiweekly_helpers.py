"""
Stage-specific helpers for the AI Weekly Report pipeline.

Stages:
  1 — Data Collection (no AI — calls news_tools APIs, deduplicates)
  2 — Content Curation (AI — one_shot researcher to deduplicate/validate/enrich)
  3 — Report Generation (AI — two-pass: analyst outlines → writer drafts report)
  4 — Quality Review (AI — two-pass: critic audits → editor polishes + verification)

Stage 1 reuses the collection logic from the existing collection_phase.
Stages 2-4 use one_shot(agent='researcher'), matching the Release Notes pattern.
"""

import os
import re
import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from backend.task_framework.utils import create_work_dir, extract_clean_markdown

logger = logging.getLogger(__name__)

from backend.task_framework.prompts.aiweekly.stages import STAGE_AGENTS


# ─── Default model assignments ───────────────────────────────────────────

def _get_stage_defaults(stage_num: int) -> dict:
    """Get stage defaults from model registry if available, otherwise use fallbacks."""
    try:
        from cmbagent.config.model_registry import get_model_registry
        return get_model_registry().get_stage_defaults("aiweekly", stage_num)
    except (ImportError, Exception):
        # Standalone fallback
        return {
            "researcher_model": "gpt-4o",
            "orchestration_model": "gpt-4o-mini",
            "formatter_model": "gpt-4o-mini",
        }


def _build_model_kwargs(stage_num: int, config_overrides: dict | None = None) -> dict:
    """Build model-related kwargs for one_shot() from registry + UI overrides.

    Merge order (highest wins):
      model_config.yaml globals < workflow "default" < stage-specific < UI config_overrides

    The UI may send a generic ``model`` key — maps to researcher_model for AI Weekly.
    """
    overrides = dict(config_overrides or {})
    if "model" in overrides:
        agent = STAGE_AGENTS[stage_num]
        overrides.setdefault(f"{agent}_model", overrides.pop("model"))

    cfg = {**_get_stage_defaults(stage_num), **overrides}
    return dict(
        researcher_model=cfg["researcher_model"],
        default_llm_model=cfg.get("orchestration_model", "gpt-4o-mini"),
        default_formatter_model=cfg.get("formatter_model", "gpt-4o-mini"),
    )


# ─── Style helpers ───────────────────────────────────────────────────────

_STYLE_RULES = {
    "concise": (
        "STYLE: CONCISE — Each item gets a brief overview (2-4 sentences, ~50-80 words). "
        "Focus on WHAT happened and WHO is involved. No deep analysis needed."
    ),
    "detailed": (
        "STYLE: DETAILED — Each item description must be ≥130 words. Include deep analysis, "
        "competitive context, business implications, and why it matters strategically."
    ),
    "technical": (
        "STYLE: TECHNICAL — Each item description must be ≥130 words with concrete metrics, "
        "implementation details, architecture specifics, and technical depth."
    ),
}


def get_style_rule(style: str) -> str:
    return _STYLE_RULES.get(style, _STYLE_RULES["concise"])


def get_expand_instruction(style: str) -> tuple:
    """Return (expand_instruction, word_rule) for the review stage."""
    if style == "concise":
        return (
            "EXPAND each title into a brief overview (2-4 sentences, ~50-80 words). "
            "Focus on WHAT happened and WHO is involved. Keep it short and direct.",
            "a brief overview (50-80 words)",
        )
    elif style == "technical":
        return (
            "EXPAND each title into a substantial technical paragraph (≥130 words) "
            "with concrete metrics, architecture details, and technical depth "
            "using the curated source data below.",
            "a substantive description (≥130 words)",
        )
    else:  # detailed
        return (
            "EXPAND each title into a substantial paragraph (≥130 words) covering "
            "what happened, why it matters, competitive context, business implications, "
            "and strategic impact using the curated source data below.",
            "a substantive description (≥130 words)",
        )


# ─── Code-wrapper stripping ──────────────────────────────────────────────

def _strip_code_wrapper(text: str) -> str:
    """Strip Python code wrapping from agent output."""
    import ast as _ast

    if not re.search(
        r'(?:^|\n)\s*(?:import os|content\s*=\s*["\']|with open\(|filepath\s*=)',
        text,
    ):
        return text

    py_fence = re.search(
        r"```[ \t]*(?:python)[ \t]*\r?\n(.*?)\r?\n[ \t]*```",
        text,
        flags=re.DOTALL,
    )
    code = py_fence.group(1) if py_fence else text

    _VAR_NAMES = {"content", "report", "text", "output", "markdown"}
    try:
        tree = _ast.parse(code)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Assign):
                for target in node.targets:
                    if isinstance(target, _ast.Name) and target.id in _VAR_NAMES:
                        if isinstance(node.value, _ast.Constant) and isinstance(node.value.value, str):
                            return node.value.value.strip()
                        # Handle concatenated string literals: ("part1" "part2" ...)
                        if isinstance(node.value, _ast.JoinedStr):
                            pass  # f-strings, skip
                        if isinstance(node.value, _ast.BinOp) and isinstance(node.value.op, _ast.Add):
                            parts = []
                            def _collect_str_parts(n):
                                if isinstance(n, _ast.Constant) and isinstance(n.value, str):
                                    parts.append(n.value)
                                elif isinstance(n, _ast.BinOp) and isinstance(n.op, _ast.Add):
                                    _collect_str_parts(n.left)
                                    _collect_str_parts(n.right)
                            _collect_str_parts(node.value)
                            if parts:
                                return "".join(parts).strip()
    except SyntaxError:
        pass

    for quote in ('"""', "'''"):
        pattern = (
            r'(?:content|report|text|output|markdown)\s*=\s*'
            + re.escape(quote)
            + r'(.*?)'
            + re.escape(quote)
        )
        m = re.search(pattern, code, flags=re.DOTALL)
        if m:
            return m.group(1).strip()

    # Handle repr()-style single/double quoted strings (may be very long).
    # Match from the assignment to the last occurrence of the closing quote
    # before a known boilerplate line (filename=, with open, etc.).
    for quote in ("'", '"'):
        # Greedy match up to the last quote before a boilerplate line
        pattern = (
            r"(?:content|report|text|output|markdown)\s*=\s*"
            + re.escape(quote)
            + r"(.*)"
            + re.escape(quote)
            + r"\s*\n"
            + r"(?:filename|filepath|path|print|with |os\.)"
        )
        m = re.search(pattern, code, flags=re.DOTALL)
        if m:
            val = m.group(1)
            val = val.replace("\\n", "\n").replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
            return val.strip()

    # Handle truncated repr() strings: content = '...<truncated>
    # Extract whatever is after `content = '` even if the closing quote is missing
    trunc_pattern = re.compile(
        r"(?:content|report|text|output|markdown)\s*=\s*(['\"])(.*)",
        re.DOTALL,
    )
    m = trunc_pattern.search(code)
    if m:
        quote_char = m.group(1)
        val = m.group(2)
        # Strip trailing boilerplate lines that leaked in
        boilerplate_start = re.search(
            r"\n\s*(?:filename|filepath|path|print|with |os\.|import |f\.write)",
            val,
        )
        if boilerplate_start:
            val = val[:boilerplate_start.start()]
        # Remove trailing unmatched quote if present
        val = val.rstrip(quote_char)
        val = val.replace("\\n", "\n").replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
        if len(val.strip()) > 200:  # Only use if substantial content was recovered
            return val.strip()

    _BOILERPLATE = re.compile(
        r"^\s*(?:import |from |content\s*=|report\s*=|filename\s*=|filepath\s*="
        r"|path\s*=|os\.|with open\(|f\.write|print\()",
    )
    lines = code.splitlines()
    kept = [ln for ln in lines if not _BOILERPLATE.match(ln)]
    if kept and len(kept) < len(lines):
        return "\n".join(kept).strip()

    return text


# ─── HTML comment stripping ──────────────────────────────────────────────

def _strip_html_comments(text: str) -> str:
    """Remove HTML comments like <!-- filename: ... --> from output."""
    text = re.sub(r'^[ \t]*<!--[^>]*-->[ \t]*\n?', '', text, flags=re.MULTILINE)
    return text.strip()


# ─── Truncation marker stripping ─────────────────────────────────────────

def _strip_truncation_markers(text: str) -> str:
    """Remove [content truncated: ...] markers injected by message limiting."""
    return re.sub(
        r'\n*\.\.\. \[content truncated: \d+ → \d+ chars\] \.\.\.\n*',
        '\n', text,
    ).strip()


# ─── Collection compaction ───────────────────────────────────────────────

def _compact_collection_for_prompt(raw_md: str) -> str:
    """Compress raw collection markdown — preserves title, source, date, full summary, and URL."""
    lines = raw_md.splitlines()
    header_lines: list[str] = []
    items: list[str] = []
    current_title = ""
    current_url = ""
    current_summary_parts: list[str] = []

    def _flush_item():
        nonlocal current_title, current_url, current_summary_parts
        if current_title:
            summary = " ".join(current_summary_parts).strip()
            entry = current_title
            if summary:
                entry += f"\n  {summary}"
            if current_url:
                entry += f"\n  Source: {current_url}"
            items.append(entry)
        current_title = ""
        current_url = ""
        current_summary_parts = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("**Date") or stripped.startswith("**Total") or stripped.startswith("**Errors"):
            header_lines.append(stripped)
            continue
        if stripped.startswith("- **"):
            _flush_item()
            current_title = stripped
            continue
        if stripped.startswith("[") and "](" in stripped:
            m = re.search(r'\]\(([^)]+)\)', stripped)
            if m:
                current_url = m.group(1)
            continue
        if stripped:
            current_summary_parts.append(stripped)

    _flush_item()

    return "\n".join(header_lines + [""] + items)


# ─── Collection chunking (Stage 2) ──────────────────────────────────────

# Target ~60K chars (~15K tokens) per chunk — fits comfortably in 128K+ context
# models while leaving room for system prompt + output.
_CHUNK_TARGET_CHARS = 60_000


def _get_chunk_budget(model: str = "gpt-4o") -> int:
    """Calculate chunk budget in chars based on model context window.

    Uses 50% of the model's context window (in chars) to leave room for
    system prompt, instructions, and output tokens.
    """
    from backend.task_framework.token_utils import get_model_limits
    max_ctx, _ = get_model_limits(model)
    # ~4 chars per token, use 50% of context for input data
    budget = int(max_ctx * 4 * 0.50)
    return max(budget, _CHUNK_TARGET_CHARS)


def split_collection_items(compact_md: str, target_chars: int = _CHUNK_TARGET_CHARS) -> list[str]:
    """Split compacted collection markdown into chunks for chunked curation.

    Handles multi-line items: each item starts with '- **' and includes
    all continuation lines (summary, Source: URL) until the next item.
    """
    if len(compact_md) <= target_chars:
        return [compact_md]

    lines = compact_md.splitlines()
    header: list[str] = []
    items: list[list[str]] = []
    current_item: list[str] = []

    for line in lines:
        if line.strip().startswith("- **"):
            if current_item:
                items.append(current_item)
            current_item = [line]
        elif current_item:
            current_item.append(line)
        elif not items:
            header.append(line)

    if current_item:
        items.append(current_item)

    if not items:
        return [compact_md]

    header_text = "\n".join(header).strip()
    header_overhead = len(header_text) + 50
    budget = target_chars - header_overhead

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_size = 0

    for item_lines in items:
        item_text = "\n".join(item_lines)
        item_size = len(item_text) + 1
        if current_size + item_size > budget and current_chunk:
            chunk_body = "\n".join(current_chunk)
            chunks.append(f"{header_text}\n\n{chunk_body}" if header_text else chunk_body)
            current_chunk = []
            current_size = 0
        current_chunk.append(item_text)
        current_size += item_size

    if current_chunk:
        chunk_body = "\n".join(current_chunk)
        chunks.append(f"{header_text}\n\n{chunk_body}" if header_text else chunk_body)

    logger.info("Split collection into %d chunks (from %d chars)", len(chunks), len(compact_md))
    return chunks


# ─── Curated items chunking (Stage 3) ───────────────────────────────────


def split_curated_items(curated_md: str, target_chars: int = _CHUNK_TARGET_CHARS) -> list[str]:
    """Split curated markdown into chunks that each fit within the message limit."""
    if len(curated_md) <= target_chars:
        return [curated_md]

    lines = curated_md.splitlines()
    header: list[str] = []
    items: list[list[str]] = []
    current_item: list[str] = []

    for line in lines:
        if line.strip().startswith("- **"):
            if current_item:
                items.append(current_item)
            current_item = [line]
        elif current_item:
            current_item.append(line)
        else:
            header.append(line)

    if current_item:
        items.append(current_item)

    if not items:
        return [curated_md]

    header_text = "\n".join(header).strip()
    header_overhead = len(header_text) + 50
    budget = target_chars - header_overhead

    chunks: list[str] = []
    current_chunk_lines: list[str] = []
    current_size = 0

    for item_lines in items:
        item_text = "\n".join(item_lines)
        item_size = len(item_text) + 1

        if current_size + item_size > budget and current_chunk_lines:
            chunk_body = "\n".join(current_chunk_lines)
            chunks.append(f"{header_text}\n\n{chunk_body}" if header_text else chunk_body)
            current_chunk_lines = []
            current_size = 0

        current_chunk_lines.append(item_text)
        current_size += item_size

    if current_chunk_lines:
        chunk_body = "\n".join(current_chunk_lines)
        chunks.append(f"{header_text}\n\n{chunk_body}" if header_text else chunk_body)

    logger.info("Split curated items into %d chunks (from %d chars)", len(chunks), len(curated_md))
    return chunks


def _compact_curated_for_review(curated_md: str) -> str:
    """Lightly compress curated items — preserves title, summary, and sources.

    Unlike the old version that stripped to one-line-per-item (causing data loss),
    this preserves the full summary text so downstream stages have enough context.
    Only removes blank lines and headers to save space.
    """
    lines = curated_md.splitlines()
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Skip empty lines and headers (already known to downstream prompts)
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        result.append(line)
    return "\n".join(result)


# ─── Result extraction ──────────────────────────────────────────────────

# ─── Chunked curation merge/dedup ────────────────────────────────────────

def merge_curated_chunks(partial_results: list[str]) -> str:
    """Merge partial curation outputs into a single deduplicated list.

    After running curation per chunk, this combines all results and removes
    duplicates (by normalized title + org). Preserves the FIRST occurrence's
    full text but merges source URLs from duplicates.
    """
    seen_titles: dict[str, int] = {}  # title_key → index in merged_items
    merged_items: list[str] = []
    current_item_lines: list[str] = []

    def _normalize_title(line: str) -> str:
        """Normalize title for dedup — use full title text (not truncated)."""
        # Remove markdown bold, strip org/date after first pipe
        normalized = re.sub(r'\*\*', '', line)
        # Keep text before the first pipe (the actual title)
        parts = normalized.split('|')
        return parts[0].strip().lower()

    def _extract_sources(lines: list[str]) -> list[str]:
        """Extract source URLs from item lines."""
        urls = []
        for ln in lines:
            if 'Sources:' in ln or 'Source:' in ln:
                urls.extend(re.findall(r'https?://[^\s,)]+', ln))
            elif re.match(r'\s*https?://', ln.strip()):
                urls.extend(re.findall(r'https?://[^\s,)]+', ln))
        return urls

    def _flush():
        nonlocal current_item_lines
        if current_item_lines:
            first_line = current_item_lines[0].strip()
            title_key = _normalize_title(first_line)
            if title_key in seen_titles:
                # Merge URLs from duplicate into existing item
                existing_idx = seen_titles[title_key]
                new_urls = _extract_sources(current_item_lines)
                if new_urls:
                    existing_text = merged_items[existing_idx]
                    existing_urls = set(re.findall(r'https?://[^\s,)]+', existing_text))
                    for url in new_urls:
                        if url not in existing_urls:
                            # Append new URL to Sources line
                            if 'Sources:' in existing_text:
                                existing_text = existing_text.rstrip() + f", {url}"
                            else:
                                existing_text += f"\n  Sources: {url}"
                            existing_urls.add(url)
                    merged_items[existing_idx] = existing_text
            else:
                seen_titles[title_key] = len(merged_items)
                merged_items.append("\n".join(current_item_lines))
        current_item_lines = []

    for partial in partial_results:
        for line in partial.splitlines():
            stripped = line.strip()
            if stripped.startswith("- **"):
                _flush()
                current_item_lines = [line]
            elif current_item_lines:
                current_item_lines.append(line)
            # Skip header lines between partials

    _flush()

    logger.info(
        "Merged %d partial curations → %d unique items (from %d total chars)",
        len(partial_results), len(merged_items),
        sum(len(p) for p in partial_results),
    )
    return "\n".join(merged_items)


# ─── Token-aware content fitting ─────────────────────────────────────────

def fit_content_to_context(
    content: str,
    model: str,
    reserved_tokens: int = 4000,
) -> tuple[str, bool]:
    """Ensure content fits within model context. Returns (content, was_truncated).

    If content exceeds model limits, truncates by removing items from the END
    (keeping newest-first ordering) rather than arbitrarily cutting mid-item.
    """
    from backend.task_framework.token_utils import count_tokens, get_model_limits

    max_ctx, _ = get_model_limits(model)
    available_tokens = max_ctx - reserved_tokens

    content_tokens = count_tokens(content, model)
    if content_tokens <= available_tokens:
        return content, False

    # Content too large — truncate by removing items from end
    lines = content.splitlines()
    items: list[list[str]] = []
    current: list[str] = []
    header_lines: list[str] = []

    for line in lines:
        if line.strip().startswith("- **"):
            if current:
                items.append(current)
            current = [line]
        elif current:
            current.append(line)
        else:
            header_lines.append(line)
    if current:
        items.append(current)

    # Binary search for how many items we can fit
    header_text = "\n".join(header_lines)
    header_tokens = count_tokens(header_text, model) if header_lines else 0
    budget = available_tokens - header_tokens - 100  # safety margin

    kept_items: list[str] = []
    running_tokens = 0
    for item_lines in items:
        item_text = "\n".join(item_lines)
        item_tokens = count_tokens(item_text, model)
        if running_tokens + item_tokens > budget:
            break
        kept_items.append(item_text)
        running_tokens += item_tokens

    truncation_note = f"\n\n<!-- NOTE: {len(items) - len(kept_items)} items omitted due to context limits -->"
    result = header_text + "\n\n" + "\n".join(kept_items) + truncation_note
    logger.warning(
        "Content truncated: %d→%d items to fit %s context (%d tokens available)",
        len(items), len(kept_items), model, available_tokens,
    )
    return result, True


def extract_stage_result(results: dict) -> str:
    """Extract the researcher's output from one_shot results."""
    chat_history = results.get("chat_history", [])

    # Prefer researcher (raw markdown) over researcher_response_formatter
    # (code-wrapped) to avoid unterminated-string-literal issues when
    # the formatter's repr()-encoded script is truncated by token limits.
    for agent_name in ("researcher", "researcher_response_formatter"):
        for msg in reversed(chat_history):
            if msg.get("name") == agent_name:
                content = msg.get("content", "")
                if content and content.strip():
                    content = _strip_code_wrapper(content)
                    content = extract_clean_markdown(content)
                    content = _strip_truncation_markers(content)
                    return _strip_html_comments(content)

    # Broad fallback
    best = ""
    for msg in chat_history:
        content = msg.get("content", "")
        if content and len(content) > len(best):
            best = content

    if best:
        logger.warning("AI Weekly extraction used broad fallback, length=%d", len(best))
        best = _strip_code_wrapper(best)
        best = extract_clean_markdown(best)
        best = _strip_truncation_markers(best)
        return _strip_html_comments(best)

    raise ValueError("No agent output found in chat history for AI Weekly stage")


def save_stage_file(content: str, work_dir: str, filename: str) -> str:
    """Write stage output to input_files/ and return file path."""
    input_dir = os.path.join(str(work_dir), "input_files")
    os.makedirs(input_dir, exist_ok=True)
    path = os.path.join(input_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("Saved AI Weekly stage file: %s (%d chars)", path, len(content))
    return path


# ═══════════════════════════════════════════════════════════════════════════
# Stage 1 — Data Collection (no AI)
# ═══════════════════════════════════════════════════════════════════════════

# Priority companies: always get extra web-search coverage
_PRIORITY_COMPANIES = [
    "openai", "google", "deepmind", "microsoft", "anthropic",
    "meta", "amazon", "huggingface",
    "nvidia", "intel", "amd", "apple",
    "bostondynamics",
    "google_quantum", "ibm", "quantinuum",
    "oracle",
    "samsung", "salesforce",
]


def run_data_collection(
    date_from: str,
    date_to: str,
    sources: list,
    work_dir: str,
    custom_sources: list | None = None,
) -> dict:
    """Run all data collection tools (non-LLM). Returns output_data dict."""
    from cmbagent.external_tools.news_tools import (
        announcements_noauth,
        curated_ai_sources_search,
        newsapi_search,
        gnews_search,
        multi_engine_web_search,
        scrape_official_news_pages,
    )

    all_items: List[Dict] = []
    seen_keys: set = set()
    errors: List[str] = []

    def _merge(items: List[Dict], source_cap: int = 0):
        added = 0
        for item in items:
            key = (
                (item.get("url") or "").strip().lower(),
                (item.get("title") or "").strip().lower()[:80],
            )
            if key not in seen_keys and key[0]:
                seen_keys.add(key)
                all_items.append(item)
                added += 1
                if source_cap and added >= source_cap:
                    break

    def _safe(fn, label, source_cap: int = 0, **kwargs):
        try:
            result = fn(**kwargs)
            items = result.get("items") or result.get("articles") or []
            print(f"[Data Collection] {label}: {len(items)} items")
            _merge(items, source_cap=source_cap)
        except Exception as e:
            errors.append(f"{label}: {e}")
            print(f"[Data Collection] {label}: ERROR {e}")

    print(f"[Data Collection] Starting collection for {date_from} to {date_to}")

    # Broad official sweep
    _safe(announcements_noauth, "Broad official sweep",
          query="", company="", from_date=date_from, to_date=date_to, limit=300)

    # Per-company official page scraping
    print("[Data Collection] Scraping official company news pages...")
    for company in _PRIORITY_COMPANIES:
        _safe(scrape_official_news_pages, f"Official/{company}",
              company=company, from_date=date_from, to_date=date_to, limit=15)

    # Curated AI sources
    _safe(curated_ai_sources_search, "Curated AI sources",
          query=f"AI news {date_from} to {date_to}", limit=40,
          from_date=date_from, to_date=date_to)

    # NewsAPI
    if "press-releases" in sources or "company-announcements" in sources:
        _safe(newsapi_search, "NewsAPI",
              query="artificial intelligence OR machine learning",
              from_date=date_from, to_date=date_to, page_size=100)

    # GNews
    _safe(gnews_search, "GNews",
          query="artificial intelligence OR machine learning",
          from_date=date_from, to_date=date_to, max_results=100)

    # Targeted web search for companies with few results
    companies_found: Dict[str, int] = {}
    for item in all_items:
        src = (item.get("source") or "").lower().strip()
        companies_found[src] = companies_found.get(src, 0) + 1

    for company in _PRIORITY_COMPANIES:
        if companies_found.get(company, 0) < 2:
            for query_variant in [
                f"{company} AI product launch announcement",
                f"{company} artificial intelligence release update",
            ]:
                _safe(multi_engine_web_search, f"Web/{company}",
                      query=query_variant,
                      max_results=5, from_date=date_from, to_date=date_to)

    # User-provided custom data sources (URLs, RSS feeds, web pages)
    if custom_sources:
        print(f"[Data Collection] Scraping {len(custom_sources)} custom data sources...")
        from cmbagent.external_tools.news_tools import (
            _direct_scrape_page_links,
            _fetch_rss_items,
        )
        from urllib.parse import urlparse

        for url in custom_sources:
            url = url.strip()
            if not url or not url.startswith("http"):
                continue
            domain = urlparse(url).netloc or "custom"
            label = domain.replace("www.", "")[:30]

            # Try RSS first (works for feed URLs)
            try:
                rss_items = _fetch_rss_items(url, label, date_from, date_to)
                if rss_items:
                    print(f"[Data Collection] Custom/{label} (RSS): {len(rss_items)} items")
                    _merge(rss_items)
                    continue
            except Exception:
                pass

            # Fall back to HTML page scraping
            try:
                page_items = _direct_scrape_page_links(url, label)
                print(f"[Data Collection] Custom/{label} (HTML): {len(page_items)} items")
                _merge(page_items)
            except Exception as e:
                errors.append(f"Custom/{label}: {e}")
                print(f"[Data Collection] Custom/{label}: ERROR {e}")

    print(f"[Data Collection] Total: {len(all_items)} unique items ({len(errors)} errors)")

    # Save raw collection
    collection_data = {
        "date_from": date_from,
        "date_to": date_to,
        "total_items": len(all_items),
        "items": all_items,
        "errors": errors,
    }

    out_dir = os.path.join(work_dir, "input_files")
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "collection.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(collection_data, f, indent=2, default=str)

    # Markdown summary
    summary_lines = [
        f"# Data Collection Summary",
        f"**Date Range:** {date_from} to {date_to}",
        f"**Total Items:** {len(all_items)}",
        f"**Errors:** {len(errors)}",
        "",
    ]
    for item in all_items:
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        source = item.get("source", "unknown")
        pub = (item.get("published_at") or "")[:10]
        desc = (item.get("summary") or "").strip()
        summary_lines.append(f"- **{title}** | {source} | {pub}")
        if desc:
            summary_lines.append(f"  {desc}")
        summary_lines.append(f"  [{url}]({url})")
        summary_lines.append("")

    summary = "\n".join(summary_lines)
    with open(os.path.join(out_dir, "collection.md"), "w", encoding="utf-8") as f:
        f.write(summary)

    return {
        "shared": {"raw_collection": summary},
        "artifacts": {"collection_json": json_path, "item_count": len(all_items)},
        "cost": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "chat_history": [],
    }


# ═══════════════════════════════════════════════════════════════════════════
# Stage 2 — Content Curation
# ═══════════════════════════════════════════════════════════════════════════

def build_curation_kwargs(
    raw_collection: str,
    date_from: str,
    date_to: str,
    topics: list,
    work_dir: str,
    api_keys: dict | None = None,
    config_overrides: dict | None = None,
    callbacks=None,
    *,
    _pre_compacted: bool = False,
) -> dict:
    """Build kwargs for one_shot() — content curation."""
    from backend.task_framework.prompts.aiweekly.stages import (
        curation_researcher_prompt,
    )

    sub_dir = create_work_dir(work_dir, "curation")

    compact = raw_collection if _pre_compacted else _compact_collection_for_prompt(raw_collection)

    task = curation_researcher_prompt.format(
        date_from=date_from,
        date_to=date_to,
        topics=", ".join(topics) if topics else "AI, ML",
        raw_collection=compact,
    )

    return dict(
        task=task,
        agent=STAGE_AGENTS[2],
        max_rounds=15,
        max_n_attempts=2,
        **_build_model_kwargs(2, config_overrides),
        work_dir=str(sub_dir),
        api_keys=api_keys,
        clear_work_dir=False,
        callbacks=callbacks,
    )


def build_curation_output(
    curated: str,
    shared_state: dict,
    file_path: str,
    chat_history: list,
) -> dict:
    return {
        "shared": {**shared_state, "curated_items": curated},
        "artifacts": {"curated.md": file_path},
        "chat_history": chat_history,
    }


def build_curation_merge_kwargs(
    partial_curations: list[str],
    date_from: str,
    date_to: str,
    topics: list,
    work_dir: str,
    api_keys: dict | None = None,
    config_overrides: dict | None = None,
    callbacks=None,
) -> dict:
    """Build kwargs for one_shot() — merge chunked curation results."""
    from backend.task_framework.prompts.aiweekly.stages import curation_merge_prompt
    from backend.task_framework.token_utils import count_tokens, get_model_limits

    sub_dir = create_work_dir(work_dir, "curation_merge")

    combined = "\n\n".join(
        f"### ── Part {i+1} of {len(partial_curations)} ──\n{part}"
        for i, part in enumerate(partial_curations)
    )

    # Check if combined partials fit in model context
    model = (config_overrides or {}).get("model", "gpt-4o")
    max_ctx, max_output = get_model_limits(model)
    input_budget = max_ctx - max_output - 1500

    task = curation_merge_prompt.format(
        date_from=date_from,
        date_to=date_to,
        topics=", ".join(topics) if topics else "AI, ML",
        num_parts=len(partial_curations),
        partial_curations=combined,
    )

    task_tokens = count_tokens(task, model)
    if task_tokens > input_budget:
        # Fit combined partials to context budget
        prompt_without_data = curation_merge_prompt.format(
            date_from=date_from,
            date_to=date_to,
            topics=", ".join(topics) if topics else "AI, ML",
            num_parts=len(partial_curations),
            partial_curations="",
        )
        overhead_tokens = count_tokens(prompt_without_data, model)
        data_budget = input_budget - overhead_tokens - 500
        combined, was_truncated = fit_content_to_context(
            combined, model, reserved_tokens=(max_ctx - data_budget),
        )
        if was_truncated:
            logger.warning(
                "Curation merge: combined partials truncated to fit context (%d tokens over)",
                task_tokens - input_budget,
            )
        task = curation_merge_prompt.format(
            date_from=date_from,
            date_to=date_to,
            topics=", ".join(topics) if topics else "AI, ML",
            num_parts=len(partial_curations),
            partial_curations=combined,
        )

    return dict(
        task=task,
        agent=STAGE_AGENTS[2],
        max_rounds=15,
        max_n_attempts=2,
        **_build_model_kwargs(2, config_overrides),
        work_dir=str(sub_dir),
        api_keys=api_keys,
        clear_work_dir=False,
        callbacks=callbacks,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Stage 3 — Report Generation (two-pass: analyst → writer)
# ═══════════════════════════════════════════════════════════════════════════

def build_generation_analysis_kwargs(
    curated_items: str,
    date_from: str,
    date_to: str,
    style: str,
    topics: list,
    work_dir: str,
    api_keys: dict | None = None,
    config_overrides: dict | None = None,
    callbacks=None,
) -> dict:
    """Build kwargs for one_shot() — Stage 3 Pass A: analyst outlines report."""
    from backend.task_framework.prompts.aiweekly.stages import (
        generation_analyst_prompt,
    )
    from backend.task_framework.token_utils import count_tokens, get_model_limits

    sub_dir = create_work_dir(work_dir, "generation_analysis")

    compact_curated = _compact_curated_for_review(curated_items)

    # Ensure curated items fit within model context for analyst
    model = (config_overrides or {}).get("model", "gpt-4o")
    max_ctx, max_output = get_model_limits(model)
    input_budget = max_ctx - max_output - 1500

    task = generation_analyst_prompt.format(
        date_from=date_from,
        date_to=date_to,
        style=style,
        topics=", ".join(topics) if topics else "AI, ML",
        curated_items=compact_curated,
    )

    task_tokens = count_tokens(task, model)
    if task_tokens > input_budget:
        # Fit curated items to budget
        prompt_without_curated = generation_analyst_prompt.format(
            date_from=date_from,
            date_to=date_to,
            style=style,
            topics=", ".join(topics) if topics else "AI, ML",
            curated_items="",
        )
        overhead_tokens = count_tokens(prompt_without_curated, model)
        curated_budget = input_budget - overhead_tokens - 500
        compact_curated, was_truncated = fit_content_to_context(
            compact_curated, model, reserved_tokens=(max_ctx - curated_budget),
        )
        if was_truncated:
            logger.warning(
                "Stage 3 analyst: curated_items truncated to fit context (%d tokens over budget)",
                task_tokens - input_budget,
            )
        task = generation_analyst_prompt.format(
            date_from=date_from,
            date_to=date_to,
            style=style,
            topics=", ".join(topics) if topics else "AI, ML",
            curated_items=compact_curated,
        )

    return dict(
        task=task,
        agent=STAGE_AGENTS[3],
        max_rounds=15,
        max_n_attempts=2,
        **_build_model_kwargs(3, config_overrides),
        work_dir=str(sub_dir),
        api_keys=api_keys,
        clear_work_dir=False,
        callbacks=callbacks,
    )


def build_generation_kwargs(
    curated_items: str,
    date_from: str,
    date_to: str,
    style: str,
    topics: list,
    work_dir: str,
    report_outline: str = "",
    api_keys: dict | None = None,
    config_overrides: dict | None = None,
    callbacks=None,
) -> dict:
    """Build kwargs for one_shot() — Stage 3 Pass B: write report from outline."""
    from backend.task_framework.prompts.aiweekly.stages import (
        generation_writer_prompt,
    )

    sub_dir = create_work_dir(work_dir, "generation")

    task = generation_writer_prompt.format(
        date_from=date_from,
        date_to=date_to,
        style=style,
        topics=", ".join(topics) if topics else "AI, ML",
        style_rule=get_style_rule(style),
        report_outline=report_outline,
        curated_items=curated_items,
    )

    return dict(
        task=task,
        agent=STAGE_AGENTS[3],
        max_rounds=15,
        max_n_attempts=2,
        **_build_model_kwargs(3, config_overrides),
        work_dir=str(sub_dir),
        api_keys=api_keys,
        clear_work_dir=False,
        callbacks=callbacks,
    )


def build_generation_output(
    draft: str,
    shared_state: dict,
    file_path: str,
    chat_history: list,
) -> dict:
    return {
        "shared": {**shared_state, "draft_report": draft},
        "artifacts": {"report_draft.md": file_path},
        "chat_history": chat_history,
    }


def build_merge_kwargs(
    partial_reports: list[str],
    date_from: str,
    date_to: str,
    style: str,
    topics: list,
    work_dir: str,
    api_keys: dict | None = None,
    config_overrides: dict | None = None,
    callbacks=None,
) -> dict:
    """Build kwargs for one_shot() — merge partial reports into one."""
    from backend.task_framework.prompts.aiweekly.stages import merge_partials_prompt

    sub_dir = create_work_dir(work_dir, "generation_merge")

    combined = "\n\n".join(
        f"### ── Part {i+1} of {len(partial_reports)} ──\n{part}"
        for i, part in enumerate(partial_reports)
    )

    task = merge_partials_prompt.format(
        date_from=date_from,
        date_to=date_to,
        style=style,
        topics=", ".join(topics) if topics else "AI, ML",
        num_parts=len(partial_reports),
        style_rule=get_style_rule(style),
        partial_reports=combined,
    )

    return dict(
        task=task,
        agent=STAGE_AGENTS[3],
        max_rounds=15,
        max_n_attempts=2,
        **_build_model_kwargs(3, config_overrides),
        work_dir=str(sub_dir),
        api_keys=api_keys,
        clear_work_dir=False,
        callbacks=callbacks,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Stage 4 — Quality Review (two-pass: critic → editor)
# ═══════════════════════════════════════════════════════════════════════════

def build_review_critique_kwargs(
    draft_report: str,
    curated_items: str,
    date_from: str,
    date_to: str,
    style: str,
    work_dir: str,
    api_keys: dict | None = None,
    config_overrides: dict | None = None,
    callbacks=None,
) -> dict:
    """Build kwargs for one_shot() — Stage 4 Pass A: critical audit."""
    from backend.task_framework.prompts.aiweekly.stages import (
        review_critic_prompt,
    )
    from backend.task_framework.token_utils import count_tokens, get_model_limits

    sub_dir = create_work_dir(work_dir, "review_critique")

    _expand_instruction, word_rule = get_expand_instruction(style)

    compact_curated = _compact_curated_for_review(curated_items)

    # Ensure combined prompt fits within model context
    model = (config_overrides or {}).get("model", "gpt-4o")
    max_ctx, max_output = get_model_limits(model)
    # Reserve tokens for: system prompt (~500), output, safety margin
    input_budget = max_ctx - max_output - 1000

    # Build prompt and check fit
    task = review_critic_prompt.format(
        date_from=date_from,
        date_to=date_to,
        style=style,
        word_rule=word_rule,
        draft_report=draft_report,
        curated_items=compact_curated,
    )

    task_tokens = count_tokens(task, model)
    if task_tokens > input_budget:
        # Curated items are the largest part — fit them to remaining budget
        prompt_without_curated = review_critic_prompt.format(
            date_from=date_from,
            date_to=date_to,
            style=style,
            word_rule=word_rule,
            draft_report=draft_report,
            curated_items="",
        )
        overhead_tokens = count_tokens(prompt_without_curated, model)
        curated_budget = input_budget - overhead_tokens - 500
        compact_curated, was_truncated = fit_content_to_context(
            compact_curated, model, reserved_tokens=(max_ctx - curated_budget),
        )
        if was_truncated:
            logger.warning(
                "Stage 4 critic: curated_items truncated to fit context (%d→%d tokens)",
                task_tokens, count_tokens(compact_curated, model) + overhead_tokens,
            )
        task = review_critic_prompt.format(
            date_from=date_from,
            date_to=date_to,
            style=style,
            word_rule=word_rule,
            draft_report=draft_report,
            curated_items=compact_curated,
        )

    return dict(
        task=task,
        agent=STAGE_AGENTS[4],
        max_rounds=15,
        max_n_attempts=2,
        **_build_model_kwargs(4, config_overrides),
        work_dir=str(sub_dir),
        api_keys=api_keys,
        clear_work_dir=False,
        callbacks=callbacks,
    )


def build_review_kwargs(
    draft_report: str,
    curated_items: str,
    date_from: str,
    date_to: str,
    style: str,
    work_dir: str,
    review_critique: str = "",
    api_keys: dict | None = None,
    config_overrides: dict | None = None,
    callbacks=None,
) -> dict:
    """Build kwargs for one_shot() — Stage 4 Pass B: apply corrections + polish."""
    from backend.task_framework.prompts.aiweekly.stages import (
        review_editor_prompt,
    )
    from backend.task_framework.token_utils import count_tokens, get_model_limits

    sub_dir = create_work_dir(work_dir, "review")

    expand_instruction, word_rule = get_expand_instruction(style)

    compact_curated = _compact_curated_for_review(curated_items)

    # Ensure combined prompt fits within model context
    model = (config_overrides or {}).get("model", "gpt-4o")
    max_ctx, max_output = get_model_limits(model)
    input_budget = max_ctx - max_output - 1000

    task = review_editor_prompt.format(
        date_from=date_from,
        date_to=date_to,
        style=style,
        expand_instruction=expand_instruction,
        word_rule=word_rule,
        style_rule=get_style_rule(style),
        review_critique=review_critique,
        draft_report=draft_report,
        curated_items=compact_curated,
    )

    task_tokens = count_tokens(task, model)
    if task_tokens > input_budget:
        # Fit curated_items to remaining budget (draft_report + critique are essential)
        prompt_without_curated = review_editor_prompt.format(
            date_from=date_from,
            date_to=date_to,
            style=style,
            expand_instruction=expand_instruction,
            word_rule=word_rule,
            style_rule=get_style_rule(style),
            review_critique=review_critique,
            draft_report=draft_report,
            curated_items="",
        )
        overhead_tokens = count_tokens(prompt_without_curated, model)
        curated_budget = input_budget - overhead_tokens - 500
        compact_curated, was_truncated = fit_content_to_context(
            compact_curated, model, reserved_tokens=(max_ctx - curated_budget),
        )
        if was_truncated:
            logger.warning(
                "Stage 4 editor: curated_items truncated to fit context (%d→%d tokens)",
                task_tokens, count_tokens(compact_curated, model) + overhead_tokens,
            )
        task = review_editor_prompt.format(
            date_from=date_from,
            date_to=date_to,
            style=style,
            expand_instruction=expand_instruction,
            word_rule=word_rule,
            style_rule=get_style_rule(style),
            review_critique=review_critique,
            draft_report=draft_report,
            curated_items=compact_curated,
        )

    return dict(
        task=task,
        agent=STAGE_AGENTS[4],
        max_rounds=15,
        max_n_attempts=2,
        **_build_model_kwargs(4, config_overrides),
        work_dir=str(sub_dir),
        api_keys=api_keys,
        clear_work_dir=False,
        callbacks=callbacks,
    )


def build_review_output(
    final_report: str,
    shared_state: dict,
    file_path: str,
    chat_history: list,
    verification_notes: list | None = None,
) -> dict:
    artifacts = {"report_final.md": file_path}
    if verification_notes:
        artifacts["verification_notes"] = verification_notes
    return {
        "shared": {**shared_state, "final_report": final_report},
        "artifacts": artifacts,
        "chat_history": chat_history,
    }


# ─── Programmatic verification (post-LLM) ───────────────────────────────

def programmatic_verification(
    content: str,
    date_from: str,
    date_to: str,
) -> tuple:
    """Run deterministic checks on the final report. Returns (cleaned_content, notes)."""
    notes = []

    # 1. Verify URLs
    urls = re.findall(r'https?://[^\s\)>\]"\']+', content)
    unique_urls = list(dict.fromkeys(urls))
    if unique_urls:
        try:
            from cmbagent.external_tools.news_tools import verify_reference_links
            print(f"[Quality Review] Verifying {len(unique_urls)} unique URLs...")
            result = verify_reference_links(unique_urls[:50])
            inaccessible = [
                r["url"] for r in result.get("results", [])
                if not r.get("accessible")
            ]
            if inaccessible:
                notes.append(f"Link verification: {len(inaccessible)}/{len(unique_urls)} URLs inaccessible")
                for bad_url in inaccessible:
                    content = content.replace(bad_url, f"{bad_url} <!-- [LINK UNVERIFIED] -->")
            else:
                notes.append(f"Link verification: all {len(unique_urls)} URLs accessible")
        except Exception as e:
            notes.append(f"Link verification skipped: {e}")

    # 2. Date range check
    if date_from and date_to:
        all_dates = re.findall(r'\b(\d{4}-\d{2}-\d{2})\b', content)
        out_of_range = [d for d in all_dates if (d < date_from or d > date_to) and d not in (date_from, date_to)]
        if out_of_range:
            unique_oor = list(dict.fromkeys(out_of_range))
            notes.append(f"Date verification: {len(unique_oor)} out-of-range dates: {', '.join(unique_oor)}")
            for d in unique_oor:
                content = content.replace(d, f"{d} <!-- [DATE OUT OF RANGE] -->")

    # 3. Placeholder URLs
    for pat in [r'https?://example\.com', r'https?://placeholder\.', r'\[Insert', r'\[TBD\]', r'\[URL\]']:
        matches = re.findall(pat, content, re.IGNORECASE)
        if matches:
            notes.append(f"Placeholder detected: {len(matches)} instances of '{pat}'")

    # 4. Unattributed superlatives
    superlatives = re.findall(
        r'\b(breakthrough|revolutionary|state-of-the-art|game-changing|best-in-class|unprecedented|groundbreaking)\b',
        content, re.IGNORECASE,
    )
    if superlatives:
        notes.append(f"Superlative check: {len(superlatives)} unattributed claims")

    # 5. Synthesis/no-source text removal
    for pat in [r'\(Synthesis of [^)]*\)', r'\(no single source[^)]*\)', r'Source:\s*\(Synthesis[^)]*\)',
                r'Source:\s*N/?A', r'Source:\s*None']:
        matches = re.findall(pat, content, re.IGNORECASE)
        if matches:
            notes.append(f"Synthesis text removed: {len(matches)} instances")
            content = re.sub(pat, '', content, flags=re.IGNORECASE)

    # 6. Truncation marker removal (safety net)
    if '[content truncated:' in content:
        content = _strip_truncation_markers(content)
        notes.append("Removed truncation markers from report")

    # 7. References section check
    if '## References' not in content and '## references' not in content.lower():
        notes.append("Missing References section — report may lack source citations")

    return content, notes
