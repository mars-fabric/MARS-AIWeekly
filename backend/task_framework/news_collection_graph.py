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

try:
    import cmbagent.external_tools.news_tools as _news_tools
except ImportError:
    _news_tools = None

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

# Fixed set of core AI companies always scraped via cmbagent (Tier 1).
# Kept small and stable — these are the companies whose blogs reliably publish
# AI news worth including regardless of topic.
_CORE_AI_COMPANIES: List[str] = [
    "openai", "anthropic", "google", "meta", "microsoft",
    "nvidia", "huggingface", "amazon", "deepmind", "apple",
    "ibm", "mistral", "xai", "deepseek", "cohere", "perplexity",
]

# Global AI news RSS feeds — official company and research sources only.
# Third-party news aggregators (TechCrunch, VentureBeat, The Verge, etc.) are
# intentionally excluded so all items link back to primary/official sources.
_GLOBAL_RSS_FEEDS: List[str] = [
    # AI research, news, and engineering sources
"https://openai.com/news/",
"https://openai.com/research/",
"https://www.anthropic.com/news",
"https://www.anthropic.com/research",

"https://blog.google/",
"https://blog.google/technology/ai/",
"https://blog.google/innovation-and-ai/",
"https://blog.google/innovation-and-ai/technology/ai/",
"https://blog.google/innovation-and-ai/technology/research/",
"https://research.google/blog/",
"https://deepmind.google/blog/",

"https://blogs.microsoft.com/",
"https://blogs.microsoft.com/ai/",
"https://microsoft.ai/",
"https://microsoft.ai/blog/",
"https://www.microsoft.com/en-us/research/blog/",
"https://azure.microsoft.com/en-us/blog/",
"https://azure.microsoft.com/en-us/blog/content-type/announcements/",

"https://ai.meta.com/blog/",
"https://ai.meta.com/research/",

"https://aws.amazon.com/blogs/aws/",
"https://aws.amazon.com/blogs/machine-learning/",

"https://blogs.nvidia.com/blog/category/ai/",
"https://blogs.nvidia.com/blog/tag/agentic-ai/",
"https://blogs.nvidia.com/blog/tag/inference/",
"https://developer.nvidia.com/blog/",

"https://huggingface.co/blog",

"https://cohere.com/blog",

"https://www.perplexity.ai/hub/blog",
]

# Add companies not in cmbagent's _OFFICIAL_NEWS_PAGES, and fix Anthropic's
# broken RSS entry. All existing company URLs are already in _GLOBAL_RSS_FEEDS
# and are handled by rss_feeds_node — no need to duplicate them here.
if _news_tools is not None:
    _news_tools._OFFICIAL_NEWS_PAGES.update({
        "cohere":     ["https://cohere.com/blog"],
        "perplexity": ["https://www.perplexity.ai/hub/blog"],
    })
    _news_tools._COMPANY_RSS_FEEDS["anthropic"] = []

# Major AI repos monitored for release notes via the GitHub public API.
_GITHUB_AI_REPOS: List[str] = [
    "openai/openai-python",
    "anthropics/anthropic-sdk-python",
    "huggingface/transformers",
    "huggingface/diffusers",
    "langchain-ai/langchain",
    "microsoft/autogen",
    "microsoft/semantic-kernel",
    "mistralai/mistral-inference",
    "vllm-project/vllm",
    "ollama/ollama",
    "google-deepmind/gemma",
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

def _strip_html(text: str) -> str:
    """Strip HTML tags and decode HTML entities from RSS summary text."""
    import html as _html
    text = _html.unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


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
    """Merge new_items into collected, skipping exact duplicates.

    Dedup key is url|title. Items without a URL use title alone as the key
    so they are not silently dropped.
    """
    seen = set(seen_keys)
    for item in new_items:
        url = (item.get("url") or "").strip().lower()
        title = (item.get("title") or "").strip().lower()[:80]
        if not title:
            continue  # no title and no URL — nothing to identify the item
        key = f"{url}|{title}" if url else title
        if key not in seen:
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
    """Broad official AI announcements sweep via cmbagent (no limits).

    Only runs when "press-releases" is selected in the UI.
    """
    if "press-releases" not in (state.get("sources") or []):
        return state
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

    Only runs when "curated-ai-websites" is selected in the UI.
    """
    if "curated-ai-websites" not in (state.get("sources") or []):
        return state
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

    Only runs when "company-announcements" is selected in the UI.
    """
    if "company-announcements" not in (state.get("sources") or []):
        return state
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
    "perplexity":   "Perplexity AI search announcement",
}


