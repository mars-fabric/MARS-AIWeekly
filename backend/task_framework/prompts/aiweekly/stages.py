"""Prompts for AI Weekly stages — multi-pass pipeline."""

# Per-stage primary agent type (used for model config lookup)
STAGE_AGENTS = {
    2: "researcher",
    3: "researcher",
    4: "researcher",
}

# Instruction appended to every prompt to prevent common LLM artifacts
_OUTPUT_RULES = (
    "\n\nOUTPUT RULES:\n"
    "- Return ONLY plain markdown. No code, no scripts, no file-saving logic.\n"
    "- Do NOT wrap your output in a Python script (no content='...', no open(), no f.write()).\n"
    "- Do NOT add HTML comments (e.g. <!-- filename: ... -->).\n"
    "- Do NOT wrap output in ```markdown fences.\n"
    "- Start directly with the content.\n"
)

# ═══════════════════════════════════════════════════════════════════════════
# Stage 2 — Content Curation
# ═══════════════════════════════════════════════════════════════════════════

curation_researcher_prompt = (
    "Curate this raw news collection into a validated, deduplicated master list.\n"
    "\n"
    "**Date Range:** {date_from} to {date_to} | **Topics:** {topics}\n"
    "\n"
    "Rules:\n"
    "- ONLY items present in raw data — zero hallucination\n"
    "- Deduplicate by TOPIC: if multiple articles cover the SAME story/announcement, \n"
    "  merge them into ONE curated item but list ALL source URLs\n"
    "- Each item: title, organization, date (YYYY-MM-DD), ALL source URLs, 2-3 sentence summary\n"
    "- Remove non-AI items, items outside date range, items without real URLs\n"
    "- Sort newest first; keep diverse orgs\n"
    "\n"
    "Output per item:\n"
    "- **[Title]** | [Organization] | [YYYY-MM-DD]\n"
    "  [Summary from source data only]\n"
    "  Sources: [URL1], [URL2], ...  (list ALL unique URLs that cover this story)\n"
    + _OUTPUT_RULES +
    "---\n"
    "Raw Collection:\n"
    "{raw_collection}\n"
)

# ═══════════════════════════════════════════════════════════════════════════
# Stage 3 — Report Generation  (two passes: analyst → writer)
# ═══════════════════════════════════════════════════════════════════════════

generation_analyst_prompt = (
    "Analyze curated news and produce a REPORT OUTLINE (not the full report).\n"
    "\n"
    "**Period:** {date_from} to {date_to} | **Style:** {style} | **Topics:** {topics}\n"
    "\n"
    "Deliver:\n"
    "1. **Themes** — 3-5 major themes, each backed by ≥2 items from different orgs\n"
    "2. **Item→Theme mapping** — assign every curated item to one theme\n"
    "3. **Impact rank** — high/medium/low per item within each theme\n"
    "4. **Cross-cutting patterns** — connections between themes\n"
    "5. **Executive Summary blueprint** — top 3-4 developments + one-line justification\n"
    "6. **Coverage gaps** — topics with zero/weak coverage\n"
    "\n"
    "Use ONLY facts from the curated data. Bullet points only, no prose."
    + _OUTPUT_RULES +
    "---\n"
    "Curated Items:\n"
    "{curated_items}\n"
)

generation_writer_prompt = (
    "Write the AI Weekly Report from the analyst outline and curated data.\n"
    "\n"
    "**Period:** {date_from} to {date_to} | **Style:** {style} | **Topics:** {topics}\n"
    "\n"
    "Structure (exactly 5 sections):\n"
    "# AI Weekly Report ({date_from} to {date_to})\n"
    "## Executive Summary — 3-4 sentences, lead with highest-impact\n"
    "## Key Highlights — group by date (### YYYY-MM-DD), each item:\n"
    "  - **[Title]** — [Org] + description per style + [Source](url)\n"
    "## Trends & Strategic Implications — 3-5 analyst themes with evidence\n"
    "## Quick Reference Table — markdown table with these columns:\n"
    "  | Date | Title | Organization | Source |\n"
    "  The Source column MUST be a clickable markdown link: [Link](actual_url)\n"
    "  Example: | 2026-04-25 | GPT-5 Launch | OpenAI | [Link](https://openai.com/gpt5) |\n"
    "## References — markdown table of all source URLs cited:\n"
    "  | # | Source | URL |\n"
    "  Example: | 1 | OpenAI Blog | [https://openai.com/gpt5](https://openai.com/gpt5) |\n"
    "\n"
    "CRITICAL: Every item in Key Highlights MUST end with a clickable source link \n"
    "in the format [Source](url). Use ONLY URLs from the curated data — never fabricate.\n"
    "The Quick Reference Table Link column and References URL column MUST be clickable markdown links.\n"
    "Do NOT write just 'Link' — always use [Link](actual_url) format.\n"
    "{style_rule}"
    + _OUTPUT_RULES +
    "---\n"
    "Analyst Outline:\n"
    "{report_outline}\n"
    "\n---\n"
    "Curated Items:\n"
    "{curated_items}\n"
)

# ═══════════════════════════════════════════════════════════════════════════
# Stage 4 — Quality Review  (two passes: critic → editor)
# ═══════════════════════════════════════════════════════════════════════════

