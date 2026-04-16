"""
Logger factory for creating session and run loggers.

Handles directory structure creation and legacy symlink compatibility.
"""

import os
from pathlib import Path
from typing import Tuple, Optional

from loggers.simple_logger import RunLogger, SessionLogger


class LoggerFactory:
    """Factory for creating run and session loggers with proper directory structure."""

    @staticmethod
    def create_loggers(
        session_id: str,
        run_id: str,
        work_dir: str,
        task_work_dir: str = None
    ) -> Tuple[RunLogger, SessionLogger, Path]:
        """
        Create run and session loggers with proper directory structure.

        Directory structure created:
        {work_dir}/
        └── sessions/
            └── {session_id}/
                ├── session.log              # ALL events from all runs in session
                └── tasks/
                    └── {run_id}/            # Task work directory
                        ├── logs/
                        │   ├── run.log                  # Infrastructure events
                        │   └── console_output.log       # Symlink to ../../session.log
                        ├── cost/
                        ├── data/
                        └── ... (other task artifacts)

        Args:
            session_id: Session identifier
            run_id: Run identifier (also task_id)
            work_dir: Base work directory path
            task_work_dir: Task-specific work directory (defaults to {work_dir}/{run_id})

        Returns:
            Tuple of (run_logger, session_logger, legacy_symlink_path)
        """
        work_dir = Path(work_dir)

        # Create session directory
        session_dir = work_dir / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Use task_work_dir if provided, otherwise nest under session/tasks/{run_id}
        if task_work_dir:
            task_dir = Path(task_work_dir)
        else:
            task_dir = session_dir / "tasks" / run_id

        # Create task logs directory (alongside cost/, data/, etc.)
        logs_dir = task_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Create loggers
        run_logger = RunLogger(logs_dir / "run.log")
        session_logger = SessionLogger(session_dir / "session.log")

        # Create symlink: console_output.log -> ../../session.log
        legacy_log = logs_dir / "console_output.log"
        if not legacy_log.exists():
            try:
                session_log_path = session_dir / "session.log"
                # Create relative symlink
                legacy_log.symlink_to(os.path.relpath(session_log_path, logs_dir))
            except Exception as e:
                print(f"[LoggerFactory] Warning: Failed to create legacy symlink: {e}")

        return run_logger, session_logger, legacy_log

    @staticmethod
    def get_log_paths(
        session_id: str,
        run_id: str,
        work_dir: str
    ) -> Tuple[Path, Path]:
        """
        Get paths to run.log and session.log without creating loggers.

        Args:
            session_id: Session identifier
            run_id: Run identifier
            work_dir: Base work directory path

        Returns:
            Tuple of (run_log_path, session_log_path)
        """
        work_dir = Path(work_dir)
        session_dir = work_dir / "sessions" / session_id
        task_dir = session_dir / "tasks" / run_id

        run_log_path = task_dir / "logs" / "run.log"
        session_log_path = session_dir / "session.log"

        return run_log_path, session_log_path
