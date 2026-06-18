"""
LangGraph-powered news collection pipeline for AIWeekly Stage 1.

Two-tier architecture
─────────────────────
Tier 1 — Structured (cmbagent news tools)
  Reliable, structured coverage of major AI companies and curated AI sources.
  Nodes: broad_sweep, curated_sources, company_scrape, newsapi_gnews

Tier 2 — Global topic search (topic-driven, no hard-coded companies/links)
  Searches the whole internet for the user's actual topic strings.
  Works for ANY topic: "healthcare AI", "autonomous driving", "video generation", etc.
  Nodes: rss_feeds, custom_sources, topic_arxiv_search, topic_web_search,
         web_surfer_agent, perplexity_agent

Post-processing
  gap_fill → date_validate → semantic_dedup → END

Key design principles
─────────────────────
- No hard-coded topic→company mappings driving the search
- All Tier-2 nodes build queries directly from state["topics"]
- cmbagent news tools are the structured baseline; agents fill global gaps
- Every node is self-contained and handles its own exceptions gracefully
- semantic_dedup uses prefix bucketing for O(n) average-case performance
"""

from __future__ import annotations

import logging
import os
import re
import time
from calendar import timegm
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

# Fixed set of core AI companies always scraped via cmbagent (Tier 1).
# Kept small and stable — these are the companies whose blogs reliably publish
# AI news worth including regardless of topic.
_CORE_AI_COMPANIES: List[str] = [
    "openai", "anthropic", "google", "meta", "microsoft",
    "nvidia", "huggingface", "amazon", "deepmind", "apple",
    "ibm", "mistral", "xai", "deepseek", "cohere",
]

# Global AI news RSS feeds — official company and research sources only.
# Third-party news aggregators (TechCrunch, VentureBeat, The Verge, etc.) are
# intentionally excluded so all items link back to primary/official sources.
_GLOBAL_RSS_FEEDS: List[str] = [
    # arXiv research categories (official academic preprint server)
    "https://arxiv.org/rss/cs.AI",
    "https://arxiv.org/rss/cs.LG",
    "https://arxiv.org/rss/cs.CL",
    "https://arxiv.org/rss/cs.RO",
    "https://arxiv.org/rss/cs.CV",
    # Official company AI/research blogs
    "https://openai.com/blog/rss.xml",
    "https://www.anthropic.com/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://blog.research.google/feeds/posts/default",
    "https://blog.google/technology/ai/rss/",
    "https://deepmind.google/blog/rss.xml",
    "https://ai.meta.com/blog/rss/",
    "https://blogs.microsoft.com/ai/feed/",
    "https://blogs.nvidia.com/feed/",
    "https://machinelearning.apple.com/rss.xml",
    "https://aws.amazon.com/blogs/machine-learning/feed/",
    "https://mistral.ai/news/rss.xml",
    "https://research.ibm.com/blog/rss",
    "https://www.databricks.com/feed",
    "https://cohere.com/blog/rss",
    "https://stability.ai/blog/rss.xml",
    # Official company newsroom / press release feeds
    "https://www.apple.com/newsroom/rss-feed.rss",
    "https://press.aboutamazon.com/rss/rss-news-releases.rss",
    "https://news.microsoft.com/feed/",
    "https://about.meta.com/news/rss/",
    "https://nvidianews.nvidia.com/rss/all.rss",
    "https://newsroom.doordash.com/rss.xml",
    "https://newsroom.uber.com/rss/",
    "https://waymo.com/blog/rss.xml",
    "https://newsroom.spotify.com/rss.xml",
]

# Topic coverage thresholds
MIN_COVERAGE_PER_TOPIC = 5    # items per topic before gap-fill triggers
MAX_GAP_FILL_ROUNDS = 2       # maximum gap-fill iterations
SIM_THRESHOLD = 0.82          # title similarity ratio above this → duplicate


# ─── LangGraph state ──────────────────────────────────────────────────────────

class NewsCollectionState(TypedDict):
    date_from: str                        # "2025-05-28"
    date_to: str                          # "2025-06-04"
    topics: List[str]                     # user-provided: ["llm", "healthcare AI"]
    sources: List[str]                    # user-selected source categories
    custom_sources: Optional[List[str]]   # user-provided URLs/RSS feeds
    collected_items: List[Dict[str, Any]] # growing list of news items
    seen_keys: List[str]                  # url|title dedup keys
    errors: List[str]                     # non-fatal per-node errors
    topic_coverage: Dict[str, int]        # items per topic (updated by gap_fill)
    gap_fill_round: int
    work_dir: str


# ─── Utility helpers ──────────────────────────────────────────────────────────

