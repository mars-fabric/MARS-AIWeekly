"""
Diff-based content patching service.

Instead of asking an LLM to regenerate an entire document, we ask it to return
small JSON find->replace edits and apply those to the original content.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class EditOperation:
    find: str
    replace: str


@dataclass
class PatchResult:
    content: str
    applied: List[EditOperation] = field(default_factory=list)
    failed: List[EditOperation] = field(default_factory=list)
    method: str = "diff"  # diff | fallback


DIFF_SYSTEM_PROMPT = """\
You are a precise document-editing assistant.

TASK: Given the user's full document and their edit request, produce a JSON
array of find-and-replace operations that satisfy the request.

RULES:
1. Return ONLY a valid JSON array (no markdown fences, no commentary).
2. Each element must contain keys:
   - "find": exact substring to locate (include whitespace/line breaks exactly)
   - "replace": replacement text
3. Use the minimum number of edits.
4. Do not modify text the user did not ask to change.
5. For deletion use "replace": "".
6. For insertion use "find" as anchor text and "replace" as anchor+inserted text.
"""


FALLBACK_SYSTEM_PROMPT = """\
You are helping refine a document.

CRITICAL:
- Return the COMPLETE updated document, not a fragment.
- Preserve unchanged sections exactly unless requested to change them.
- No commentary, no markdown fences, no preamble.
"""


def build_diff_prompt(content: str, user_request: str) -> str:
    return f"--- DOCUMENT ---\n{content}\n\n--- EDIT REQUEST ---\n{user_request}"


def build_fallback_prompt(content: str, user_request: str) -> str:
    return (
        f"--- CURRENT CONTENT (FULL DOCUMENT) ---\n{content}\n\n"
        f"--- USER REQUEST ---\n{user_request}\n\n"
        "Return the COMPLETE updated document with the changes applied."
    )


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()


def parse_edit_operations(raw_response: str) -> List[EditOperation]:
    cleaned = _strip_markdown_fences(raw_response)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        fixed = re.sub(r',\s*([}\]])', r'\1', cleaned)
        data = json.loads(fixed)

    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")

    ops: List[EditOperation] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Edit #{i} is not an object")
        find_val = item.get("find")
        replace_val = item.get("replace")
        if find_val is None or replace_val is None:
            raise ValueError(f"Edit #{i} missing find/replace")
        ops.append(EditOperation(find=str(find_val), replace=str(replace_val)))

    if not ops:
        raise ValueError("LLM returned empty edit array")

    return ops


def _normalize_ws(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def _fuzzy_find(content: str, target: str) -> Optional[Tuple[int, int]]:
    idx = content.find(target)
    if idx != -1:
        return idx, idx + len(target)

    norm_target = _normalize_ws(target)
    pattern_parts = [re.escape(tok) for tok in norm_target.split(' ') if tok]
    if pattern_parts:
        ws_pattern = re.compile(r'\s+'.join(pattern_parts), re.DOTALL)
        m = ws_pattern.search(content)
        if m:
            return m.start(), m.end()

    lines = [ln.strip() for ln in target.strip().splitlines() if ln.strip()]
    if len(lines) >= 2:
        anchor = re.compile(re.escape(lines[0]) + r'.*?' + re.escape(lines[-1]), re.DOTALL)
        m = anchor.search(content)
        if m:
            return m.start(), m.end()

    return None


def apply_patches(content: str, operations: List[EditOperation]) -> PatchResult:
    result = PatchResult(content=content, method="diff")

    for op in operations:
        span = _fuzzy_find(result.content, op.find)
        if span is None:
            result.failed.append(op)
            logger.warning("diff_patch_miss find=%r", op.find[:80])
            continue

        start, end = span
        result.content = result.content[:start] + op.replace + result.content[end:]
        result.applied.append(op)

    return result


def refine_with_diff(
    content: str,
    user_request: str,
    *,
    llm_call,
    model: str = "gpt-4o",
    temperature: float = 0.4,
    fallback_temperature: float = 0.7,
) -> PatchResult:
    try:
        diff_response = llm_call(
            messages=[
                {"role": "system", "content": DIFF_SYSTEM_PROMPT},
                {"role": "user", "content": build_diff_prompt(content, user_request)},
            ],
            model=model,
            temperature=temperature,
            max_tokens=4096,
        )

        operations = parse_edit_operations(diff_response)
        result = apply_patches(content, operations)

        if result.applied:
            if result.failed:
                logger.warning("diff_patch_partial applied=%d failed=%d", len(result.applied), len(result.failed))
            else:
                logger.info("diff_patch_success edits_applied=%d", len(result.applied))
            return result

        logger.warning("diff_patch_all_failed count=%d, falling back", len(result.failed))
    except Exception as exc:
        logger.warning("diff_patch_failed error=%s, falling back", exc)

    estimated_tokens = len(content) // 3
    fallback_max_tokens = min(max(4096, int(estimated_tokens * 1.5)), 16384)

    fallback_response = llm_call(
        messages=[
            {"role": "system", "content": FALLBACK_SYSTEM_PROMPT},
            {"role": "user", "content": build_fallback_prompt(content, user_request)},
        ],
        model=model,
        temperature=fallback_temperature,
        max_tokens=fallback_max_tokens,
    )

    return PatchResult(content=fallback_response, method="fallback")