def company_ddg_news_node(state: NewsCollectionState) -> NewsCollectionState:
    """DuckDuckGo news search for each core AI company — no API key required.

    This supplements the cmbagent company_scrape (which depends on cmbagent tools)
    with a direct DDGS.news() search per company. Ensures company news appears even
    when cmbagent tools are unavailable or return sparse results.

    Only runs when "company-announcements" is selected in the UI.
    """
    if "company-announcements" not in (state.get("sources") or []):
        return state
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


def github_releases_node(state: NewsCollectionState) -> NewsCollectionState:
    """Fetch recent releases from major AI GitHub repos via the public REST API.

    Only runs when "github" is included in state["sources"] (i.e. the user
    selected "GitHub Releases" in the UI).

    Uses GITHUB_TOKEN env var when available (5000 req/hr); falls back to
    unauthenticated requests (60 req/hr — sufficient for ~10 repos per run).
    """
    if "github" not in (state.get("sources") or []):
        return state

    import json
    from urllib.request import Request, urlopen
    from urllib.error import URLError

    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])

    date_from = _parse_date(state.get("date_from", ""))
    date_to   = _parse_date(state.get("date_to", ""))
    token     = os.environ.get("GITHUB_TOKEN", "")

    for repo in _GITHUB_AI_REPOS:
        try:
            api_url = f"https://api.github.com/repos/{repo}/releases?per_page=10"
            headers = {
                "User-Agent": "MARS-AIWeekly/1.0",
                "Accept": "application/vnd.github+json",
            }
            if token:
                headers["Authorization"] = f"Bearer {token}"
            req = Request(api_url, headers=headers)
            with urlopen(req, timeout=8) as resp:
                releases = json.loads(resp.read().decode())

            if not isinstance(releases, list):
                continue

            items = []
            for r in releases:
                pub_str = (r.get("published_at") or r.get("created_at") or "")[:10]
                pub_dt  = _parse_date(pub_str) if pub_str else None
                if pub_dt and date_from and date_to:
                    if not (date_from <= pub_dt <= date_to):
                        continue
                tag = r.get("name") or r.get("tag_name") or ""
                if not tag:
                    continue
                repo_short = repo.split("/")[-1]
                items.append({
                    "title":        f"{repo_short} {tag}",
                    "url":          r.get("html_url") or "",
                    "summary":      (r.get("body") or "")[:500],
                    "source":       "github_releases",
                    "published_at": pub_str,
                })

            before = len(collected)
            collected, seen = _merge_items(items, collected, seen)
            added = len(collected) - before
            if added:
                print(f"[Collection] GitHub/{repo}: {added} releases")
            time.sleep(0.5)
        except Exception as exc:
            errors.append(f"github_releases/{repo}: {exc}")

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
    """Parse global AI RSS feeds via feedparser (date-filtered, no topic constraint).

    Always runs — hardcoded feeds are independent of source checkbox selection.
    """
    try:
        import feedparser
    except ImportError:
        return {**state, "errors": state["errors"] + ["rss_feeds: feedparser not installed"]}

    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])
    date_from = _parse_date(state["date_from"])
    date_to_dt = _parse_date(state["date_to"])
    date_to_eod = date_to_dt.replace(hour=23, minute=59, second=59) if date_to_dt else None

    # Known RSS feed URLs for blog pages that don't auto-discover well
    _KNOWN_FEEDS = {
        "https://huggingface.co/blog":                        "https://huggingface.co/blog/feed.xml",
        "https://aws.amazon.com/blogs/aws/":                  "https://aws.amazon.com/blogs/aws/feed/",
        "https://aws.amazon.com/blogs/machine-learning/":     "https://aws.amazon.com/blogs/machine-learning/feed/",
        "https://blogs.nvidia.com/blog/category/ai/":         "https://blogs.nvidia.com/feed/",
        "https://blogs.nvidia.com/blog/tag/agentic-ai/":      "https://blogs.nvidia.com/blog/tag/agentic-ai/feed/",
        "https://blogs.nvidia.com/blog/tag/inference/":       "https://blogs.nvidia.com/blog/tag/inference/feed/",
        "https://developer.nvidia.com/blog/":                 "https://developer.nvidia.com/blog/feed/",
    }

    def _try_feed(url: str):
        """Resolve blog URL to its RSS feed. Checks known map first, then auto-discovers."""
        resolved = _KNOWN_FEEDS.get(url.rstrip("/") + "/") or _KNOWN_FEEDS.get(url.rstrip("/")) or url
        f = feedparser.parse(resolved)
        if f.entries:
            return f
        # Auto-discovery fallback for unmapped URLs
        for suffix in ("/feed/", "/feed.xml", "/rss/", "/atom/"):
            candidate = url.rstrip("/") + suffix
            f2 = feedparser.parse(candidate)
            if f2.entries:
                return f2
        return f

    for feed_url in _GLOBAL_RSS_FEEDS:
        try:
            feed = _try_feed(feed_url)
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

                if pub_dt and date_from and date_to_eod:
                    if not (date_from <= pub_dt <= date_to_eod):
                        continue

                title = (entry.get("title") or "").strip()
                url = (entry.get("link") or "").strip()
                summary = _strip_html(entry.get("summary") or "")[:500]
                if title and url:
                    items.append({"title": title, "url": url, "summary": summary,
                                   "source": source_label, "published_at": pub_str})

            if items:
                before = len(collected)
                collected, seen = _merge_items(items, collected, seen)
                print(f"[Collection] RSS/{source_label}: {len(collected) - before} new items")
            else:
                # No usable RSS items — feedparser may have parsed HTML as a
                # partial/bozo feed with entries that fail date/title checks.
                # Always fall back to HTML scraping for non-RSS URLs.
                try:
                    html_items = _scrape_page_permissive(feed_url, source_label)
                    if html_items:
                        before = len(collected)
                        collected, seen = _merge_items(html_items, collected, seen)
                        print(f"[Collection] HTML/{source_label}: {len(collected) - before} new items")
                except Exception:
                    pass
        except Exception as exc:
            errors.append(f"rss/{feed_url}: {exc}")
        time.sleep(0.3)

    return {**state, "collected_items": collected, "seen_keys": seen, "errors": errors}