def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse a date string in ISO, RFC 2822, and common formats."""
    if not date_str:
        return None
    s = str(date_str).strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d %b %Y",
        "%B %d, %Y",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%d %b %Y %H:%M:%S %z",
    ):
        try:
            return datetime.strptime(s[:31], fmt).replace(tzinfo=None)
        except (ValueError, IndexError):
            continue
    return None


def _parse_struct_time(st) -> Optional[datetime]:
    """Convert a feedparser time.struct_time (9-tuple) to a naive datetime."""
    try:
        return datetime.utcfromtimestamp(timegm(st))
    except Exception:
        return None


def _merge_items(
    new_items: List[Dict],
    collected: List[Dict],
    seen_keys: List[str],
) -> tuple[List[Dict], List[str]]:
    """Merge new_items into collected, skipping URL-level exact duplicates."""
    seen = set(seen_keys)
    for item in new_items:
        url = (item.get("url") or "").strip().lower()
        title = (item.get("title") or "").strip().lower()[:80]
        key = f"{url}|{title}"
        if url and key not in seen:
            seen.add(key)
            collected.append(item)
    return collected, list(seen)


def _compute_topic_coverage(
    items: List[Dict], topics: List[str]
) -> Dict[str, int]:
    """Count items that mention each topic in title or summary."""
    coverage: Dict[str, int] = {}
    for topic in topics:
        t_lower = topic.lower()
        coverage[topic] = sum(
            1 for item in items
            if t_lower in (
                (item.get("title") or "") + " " + (item.get("summary") or "")
            ).lower()
        )
    return coverage


def _topic_to_search_query(topic: str) -> str:
    """Convert a user topic string to a natural-language search query."""
    q = topic.lower().replace("-", " ").replace("_", " ").strip()
    if "ai" not in q and "artificial intelligence" not in q and "machine learning" not in q:
        q = q + " AI"
    return q


def _topic_to_arxiv_query(topic: str) -> str:
    """Convert a user topic string to an arXiv search query.

    For short/known topics, returns an expanded expert query.
    For arbitrary topics (e.g. "healthcare AI"), uses the topic directly
    so the graph works for any user-provided input.
    """
    q = topic.lower().replace("-", " ").replace("_", " ").strip()
    # Short-form aliases → expanded arXiv-friendly queries
    _ARXIV_EXPANSION: Dict[str, str] = {
        "llm": "large language model transformer generation",
        "cv": "computer vision image recognition object detection",
        "rl": "reinforcement learning reward policy gradient",
        "robotics": "robotics manipulation locomotion autonomous",
        "quantum": "quantum computing quantum machine learning",
        "ai": "artificial intelligence deep learning neural network",
        "ml": "machine learning optimization generalization",
        "nlp": "natural language processing text generation",
        "multimodal": "multimodal vision language foundation model",
        "agents": "autonomous agent tool use reasoning LLM",
        "diffusion": "diffusion model image generation synthesis",
    }
    return _ARXIV_EXPANSION.get(q, f"{q} deep learning")


def _parse_agent_result_to_items(text: str, source: str) -> List[Dict[str, Any]]:
    """Parse a cmbagent response (markdown text) into structured news items.

    Handles bullet lists, numbered lists, and markdown link formats:
      - **Title** | URL | date\\n  summary
      1. [Title](URL)\\n   summary
    """
    if not text:
        return []

    items: List[Dict[str, Any]] = []
    url_re = re.compile(r'https?://[^\s\)\]\,\"\'<>|]+')
    md_link_re = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)')
    seen_urls: set = set()

    # Split text into candidate blocks by blank lines or list markers
    blocks = re.split(r'\n\s*\n|\n(?=\s*[\d]+\.\s|\s*[-*•]\s)', text)

    for block in blocks:
        block = block.strip()
        if not block or len(block) < 20:
            continue

        # Try markdown link first: [Title](URL)
        md_match = md_link_re.search(block)
        if md_match:
            title = md_match.group(1).strip()[:200]
            url = md_match.group(2).strip().rstrip('.,;:)')
            if url in seen_urls:
                continue
            seen_urls.add(url)
            summary = md_link_re.sub('', block).strip()
            summary = re.sub(r'\*{1,2}|#{1,6}|^\s*[\d\-\*\•\.]+\s*', '', summary).strip()[:500]
            if title and len(title) >= 5:
                items.append({"title": title, "url": url, "summary": summary,
                               "source": source, "published_at": ""})
            continue

        # Fall back to first-URL-in-block approach
        urls = url_re.findall(block)
        if not urls:
            continue
        url = urls[0].rstrip('.,;:)')
        if url in seen_urls or len(url) < 12:
            continue
        seen_urls.add(url)

        lines = block.split('\n')
        first_line = lines[0]
        title = url_re.sub('', first_line)
        title = re.sub(r'\*{1,2}|#{1,6}|\|.*?$', '', title)
        title = re.sub(r'^\s*[\d\-\*\•\.]+\s*', '', title).strip()[:200]

        if not title or len(title) < 5:
            continue

        summary = ' '.join(lines[1:]).strip()
        summary = url_re.sub('', summary)
        summary = re.sub(r'\*{1,2}|#{1,6}', '', summary).strip()[:500]

        items.append({"title": title, "url": url, "summary": summary,
                       "source": source, "published_at": ""})

    return items


def _parse_ddg_snippet(raw: str, query: str) -> List[Dict[str, Any]]:
    """Parse a DuckDuckGo text snippet into structured items.

    DDG returns a raw text blob. We extract URLs and surrounding text
    to build title + summary pairs. If no URLs found, store as one blob.
    """
    items: List[Dict[str, Any]] = []
    url_re = re.compile(r'https?://[^\s\)\]\,\"\'<>]+')
    seen_urls: set = set()

    lines = [ln.strip() for ln in raw.split('\n') if ln.strip()]
    cur_title, cur_url, cur_summary_parts = "", "", []

    def _flush():
        if cur_title and cur_url:
            items.append({
                "title": cur_title[:200],
                "url": cur_url,
                "summary": " ".join(cur_summary_parts)[:500],
                "source": "duckduckgo",
                "published_at": "",
            })

    for line in lines:
        found = url_re.findall(line)
        if found:
            _flush()
            cur_url = found[0].rstrip('.,;)')
            if cur_url in seen_urls:
                cur_url = ""
                continue
            seen_urls.add(cur_url)
            candidate_title = url_re.sub('', line).strip(' |-:')
            cur_title = candidate_title[:200] if candidate_title else query[:80]
            cur_summary_parts = []
        elif cur_url:
            cur_summary_parts.append(line)

    _flush()

    if not items and len(raw) > 50:
        items.append({
            "title": f"Search: {query[:80]}",
            "url": f"https://duckduckgo.com/?q={query[:100].replace(' ', '+')}",
            "summary": raw[:800],
            "source": "duckduckgo",
            "published_at": "",
        })

    return items


# ─── Tier 1: cmbagent structured tools ───────────────────────────────────────

def broad_sweep_node(state: NewsCollectionState) -> NewsCollectionState:
    """Broad official AI announcements sweep via cmbagent (no limits)."""
    try:
        from cmbagent.external_tools.news_tools import announcements_noauth
        result = announcements_noauth(
            query="", company="",
            from_date=state["date_from"], to_date=state["date_to"],
            limit=9999,
        )
        items = result.get("items") or []
        collected, seen = _merge_items(items, state["collected_items"], state["seen_keys"])
        print(f"[Collection] Broad sweep: {len(items)} raw → {len(collected)} total")
        return {**state, "collected_items": collected, "seen_keys": seen}
    except Exception as exc:
        return {**state, "errors": state["errors"] + [f"broad_sweep: {exc}"]}


def curated_sources_node(state: NewsCollectionState) -> NewsCollectionState:
    """cmbagent curated AI sources — one search query per user topic.

    Running per-topic (not one generic query) ensures curated sources
    return relevant articles for any topic the user specifies.
    """
    try:
        from cmbagent.external_tools.news_tools import curated_ai_sources_search
    except ImportError as exc:
        return {**state, "errors": state["errors"] + [f"curated_sources import: {exc}"]}

    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])

    queries: List[str] = [
        f"{_topic_to_search_query(t)} news {state['date_from']} to {state['date_to']}"
        for t in state["topics"]
    ]
    if not queries:
        queries = [f"artificial intelligence news {state['date_from']} to {state['date_to']}"]

    for query in queries:
        try:
            result = curated_ai_sources_search(
                query=query, limit=9999,
                from_date=state["date_from"], to_date=state["date_to"],
            )
            items = result.get("items") or []
            before = len(collected)
            collected, seen = _merge_items(items, collected, seen)
            added = len(collected) - before
            if added:
                print(f"[Collection] Curated/{query[:55]}: {added} new items")
        except Exception as exc:
            errors.append(f"curated_sources/{query[:40]}: {exc}")

    return {**state, "collected_items": collected, "seen_keys": seen, "errors": errors}


def company_scrape_node(state: NewsCollectionState) -> NewsCollectionState:
    """cmbagent per-company official page scraping for core AI companies.

    Uses a fixed list of 15 major AI companies — independent of user topics.
    These companies reliably publish AI news that is always relevant.
    """
    try:
        from cmbagent.external_tools.news_tools import scrape_official_news_pages
    except ImportError as exc:
        return {**state, "errors": state["errors"] + [f"company_scrape import: {exc}"]}

    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])

    for company in _CORE_AI_COMPANIES:
        try:
            result = scrape_official_news_pages(
                company=company,
                from_date=state["date_from"],
                to_date=state["date_to"],
                limit=50,
            )
            items = result.get("items") or []
            before = len(collected)
            collected, seen = _merge_items(items, collected, seen)
            added = len(collected) - before
            if added:
                print(f"[Collection] Official/{company}: {added} items")
        except Exception as exc:
            errors.append(f"company_scrape/{company}: {exc}")

    return {**state, "collected_items": collected, "seen_keys": seen, "errors": errors}


# Company name → natural search query (avoids ambiguous single-word searches)
_COMPANY_DDG_QUERIES: Dict[str, str] = {
    "openai":       "OpenAI GPT announcement",
    "anthropic":    "Anthropic Claude AI announcement",
    "google":       "Google AI Gemini announcement",
    "meta":         "Meta AI Llama announcement",
    "microsoft":    "Microsoft AI Copilot Azure announcement",
    "nvidia":       "NVIDIA AI GPU announcement",
    "huggingface":  "Hugging Face AI model release",
    "amazon":       "Amazon AWS AI Bedrock announcement",
    "deepmind":     "Google DeepMind AI research",
    "apple":        "Apple AI machine learning announcement",
    "ibm":          "IBM AI watsonx announcement",
    "mistral":      "Mistral AI model release",
    "xai":          "xAI Grok announcement",
    "deepseek":     "DeepSeek AI model release",
    "cohere":       "Cohere AI enterprise announcement",
}


def company_ddg_news_node(state: NewsCollectionState) -> NewsCollectionState:
    """DuckDuckGo news search for each core AI company — no API key required.

    This supplements the cmbagent company_scrape (which depends on cmbagent tools)
    with a direct DDGS.news() search per company. Ensures company news appears even
    when cmbagent tools are unavailable or return sparse results.
    """
    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])

    try:
        from ddgs import DDGS
    except ImportError:
        errors.append("company_ddg_news: ddgs not installed")
        return {**state, "errors": errors}

    for slug, query in _COMPANY_DDG_QUERIES.items():
        try:
            with DDGS() as ddgs:
                results = list(ddgs.news(query, max_results=8))
            items = [
                {
                    "title":        (r.get("title") or "")[:200],
                    "url":          r.get("url") or r.get("link") or "",
                    "summary":      (r.get("body") or "")[:500],
                    "source":       "company_ddg",
                    "company":      slug,
                    "published_at": r.get("date") or "",
                }
                for r in results
                if r.get("url") or r.get("link")
            ]
            before = len(collected)
            collected, seen = _merge_items(items, collected, seen)
            added = len(collected) - before
            if added:
                print(f"[Collection] Company DDG/{slug}: {added} new items")
            time.sleep(1.0)
        except Exception as exc:
            errors.append(f"company_ddg/{slug}: {exc}")

    return {**state, "collected_items": collected, "seen_keys": seen, "errors": errors}


def newsapi_gnews_node(state: NewsCollectionState) -> NewsCollectionState:
    """NewsAPI + GNews — one query per user topic (conditional on API keys)."""
    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])

    newsapi_key = os.environ.get("NEWSAPI_KEY")
    gnews_key = os.environ.get("GNEWS_API_KEY")
    if not newsapi_key and not gnews_key:
        return state

    try:
        from cmbagent.external_tools.news_tools import newsapi_search, gnews_search
    except ImportError as exc:
        return {**state, "errors": errors + [f"newsapi_gnews import: {exc}"]}

    queries: List[str] = [_topic_to_search_query(t) for t in state["topics"]]
    if not queries:
        queries = ["artificial intelligence machine learning"]

    for query in queries:
        if newsapi_key:
            try:
                result = newsapi_search(
                    query=query,
                    from_date=state["date_from"], to_date=state["date_to"],
                    page_size=100,
                )
                items = result.get("items") or result.get("articles") or []
                before = len(collected)
                collected, seen = _merge_items(items, collected, seen)
                if len(collected) > before:
                    print(f"[Collection] NewsAPI/{query[:40]}: {len(collected) - before} new")
            except Exception as exc:
                errors.append(f"newsapi/{query[:40]}: {exc}")

        if gnews_key:
            try:
                result = gnews_search(
                    query=query,
                    from_date=state["date_from"], to_date=state["date_to"],
                    max_results=100,
                )
                items = result.get("items") or result.get("articles") or []
                before = len(collected)
                collected, seen = _merge_items(items, collected, seen)
                if len(collected) > before:
                    print(f"[Collection] GNews/{query[:40]}: {len(collected) - before} new")
            except Exception as exc:
                errors.append(f"gnews/{query[:40]}: {exc}")

    return {**state, "collected_items": collected, "seen_keys": seen, "errors": errors}


# ─── Tier 1 + common feeds ────────────────────────────────────────────────────

def rss_feeds_node(state: NewsCollectionState) -> NewsCollectionState:
    """Parse global AI RSS feeds via feedparser (date-filtered, no topic constraint)."""
    try:
        import feedparser
    except ImportError:
        return {**state, "errors": state["errors"] + ["rss_feeds: feedparser not installed"]}

    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])
    date_from = _parse_date(state["date_from"])
    date_to_dt = _parse_date(state["date_to"])

    for feed_url in _GLOBAL_RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source_label = feed.feed.get("title") or feed_url.split("/")[2]

            items: List[Dict] = []
            for entry in feed.entries:
                # Prefer feedparser's pre-parsed struct_time for reliable date extraction
                pub_dt: Optional[datetime] = None
                pub_str = ""
                if entry.get("published_parsed"):
                    pub_dt = _parse_struct_time(entry.published_parsed)
                    pub_str = pub_dt.strftime("%Y-%m-%d") if pub_dt else ""
                elif entry.get("updated_parsed"):
                    pub_dt = _parse_struct_time(entry.updated_parsed)
                    pub_str = pub_dt.strftime("%Y-%m-%d") if pub_dt else ""
                else:
                    raw = entry.get("published") or entry.get("updated") or ""
                    pub_dt = _parse_date(raw)
                    pub_str = raw[:10] if raw else ""

                if pub_dt and date_from and date_to_dt:
                    if not (date_from <= pub_dt <= date_to_dt):
                        continue

                title = (entry.get("title") or "").strip()
                url = (entry.get("link") or "").strip()
                summary = (entry.get("summary") or "").strip()[:500]
                if title and url:
                    items.append({"title": title, "url": url, "summary": summary,
                                   "source": source_label, "published_at": pub_str})

            if items:
                before = len(collected)
                collected, seen = _merge_items(items, collected, seen)
                print(f"[Collection] RSS/{source_label}: {len(collected) - before} new items")
        except Exception as exc:
            errors.append(f"rss/{feed_url}: {exc}")
        time.sleep(0.3)

    return {**state, "collected_items": collected, "seen_keys": seen, "errors": errors}


def custom_sources_node(state: NewsCollectionState) -> NewsCollectionState:
    """User-provided custom sources (RSS feed URLs or HTML pages)."""
    custom_sources = state.get("custom_sources") or []
    if not custom_sources:
        return state

    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])

    try:
        from cmbagent.external_tools.news_tools import _direct_scrape_page_links, _fetch_rss_items
        from urllib.parse import urlparse

        for url in custom_sources:
            url = (url or "").strip()
            if not url.startswith("http"):
                continue
            label = (urlparse(url).netloc or "custom").replace("www.", "")[:30]
            try:
                rss_items = _fetch_rss_items(url, label, state["date_from"], state["date_to"])
                if rss_items:
                    collected, seen = _merge_items(rss_items, collected, seen)
                    print(f"[Collection] Custom/{label} (RSS): {len(rss_items)} items")
                    continue
            except Exception:
                pass
            try:
                page_items = _direct_scrape_page_links(url, label)
                collected, seen = _merge_items(page_items, collected, seen)
                print(f"[Collection] Custom/{label} (HTML): {len(page_items)} items")
            except Exception as exc:
                errors.append(f"custom/{label}: {exc}")

    except Exception as exc:
        errors.append(f"custom_sources: {exc}")

    return {**state, "collected_items": collected, "seen_keys": seen, "errors": errors}


# ─── Tier 2: Global topic search ──────────────────────────────────────────────

def topic_arxiv_search_node(state: NewsCollectionState) -> NewsCollectionState:
    """arXiv paper search — query built directly from each user topic string.

    Works for any topic: "healthcare AI" → "healthcare AI deep learning",
    "autonomous driving" → "autonomous driving deep learning", etc.
    No pre-defined mapping required.
    """
    try:
        import arxiv as arxiv_pkg
    except ImportError:
        return {**state, "errors": state["errors"] + ["arxiv: package not installed"]}

    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])
    date_from = _parse_date(state["date_from"])
    date_to_dt = _parse_date(state["date_to"])

    # One query per topic + one catch-all
    queries: List[str] = [_topic_to_arxiv_query(t) for t in state["topics"]]
    if not queries:
        queries = ["artificial intelligence machine learning neural network"]

    # Use a client with a short delay_seconds to avoid long retries
    client = arxiv_pkg.Client(delay_seconds=1.0, num_retries=1)
    for query in queries:
        try:
            search = arxiv_pkg.Search(
                query=query,
                max_results=25,                        # 25 is enough; arXiv slows at 100
                sort_by=arxiv_pkg.SortCriterion.SubmittedDate,
            )
            items: List[Dict] = []
            for paper in client.results(search):
                pub_dt = paper.published.replace(tzinfo=None) if paper.published else None
                if pub_dt and date_from and date_to_dt:
                    if not (date_from <= pub_dt <= date_to_dt):
                        continue
                pub_str = pub_dt.strftime("%Y-%m-%d") if pub_dt else ""
                items.append({
                    "title": paper.title,
                    "url": paper.entry_id,
                    "summary": (paper.summary or "")[:500],
                    "source": "arxiv",
                    "published_at": pub_str,
                })
            if items:
                before = len(collected)
                collected, seen = _merge_items(items, collected, seen)
                print(f"[Collection] arXiv/{query[:50]}: {len(collected) - before} new papers")
        except Exception as exc:
            errors.append(f"arxiv/{query[:40]}: {exc}")
        time.sleep(1.0)

    return {**state, "collected_items": collected, "seen_keys": seen, "errors": errors}


def topic_web_search_node(state: NewsCollectionState) -> NewsCollectionState:
    """DuckDuckGo news search — structured global news results per user topic.

    Uses ddgs.DDGS.news() for structured per-article output
    (title, url, body, date, source). Falls back to DuckDuckGoSearchRun
    text parsing if the ddgs package is unavailable.
    Queries are built from the user's actual topic strings.
    """
    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])

    # Build queries: two per topic + one general AI sweep
    queries: List[str] = []
    for topic in state["topics"]:
        q = _topic_to_search_query(topic)
        queries.append(f"{q} news {state['date_from']}")
        queries.append(f"{q} announcement release {state['date_to'][:7]}")
    queries.append(f"artificial intelligence major announcement {state['date_from']}")

    try:
        from ddgs import DDGS
        _use_structured = True
    except ImportError:
        _use_structured = False

    for query in queries:
        try:
            if _use_structured:
                with DDGS() as ddgs:
                    results = list(ddgs.news(query, max_results=10))
                items = [
                    {
                        "title": (r.get("title") or "")[:200],
                        "url": r.get("url") or r.get("link") or "",
                        "summary": (r.get("body") or "")[:500],
                        "source": "duckduckgo_news",
                        "published_at": r.get("date") or "",
                    }
                    for r in results
                    if r.get("url") or r.get("link")
                ]
            else:
                from langchain_community.tools import DuckDuckGoSearchRun
                raw = DuckDuckGoSearchRun().run(query)
                items = _parse_ddg_snippet(raw, query)

            before = len(collected)
            collected, seen = _merge_items(items, collected, seen)
            added = len(collected) - before
            if added:
                print(f"[Collection] DDG news/{query[:55]}: {added} new items")
            time.sleep(1.5)
        except Exception as exc:
            errors.append(f"ddg_news/{query[:40]}: {exc}")

    return {**state, "collected_items": collected, "seen_keys": seen, "errors": errors}


def web_surfer_agent_node(state: NewsCollectionState) -> NewsCollectionState:
    """Broad web search using DuckDuckGo — no API key required.

    Uses DDGS.text() for broader coverage (blogs, announcements, product pages)
    complementing topic_web_search_node's news-focused DDGS.news() queries.
    """
    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])

    try:
        from ddgs import DDGS
    except ImportError:
        errors.append("web_surfer_ddgs: ddgs not installed")
        return {**state, "collected_items": collected, "seen_keys": seen, "errors": errors}

    for topic in state["topics"]:
        q = _topic_to_search_query(topic)
        queries = [
            f"{q} announcement release blog {state['date_from'][:7]}",
            f"{q} AI research product launch {state['date_to'][:7]}",
        ]
        for query in queries:
            try:
                with DDGS() as ddgs:
                    results = list(ddgs.text(query, max_results=10))
                items = [
                    {
                        "title": (r.get("title") or "")[:200],
                        "url": r.get("href") or r.get("url") or "",
                        "summary": (r.get("body") or "")[:500],
                        "source": "web_surfer_ddgs",
                        "published_at": "",
                    }
                    for r in results
                    if r.get("href") or r.get("url")
                ]
                before = len(collected)
                collected, seen = _merge_items(items, collected, seen)
                print(f"[Collection] web_surfer_ddgs/{query[:50]}: {len(collected) - before} new items")
                time.sleep(1.5)
            except Exception as exc:
                errors.append(f"web_surfer_ddgs/{topic}: {exc}")

    return {**state, "collected_items": collected, "seen_keys": seen, "errors": errors}


def perplexity_agent_node(state: NewsCollectionState) -> NewsCollectionState:
    """cmbagent perplexity: academic paper discovery via Perplexity API.

    Only runs when PERPLEXITY_API_KEY is set in .env.
    Without the key the AutoGen loop routes back to itself endlessly.
    Academic coverage is already handled by the arxiv node when key is absent.
    """
    if not os.environ.get("PERPLEXITY_API_KEY"):
        print("[Collection] perplexity_agent: skipped (no PERPLEXITY_API_KEY in .env)")
        return state

    try:
        from cmbagent import one_shot
    except ImportError:
        return state

    topics_str = ", ".join(state["topics"]) if state["topics"] else "artificial intelligence"
    task = (
        f"Find the most significant AI research papers published on arXiv "
        f"between {state['date_from']} and {state['date_to']} "
        f"covering these topics: {topics_str}.\n\n"
        f"For each paper provide:\n"
        f"- Full title\n"
        f"- arXiv URL (https://arxiv.org/abs/XXXX.XXXXX)\n"
        f"- First two authors\n"
        f"- Two-sentence abstract summary highlighting practical impact\n\n"
        f"Focus on papers with significant results or novel architectures. "
        f"Return at least 15 papers if available."
    )
    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])
    try:
        result = one_shot(agent="perplexity", task=task)
        if result:
            items = _parse_agent_result_to_items(result, source="perplexity")
            before = len(collected)
            collected, seen = _merge_items(items, collected, seen)
            print(f"[Collection] perplexity/{topics_str[:50]}: {len(collected) - before} new items")
    except Exception as exc:
        errors.append(f"perplexity: {exc}")

    return {**state, "collected_items": collected, "seen_keys": seen, "errors": errors}


# ─── Post-processing ──────────────────────────────────────────────────────────

def gap_fill_node(state: NewsCollectionState) -> NewsCollectionState:
    """Topic-based gap fill: re-search any topic with insufficient coverage.

    Measures how many collected items mention each user topic.
    For under-covered topics, runs 3 different targeted web searches.
    Topic-driven (not company-driven) so it works for any topic.
    """
    if state["gap_fill_round"] >= MAX_GAP_FILL_ROUNDS:
        return state

    try:
        from cmbagent.external_tools.news_tools import multi_engine_web_search
    except ImportError:
        return state

    coverage = _compute_topic_coverage(state["collected_items"], state["topics"])
    under_covered = [t for t, c in coverage.items() if c < MIN_COVERAGE_PER_TOPIC]

    if not under_covered:
        print(f"[Collection] Gap fill: all topics have ≥{MIN_COVERAGE_PER_TOPIC} items")
        return {**state, "topic_coverage": coverage}

    print(f"[Collection] Gap fill round {state['gap_fill_round'] + 1}: "
          f"{len(under_covered)} under-covered topics: {under_covered}")

    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])

    for topic in under_covered:
        q_base = _topic_to_search_query(topic)
        for query in [
            f"{q_base} news latest 2025",
            f"{q_base} announcement breakthrough",
            f"{q_base} research paper release",
        ]:
            try:
                result = multi_engine_web_search(
                    query=query, max_results=15,
                    from_date=state["date_from"], to_date=state["date_to"],
                )
                items = result.get("items") or []
                collected, seen = _merge_items(items, collected, seen)
            except Exception as exc:
                errors.append(f"gap_fill/{topic}: {exc}")
        time.sleep(0.5)

    return {
        **state,
        "collected_items": collected,
        "seen_keys": seen,
        "errors": errors,
        "topic_coverage": _compute_topic_coverage(collected, state["topics"]),
        "gap_fill_round": state["gap_fill_round"] + 1,
    }


def date_validate_node(state: NewsCollectionState) -> NewsCollectionState:
    """Strictly filter items to the requested date range.

    - Items with a known date outside the range are removed.
    - Items with no date are kept (flagged with _undated=True) for Stage 4
      programmatic verification to handle.
    """
    date_from = _parse_date(state["date_from"])
    date_to_dt = _parse_date(state["date_to"])

    if not date_from or not date_to_dt:
        return state

    in_range: List[Dict] = []
    undated: List[Dict] = []
    out_of_range = 0

    for item in state["collected_items"]:
        pub = item.get("published_at") or item.get("date") or ""
        pub_dt = _parse_date(pub)
        if pub_dt is None:
            undated.append({**item, "_undated": True})
        elif date_from <= pub_dt <= date_to_dt:
            in_range.append(item)
        else:
            out_of_range += 1

    print(f"[Collection] Date filter: {len(in_range)} in-range, "
          f"{len(undated)} undated, {out_of_range} removed")
    return {**state, "collected_items": in_range + undated}


def semantic_dedup_node(state: NewsCollectionState) -> NewsCollectionState:
    """Remove near-duplicate items using title similarity.

    Algorithm: prefix-bucket deduplication
    - Group titles by their first 2 and 3 words (O(1) bucket lookup)
    - Only compare items that share a prefix bucket
    - Average O(n) instead of O(n²) — handles 5,000+ items efficiently
    - SIM_THRESHOLD 0.82: aggressive enough to catch rephrased duplicates
      while preserving legitimately different articles about the same event
    """
    unique: List[Dict] = []
    prefix_buckets: Dict[str, List[str]] = {}

    for item in state["collected_items"]:
        title = (item.get("title") or "").lower().strip()
        if not title:
            unique.append(item)
            continue

        words = title.split()
        # Two bucket keys: 2-word and 3-word prefixes
        bucket_keys = [" ".join(words[:2])]
        if len(words) >= 3:
            bucket_keys.append(" ".join(words[:3]))

        is_dup = False
        for bk in bucket_keys:
            for existing in prefix_buckets.get(bk, []):
                if SequenceMatcher(None, title, existing).ratio() > SIM_THRESHOLD:
                    is_dup = True
                    break
            if is_dup:
                break

        if not is_dup:
            unique.append(item)
            for bk in bucket_keys:
                prefix_buckets.setdefault(bk, []).append(title)

    removed = len(state["collected_items"]) - len(unique)
    print(f"[Collection] Semantic dedup: removed {removed} near-duplicates, "
          f"{len(unique)} unique items remain")
    return {**state, "collected_items": unique}


# ─── Graph assembly ───────────────────────────────────────────────────────────

def build_news_graph():
    """Compile and return the news collection LangGraph StateGraph."""
    graph = StateGraph(NewsCollectionState)

    # Tier 1 — cmbagent structured tools
    graph.add_node("broad_sweep",        broad_sweep_node)
    graph.add_node("curated_sources",    curated_sources_node)
    graph.add_node("company_scrape",     company_scrape_node)
    graph.add_node("company_ddg_news",   company_ddg_news_node)
    graph.add_node("newsapi_gnews",      newsapi_gnews_node)

    # Common feeds + user sources
    graph.add_node("rss_feeds",        rss_feeds_node)
    graph.add_node("custom_sources",   custom_sources_node)

    # Tier 2 — global topic search
    graph.add_node("topic_arxiv_search",   topic_arxiv_search_node)
    graph.add_node("topic_web_search",     topic_web_search_node)
    graph.add_node("web_surfer_agent",     web_surfer_agent_node)
    graph.add_node("perplexity_agent",     perplexity_agent_node)

    # Post-processing
    graph.add_node("gap_fill",        gap_fill_node)
    graph.add_node("date_validate",   date_validate_node)
    graph.add_node("semantic_dedup",  semantic_dedup_node)

    # Sequential edges
    graph.set_entry_point("broad_sweep")
    graph.add_edge("broad_sweep",          "curated_sources")
    graph.add_edge("curated_sources",      "company_scrape")
    graph.add_edge("company_scrape",       "company_ddg_news")
    graph.add_edge("company_ddg_news",     "newsapi_gnews")
    graph.add_edge("newsapi_gnews",        "rss_feeds")
    graph.add_edge("rss_feeds",            "custom_sources")
    graph.add_edge("custom_sources",       "topic_arxiv_search")
    graph.add_edge("topic_arxiv_search",   "topic_web_search")
    graph.add_edge("topic_web_search",     "web_surfer_agent")
    graph.add_edge("web_surfer_agent",     "perplexity_agent")
    graph.add_edge("perplexity_agent",     "gap_fill")
    graph.add_edge("gap_fill",             "date_validate")
    graph.add_edge("date_validate",        "semantic_dedup")
    graph.add_edge("semantic_dedup",       END)

    return graph.compile()


def run_news_collection_graph(
    date_from: str,
    date_to: str,
    topics: List[str],
    sources: List[str],
    custom_sources: Optional[List[str]] = None,
) -> NewsCollectionState:
    """Entry point: build and invoke the news collection graph.

    Returns the final NewsCollectionState with:
      - collected_items: deduplicated list of news items
      - topic_coverage:  items per user topic (computed by gap_fill)
      - errors:          non-fatal errors from each node
    """
    graph = build_news_graph()
    initial_state: NewsCollectionState = {
        "date_from": date_from,
        "date_to": date_to,
        "topics": topics,
        "sources": sources,
        "custom_sources": custom_sources or [],
        "collected_items": [],
        "seen_keys": [],
        "errors": [],
        "topic_coverage": {},
        "gap_fill_round": 0,
        "work_dir": "",
    }
    return graph.invoke(initial_state)