review_critic_prompt = (
    "Audit this AI Weekly Report draft against the curated source data.\n"
    "Produce a numbered CORRECTIONS LIST only — do NOT rewrite the report.\n"
    "\n"
    "**Period:** {date_from} to {date_to} | **Style:** {style}\n"
    "\n"
    "Check:\n"
    "1. Missing items — curated items absent from report\n"
    "2. Fact mismatches — wrong dates/names/orgs vs curated data\n"
    "3. Fabricated or missing URLs — every highlight MUST have a [Source](url) link\n"
    "4. Org/topic balance\n"
    "5. Structure — all 5 sections present (incl. References)?\n"
    "6. Title-only entries needing {word_rule}\n"
    "7. Duplicates, placeholders, unsupported superlatives\n"
    "8. Quick Reference Table — Link column must be [Link](url), NOT plain text 'Link'\n"
    "9. References section — must be a table with clickable URLs, listing all cited sources\n"
    "\n"
    "Format: 1. [TAG] description ... End with: **TOTAL: X corrections**"
    + _OUTPUT_RULES +
    "---\n"
    "Draft Report:\n"
    "{draft_report}\n"
    "\n---\n"
    "Curated Source Data:\n"
    "{curated_items}\n"
)

review_editor_prompt = (
    "Produce the FINAL publication-ready AI Weekly Report.\n"
    "\n"
    "**Period:** {date_from} to {date_to} | **Style:** {style}\n"
    "\n"
    "Apply EVERY correction from the critic:\n"
    "- Add missing items, fix fact mismatches, fix/remove bad URLs\n"
    "- {expand_instruction}\n"
    "- Remove duplicates, placeholders, unsupported superlatives\n"
    "\n"
    "Ensure: 5 sections (Executive Summary, Key Highlights, Trends, Quick Reference Table, References).\n"
    "Every item in Key Highlights MUST have a clickable [Source](url) link from curated data.\n"
    "Quick Reference Table Source column: [Link](actual_url) — NOT just 'Link'.\n"
    "References section: table with | # | Source | URL | where URL is [clickable](url).\n"
    "Date-grouped highlights, {word_rule} per item, table matches body.\n"
    "Fact-check every edit against curated data.\n"
    "{style_rule}"
    + _OUTPUT_RULES +
    "---\n"
    "Critic Corrections:\n"
    "{review_critique}\n"
    "\n---\n"
    "Draft Report:\n"
    "{draft_report}\n"
    "\n---\n"
    "Curated Source Data:\n"
    "{curated_items}\n"
)

# ═══════════════════════════════════════════════════════════════════════════
# Merge prompt — combines partial reports from chunked generation
# ═══════════════════════════════════════════════════════════════════════════

merge_partials_prompt = (
    "Merge these partial AI Weekly Report sections into ONE cohesive report.\n"
    "\n"
    "**Period:** {date_from} to {date_to} | **Style:** {style} | **Topics:** {topics}\n"
    "\n"
    "You are given {num_parts} partial reports (Part 1, Part 2, …). Each covers a "
    "different subset of curated news items. Combine them into a SINGLE report.\n"
    "\n"
    "Structure (exactly 5 sections):\n"
    "# AI Weekly Report ({date_from} to {date_to})\n"
    "## Executive Summary — synthesize ALL parts into 3-4 sentences\n"
    "## Key Highlights — merge all items, group by date (### YYYY-MM-DD), "
    "newest first. Each item: **[Title]** — [Org] + description + [Source](url)\n"
    "## Trends & Strategic Implications — unify themes from all parts\n"
    "## Quick Reference Table — | Title | Org | Date | Link | for ALL items\n"
    "## References — numbered list of ALL source URLs cited\n"
    "\n"
    "Rules:\n"
    "- Include EVERY item from every part — do NOT drop any\n"
    "- Deduplicate if same item appears in multiple parts\n"
    "- Keep all [Source](url) links from partials — never fabricate new URLs\n"
    "- Do NOT add items not present in any partial\n"
    "{style_rule}"
    + _OUTPUT_RULES +
    "---\n"
    "Partial Reports:\n"
    "{partial_reports}\n"
)

# ═══════════════════════════════════════════════════════════════════════════
# Curation merge prompt — consolidates partial curation chunks
# ═══════════════════════════════════════════════════════════════════════════

curation_merge_prompt = (
    "Merge and deduplicate these partial curation results into a single master curated list.\n"
    "\n"
    "**Date Range:** {date_from} to {date_to} | **Topics:** {topics}\n"
    "\n"
    "You are given {num_parts} partial curation results. Each was curated from a different "
    "subset of the raw collection. Combine them into ONE consolidated list.\n"
    "\n"
    "Rules:\n"
    "- Include EVERY unique item from all parts — do NOT drop any\n"
    "- Deduplicate by TOPIC: if the same news story appears in multiple parts, "
    "merge into ONE item but combine ALL source URLs\n"
    "- Preserve the FULL summary text — do not shorten or omit descriptions\n"
    "- Keep the exact format:\n"
    "  - **[Title]** | [Organization] | [YYYY-MM-DD]\n"
    "    [Full summary]\n"
    "    Sources: [URL1], [URL2], ...\n"
    "- Sort newest first\n"
    "- Final count MUST be >= items in the largest partial (you are MERGING not filtering)\n"
    + _OUTPUT_RULES +
    "---\n"
    "Partial Curation Results ({num_parts} parts):\n"
    "{partial_curations}\n"
)