def _scrape_page_permissive(page_url: str, label: str) -> List[Dict]:
    """Scrape a blog/news page and return all article-like links.

    Unlike cmbagent's _direct_scrape_page_links, this does NOT require a URL
    path signal (e.g. /blog/, /news/) — it accepts any same-domain link that
    has at least 2 path segments and a meaningful anchor text.

    Date extraction strategy (tried in order):
      1. Date anywhere in anchor text (handles Anthropic, Cohere, X.ai)
      2. Nearest <time datetime="..."> tag within 2 000 chars (handles AWS, HuggingFace)
      3. Inline "Mon DD, YYYY" in the 500 HTML chars before the anchor (handles Mistral, NVIDIA)
      4. Date embedded in the URL path  /YYYY/MM/DD/

    Domain matching: same domain OR same apex company domain family, so that
    e.g. deepmind.google/blog links to blog.google and microsoft.ai links to
    blogs.microsoft.com are both accepted.
    """
    import re as _re
    import datetime as _dt
    from html import unescape as _unescape
    from urllib.parse import urlparse as _urlparse
    from urllib.request import Request as _Req, urlopen as _open

    _NAV_SKIP = [
        r"^/$", r"/category/", r"/tag/", r"/page/\d", r"/author/",
        r"/search", r"/login", r"/signup", r"/contact", r"/about/?$",
        r"/privacy", r"/terms", r"/sitemap", r"\.(css|js|png|jpg|svg|ico)$",
        r"/store/", r"/pricing", r"/download", r"/careers", r"/jobs",
        r"/legal", r"/account", r"/settings", r"/profile", r"/dashboard",
        r"/feed/?$", r"/rss/?$",
    ]
    _NAV_TITLES = {
        "read more", "learn more", "see all", "view all", "click here",
        "more", "next", "previous", "sign in", "sign up", "log in",
        "get started", "try free", "contact us", "register now",
        "view more", "explore", "subscribe",
        # topic-filter / category navigation labels common on research/news pages
        "alignment", "economics", "interpretability", "societal impacts",
        "frontier red team", "product", "research", "policy", "news",
        "announcements", "company",
        # Google blog subcategory nav labels
        "google deepmind", "google research", "google labs", "gemini models",
        "quantum computing", "developer tools", "gemini app", "gemini notebook",
        "global network", "google cloud", "safety & security", "google health",
        "google workspace", "google play", "google nest", "chromebook",
        "sustainability", "shopping", "google.org", "public policy",
        "creating opportunity", "around the globe", "life at google",
        # Microsoft topic labels
        "innovation", "digital transformation", "security", "work & life",
        "diversity & inclusion",
        # Generic single-word/short category labels
        "science", "technology", "robotics", "infrastructure",
    }
    _DATE_PAT = r"([A-Za-z]{3}\s+\d{1,2},?\s+20\d{2})"

    def _apex(netloc: str) -> str:
        """Return the company name that owns the domain.

        For brand/vanity TLDs (.google, .amazon, .apple, .microsoft) the TLD
        itself IS the company name, so we return it.  For everything else we
        return the second-to-last label (openai for openai.com, microsoft for
        blogs.microsoft.com, huggingface for huggingface.co, etc.).

        This lets deepmind.google ↔ blog.google and
        microsoft.ai ↔ blogs.microsoft.com be recognised as the same company.
        """
        _BRAND_TLDS = {"google", "amazon", "apple", "microsoft"}
        parts = netloc.lower().replace("www.", "").rstrip(".").split(".")
        if len(parts) == 1:
            return parts[0]
        if parts[-1] in _BRAND_TLDS:
            return parts[-1]
        return parts[-2] if len(parts) >= 2 else parts[0]

    def _parse_inline_date(s: str) -> str:
        m = _re.search(_DATE_PAT, s)
        if m:
            try:
                return _dt.datetime.strptime(m.group(1).replace(",", ""), "%b %d %Y").strftime("%Y-%m-%d")
            except ValueError:
                pass
        return ""

    try:
        req = _Req(page_url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
        })
        with _open(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    if len(html) < 500:
        return []

    parsed_base = _urlparse(page_url)
    base_domain = parsed_base.netloc.lower().replace("www.", "")
    base_apex   = _apex(parsed_base.netloc)

    # Strategy 2: build position-indexed map of <time datetime="..."> dates
    _time_positions: List[tuple] = []
    for tm in _re.finditer(r'<time[^>]+datetime="([^"]*)"', html, _re.I):
        raw_dt = tm.group(1).strip()
        d = ""
        iso_m = _re.match(r"(20\d{2}-\d{2}-\d{2})", raw_dt)
        if iso_m:
            d = iso_m.group(1)
        else:
            for fmt in ("%B %Y", "%b %Y"):
                try:
                    d = _dt.datetime.strptime(raw_dt[:16], fmt).strftime("%Y-%m-01")
                    break
                except ValueError:
                    pass
        if d:
            _time_positions.append((tm.start(), d))

    def _nearest_time_date(pos: int, radius: int = 2000) -> str:
        best, best_dist = "", radius + 1
        for tpos, td in _time_positions:
            dist = abs(tpos - pos)
            if dist < best_dist:
                best_dist, best = dist, td
        return best if best_dist <= radius else ""

    link_re = _re.compile(r'<a\b([^>]*?)>(.*?)</a>', _re.I | _re.S)
    items: List[Dict] = []
    seen_urls: set = set()

    for match in link_re.finditer(html):
        attrs_str  = match.group(1)
        title_html = match.group(2)

        # Extract href from attributes string
        href_m = _re.search(r'\bhref=["\']([^"\'#]+)["\']', attrs_str, _re.I)
        if not href_m:
            continue
        href = href_m.group(1).strip()
        if href.startswith("/"):
            href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
        if not href.startswith("http"):
            continue

        # Domain check: same domain, containment, OR same company apex family
        link_parsed = _urlparse(href)
        link_domain = link_parsed.netloc.lower().replace("www.", "")
        if (base_domain not in link_domain
                and link_domain not in base_domain
                and _apex(link_parsed.netloc) != base_apex):
            continue

        path = link_parsed.path.lower()
        if any(_re.search(pat, path) for pat in _NAV_SKIP):
            continue

        path_parts = [p for p in path.split("/") if p]
        if len(path_parts) < 2:
            continue

        # Strip query/fragment for dedup key
        url_key = f"{link_parsed.scheme}://{link_parsed.netloc}{link_parsed.path}".lower().rstrip("/")
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)

        # Extract title: anchor inner text first, then attribute fallbacks
        raw_text = _re.sub(r"<[^>]+>", "", _unescape(title_html)).strip()
        raw_text = _re.sub(r"\s+", " ", raw_text).strip()
        if not raw_text or len(raw_text) < 5:
            # Fallback: aria-label or data-event-content-name (DeepMind-style overlays).
            # Try both and keep the first that isn't itself a nav label (e.g. "Learn more").
            for attr in ("aria-label", "data-event-content-name"):
                am = _re.search(rf'\b{attr}="([^"]+)"', attrs_str, _re.I)
                if am:
                    candidate = _re.sub(
                        r'\s*[-–]\s*(?:learn more|read more|view post)$',
                        "", am.group(1), flags=_re.I
                    ).strip()
                    if len(candidate) > 5 and candidate.lower() not in _NAV_TITLES:
                        raw_text = candidate
                        break
        if not raw_text or len(raw_text) < 5 or len(raw_text) > 400:
            continue

        # -- Date extraction --
        pub_date = ""

        # Strategy 1: date anywhere in anchor text
        date_m = _re.search(_DATE_PAT, raw_text)
        if date_m:
            pub_date = _parse_inline_date(date_m.group(1))
            before = raw_text[:date_m.start()].strip()
            after  = raw_text[date_m.end():].strip()
            # Use whichever side of the date has more real title content
            raw_text = before if len(before) >= len(after) else after
            # Strip a leading CamelCase category prefix (e.g. "AnnouncementsTitle")
            raw_text = _re.sub(r"^([A-Z][a-z]{3,})(?=[A-Z])", "", raw_text).strip()
            raw_text = _re.sub(r"^([A-Z][a-z]{3,})\s+(?=[A-Z])", "", raw_text).strip()

        # Strategy 2: nearest <time datetime> tag
        if not pub_date:
            pub_date = _nearest_time_date(match.start())

        # Strategy 3: inline date in the 500 HTML chars preceding this anchor
        if not pub_date:
            ctx = html[max(0, match.start() - 500): match.start()]
            # Use the LAST (most recent / closest) date found before this anchor
            ctx_dates = _re.findall(_DATE_PAT, ctx)
            if ctx_dates:
                pub_date = _parse_inline_date(ctx_dates[-1])

        # Strategy 4: date in URL path  /YYYY/MM/DD/
        if not pub_date:
            url_date = _re.search(r"/(20\d{2})[/-](0[1-9]|1[0-2])[/-](\d{2})?", href)
            if url_date:
                y, mo = url_date.group(1), url_date.group(2)
                d = url_date.group(3) or "15"
                pub_date = f"{y}-{mo}-{d}"

        title = raw_text
        if not title or len(title) < 8 or len(title) > 300:
            continue
        if title.lower() in _NAV_TITLES:
            continue

        items.append({"title": title, "url": href, "source": label,
                      "published_at": pub_date, "summary": ""})

    return items


