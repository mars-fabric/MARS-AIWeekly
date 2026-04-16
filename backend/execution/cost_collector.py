"""
Cost collector that reads JSON files written by cmbagent's display_cost().
Single path for cost data to reach database and WebSocket.
"""
import json
import os
import logging
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger(__name__)


class CostCollector:
    """Reads cost JSON from work_dir/cost/ and persists to database."""

    def __init__(self, db_session, session_id: str, run_id: str):
        self.db_session = db_session
        self.session_id = session_id
        self.run_id = run_id
        self._processed_files: set = set()

    def collect_from_callback(self, cost_data: Dict[str, Any],
                              ws_send_func: Optional[Callable] = None) -> None:
        """Process cost data received via on_cost_update callback.

        Never raises – cost tracking must not crash the workflow.
        """
        try:
            json_path = cost_data.get("cost_json_path")
            records = cost_data.get("records", [])

            if json_path and json_path in self._processed_files:
                return  # Already processed (idempotent)

            if json_path:
                self._processed_files.add(json_path)

            if not records and json_path and os.path.exists(json_path):
                try:
                    with open(json_path, 'r') as f:
                        records = json.load(f)
                except Exception as e:
                    logger.error("cost_json_read_failed path=%s error=%s", json_path, e)
                    return

            self._persist_records(records)
            if ws_send_func:
                self._emit_ws_events(records, ws_send_func)
        except Exception as e:
            logger.error("cost_collect_failed error=%s", e)

    def collect_from_work_dir(self, work_dir: str,
                              ws_send_func: Optional[Callable] = None) -> None:
        """Scan work_dir/cost/ for any unprocessed JSON files."""
        cost_dir = os.path.join(work_dir, "cost")
        if not os.path.isdir(cost_dir):
            return

        for fname in sorted(os.listdir(cost_dir)):
            if fname.endswith(".json"):
                json_path = os.path.join(cost_dir, fname)
                if json_path not in self._processed_files:
                    self.collect_from_callback(
                        {"cost_json_path": json_path},
                        ws_send_func=ws_send_func
                    )

    def _persist_records(self, records: List[Dict]) -> None:
        """Persist cost records with ACTUAL token counts from JSON."""
        if not self.db_session:
            return

        try:
            from cmbagent.database.repository import CostRepository

            cost_repo = CostRepository(self.db_session, self.session_id)

            for entry in records:
                if entry.get("Agent") == "Total":
                    continue

                cost_str = str(entry.get("Cost ($)", "$0.0"))
                cost_value = float(cost_str.replace("$", ""))
                prompt_tokens = int(float(str(entry.get("Prompt Tokens", 0))))
                completion_tokens = int(float(str(entry.get("Completion Tokens", 0))))

                if cost_value > 0 or prompt_tokens > 0 or completion_tokens > 0:
                    cost_repo.record_cost(
                        run_id=self.run_id,
                        model=entry.get("Model", "unknown"),
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        cost_usd=cost_value,
                        agent_name=entry.get("Agent", "unknown"),
                    )

        except Exception as e:
            logger.error("cost_persist_failed error=%s", e)
            if self.db_session:
                try:
                    self.db_session.rollback()
                except Exception:
                    pass

    def _emit_ws_events(self, records: List[Dict],
                        ws_send_func: Callable) -> None:
        """Emit cost_update WS events with real data."""
        total_cost = 0.0
        for entry in records:
            if entry.get("Agent") == "Total":
                continue
            cost_str = str(entry.get("Cost ($)", "$0.0"))
            cost_value = float(cost_str.replace("$", ""))
            total_cost += cost_value
            ws_send_func("cost_update", {
                "run_id": self.run_id,
                "agent": entry.get("Agent", "unknown"),
                "model": entry.get("Model", "unknown"),
                "tokens": int(float(str(entry.get("Total Tokens", 0)))),
                "input_tokens": int(float(str(entry.get("Prompt Tokens", 0)))),
                "output_tokens": int(float(str(entry.get("Completion Tokens", 0)))),
                "cost_usd": cost_value,
                "total_cost_usd": total_cost,
            })
