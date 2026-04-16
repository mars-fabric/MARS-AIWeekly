"""
File-based task store for AI Weekly.

Stores all session/task/stage data as JSON files under
~/Desktop/cmbdir/aiweekly/{task_id_prefix}/task.json

Replaces all cmbagent.database dependencies for the AI Weekly workflow.
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_lock = threading.Lock()

AIWEEKLY_BASE_DIR = os.path.expanduser("~/Desktop/cmbdir/aiweekly")


def _task_path(work_dir: str) -> str:
    return os.path.join(work_dir, "task.json")


def _read_task(work_dir: str) -> Optional[Dict[str, Any]]:
    path = _task_path(work_dir)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_task(work_dir: str, data: Dict[str, Any]):
    path = _task_path(work_dir)
    os.makedirs(work_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_task(
    task_id: str,
    work_dir: str,
    task_description: str,
    task_config: Dict[str, Any],
    model: str,
    stages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Create a new task with stage definitions."""
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "id": task_id,
        "status": "executing",
        "task_description": task_description,
        "mode": "aiweekly",
        "model": model,
        "work_dir": work_dir,
        "task_config": task_config,
        "created_at": now,
        "completed_at": None,
        "stages": [
            {
                "stage_number": s["number"],
                "stage_name": s["name"],
                "status": "pending",
                "output_data": None,
                "error_message": None,
                "started_at": None,
                "completed_at": None,
            }
            for s in stages
        ],
    }
    with _lock:
        _write_task(work_dir, data)
    return data


def get_task(task_id: str, work_dir: str = None) -> Optional[Dict[str, Any]]:
    """Load task data. If work_dir not given, search by task_id."""
    if work_dir:
        return _read_task(work_dir)
    return _find_task_by_id(task_id)


def _find_task_by_id(task_id: str) -> Optional[Dict[str, Any]]:
    """Scan the base dir to find a task by its ID."""
    base = AIWEEKLY_BASE_DIR
    if not os.path.isdir(base):
        return None
    for entry in os.listdir(base):
        entry_path = os.path.join(base, entry)
        if not os.path.isdir(entry_path):
            continue
        data = _read_task(entry_path)
        if data and data.get("id") == task_id:
            return data
    return None


def get_task_or_404(task_id: str):
    """Get task or raise an HTTPException."""
    from fastapi import HTTPException
    task = _find_task_by_id(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


def update_task(task_id: str, updates: Dict[str, Any]):
    """Update top-level task fields."""
    with _lock:
        data = _find_task_by_id(task_id)
        if not data:
            return
        data.update(updates)
        _write_task(data["work_dir"], data)


def get_stage(task_id: str, stage_num: int) -> Optional[Dict[str, Any]]:
    """Get a specific stage from a task."""
    data = _find_task_by_id(task_id)
    if not data:
        return None
    for s in data.get("stages", []):
        if s["stage_number"] == stage_num:
            return s
    return None


def update_stage(task_id: str, stage_num: int, updates: Dict[str, Any]):
    """Update fields on a specific stage."""
    with _lock:
        data = _find_task_by_id(task_id)
        if not data:
            return
        for s in data.get("stages", []):
            if s["stage_number"] == stage_num:
                s.update(updates)
                break
        _write_task(data["work_dir"], data)


def get_completed_stages(task_id: str, before_stage: int) -> List[Dict[str, Any]]:
    """Get completed stages before a given stage number."""
    data = _find_task_by_id(task_id)
    if not data:
        return []
    return [
        s for s in data.get("stages", [])
        if s["stage_number"] < before_stage and s["status"] == "completed"
    ]


def list_recent_tasks(limit: int = 10) -> List[Dict[str, Any]]:
    """List recent AI Weekly tasks sorted by creation time."""
    base = AIWEEKLY_BASE_DIR
    if not os.path.isdir(base):
        return []

    tasks = []
    for entry in os.listdir(base):
        entry_path = os.path.join(base, entry)
        if not os.path.isdir(entry_path):
            continue
        data = _read_task(entry_path)
        if data and data.get("mode") == "aiweekly":
            if data.get("status") in ("executing", "draft", "completed"):
                tasks.append(data)

    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return tasks[:limit]


def delete_task(task_id: str):
    """Delete a task and its work directory."""
    import shutil
    data = _find_task_by_id(task_id)
    if not data:
        return False
    work_dir = data.get("work_dir", "")
    if work_dir and os.path.isdir(work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)
    return True
