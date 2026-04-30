"""
AI Weekly Report endpoints.

task_framework pipeline using one_shot(agent='researcher'):
  1. Data Collection — Direct tool calls (RSS, APIs, web search)
  2. Content Curation — one_shot researcher to deduplicate/validate/enrich
  3. Report Generation — one_shot researcher to write 4-section report
  4. Quality Review — one_shot researcher to polish + programmatic verification
"""

import asyncio
import json
import mimetypes
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from models.aiweekly_schemas import (
    AIWeeklyCreateRequest,
    AIWeeklyCreateResponse,
    AIWeeklyExecuteRequest,
    AIWeeklyStageResponse,
    AIWeeklyStageContentResponse,
    AIWeeklyContentUpdateRequest,
    AIWeeklyRefineRequest,
    AIWeeklyRefineResponse,
    AIWeeklyTaskStateResponse,
    AIWeeklyRecentTaskResponse,
)
from core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/aiweekly", tags=["AI Weekly Report"])


# =============================================================================
# Stage definitions
# =============================================================================
STAGE_DEFS = [
    {"number": 1, "name": "data_collection",     "shared_key": "raw_collection",  "file": "collection.md"},
    {"number": 2, "name": "content_curation",     "shared_key": "curated_items",   "file": "curated.md"},
    {"number": 3, "name": "report_generation",    "shared_key": "draft_report",    "file": "report_draft.md"},
    {"number": 4, "name": "quality_review",       "shared_key": "final_report",    "file": "report_final.md"},
]

STAGE_NAMES = {d["number"]: d["name"] for d in STAGE_DEFS}


def _get_default_model() -> str:
    try:
        from cmbagent.config import get_workflow_config
        return get_workflow_config().default_llm_model
    except Exception:
        return "gpt-4o"


# =============================================================================
# Background task tracking
# =============================================================================
_running_tasks: Dict[str, asyncio.Task] = {}
_console_buffers: Dict[str, List[str]] = {}
_console_lock = threading.Lock()


class _ConsoleCapture:
    """Thread-safe stdout capture for streaming console to UI."""

    # Lines matching these patterns are noise — never show in UI
    _NOISE_PATTERNS = (
        "DeprecationWarning:",
        "UserWarning:",
        "warnings.warn(",
        "/site-packages/",
        ".venv/lib/python",
        "FutureWarning:",
        "RuntimeWarning:",
        "/home/",
        "/tmp/",
        "/root/",
        "/usr/",
        "/opt/",
        "C:\\",
        "Desktop/",
        "register_hand_off",
        "register_nested_chats",
        "TransformMessages",
        "MessageHistoryLimiter",
        "MessageContentTruncator",
        "apply_transform",
        "content truncated:",
        "agent_obj.agent",
        "Applied content truncator",
        "Applied history limiter",
        "REGISTERING AGENT",
        "register_reply",
        "Registering function",
        "register_function",
        "ConversableAgent",
        "GroupChat",
        "GroupChatManager",
        "initiate_chat",
        "assistant_agent",
        "Traceback (most recent",
        "  File \"",
        "DEBUG:",
        "debug_print",
        "cmbagent.handoffs",
        "cmbagent.workflows",
        "autogen.",
        "ag2.",
        "openai.",
        "httpx.",
        "httpcore.",
        "model_config",
        "researcher_model",
        "default_llm_model",
        "default_formatter_model",
    )

    # Suppress agent code-output lines from the console stream
    _CODE_PATTERNS = (
        "import os",
        "content = '",
        'content = "',
        "content = '''",
        'content = """',
        "filename = ",
        "filepath = ",
        "os.path.join(",
        "with open(",
        "f.write(",
        "print(f'Saved",
        'print(f"Saved',
    )

    def __init__(self, buf_key: str, original):
        self._buf_key = buf_key
        self._original = original

    def write(self, text: str):
        if self._original:
            self._original.write(text)
        if text.strip():
            stripped = text.strip()
            if any(p in text for p in self._NOISE_PATTERNS):
                return
            if any(stripped.startswith(p) for p in self._CODE_PATTERNS):
                return
            with _console_lock:
                _console_buffers.setdefault(self._buf_key, []).append(text.rstrip())

    def flush(self):
        if self._original:
            self._original.flush()

    def isatty(self):
        return False

    def fileno(self):
        if self._original:
            return self._original.fileno()
        raise AttributeError("no fileno")


def _get_console_lines(buf_key: str, since_index: int = 0) -> List[str]:
    with _console_lock:
        buf = _console_buffers.get(buf_key, [])
        return buf[since_index:]


# =============================================================================
# one_shot sync helper
# =============================================================================

def _patch_solve_once():
    """Monkey-patch CMBAgent.solve to enforce agent_for_sub_task in one_shot mode.

    cmbagent's control agent LLM sometimes overrides the initial_agent choice
    (e.g. picks 'engineer' when 'researcher' was requested). We fix this by
    strengthening current_instructions so the control agent cannot deviate.
    """
    from cmbagent.cmbagent import CMBAgent
    _original_solve = CMBAgent.solve

    def _patched_solve(self, task, initial_agent='task_improver', shared_context=None,
                       mode="default", step=None, max_rounds=10):
        if mode == "one_shot" and initial_agent == "researcher":
            shared_context = dict(shared_context or {})
            shared_context.setdefault(
                "current_instructions",
                f"Use ONLY the researcher agent. Do NOT use the engineer agent. "
                f"The researcher will produce the output directly as text."
            )
        return _original_solve(self, task, initial_agent=initial_agent,
                               shared_context=shared_context, mode=mode,
                               step=step, max_rounds=max_rounds)

    CMBAgent.solve = _patched_solve