def custom_sources_node(state: NewsCollectionState) -> NewsCollectionState:
    """User-provided custom sources (RSS feed URLs or HTML pages).

    Strategy per URL:
    1. Try RSS/Atom via cmbagent's _fetch_rss_items (date-filtered).
    2. Try cmbagent's _direct_scrape_page_links (requires article-path signals).
    3. Fall back to _scrape_page_permissive which accepts any same-domain link
       — needed for sites like blog.google/* whose article paths don't contain
       /blog/ or /news/ but still produce real articles.
    """
    from urllib.parse import urlparse

    custom_sources = state.get("custom_sources") or []
    if not custom_sources:
        return state

    collected = list(state["collected_items"])
    seen = list(state["seen_keys"])
    errors = list(state["errors"])

    if _news_tools is not None:
        _fetch_rss = getattr(_news_tools, "_fetch_rss_items", None)
        _scrape    = getattr(_news_tools, "_direct_scrape_page_links", None)
    else:
        _fetch_rss = _scrape = None

    for url in custom_sources:
        url = (url or "").strip()
        if not url.startswith("http"):
            continue
        label = (urlparse(url).netloc or "custom").replace("www.", "")[:30]

        # 1. RSS
        if _fetch_rss is not None:
            try:
                rss_items = _fetch_rss(url, label, state["date_from"], state["date_to"])
                if rss_items:
                    before = len(collected)
                    collected, seen = _merge_items(rss_items, collected, seen)
                    print(f"[Collection] Custom/{label} (RSS): {len(collected) - before} items")
                    continue
            except Exception:
                pass

        # 2. cmbagent HTML scraper (signal-filtered)
        scraped: List[Dict] = []
        if _scrape is not None:
            try:
                scraped = _scrape(url, label)
            except Exception:
                pass

        # 3. Permissive fallback if step 2 found nothing
        if not scraped:
            try:
                scraped = _scrape_page_permissive(url, label)
            except Exception as exc:
                errors.append(f"custom/{label}: {exc}")

        if scraped:
            before = len(collected)
            collected, seen = _merge_items(scraped, collected, seen)
            print(f"[Collection] Custom/{label} (HTML): {len(collected) - before} items")

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
    - date_to is treated as end-of-day so articles published on that day
      with a time component (e.g. 15:48:26) are not incorrectly dropped.
    - Items with no date are kept (flagged with _undated=True).
    """
    from datetime import timedelta
    date_from = _parse_date(state["date_from"])
    date_to_dt = _parse_date(state["date_to"])

    if not date_from or not date_to_dt:
        return state

    # Extend date_to to end-of-day so time-stamped articles on that day are kept
    date_to_eod = date_to_dt.replace(hour=23, minute=59, second=59)

    in_range: List[Dict] = []
    undated: List[Dict] = []
    out_of_range = 0

    for item in state["collected_items"]:
        pub = item.get("published_at") or item.get("date") or ""
        pub_dt = _parse_date(pub)
        if pub_dt is None:
            undated.append({**item, "_undated": True})
        elif date_from <= pub_dt <= date_to_eod:
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
    graph.add_node("github_releases",    github_releases_node)
    graph.add_node("company_ddg_news",   company_ddg_news_node)
    graph.add_node("newsapi_gnews",      newsapi_gnews_node)

    # Common feeds + user sources
    graph.add_node("rss_feeds",        rss_feeds_node)
    graph.add_node("custom_sources",   custom_sources_node)

    # Tier 2 — global topic search
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
    graph.add_edge("company_scrape",       "github_releases")
    graph.add_edge("github_releases",      "company_ddg_news")
    graph.add_edge("company_ddg_news",     "newsapi_gnews")
    graph.add_edge("newsapi_gnews",        "rss_feeds")
    graph.add_edge("rss_feeds",            "custom_sources")
    graph.add_edge("custom_sources",       "topic_web_search")
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
