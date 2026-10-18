"""Prompts for AI Weekly stages."""

# Primary agents per stage (int key) + sub-task agents (string key)
STAGE_AGENTS = {
    # Stage 2 — Content Curation
    2: "researcher",              # curate + merge
    "2_enrich": "web_surfer",     # enrich articles with missing summaries by browsing real URLs
    "2_summarize": "summarizer",  # compress uploaded documents into structured entries
    # Stage 3 — Report Generation
    3: "researcher",              # write final report
    "3_citations": "perplexity",  # academic citation enrichment for arXiv items
    # Stage 4 — Quality Review
    4: "researcher",              # critic + editor
    "4_verify": "web_surfer",     # verify report URLs are accessible and match content
}

_OUTPUT_RULES = (
    "\n\nReturn ONLY plain markdown. No code blocks, no HTML comments, no ```markdown fences."
)

# ── Stage 2 — Content Curation (researcher) ───────────────────────────────────

curation_researcher_prompt = (
    "Curate the raw AI news collection below for {date_from} to {date_to}.\n"
    "Topics: {topics}\n\n"
    "For each unique story: title | organization | YYYY-MM-DD date | 2-sentence summary | all source URLs (official first).\n"
    "Merge duplicates into one entry. Drop anything outside the date range or unrelated to AI."
    + _OUTPUT_RULES
    + "\n\n---\nRaw Collection:\n{raw_collection}\n"
)

curation_merge_prompt = (
    "Merge these {num_parts} partial curation results into one deduplicated master list for {date_from} to {date_to}.\n"
    "Combine duplicate stories (keep all source URLs). Preserve every unique item. Sort newest first."
    + _OUTPUT_RULES
    + "\n\n---\nPartial Results:\n{partial_curations}\n"
)

# ── Stage 2 — URL Enrichment (web_surfer) ────────────────────────────────────

enrich_urls_prompt = (
    "Browse each URL below and extract the real article content.\n"
    "For each: verify the title, write a 2-3 sentence summary of what was actually announced.\n"
    "Return: - **Exact Title** | Organization | Date | Summary | URL"
    + _OUTPUT_RULES
    + "\n\n---\nArticles to enrich:\n{items_with_urls}\n"
)

# ── Stage 2 — Document Summarization (summarizer) ────────────────────────────

document_summarize_prompt = (
    "Extract all distinct AI/ML news items from this document ({filename}).\n"
    "For each item: - **Title** | Organization | YYYY-MM-DD | 2-sentence summary | URL (if present)\n"
    "Only include factual content from the document."
    + _OUTPUT_RULES
    + "\n\n---\nDocument:\n{document_text}\n"
)

# ── Stage 3 — Academic Citations (perplexity) ────────────────────────────────
# perplexity receives a paragraph of text and returns it UNCHANGED except for
# inline arXiv citations added as [1], [2], etc. — pass analyst_text directly.

citation_prompt = "{analyst_text}"

# ── Stage 3 — Report Writing (researcher) ────────────────────────────────────

generation_analyst_prompt = (
    "Analyze the curated AI news below ({date_from} to {date_to}).\n"
    "Outline: 3-5 themes with item-to-theme mapping, impact rank (high/medium/low), 3-sentence executive summary draft."
    + _OUTPUT_RULES
    + "\n\n---\nCurated Items:\n{curated_items}\n"
)

generation_writer_prompt = (
    "Write the AI Weekly Report ({date_from} to {date_to}, style: {style}).\n\n"
    "Sections:\n"
    "1. # AI Weekly Report ({date_from} to {date_to})\n"
    "2. ## Executive Summary — 3-4 sentences\n"
    "3. ## Key Highlights — grouped by ### YYYY-MM-DD, each item ends with [Source](url)\n"
    "4. ## Trends & Strategic Implications — 3-5 themes from the data\n"
    "5. ## Quick Reference Table — | Date | Title | Organization | [Link](url) |\n"
    "6. ## References — | # | Source | URL |\n\n"
    "{style_rule} Use only URLs from curated data."
    + _OUTPUT_RULES
    + "\n\n---\nAnalyst Outline:\n{report_outline}\n\n"
    "---\nAcademic Citations:\n{citations}\n\n"
    "---\nEnriched Articles:\n{enriched_data}\n\n"
    "---\nCurated Items:\n{curated_items}\n"
)

merge_partials_prompt = (
    "Merge these {num_parts} partial AI Weekly Reports into one complete report ({date_from} to {date_to}, style: {style}).\n"
    "Include every item. Deduplicate. Keep all [Source](url) links. {style_rule}"
    + _OUTPUT_RULES
    + "\n\n---\nPartial Reports:\n{partial_reports}\n"
)

# ── Stage 4 — URL Verification (web_surfer) ──────────────────────────────────

url_verify_prompt = (
    "Browse each URL below from an AI Weekly report.\n"
    "For each: is it accessible? Does the page content match an AI news story?\n"
    "Return a table: | URL | Accessible | Matches AI news | Notes |"
    + _OUTPUT_RULES
    + "\n\n---\nURLs:\n{report_urls}\n"
)

# ── Stage 4 — Quality Review (researcher critic + editor) ────────────────────

review_critic_prompt = (
    "Audit this AI Weekly Report draft ({date_from} to {date_to}) against the curated source data.\n"
    "List only corrections needed: missing items, wrong dates/orgs, missing [Source](url) links, bad URLs, structure issues.\n"
    "Format: numbered list. End with **TOTAL: X corrections**."
    + _OUTPUT_RULES
    + "\n\n---\nDraft:\n{draft_report}\n\n---\nCurated Data:\n{curated_items}\n"
)

review_editor_prompt = (
    "Apply the critic's corrections to the draft report ({date_from} to {date_to}, style: {style}).\n"
    "Patch only what the critic flagged. Copy everything else exactly. {expand_instruction} {style_rule}\n"
    "Every highlight must end with [Source](url). Use only URLs from curated data."
    + _OUTPUT_RULES
    + "\n\n---\nCorrections:\n{review_critique}\n\n---\nDraft:\n{draft_report}\n\n---\nCurated Data:\n{curated_items}\n"
)