_patch_solve_once()


def _run_one_shot_sync(**kwargs) -> Dict[str, Any]:
    """Synchronous wrapper around cmbagent.one_shot for asyncio.to_thread."""
    import cmbagent
    return cmbagent.one_shot(**kwargs)


# =============================================================================
# Helper: build shared state from prior stages
# =============================================================================
def _build_shared_state(task_id: str, stage_num: int, task_config: dict) -> dict:
    from services.file_task_store import get_completed_stages

    shared: dict = {"task_config": task_config}
    prior = get_completed_stages(task_id, before_stage=stage_num)
    for s in prior:
        od = s.get("output_data")
        if od and isinstance(od, dict):
            shared.update(od.get("shared", {}))
    return shared


# =============================================================================
# task_framework one_shot stage execution
# =============================================================================

async def _run_aiweekly_one_shot_stage(
    task_id: str,
    stage_num: int,
    buf_key: str,
    work_dir: str,
    task_config: dict,
    shared_state: Dict[str, Any],
    config_overrides: Dict[str, Any],
    callbacks=None,
) -> Dict[str, Any]:
    """Run a single AI Weekly stage via one_shot with aiweekly_helpers.

    Stage 1: non-LLM data collection via aiweekly_helpers.run_data_collection
    Stages 2-4: one_shot(agent='researcher')
    """
    from backend.task_framework import aiweekly_helpers as helpers

    stage_def = STAGE_DEFS[stage_num - 1]
    stage_name = stage_def["name"]
    shared_key = stage_def["shared_key"]
    file_name = stage_def["file"]

    date_from = task_config.get("date_from", "")
    date_to = task_config.get("date_to", "")
    topics = task_config.get("topics", [])
    sources = task_config.get("sources", [])
    custom_sources = task_config.get("custom_sources", [])
    style = task_config.get("style", "concise")

    if stage_num == 1:
        # Data collection — no LLM, direct API calls
        with _console_lock:
            _console_buffers.setdefault(buf_key, []).append(
                "Running data collection (APIs, RSS, web search)..."
            )

        original_stdout, original_stderr = sys.stdout, sys.stderr
        capture_out = _ConsoleCapture(buf_key, original_stdout)
        capture_err = _ConsoleCapture(buf_key, original_stderr)

        try:
            sys.stdout = capture_out
            sys.stderr = capture_err

            output_data = await asyncio.to_thread(
                helpers.run_data_collection,
                date_from=date_from,
                date_to=date_to,
                sources=sources,
                custom_sources=custom_sources,
                work_dir=work_dir,
            )
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr

        item_count = output_data.get("artifacts", {}).get("item_count", 0)
        with _console_lock:
            _console_buffers.setdefault(buf_key, []).append(
                f"Data collection complete — {item_count} items"
            )
        return output_data

    # Stages 2-4: build kwargs, run one_shot (multi-pass for stages 3 & 4)
    if stage_num == 2:
        raw_collection = shared_state.get("raw_collection", "")

        # Compact then split into chunks using token-aware budget
        compact = helpers._compact_collection_for_prompt(raw_collection)
        model_for_budget = config_overrides.get("model", "gpt-4o")
        chunk_budget = helpers._get_chunk_budget(model_for_budget)
        chunks = helpers.split_collection_items(compact, target_chars=chunk_budget)

        with _console_lock:
            _console_buffers.setdefault(buf_key, []).append(
                f"Curating collection ({len(chunks)} chunk(s), budget={chunk_budget} chars/chunk)..."
            )

        if len(chunks) == 1:
            # Single chunk — standard path
            kwargs = helpers.build_curation_kwargs(
                raw_collection=chunks[0],
                date_from=date_from,
                date_to=date_to,
                topics=topics,
                work_dir=work_dir,
                config_overrides=config_overrides,
                callbacks=callbacks,
                _pre_compacted=True,
            )
        else:
            # Multiple chunks — run curation per chunk, then LLM merge
            partial_results: list[str] = []
            all_chat_history: list = []
            for ci, chunk in enumerate(chunks, 1):
                with _console_lock:
                    _console_buffers.setdefault(buf_key, []).append(
                        f"Curating chunk {ci}/{len(chunks)}..."
                    )
                chunk_kwargs = helpers.build_curation_kwargs(
                    raw_collection=chunk,
                    date_from=date_from,
                    date_to=date_to,
                    topics=topics,
                    work_dir=work_dir,
                    config_overrides=config_overrides,
                    callbacks=callbacks,
                    _pre_compacted=True,
                )
                original_stdout, original_stderr = sys.stdout, sys.stderr
                capture_out = _ConsoleCapture(buf_key, original_stdout)
                capture_err = _ConsoleCapture(buf_key, original_stderr)
                try:
                    sys.stdout = capture_out
                    sys.stderr = capture_err
                    chunk_result = await asyncio.to_thread(
                        _run_one_shot_sync, **chunk_kwargs,
                    )
                finally:
                    sys.stdout = original_stdout
                    sys.stderr = original_stderr

                partial = helpers.extract_stage_result(chunk_result)
                helpers.save_stage_file(partial, work_dir, f"curated_part_{ci}.md")
                partial_results.append(partial)
                all_chat_history.extend(chunk_result.get("chat_history", []))

            # Step 1: Programmatic dedup merge
            combined = helpers.merge_curated_chunks(partial_results)
            helpers.save_stage_file(combined, work_dir, "curated_merged_raw.md")

            with _console_lock:
                _console_buffers.setdefault(buf_key, []).append(
                    f"All {len(chunks)} chunks curated ({len(combined)} chars). "
                    "Running LLM merge/dedup pass..."
                )

            # Step 2: LLM merge pass — consolidate and deduplicate properly
            # Check if combined fits in one LLM call; if so, run merge
            combined_fits, _ = helpers.fit_content_to_context(
                combined, model_for_budget, reserved_tokens=6000
            )

            merge_kwargs = helpers.build_curation_merge_kwargs(
                partial_curations=partial_results,
                date_from=date_from,
                date_to=date_to,
                topics=topics,
                work_dir=work_dir,
                config_overrides=config_overrides,
                callbacks=callbacks,
            )

            original_stdout, original_stderr = sys.stdout, sys.stderr
            capture_out = _ConsoleCapture(buf_key, original_stdout)
            capture_err = _ConsoleCapture(buf_key, original_stderr)
            try:
                sys.stdout = capture_out
                sys.stderr = capture_err
                merge_result = await asyncio.to_thread(
                    _run_one_shot_sync, **merge_kwargs,
                )
            finally:
                sys.stdout = original_stdout
                sys.stderr = original_stderr

            merged_content = helpers.extract_stage_result(merge_result)
            all_chat_history.extend(merge_result.get("chat_history", []))

            # Safety check: if LLM merge is shorter than programmatic merge,
            # the LLM dropped items — use the programmatic merge instead
            if len(merged_content) < len(combined) * 0.7:
                logger.warning(
                    "LLM merge lost data (%d vs %d chars), using programmatic merge",
                    len(merged_content), len(combined),
                )
                merged_content = combined

            file_path = helpers.save_stage_file(merged_content, work_dir, file_name)

            with _console_lock:
                _console_buffers.setdefault(buf_key, []).append(
                    f"{stage_name} complete — {len(merged_content)} chars ({len(chunks)} chunks merged)"
                )

            output_data: Dict[str, Any] = {
                "shared": {**shared_state, shared_key: merged_content},
                "artifacts": {
                    file_name: file_path,
                    "orchestration": "one_shot",
                    "num_chunks": len(chunks),
                },
                "chat_history": all_chat_history,
            }
            return output_data

    elif stage_num == 3:
        curated_items = shared_state.get("curated_items", "")

        # ── Pass A: Analyst — theme analysis + report outline ──
        with _console_lock:
            _console_buffers.setdefault(buf_key, []).append(
                "Running analyst pass (theme analysis & report outline)..."
            )

        analysis_kwargs = helpers.build_generation_analysis_kwargs(
            curated_items=curated_items,
            date_from=date_from,
            date_to=date_to,
            style=style,
            topics=topics,
            work_dir=work_dir,
            config_overrides=config_overrides,
            callbacks=callbacks,
        )

        original_stdout, original_stderr = sys.stdout, sys.stderr
        capture_out = _ConsoleCapture(buf_key, original_stdout)
        capture_err = _ConsoleCapture(buf_key, original_stderr)
        try:
            sys.stdout = capture_out
            sys.stderr = capture_err
            analysis_result = await asyncio.to_thread(
                _run_one_shot_sync, **analysis_kwargs,
            )
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr

        report_outline = helpers.extract_stage_result(analysis_result)
        helpers.save_stage_file(report_outline, work_dir, "report_outline.md")

        # ── Pass B: Writer — chunked generation ──
        chunk_budget = helpers._get_chunk_budget(config_overrides.get("model", "gpt-4o"))
        chunks = helpers.split_curated_items(curated_items, target_chars=chunk_budget)

        with _console_lock:
            _console_buffers.setdefault(buf_key, []).append(
                f"Analyst pass complete — {len(report_outline)} chars. "
                f"Running writer pass ({len(chunks)} chunk(s))..."
            )

        if len(chunks) == 1:
            kwargs = helpers.build_generation_kwargs(
                curated_items=curated_items,
                date_from=date_from,
                date_to=date_to,
                style=style,
                topics=topics,
                work_dir=work_dir,
                report_outline=report_outline,
                config_overrides=config_overrides,
                callbacks=callbacks,
            )
        else:
            # Multiple chunks — run writer per chunk, then LLM merge into final report
            partial_reports: list[str] = []
            all_chat_history: list = []
            for ci, chunk in enumerate(chunks, 1):
                with _console_lock:
                    _console_buffers.setdefault(buf_key, []).append(
                        f"Writing report part {ci}/{len(chunks)}..."
                    )
                chunk_kwargs = helpers.build_generation_kwargs(
                    curated_items=chunk,
                    date_from=date_from,
                    date_to=date_to,
                    style=style,
                    topics=topics,
                    work_dir=work_dir,
                    report_outline=report_outline,
                    config_overrides=config_overrides,
                    callbacks=callbacks,
                )
                original_stdout, original_stderr = sys.stdout, sys.stderr
                capture_out = _ConsoleCapture(buf_key, original_stdout)
                capture_err = _ConsoleCapture(buf_key, original_stderr)
                try:
                    sys.stdout = capture_out
                    sys.stderr = capture_err
                    chunk_result = await asyncio.to_thread(
                        _run_one_shot_sync, **chunk_kwargs,
                    )
                finally:
                    sys.stdout = original_stdout
                    sys.stderr = original_stderr

                partial = helpers.extract_stage_result(chunk_result)
                helpers.save_stage_file(partial, work_dir, f"report_part_{ci}.md")
                partial_reports.append(partial)
                all_chat_history.extend(chunk_result.get("chat_history", []))

            with _console_lock:
                _console_buffers.setdefault(buf_key, []).append(
                    f"All {len(chunks)} parts written. Running LLM merge into unified report..."
                )

            # Use the merge_partials_prompt to properly combine reports
            merge_kwargs = helpers.build_merge_kwargs(
                partial_reports=partial_reports,
                date_from=date_from,
                date_to=date_to,
                style=style,
                topics=topics,
                work_dir=work_dir,
                config_overrides=config_overrides,
                callbacks=callbacks,
            )

            original_stdout, original_stderr = sys.stdout, sys.stderr
            capture_out = _ConsoleCapture(buf_key, original_stdout)
            capture_err = _ConsoleCapture(buf_key, original_stderr)
            try:
                sys.stdout = capture_out
                sys.stderr = capture_err
                merge_result = await asyncio.to_thread(
                    _run_one_shot_sync, **merge_kwargs,
                )
            finally:
                sys.stdout = original_stdout
                sys.stderr = original_stderr

            merged_report = helpers.extract_stage_result(merge_result)
            all_chat_history.extend(merge_result.get("chat_history", []))

            # Safety: if merge is suspiciously short, use raw concatenation
            raw_combined = "\n\n".join(partial_reports)
            if len(merged_report) < len(raw_combined) * 0.5:
                logger.warning(
                    "LLM merge lost data (%d vs %d chars), using raw concatenation",
                    len(merged_report), len(raw_combined),
                )
                merged_report = raw_combined

            file_path = helpers.save_stage_file(merged_report, work_dir, file_name)

            with _console_lock:
                _console_buffers.setdefault(buf_key, []).append(
                    f"{stage_name} complete — {len(merged_report)} chars ({len(chunks)} parts merged)"
                )

            output_data: Dict[str, Any] = {
                "shared": {**shared_state, shared_key: merged_report},
                "artifacts": {
                    file_name: file_path,
                    "orchestration": "one_shot",
                    "num_parts": len(chunks),
                },
                "chat_history": all_chat_history,
            }
            return output_data

    elif stage_num == 4:
        # ── Pass A: Critic — critical audit of draft ──
        with _console_lock:
            _console_buffers.setdefault(buf_key, []).append(
                "Running critic pass (editorial audit)..."
            )

        critique_kwargs = helpers.build_review_critique_kwargs(
            draft_report=shared_state.get("draft_report", ""),
            curated_items=shared_state.get("curated_items", ""),
            date_from=date_from,
            date_to=date_to,
            style=style,
            work_dir=work_dir,
            config_overrides=config_overrides,
            callbacks=callbacks,
        )

        original_stdout, original_stderr = sys.stdout, sys.stderr
        capture_out = _ConsoleCapture(buf_key, original_stdout)
        capture_err = _ConsoleCapture(buf_key, original_stderr)
        try:
            sys.stdout = capture_out
            sys.stderr = capture_err
            critique_result = await asyncio.to_thread(
                _run_one_shot_sync, **critique_kwargs,
            )
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr

        review_critique = helpers.extract_stage_result(critique_result)
        helpers.save_stage_file(review_critique, work_dir, "review_critique.md")

        with _console_lock:
            _console_buffers.setdefault(buf_key, []).append(
                f"Critic pass complete — {len(review_critique)} chars. "
                "Running editor pass..."
            )

        # ── Pass B: Editor — apply corrections + final polish ──
        kwargs = helpers.build_review_kwargs(
            draft_report=shared_state.get("draft_report", ""),
            curated_items=shared_state.get("curated_items", ""),
            date_from=date_from,
            date_to=date_to,
            style=style,
            work_dir=work_dir,
            review_critique=review_critique,
            config_overrides=config_overrides,
            callbacks=callbacks,
        )
    else:
        raise ValueError(f"Unknown AI Weekly stage: {stage_num}")

    with _console_lock:
        _console_buffers.setdefault(buf_key, []).append(
            f"Running one_shot for {stage_name}..."
        )

    # Pass all kwargs directly to one_shot (models, agent, etc. from helpers)
    original_stdout, original_stderr = sys.stdout, sys.stderr
    capture_out = _ConsoleCapture(buf_key, original_stdout)
    capture_err = _ConsoleCapture(buf_key, original_stderr)

    try:
        sys.stdout = capture_out
        sys.stderr = capture_err

        result = await asyncio.to_thread(
            _run_one_shot_sync, **kwargs,
        )
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr

    # Extract result content
    result_content = helpers.extract_stage_result(result)

    # Stage 4: run programmatic verification
    if stage_num == 4:
        result_content, verification_notes = helpers.programmatic_verification(
            result_content, date_from, date_to,
        )
    else:
        verification_notes = None

    file_path = helpers.save_stage_file(result_content, work_dir, file_name)

    with _console_lock:
        _console_buffers.setdefault(buf_key, []).append(
            f"{stage_name} complete — {len(result_content)} chars"
        )

    # Build output_data
    chat_history = result.get("chat_history", [])
    output_data: Dict[str, Any] = {
        "shared": {**shared_state, shared_key: result_content},
        "artifacts": {file_name: file_path, "orchestration": "one_shot"},
        "chat_history": chat_history,
    }
    if verification_notes:
        output_data["artifacts"]["verification_notes"] = verification_notes

    return output_data


