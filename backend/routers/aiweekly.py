"""
AI Weekly Report endpoints.

Phase-based pipeline:
  1. Data Collection — Direct tool calls (RSS, APIs, web search)
  2. Content Curation — LLM filters and deduplicates
  3. Report Generation — LLM writes the 4-section report
  4. Quality Review — LLM polishes to publication quality
"""

import asyncio
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

    def __init__(self, buf_key: str, original):
        self._buf_key = buf_key
        self._original = original

    def write(self, text: str):
        if self._original:
            self._original.write(text)
        if text.strip():
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
# Phase class loading
# =============================================================================
_PHASE_CLASSES = {
    1: "cmbagent.phases.aiweekly.collection_phase:AIWeeklyCollectionPhase",
    2: "cmbagent.phases.aiweekly.curation_phase:AIWeeklyCurationPhase",
    3: "cmbagent.phases.aiweekly.generation_phase:AIWeeklyGenerationPhase",
    4: "cmbagent.phases.aiweekly.review_phase:AIWeeklyReviewPhase",
}


def _load_phase_class(stage_num: int):
    import importlib
    ref = _PHASE_CLASSES[stage_num]
    module_path, cls_name = ref.rsplit(":", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, cls_name)


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
# Stage execution
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
    from services.file_task_store import update_stage, update_task, get_task
    from cmbagent.phases.base import PhaseContext

    buf_key = f"{task_id}:{stage_num}"
    old_stdout, old_stderr = sys.stdout, sys.stderr
    cap = _ConsoleCapture(buf_key, old_stdout)
    sys.stdout = cap
    sys.stderr = cap

    try:
        update_stage(task_id, stage_num, {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

        PhaseClass = _load_phase_class(stage_num)
        ConfigClass = PhaseClass.config_class if hasattr(PhaseClass, "config_class") else None

        if stage_num == 1:
            # Data collection — no LLM config needed
            phase = PhaseClass()
        else:
            config = ConfigClass(
                model=model,
                n_reviews=n_reviews,
                review_model=review_model,
                specialist_model=specialist_model,
                temperature=temperature,
            ) if ConfigClass else None
            phase = PhaseClass(config=config)

        shared_state = _build_shared_state(task_id, stage_num, task_config)
        ctx = PhaseContext(
            workflow_id=f"aiweekly_{task_id}",
            run_id=task_id,
            phase_id=f"stage{stage_num}_{uuid.uuid4().hex[:6]}",
            task=task_text,
            work_dir=work_dir,
            shared_state=shared_state,
        )

        # Stage 1 does blocking network I/O (RSS, APIs) — run in a thread
        # to avoid starving the event loop and crashing the HTTP server.
        # Stages 2-4 already use asyncio.to_thread internally for LLM calls.
        if stage_num == 1:
            import functools

            def _run_sync():
                import asyncio as _aio
                loop = _aio.new_event_loop()
                try:
                    return loop.run_until_complete(phase.execute(ctx))
                finally:
                    loop.close()

            result = await asyncio.wait_for(
                asyncio.to_thread(_run_sync), timeout=900
            )
        else:
            result = await asyncio.wait_for(phase.execute(ctx), timeout=900)

        if result.status.value == "completed":
            output_data = result.context.output_data or {}
            stage_def = next((d for d in STAGE_DEFS if d["number"] == stage_num), {})
            content = output_data.get("shared", {}).get(stage_def.get("shared_key", ""), "")

            # Track cost from phase output
            cost_data = output_data.get("cost", {})
            prompt_tokens = cost_data.get("prompt_tokens", 0) if cost_data else 0
            completion_tokens = cost_data.get("completion_tokens", 0) if cost_data else 0
            cost_usd = (prompt_tokens * 0.002 + completion_tokens * 0.008) / 1000

            # Ensure cost is stored in output_data for per-stage breakdown
            if "cost" not in output_data:
                output_data["cost"] = {}
            output_data["cost"]["cost_usd"] = cost_usd

            update_stage(task_id, stage_num, {
                "status": "completed",
                "output_data": output_data,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })

            # If all stages are now completed, mark the task as completed
            task_data = get_task(task_id)
            if task_data:
                all_stages = task_data.get("stages", [])
                if all_stages and all(s["status"] == "completed" for s in all_stages):
                    update_task(task_id, {
                        "status": "completed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    })
                    # Generate cost summary file
                    try:
                        task_data = get_task(task_id)  # reload
                        _generate_cost_summary(task_id, work_dir, task_data.get("stages", []))
                    except Exception as exc:
                        logger.warning(f"Failed to generate cost summary: {exc}")

            print(f"[Stage {stage_num}] ✅ Complete — {len(content)} chars")
        else:
            error_msg = result.error or "Unknown error"
            update_stage(task_id, stage_num, {
                "status": "failed",
                "error_message": error_msg,
            })
            print(f"[Stage {stage_num}] ❌ Failed — {error_msg}")

    except asyncio.TimeoutError:
        update_stage(task_id, stage_num, {
            "status": "failed",
            "error_message": "Stage timed out (900s)",
        })
        print(f"[Stage {stage_num}] ❌ Timeout")
    except Exception as exc:
        logger.error("AIWeekly stage %d failed: %s", stage_num, exc, exc_info=True)
        update_stage(task_id, stage_num, {
            "status": "failed",
            "error_message": str(exc),
        })
        print(f"[Stage {stage_num}] ❌ Error: {exc}")
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


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
        "style": request.style,
        "custom_sources": request.custom_sources or [],
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
    import json
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

        results.append(AIWeeklyRecentTaskResponse(
            task_id=t["id"],
            task=t.get("task_description", ""),
            status=t.get("status", ""),
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
    from cmbagent.phases.rfp.token_utils import count_tokens, get_model_limits

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
    """Stop a running AI Weekly task.

    Cancels any executing background stage and marks it as failed.
    """
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
body {{ font-family: Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.5; color: #1a1a1a; }}
h1 {{ font-size: 20pt; margin-top: 18pt; margin-bottom: 8pt; }}
h2 {{ font-size: 16pt; margin-top: 14pt; margin-bottom: 6pt; }}
h3 {{ font-size: 13pt; margin-top: 10pt; margin-bottom: 4pt; }}
table {{ border-collapse: collapse; width: 100%; margin: 10pt 0; }}
th, td {{ border: 1px solid #ccc; padding: 6px 8px; text-align: left; font-size: 9pt; }}
th {{ background-color: #f2f2f2; font-weight: bold; }}
a {{ color: #1a73e8; }}
ul, ol {{ padding-left: 18pt; }}
</style></head><body>{html_body}</body></html>"""

    story = fitz.Story(html=html)
    writer = fitz.DocumentWriter(pdf_path)
    mediabox = fitz.paper_rect("a4")
    content_rect = mediabox + (36, 36, -36, -36)  # 0.5-inch margins

    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(content_rect)
        story.draw(device)
        writer.end_page()
    writer.close()


@router.get("/{task_id}/download-pdf/{filename}")
async def download_aiweekly_artifact_pdf(task_id: str, filename: str, inline: bool = False):
    """Download a report file converted to PDF.

    Pass ?inline=true to serve for in-browser preview (Content-Disposition: inline).
    """
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