# =============================================================================
# Stage execution orchestrator
# =============================================================================

async def _run_aiweekly_stage(
    task_id: str,
    stage_num: int,
    task_text: str,
    work_dir: str,
    task_config: dict,
    model: str,
    n_reviews: int = 1,
    review_model: str = None,
    specialist_model: str = None,
    temperature: float = 0.7,
):
    """Execute a single AI Weekly stage using one_shot via task_framework helpers."""
    from services.file_task_store import update_stage, update_task, get_task

    sdef = STAGE_DEFS[stage_num - 1]
    buf_key = f"{task_id}:{stage_num}"
    with _console_lock:
        _console_buffers[buf_key] = [f"Starting {sdef['name']}..."]

    try:
        update_stage(task_id, stage_num, {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

        # Build shared state and config overrides
        shared_state = _build_shared_state(task_id, stage_num, task_config)
        config_overrides = {"model": model, "researcher_model": model}
        if review_model:
            config_overrides["review_model"] = review_model
        if specialist_model:
            config_overrides["specialist_model"] = specialist_model

        output_data = await _run_aiweekly_one_shot_stage(
            task_id=task_id,
            stage_num=stage_num,
            buf_key=buf_key,
            work_dir=work_dir,
            task_config=task_config,
            shared_state=shared_state,
            config_overrides=config_overrides,
        )

        # Extract cost from cost JSON files in work_dir and all subdirectories
        try:
            total_prompt = 0
            total_completion = 0
            total_cost_usd = 0.0

            cost_dirs = []
            top_cost = os.path.join(work_dir, "cost")
            if os.path.isdir(top_cost):
                cost_dirs.append(top_cost)
            for entry in os.listdir(work_dir):
                sub_cost = os.path.join(work_dir, entry, "cost")
                if os.path.isdir(sub_cost):
                    cost_dirs.append(sub_cost)

            for cost_dir in cost_dirs:
                for fname in sorted(os.listdir(cost_dir)):
                    if fname.endswith(".json"):
                        with open(os.path.join(cost_dir, fname), "r") as f:
                            records = json.load(f)
                        for entry in records:
                            if entry.get("Agent") == "Total":
                                continue
                            total_prompt += int(float(str(entry.get("Prompt Tokens", 0))))
                            total_completion += int(float(str(entry.get("Completion Tokens", 0))))
                            cost_str = str(entry.get("Cost ($)", "0"))
                            total_cost_usd += float(cost_str.replace("$", ""))

            if total_prompt > 0 or total_completion > 0 or total_cost_usd > 0:
                output_data["cost"] = {
                    "prompt_tokens": total_prompt,
                    "completion_tokens": total_completion,
                    "cost_usd": total_cost_usd,
                }
        except Exception as exc:
            logger.debug("aiweekly_cost_extract_failed error=%s", exc)

        # Persist results
        update_stage(task_id, stage_num, {
            "status": "completed",
            "output_data": output_data,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

        # Check if all stages completed → mark workflow done
        task_data = get_task(task_id)
        if task_data:
            all_stages = task_data.get("stages", [])
            if all_stages and all(s["status"] == "completed" for s in all_stages):
                update_task(task_id, {
                    "status": "completed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                })
                try:
                    _generate_cost_summary(task_id, work_dir, all_stages)
                except Exception as exc:
                    logger.warning(f"Failed to generate cost summary: {exc}")

        logger.info("aiweekly_stage_completed task=%s stage=%d", task_id, stage_num)
        print(f"[Stage {stage_num}] Complete")

    except asyncio.TimeoutError:
        update_stage(task_id, stage_num, {
            "status": "failed",
            "error_message": "Stage timed out (900s)",
        })
        print(f"[Stage {stage_num}] Timeout")
    except Exception as exc:
        logger.error("AIWeekly stage %d failed: %s", stage_num, exc, exc_info=True)
        with _console_lock:
            _console_buffers.setdefault(buf_key, []).append(f"Error: {exc}")
        update_stage(task_id, stage_num, {
            "status": "failed",
            "error_message": str(exc)[:2000],
        })
        print(f"[Stage {stage_num}] Error: {exc}")
    finally:
        _running_tasks.pop(f"{task_id}:{stage_num}", None)


# =============================================================================
# Cost summary generator
# =============================================================================

_STAGE_DISPLAY_NAMES = {
    1: "Data Collection",
    2: "Content Curation",
    3: "Report Generation",
    4: "Quality Review",
}


def _generate_cost_summary(task_id: str, work_dir: str, stages) -> str:
    """Generate a formatted cost_summary.md file with per-stage and total cost breakdown."""
    lines: List[str] = []
    lines.append("# AI Weekly Report — Cost Summary")
    lines.append("")
    lines.append(f"**Task ID:** `{task_id}`")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Table header
    lines.append("## Per-Stage Cost Breakdown")
    lines.append("")
    lines.append("| # | Stage | Model | Prompt Tokens | Completion Tokens | Total Tokens | Cost (USD) |")
    lines.append("|---|-------|-------|--------------|-------------------|-------------|------------|")

    total_prompt = 0
    total_completion = 0
    total_tokens = 0
    total_cost = 0.0

    sorted_stages = sorted(stages, key=lambda s: s["stage_number"])
    for stage in sorted_stages:
        num = stage["stage_number"]
        display = _STAGE_DISPLAY_NAMES.get(num, stage.get("stage_name") or f"Stage {num}")
        cost_info = {}
        model_name = "—"
        od = stage.get("output_data")
        if od and isinstance(od, dict):
            cost_info = od.get("cost", {})
            artifacts = od.get("artifacts", {})
            model_name = artifacts.get("model", "—")

        pt = cost_info.get("prompt_tokens", 0)
        ct = cost_info.get("completion_tokens", 0)
        tt = pt + ct
        cu = cost_info.get("cost_usd", 0.0)

        total_prompt += pt
        total_completion += ct
        total_tokens += tt
        total_cost += cu

        lines.append(
            f"| {num} | {display} | {model_name} | "
            f"{pt:,} | {ct:,} | {tt:,} | ${cu:.4f} |"
        )

    # Totals row
    lines.append(f"| | **TOTAL** | | **{total_prompt:,}** | **{total_completion:,}** | **{total_tokens:,}** | **${total_cost:.4f}** |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Summary section
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total Prompt Tokens:** {total_prompt:,}")
    lines.append(f"- **Total Completion Tokens:** {total_completion:,}")
    lines.append(f"- **Total Tokens Used:** {total_tokens:,}")
    lines.append(f"- **Total Cost:** ${total_cost:.4f}")
    lines.append("")

    content = "\n".join(lines)
    input_dir = os.path.join(work_dir, "input_files")
    os.makedirs(input_dir, exist_ok=True)
    summary_path = os.path.join(input_dir, "cost_summary.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(content)
    return summary_path


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/create", response_model=AIWeeklyCreateResponse)
async def create_aiweekly_task(request: AIWeeklyCreateRequest):
    """Create a new AI Weekly Report task with 4 stages."""
    from services.file_task_store import create_task

    task_id = str(uuid.uuid4())

    work_dir = request.work_dir or os.path.join(
        os.path.expanduser("~/Desktop/cmbdir"), "aiweekly", task_id[:8]
    )
    os.makedirs(work_dir, exist_ok=True)

    task_config = {
        "date_from": request.date_from,
        "date_to": request.date_to,
        "topics": request.topics,
        "sources": request.sources,
        "custom_sources": request.custom_sources or [],
        "style": request.style,
    }

    create_task(
        task_id=task_id,
        work_dir=work_dir,
        task_description=f"AI Weekly Report: {request.date_from} to {request.date_to}",
        task_config=task_config,
        model=_get_default_model(),
        stages=STAGE_DEFS,
    )

    stages_out = [
        {
            "stage_number": sd["number"],
            "stage_name": sd["name"],
            "status": "pending",
        }
        for sd in STAGE_DEFS
    ]

    # Save task config to file
    input_dir = os.path.join(work_dir, "input_files")
    os.makedirs(input_dir, exist_ok=True)
    with open(os.path.join(input_dir, "task_config.json"), "w") as f:
        json.dump(task_config, f, indent=2)

    return AIWeeklyCreateResponse(
        task_id=task_id,
        work_dir=work_dir,
        stages=stages_out,
    )


ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".pdf", ".txt", ".md", ".json", ".xml", ".html"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/{task_id}/upload")
async def upload_data_source(task_id: str, file: UploadFile = File(...)):
    """Upload a file as a custom data source for the task."""
    from services.file_task_store import get_task_or_404

    task_data = get_task_or_404(task_id)
    work_dir = task_data.get("work_dir", "")

    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(400, f"File type {ext} not allowed. Allowed: {', '.join(ALLOWED_UPLOAD_EXTENSIONS)}")

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"File too large. Max size: {MAX_UPLOAD_SIZE // (1024 * 1024)} MB")

    uploads_dir = os.path.join(work_dir, "input_files", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    safe_name = os.path.basename(file.filename)
    save_path = os.path.join(uploads_dir, safe_name)
    with open(save_path, "wb") as f:
        f.write(content)

    return {"filename": safe_name, "size": len(content), "path": save_path}


@router.post("/{task_id}/stages/{stage_num}/execute")
async def execute_aiweekly_stage(
    task_id: str,
    stage_num: int,
    request: AIWeeklyExecuteRequest = None,
):
    """Execute a specific stage."""
    if stage_num < 1 or stage_num > 4:
        raise HTTPException(400, f"Invalid stage number: {stage_num}")

    from services.file_task_store import get_task_or_404

    task_data = get_task_or_404(task_id)
    work_dir = task_data.get("work_dir", "")
    task_config = task_data.get("task_config", {})

    config_overrides = (request.config_overrides if request else None) or {}
    model = config_overrides.get("model", _get_default_model())
    n_reviews = config_overrides.get("n_reviews", 1)
    review_model = config_overrides.get("review_model") or None
    specialist_model = config_overrides.get("specialist_model") or None
    temperature = config_overrides.get("temperature", 0.7)

    task_text = f"AI Weekly Report: {task_config.get('date_from')} to {task_config.get('date_to')}"

    task = asyncio.create_task(
        _run_aiweekly_stage(
            task_id, stage_num, task_text, work_dir, task_config,
            model, n_reviews, review_model, specialist_model, temperature,
        )
    )
    _running_tasks[f"{task_id}:{stage_num}"] = task

    return {"status": "started", "stage_num": stage_num, "model": model, "review_model": review_model, "specialist_model": specialist_model}


# =============================================================================
# Recent tasks (for resume flow — must be BEFORE /{task_id} routes)
# =============================================================================
@router.get("/recent", response_model=List[AIWeeklyRecentTaskResponse])
async def get_recent_aiweekly_tasks():
    """List started AI Weekly tasks for the resume flow."""
    from services.file_task_store import list_recent_tasks

    tasks = list_recent_tasks(limit=10)
    results = []
    for t in tasks:
        stages = t.get("stages", [])
        current = None
        completed_count = 0
        for s in stages:
            if s["status"] == "completed":
                completed_count += 1
            elif current is None:
                current = s["stage_number"]

        total_stages = len(stages) or 4
        progress = round((completed_count / total_stages) * 100, 1)

        # Map internal statuses to frontend-expected values
        raw_status = t.get("status", "")
        any_running = any(s["status"] == "running" for s in stages)
        if any_running or raw_status == "executing":
            mapped_status = "running"
        elif raw_status == "completed":
            mapped_status = "completed"
        elif raw_status in ("failed", "error"):
            mapped_status = "failed"
        else:
            mapped_status = "pending"

        results.append(AIWeeklyRecentTaskResponse(
            task_id=t["id"],
            task=t.get("task_description", ""),
            status=mapped_status,
            created_at=t.get("created_at"),
            current_stage=current,
            progress_percent=progress,
        ))

    return results


@router.get("/{task_id}", response_model=AIWeeklyTaskStateResponse)
async def get_aiweekly_task(task_id: str):
    """Get full task state."""
    from services.file_task_store import get_task_or_404

    task_data = get_task_or_404(task_id)
    stages = task_data.get("stages", [])

    completed = sum(1 for s in stages if s["status"] == "completed")
    progress = (completed / len(STAGE_DEFS)) * 100 if stages else 0

    # Aggregate cost from per-stage output_data
    total_cost = None
    total_cost_usd = None
    tp, tc, tt = 0, 0, 0
    cost_usd_sum = 0.0
    for s in stages:
        od = s.get("output_data")
        if od and isinstance(od, dict):
            ci = od.get("cost", {})
            tp += ci.get("prompt_tokens", 0)
            tc += ci.get("completion_tokens", 0)
            cost_usd_sum += ci.get("cost_usd", 0.0)
    tt = tp + tc
    if tt > 0:
        total_cost = {"prompt_tokens": tp, "completion_tokens": tc, "total_tokens": tt}
        total_cost_usd = cost_usd_sum if cost_usd_sum > 0 else (tp * 0.002 + tc * 0.008) / 1000

    return AIWeeklyTaskStateResponse(
        task_id=task_id,
        status=task_data.get("status", ""),
        progress=progress,
        total_cost=total_cost,
        total_cost_usd=total_cost_usd,
        stages=[
            AIWeeklyStageResponse(
                stage_number=s["stage_number"],
                stage_name=s["stage_name"],
                status=s["status"],
                error=s.get("error_message"),
                started_at=s.get("started_at"),
                completed_at=s.get("completed_at"),
            ) for s in stages
        ],
    )


@router.get("/{task_id}/stages/{stage_num}/content", response_model=AIWeeklyStageContentResponse)
async def get_aiweekly_stage_content(task_id: str, stage_num: int):
    """Get stage output content."""
    from services.file_task_store import get_task_or_404

    task_data = get_task_or_404(task_id)
    stage = None
    for s in task_data.get("stages", []):
        if s["stage_number"] == stage_num:
            stage = s
            break
    if not stage:
        raise HTTPException(404, "Stage not found")

    stage_def = next((d for d in STAGE_DEFS if d["number"] == stage_num), {})
    shared_key = stage_def.get("shared_key", "")
    content = ""
    od = stage.get("output_data")
    if od and isinstance(od, dict):
        content = od.get("shared", {}).get(shared_key, "")

    return AIWeeklyStageContentResponse(
        stage_number=stage_num,
        stage_name=stage_def.get("name", ""),
        content=content,
        field=shared_key,
    )


@router.put("/{task_id}/stages/{stage_num}/content")
async def save_aiweekly_stage_content(task_id: str, stage_num: int, request: AIWeeklyContentUpdateRequest):
    """Save user edits to stage content."""
    from services.file_task_store import get_task_or_404, update_stage

    task_data = get_task_or_404(task_id)
    stage = None
    for s in task_data.get("stages", []):
        if s["stage_number"] == stage_num:
            stage = s
            break
    if not stage:
        raise HTTPException(404, "Stage not found")

    od = stage.get("output_data") or {}
    if "shared" not in od:
        od["shared"] = {}
    od["shared"][request.field] = request.content
    update_stage(task_id, stage_num, {"output_data": od})

    # Also save to file
    work_dir = task_data.get("work_dir", "")
    stage_def = next((d for d in STAGE_DEFS if d["number"] == stage_num), {})
    filename = stage_def.get("file")
    if filename and work_dir:
        file_path = os.path.join(work_dir, "input_files", filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(request.content)

    return {"status": "saved", "field": request.field}


@router.post("/{task_id}/stages/{stage_num}/refine", response_model=AIWeeklyRefineResponse)
async def refine_aiweekly_content(task_id: str, stage_num: int, request: AIWeeklyRefineRequest):
    """LLM refinement of stage content."""
    from cmbagent.llm_provider import safe_completion
    from backend.task_framework.token_utils import count_tokens, get_model_limits

    model = _get_default_model()
    max_ctx, _ = get_model_limits(model)
    system_msg = "You are an AI news editor. Refine the content based on the instruction. Return ONLY the refined markdown."
    user_msg = f"Current content:\n\n{request.content}\n\n---\n\nInstruction: {request.message}"

    prompt_tokens = count_tokens(system_msg, model) + count_tokens(user_msg, model) + 6
    available = max_ctx - prompt_tokens - 200
    max_comp = min(16384, max(available, 4096))

    def _call():
        return safe_completion(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            model=model,
            temperature=0.7,
            max_tokens=max_comp,
        )

    refined = await asyncio.to_thread(_call)
    refined = refined or request.content
    return AIWeeklyRefineResponse(refined_content=refined, message="Content refined successfully")


@router.get("/{task_id}/stages/{stage_num}/console")
async def get_aiweekly_console(task_id: str, stage_num: int, since: int = 0):
    """Get console output for a running stage."""
    buf_key = f"{task_id}:{stage_num}"
    lines = _get_console_lines(buf_key, since_index=since)
    return {"lines": lines, "next_index": since + len(lines), "stage_num": stage_num}


@router.post("/{task_id}/reset-from/{stage_num}")
async def reset_aiweekly_from_stage(task_id: str, stage_num: int):
    """Reset stages from stage_num onwards to pending."""
    from services.file_task_store import get_task_or_404, update_stage

    task_data = get_task_or_404(task_id)
    for s in task_data.get("stages", []):
        if s["stage_number"] >= stage_num:
            update_stage(task_id, s["stage_number"], {
                "status": "pending",
                "output_data": None,
                "error_message": None,
                "started_at": None,
                "completed_at": None,
            })

    return {"status": "reset", "from_stage": stage_num}


# =============================================================================
# Stop a running task
# =============================================================================
@router.post("/{task_id}/stop")
async def stop_aiweekly_task(task_id: str):
    """Stop a running AI Weekly task."""
    from services.file_task_store import get_task_or_404, update_stage, update_task

    # Cancel any running asyncio tasks for this task_id
    cancelled = []
    for key in list(_running_tasks):
        if key.startswith(f"{task_id}:"):
            bg_task = _running_tasks.get(key)
            if bg_task and not bg_task.done():
                bg_task.cancel()
                cancelled.append(key)

    task_data = get_task_or_404(task_id)
    for s in task_data.get("stages", []):
        if s["status"] == "running":
            update_stage(task_id, s["stage_number"], {
                "status": "failed",
                "error_message": "Stopped by user",
            })

    update_task(task_id, {"status": "failed"})

    return {"status": "stopped", "task_id": task_id, "cancelled_stages": cancelled}


@router.delete("/{task_id}")
async def delete_aiweekly_task(task_id: str):
    """Delete a weekly task and its data."""
    from services.file_task_store import delete_task, get_task_or_404

    get_task_or_404(task_id)  # raises 404 if not found
    delete_task(task_id)
    return {"status": "deleted"}


@router.get("/{task_id}/download/{filename}")
async def download_aiweekly_artifact(task_id: str, filename: str):
    """Download a report file."""
    from services.file_task_store import get_task_or_404

    # Validate filename
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid filename")

    task_data = get_task_or_404(task_id)
    work_dir = task_data.get("work_dir", "")
    file_path = os.path.join(work_dir, "input_files", filename)

    # If cost_summary.md is missing, try to regenerate it on-demand
    if not os.path.isfile(file_path) and filename == "cost_summary.md":
        try:
            stages = task_data.get("stages", [])
            if stages:
                _generate_cost_summary(task_id, work_dir, stages)
        except Exception:
            pass

    if not os.path.isfile(file_path):
        raise HTTPException(404, "File not found")

    mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    return FileResponse(
        file_path,
        filename=filename,
        media_type=mime_type,
    )


def _md_to_pdf(md_path: str, pdf_path: str) -> None:
    """Convert a markdown file to PDF using markdown + PyMuPDF."""
    import markdown
    import fitz

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc"],
    )

    html = f"""<!DOCTYPE html>
<html><head><style>
body {{ font-family: Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.5; color: #1a1a1a; word-wrap: break-word; overflow-wrap: break-word; }}
h1 {{ font-size: 20pt; margin-top: 18pt; margin-bottom: 8pt; }}
h2 {{ font-size: 16pt; margin-top: 14pt; margin-bottom: 6pt; }}
h3 {{ font-size: 13pt; margin-top: 10pt; margin-bottom: 4pt; }}
table {{ border-collapse: collapse; width: 100%; margin: 10pt 0; table-layout: fixed; }}
th, td {{ border: 1px solid #ccc; padding: 6px 8px; text-align: left; font-size: 9pt; word-wrap: break-word; overflow-wrap: break-word; }}
th {{ background-color: #f2f2f2; font-weight: bold; }}
a {{ color: #1a73e8; word-break: break-all; }}
ul, ol {{ padding-left: 18pt; }}
pre, code {{ font-size: 9pt; word-wrap: break-word; overflow-wrap: break-word; white-space: pre-wrap; }}
</style></head><body>{html_body}</body></html>"""

    mediabox = fitz.paper_rect("a4")
    content_rect = mediabox + (36, 36, -36, -36)  # 0.5-inch margins

    def rectfn(rect_num, filled):
        return mediabox, content_rect, None

    story = fitz.Story(html=html)
    writer = fitz.DocumentWriter(pdf_path)
    story.write(writer, rectfn)
    writer.close()


@router.get("/{task_id}/download-pdf/{filename}")
async def download_aiweekly_artifact_pdf(task_id: str, filename: str, inline: bool = False):
    """Download a report file converted to PDF."""
    from services.file_task_store import get_task_or_404

    # Validate filename — must be a .md file
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid filename")
    if not filename.endswith(".md"):
        raise HTTPException(400, "Only markdown files can be converted to PDF")

    task_data = get_task_or_404(task_id)
    work_dir = task_data.get("work_dir", "")
    md_path = os.path.join(work_dir, "input_files", filename)
    if not os.path.isfile(md_path):
        raise HTTPException(404, "File not found")

    pdf_filename = filename.rsplit(".", 1)[0] + ".pdf"
    pdf_path = os.path.join(work_dir, "input_files", pdf_filename)

    _md_to_pdf(md_path, pdf_path)

    disposition = f'inline; filename="{pdf_filename}"' if inline else f'attachment; filename="{pdf_filename}"'
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )
