"""
DAG Tracker for workflow visualization and state management.
"""

import copy
import hashlib
import os
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import WebSocket
from core.logging import get_logger

logger = get_logger(__name__)


def _safe_commit(db_session, context: str = "unknown") -> bool:
    """Commit with rollback on IntegrityError/OperationalError.

    Returns True on success, False on failure (after rollback).
    """
    try:
        db_session.commit()
        return True
    except Exception as e:
        error_type = type(e).__name__
        logger.error("db_commit_failed context=%s error_type=%s error=%s",
                      context, error_type, e)
        try:
            db_session.rollback()
        except Exception as rb_err:
            logger.warning("db_rollback_failed context=%s error=%s", context, rb_err)
        return False

# ---------------------------------------------------------------------------
# Template-based DAG definitions (Task 1.1)
# ---------------------------------------------------------------------------

DAG_TEMPLATES = {
    "plan-execute": {
        "initial_nodes": [
            {"id": "planning", "label": "Planning Phase", "type": "planning",
             "agent": "planner", "status": "pending", "step_number": 0,
             "description": "Analyzing task and creating execution plan"},
        ],
        "initial_edges": [],
        "dynamic_steps": True,
    },
    "fixed-pipeline": {
        "initial_nodes": [
            {"id": "init", "label": "Initialize", "type": "planning",
             "status": "pending", "step_number": 0, "description": "Initialize agent"},
            {"id": "execute", "label": "Execute", "type": "agent",
             "status": "pending", "step_number": 1, "description": "Execute task"},
            {"id": "terminator", "label": "Completion", "type": "terminator",
             "agent": "system", "status": "pending", "step_number": 2},
        ],
        "initial_edges": [
            {"source": "init", "target": "execute"},
            {"source": "execute", "target": "terminator"},
        ],
        "dynamic_steps": False,
    },
    "three-stage-pipeline": {
        "initial_nodes": [
            {"id": "init", "label": "Initialize", "type": "planning",
             "status": "pending", "step_number": 0},
            {"id": "process", "label": "Process", "type": "agent",
             "status": "pending", "step_number": 1},
            {"id": "output", "label": "Output", "type": "agent",
             "status": "pending", "step_number": 2},
            {"id": "terminator", "label": "Completion", "type": "terminator",
             "agent": "system", "status": "pending", "step_number": 3},
        ],
        "initial_edges": [
            {"source": "init", "target": "process"},
            {"source": "process", "target": "output"},
            {"source": "output", "target": "terminator"},
        ],
        "dynamic_steps": False,
    },
    "lit-plan-execute-synthesize": {
        "initial_nodes": [
            {"id": "literature_review", "label": "Literature Review", "type": "agent",
             "agent": "researcher", "status": "pending", "step_number": 0,
             "description": "Reviewing existing research and literature"},
            {"id": "planning", "label": "Planning Phase", "type": "planning",
             "agent": "planner", "status": "pending", "step_number": 1,
             "description": "Analyzing task and creating execution plan"},
        ],
        "initial_edges": [
            {"source": "literature_review", "target": "planning"},
        ],
        "dynamic_steps": True,
        "synthesis_after_steps": True,
    },
}

MODE_TO_TEMPLATE = {
    "planning-control": ("plan-execute", {"planning": {"label": "Planning Phase"}}),
    "hitl-interactive": ("plan-execute", {"planning": {"label": "HITL Planning"}}),
    "idea-generation": ("plan-execute", {"planning": {"label": "Idea Planning Phase"}}),
    "one-shot": ("fixed-pipeline", {}),
    "ocr": ("three-stage-pipeline", {
        "init": {"label": "Initialize OCR"},
        "process": {"label": "Process PDFs", "agent": "ocr"},
        "output": {"label": "Save Output", "agent": "ocr"},
    }),
    "arxiv": ("three-stage-pipeline", {
        "init": {"label": "Parse Text"},
        "process": {"label": "Filter arXiv URLs", "agent": "arxiv"},
        "output": {"label": "Download Papers", "agent": "arxiv"},
    }),
    "enhance-input": ("fixed-pipeline", {
        "execute": {"label": "Enhance Input", "agent": "enhancer"},
    }),
    "deep-research-extended": ("lit-plan-execute-synthesize", {}),
}


class DAGTracker:
    """Track DAG state and emit events for UI visualization using database."""

    def __init__(self, websocket: WebSocket, task_id: str, mode: str,
                 send_event_func, run_id: str = None,
                 db_session=None, session_id: str = None,
                 event_loop=None):
        self.websocket = websocket
        self.task_id = task_id
        self.mode = mode
        self.send_event = send_event_func
        self.nodes = []
        self.edges = []
        self.current_step = 0
        self.node_statuses = {}
        self.db_session = None
        self._owns_db_session = False  # True when we created the session ourselves
        self.run_id = run_id
        self.session_id = session_id  # Propagated to all WS events
        self.event_repo = None
        self.node_event_map = {}
        self.execution_order_counter = 0
        self._event_loop = event_loop  # For cross-thread WS emission

        # Track current workflow phase (planning, control, execution)
        self.current_phase = "execution"
        self.current_step_number = None

        if db_session:
            # Use injected DB session (Task 1.5)
            self.db_session = db_session
            self.session_id = session_id
            self._setup_repos()
        else:
            self._init_database()

    def _init_database(self) -> None:
        """Initialize database connection from scratch."""
        try:
            from cmbagent.database import get_db_session as get_session, init_database
            from cmbagent.database.repository import WorkflowRepository, EventRepository
            from cmbagent.database.session_manager import SessionManager

            init_database()
            self.db_session = get_session()
            self._owns_db_session = True

            session_manager = SessionManager(self.db_session)
            if not self.session_id:
                self.session_id = session_manager.get_or_create_default_session()

            self._setup_repos()
            logger.info("dag_system_initialized", run_id=self.run_id)
        except Exception as e:
            logger.warning("dag_system_init_failed", error=str(e), exc_info=True)

    def close(self) -> None:
        """Close the DB session if we own it."""
        if self._owns_db_session and self.db_session:
            try:
                self.db_session.close()
            except Exception:
                pass
            self.db_session = None
            self._owns_db_session = False

    def _setup_repos(self) -> None:
        """Set up repositories assuming db_session and session_id are set."""
        from cmbagent.database.repository import WorkflowRepository, EventRepository

        self.workflow_repo = WorkflowRepository(self.db_session, self.session_id)
        self.event_repo = EventRepository(self.db_session, self.session_id)

        if not self.run_id:
            logger.debug("no_run_id_provided", task_id=self.task_id)
            self.run_id = self.task_id

        # Create WorkflowRun record if it doesn't exist
        self._ensure_workflow_run_exists(self.mode, self.task_id)

    def _ensure_workflow_run_exists(self, mode: str, task_id: str):
        """Ensure a WorkflowRun record exists for this run_id.

        This is critical for play-from-node and branching features to work,
        as they query WorkflowRun by run_id.
        """
        try:
            from cmbagent.database.models import WorkflowRun

            # Check if WorkflowRun already exists
            existing_run = self.db_session.query(WorkflowRun).filter(
                WorkflowRun.id == self.run_id
            ).first()

            if existing_run:
                logger.debug("workflow_run_exists", run_id=self.run_id)
                return

            # Create new WorkflowRun record with all required fields
            workflow_run = WorkflowRun(
                id=self.run_id,
                session_id=self.session_id,
                mode=mode,
                agent="unknown",  # Will be updated in _update_workflow_run_task
                model="unknown",  # Will be updated in _update_workflow_run_task
                status="executing",
                started_at=datetime.now(timezone.utc),
                task_description=f"Task {task_id}",  # Will be updated later
                meta={"task_id": task_id}
            )
            self.db_session.add(workflow_run)
            _safe_commit(self.db_session, "workflow_run_create")
            logger.info("workflow_run_created", run_id=self.run_id)

        except Exception as e:
            logger.error("workflow_run_ensure_failed", error=str(e), exc_info=True)

    def _update_workflow_run_task(self, task: str, config: Dict[str, Any]):
        """Update WorkflowRun with actual task description and config."""
        if not self.db_session or not self.run_id:
            return

        try:
            from cmbagent.database.models import WorkflowRun

            run = self.db_session.query(WorkflowRun).filter(
                WorkflowRun.id == self.run_id
            ).first()

            if run:
                run.task_description = task[:500] if task else "No task description"
                run.agent = config.get("agent", "engineer")
                run.model = config.get("model", "gpt-4o")
                if run.meta:
                    run.meta["config"] = {
                        k: v for k, v in config.items()
                        if k not in ["apiKeys", "api_keys"]  # Don't store API keys
                    }
                self.db_session.commit()
                logger.debug("workflow_run_task_updated")
        except Exception as e:
            logger.error("workflow_run_task_update_failed", error=str(e))
            try:
                self.db_session.rollback()
            except Exception:
                pass

    def create_dag_for_mode(self, task: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create initial DAG structure based on execution mode using templates."""
        self._update_workflow_run_task(task, config)

        template_key, overrides = MODE_TO_TEMPLATE.get(self.mode, ("fixed-pipeline", {}))
        template = DAG_TEMPLATES[template_key]

        # Dynamic overrides based on config
        if self.mode == "one-shot":
            agent = config.get("agent", "engineer")
            overrides = {"execute": {"label": f"Execute ({agent})", "agent": agent}}
        elif self.mode == "hitl-interactive":
            hitl_variant = config.get("hitlVariant", "full_interactive")
            label = "HITL Planning" if hitl_variant in ("planning_only", "full_interactive") else "Planning Phase"
            overrides = {"planning": {"label": label}}

        return self._create_from_template(template, task, overrides)

    def _create_from_template(self, template: Dict[str, Any], task: str,
                              overrides: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Create DAG nodes and edges from a template with optional overrides."""
        self.nodes = copy.deepcopy(template["initial_nodes"])
        self.edges = copy.deepcopy(template["initial_edges"])

        # Apply per-node overrides
        for node in self.nodes:
            node_overrides = overrides.get(node["id"])
            if node_overrides:
                node.update(node_overrides)

        # Add task display to first node
        if self.nodes:
            task_display = task[:100] + "..." if len(task) > 100 else task
            self.nodes[0]["task"] = task_display

        for node in self.nodes:
            self.node_statuses[node["id"]] = "pending"

        # Persist all DAGs to database (both dynamic and fixed-pipeline)
        self._persist_dag_nodes_to_db()

        return {"nodes": self.nodes, "edges": self.edges, "levels": len(self.nodes)}

    def _make_dag_node_id(self, node_id: str) -> str:
        """Create a unique DAG node ID for database storage.

        Generates a deterministic UUID-like ID scoped to the current run,
        avoiding cross-run collisions for generic IDs like 'planning', 'step_1'.
        Keeps a mapping so the same input always returns the same output.
        """
        if not hasattr(self, '_node_id_map'):
            self._node_id_map = {}

        if node_id in self._node_id_map:
            return self._node_id_map[node_id]

        if not self.run_id:
            self._node_id_map[node_id] = node_id
            return node_id

        # Create a deterministic short hash: run_id + node_id → consistent ID
        combined = f"{self.run_id}:{node_id}"
        hash_hex = hashlib.md5(combined.encode()).hexdigest()
        # Use first 32 chars of hex as a UUID-like ID (fits in String(36))
        db_id = hash_hex[:32]
        self._node_id_map[node_id] = db_id
        return db_id

    def _reverse_node_id(self, db_node_id: str) -> str:
        """Reverse map a DB node ID back to the original short node ID."""
        if not hasattr(self, '_node_id_map'):
            return db_node_id
        for short_id, mapped_id in self._node_id_map.items():
            if mapped_id == db_node_id:
                return short_id
        return db_node_id

    def _persist_dag_nodes_to_db(self):
        """Persist DAG nodes to database to satisfy foreign key constraints."""
        if not self.db_session or not self.run_id:
            return

        try:
            from cmbagent.database.models import DAGNode, DAGEdge

            for idx, node in enumerate(self.nodes):
                db_node_id = self._make_dag_node_id(node["id"])

                existing_node = self.db_session.query(DAGNode).filter(
                    DAGNode.id == db_node_id,
                    DAGNode.run_id == self.run_id
                ).first()

                if existing_node:
                    # Update status and meta for existing nodes
                    existing_node.status = node.get("status", existing_node.status)
                    existing_node.meta = node
                else:
                    dag_node = DAGNode(
                        id=db_node_id,
                        run_id=self.run_id,
                        session_id=self.session_id,
                        node_type=node.get("type", "agent"),
                        agent=node.get("agent", "unknown"),
                        status=node.get("status", "pending"),
                        order_index=node.get("step_number", idx),
                        meta=node
                    )
                    self.db_session.add(dag_node)

            for edge in self.edges:
                db_source_id = self._make_dag_node_id(edge["source"])
                db_target_id = self._make_dag_node_id(edge["target"])

                existing_edge = self.db_session.query(DAGEdge).filter(
                    DAGEdge.from_node_id == db_source_id,
                    DAGEdge.to_node_id == db_target_id
                ).first()

                if not existing_edge:
                    dag_edge = DAGEdge(
                        from_node_id=db_source_id,
                        to_node_id=db_target_id,
                        dependency_type="sequential"
                    )
                    self.db_session.add(dag_edge)

            _safe_commit(self.db_session, "dag_persist")
            logger.debug("dag_persisted", nodes=len(self.nodes), edges=len(self.edges))

        except Exception as e:
            error_msg = str(e).lower()
            if 'prepared' in error_msg or 'transaction' in error_msg or 'commit' in error_msg:
                logger.debug("dag_persist_skipped_concurrent", error=str(e))
            else:
                logger.error("dag_persist_failed", error=str(e), exc_info=True)

            if self.db_session:
                try:
                    self.db_session.rollback()
                except Exception:
                    pass

    def _update_node_status_in_db(self, node_id: str, new_status: str, error: str = None):
        """Update a single node's status in the database."""
        if not self.db_session or not self.run_id:
            return

        try:
            from cmbagent.database.models import DAGNode

            db_node_id = self._make_dag_node_id(node_id)
            db_node = self.db_session.query(DAGNode).filter(
                DAGNode.id == db_node_id,
                DAGNode.run_id == self.run_id
            ).first()

            if db_node:
                db_node.status = new_status
                # Update meta with current in-memory node data
                for node in self.nodes:
                    if node["id"] == node_id:
                        db_node.meta = node
                        break
                _safe_commit(self.db_session, f"dag_node_status_{node_id}")
            else:
                # Node not yet persisted - persist all nodes first
                self._persist_dag_nodes_to_db()
        except Exception as e:
            logger.debug("dag_node_status_update_failed", node_id=node_id, error=str(e))
            if self.db_session:
                try:
                    self.db_session.rollback()
                except Exception:
                    pass

    async def add_step_nodes(self, steps: list):
        """Dynamically add step nodes after planning completes."""
        for i, step_info in enumerate(steps, 1):
            step_id = f"step_{i}"
            if isinstance(step_info, dict):
                # Handle both formats: standard planning uses "task"/"agent", HITL uses "sub_task"/"sub_task_agent"
                description = step_info.get("description") or step_info.get("sub_task_description", "")
                task = step_info.get("task") or step_info.get("sub_task", "")
                agent = step_info.get("agent") or step_info.get("sub_task_agent", "engineer")
                insights = step_info.get("insights", "")
                goal = step_info.get("goal", "")
                summary = step_info.get("summary", "")
                bullet_points = step_info.get("bullet_points", [])

                # Use task as description if description is empty
                if not description and task:
                    description = task

                # Build label from the most informative field
                label_source = goal or task or description
                if label_source:
                    truncated_label = label_source.strip()[:80]
                    if len(label_source.strip()) > 80:
                        truncated_label += "..."
                    label = f"Step {i}: {truncated_label}"
                else:
                    label = step_info.get("title", f"Step {i}: {agent}")
            else:
                label = f"Step {i}"
                description = str(step_info)[:200] if step_info else ""
                task = str(step_info) if step_info else ""
                agent = "engineer"
                insights = ""
                goal = ""
                summary = ""
                bullet_points = []

            self.nodes.append({
                "id": step_id,
                "label": label,
                "type": "agent",
                "agent": agent,
                "status": "pending",
                "step_number": i,
                "description": description,
                "task": task,
                "insights": insights,
                "goal": goal,
                "summary": summary,
                "bullet_points": bullet_points
            })
            self.node_statuses[step_id] = "pending"

        # Add terminator node
        terminator_step = len(steps) + 1

        # Check if template has synthesis_after_steps
        template_key, _ = MODE_TO_TEMPLATE.get(self.mode, ("fixed-pipeline", {}))
        template = DAG_TEMPLATES.get(template_key, {})
        has_synthesis = template.get("synthesis_after_steps", False)

        if has_synthesis:
            # Insert synthesis node before terminator
            synthesis_step = terminator_step
            terminator_step = synthesis_step + 1

            self.nodes.append({
                "id": "synthesis",
                "label": "Result Synthesis",
                "type": "agent",
                "agent": "researcher",
                "status": "pending",
                "step_number": synthesis_step,
                "description": "Synthesizing results from all phases",
            })
            self.node_statuses["synthesis"] = "pending"

        self.nodes.append({
            "id": "terminator",
            "label": "Completion",
            "type": "terminator",
            "agent": "system",
            "status": "pending",
            "step_number": terminator_step,
            "description": "Workflow completed"
        })
        self.node_statuses["terminator"] = "pending"

        # Preserve pre-planning edges (e.g. literature_review → planning)
        pre_planning_edges = [
            e for e in self.edges
            if e.get("target") != "step_1" and not e.get("source", "").startswith("step_")
        ]
        self.edges = list(pre_planning_edges)

        # Create edges for steps: planning → step_1 → step_2 → ... → [synthesis →] terminator
        self.edges.append({"source": "planning", "target": "step_1"})
        for i in range(1, len(steps)):
            self.edges.append({"source": f"step_{i}", "target": f"step_{i+1}"})

        if has_synthesis:
            self.edges.append({"source": f"step_{len(steps)}", "target": "synthesis"})
            self.edges.append({"source": "synthesis", "target": "terminator"})
        else:
            self.edges.append({"source": f"step_{len(steps)}", "target": "terminator"})

        # Persist all nodes (including new step nodes) to database
        self._persist_dag_nodes_to_db()

        # Emit dag_updated event
        try:
            effective_run_id = self.run_id or self.task_id
            await self.send_event(
                self.websocket,
                "dag_updated",
                {
                    "run_id": effective_run_id,
                    "nodes": self.nodes,
                    "edges": self.edges,
                    "levels": len(steps) + 2
                },
                run_id=effective_run_id,
                session_id=self.session_id
            )
        except Exception as e:
            logger.warning("dag_updated_event_failed", error=str(e))

    async def emit_dag_created(self):
        """Emit DAG created event."""
        effective_run_id = self.run_id or self.task_id
        try:
            await self.send_event(
                self.websocket,
                "dag_created",
                {
                    "run_id": effective_run_id,
                    "nodes": self.nodes,
                    "edges": self.edges,
                    "levels": len(set(n.get("step_number", 0) for n in self.nodes))
                },
                run_id=effective_run_id,
                session_id=self.session_id
            )
        except Exception as e:
            logger.warning("dag_created_event_failed", error=str(e))

    async def update_node_status(self, node_id: str, new_status: str,
                                  error: str = None, work_dir: str = None):
        """Update a node's status and emit event."""
        old_status = self.node_statuses.get(node_id, "pending")
        self.node_statuses[node_id] = new_status
        effective_run_id = self.run_id or self.task_id

        node_info = None
        for node in self.nodes:
            if node["id"] == node_id:
                node["status"] = new_status
                if error:
                    node["error"] = error
                node_info = node
                break

        # Auto-detect phase from node_id when node starts running
        if new_status == "running":
            if node_id == "planning" or node_id == "init":
                self.set_phase("planning", None)
            elif node_id.startswith("step_"):
                try:
                    step_num = int(node_id.split("_")[1])
                    self.set_phase("control", step_num)
                except (ValueError, IndexError):
                    self.set_phase("control", None)
            elif node_id == "execute":
                self.set_phase("execution", None)
            elif node_id == "terminator":
                pass  # Keep current phase

        if new_status == "completed" and work_dir:
            self.track_files_in_work_dir(work_dir, node_id)

        # Update persisted node status in database
        self._update_node_status_in_db(node_id, new_status, error)

        # Create ExecutionEvent in database
        if self.event_repo and node_info:
            try:
                agent_name = node_info.get("agent", "unknown")
                db_node_id = self._make_dag_node_id(node_id)

                if new_status == "running":
                    self.execution_order_counter += 1
                    event = self.event_repo.create_event(
                        run_id=self.run_id,
                        node_id=db_node_id,
                        event_type="agent_call",
                        execution_order=self.execution_order_counter,
                        event_subtype="execution",
                        agent_name=agent_name,
                        status="running",
                        started_at=datetime.now(timezone.utc),
                        inputs={"node_info": node_info},
                        meta={"old_status": old_status, "new_status": new_status}
                    )
                    self.node_event_map[node_id] = event.id

                elif new_status in ["completed", "error"]:
                    event_id = self.node_event_map.get(node_id)
                    if event_id:
                        completed_at = datetime.now(timezone.utc)
                        started_at_event = self.event_repo.get_event(event_id)
                        duration_ms = None
                        if started_at_event and started_at_event.started_at:
                            started_at = started_at_event.started_at
                            if started_at.tzinfo is None:
                                started_at = started_at.replace(tzinfo=timezone.utc)
                            duration_ms = int((completed_at - started_at).total_seconds() * 1000)

                        self.event_repo.update_event(
                            event_id=event_id,
                            completed_at=completed_at,
                            duration_ms=duration_ms,
                            outputs={"status": new_status},
                            error_message=error,
                            status="completed" if new_status == "completed" else "failed"
                        )
                    else:
                        self.execution_order_counter += 1
                        self.event_repo.create_event(
                            run_id=self.run_id,
                            node_id=db_node_id,
                            event_type="agent_call",
                            execution_order=self.execution_order_counter,
                            event_subtype="execution",
                            agent_name=agent_name,
                            status="completed" if new_status == "completed" else "failed",
                            started_at=datetime.now(timezone.utc),
                            completed_at=datetime.now(timezone.utc),
                            inputs={"node_info": node_info},
                            outputs={"status": new_status},
                            error_message=error,
                            meta={"old_status": old_status, "new_status": new_status}
                        )

            except Exception as e:
                logger.error("execution_event_creation_failed", node_id=node_id, error=str(e), exc_info=True)
                if self.db_session:
                    try:
                        self.db_session.rollback()
                    except Exception:
                        pass

        # Send WebSocket event
        try:
            data = {
                "node_id": node_id,
                "old_status": old_status,
                "new_status": new_status,
                "node": node_info
            }
            if error:
                data["error"] = error
            await self.send_event(
                self.websocket,
                "dag_node_status_changed",
                data,
                run_id=effective_run_id,
                session_id=self.session_id
            )

            await self.send_event(
                self.websocket,
                "dag_updated",
                {
                    "run_id": effective_run_id,
                    "nodes": self.nodes,
                    "edges": self.edges
                },
                run_id=effective_run_id,
                session_id=self.session_id
            )
        except Exception as e:
            logger.warning("dag_node_status_event_failed", error=str(e))

    def get_node_by_step(self, step_number: int) -> Optional[str]:
        """Get node ID by step number."""
        for node in self.nodes:
            if node.get("step_number") == step_number:
                return node["id"]
        return None

    def get_first_node(self) -> Optional[str]:
        """Get the first node ID."""
        if self.nodes:
            return self.nodes[0]["id"]
        return None

    def get_last_node(self) -> Optional[str]:
        """Get the last node ID (terminator)."""
        for node in self.nodes:
            if node.get("type") == "terminator":
                return node["id"]
        return None

    def set_phase(self, phase: str, step_number: int = None):
        """Set the current workflow phase and optional step number.

        Args:
            phase: One of 'planning', 'control', 'execution'
            step_number: Optional step number for control phase
        """
        self.current_phase = phase
        self.current_step_number = step_number
        logger.debug("phase_set", phase=phase, step=step_number)

    def get_current_phase(self) -> str:
        """Get the current workflow phase."""
        return self.current_phase

    def get_current_step_number(self) -> Optional[int]:
        """Get the current step number."""
        return self.current_step_number

    def track_files_in_work_dir(self, work_dir: str, node_id: str = None,
                               step_id: str = None, generating_agent: str = None,
                               workflow_phase: str = None):
        """Scan work directory and track generated files using FileRepository.

        Args:
            work_dir: Root work directory to scan.
            node_id: DAG node that produced the files.
            step_id: Explicit workflow step ID.
            generating_agent: Agent that generated the files.
            workflow_phase: Explicit phase (overrides path guessing).
        """
        if not self.db_session or not self.run_id:
            return 0

        try:
            from cmbagent.database.file_repository import FileRepository
            from cmbagent.database.models import WorkflowStep

            file_repo = FileRepository(self.db_session, self.session_id)
            event_id = self.node_event_map.get(node_id) if node_id else None
            # Use DB-scoped node_id for FK reference
            db_node_id = self._make_dag_node_id(node_id) if node_id else None

            # Resolve step_id from node_id or current state
            db_step_id = step_id
            if not db_step_id and node_id and node_id.startswith("step_"):
                try:
                    step_num = int(node_id.split("_")[1])
                    step = self.db_session.query(WorkflowStep).filter(
                        WorkflowStep.run_id == self.run_id,
                        WorkflowStep.step_number == step_num
                    ).first()
                    if step:
                        db_step_id = step.id
                except (ValueError, IndexError):
                    pass
            elif not db_step_id and self.current_step_number and self.current_phase == "control":
                try:
                    step = self.db_session.query(WorkflowStep).filter(
                        WorkflowStep.run_id == self.run_id,
                        WorkflowStep.step_number == self.current_step_number
                    ).first()
                    if step:
                        db_step_id = step.id
                except Exception:
                    pass

            # Use explicit phase instead of guessing from path
            phase = workflow_phase or self.current_phase or "execution"

            output_dirs = [
                "data", "codebase", "outputs", "chats", "cost", "time",
                "planning", "control", "context", "docs", "summaries", "runs"
            ]
            files_tracked = 0

            if not os.path.exists(work_dir):
                return 0

            for output_dir_name in output_dirs:
                output_dir = os.path.join(work_dir, output_dir_name)
                if not os.path.exists(output_dir):
                    continue

                for root, dirs, files in os.walk(output_dir):
                    dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']

                    for filename in files:
                        if filename.startswith('.'):
                            continue

                        file_path = os.path.join(root, filename)
                        rel_path = os.path.relpath(file_path, work_dir)
                        file_type = self._classify_file_type(filename, rel_path)

                        # Determine workflow phase: explicit > directory-based > tracker state
                        rel_parts = rel_path.lower().split(os.sep)
                        if workflow_phase:
                            file_phase = workflow_phase
                        elif 'planning' in rel_parts:
                            file_phase = "planning"
                        elif 'control' in rel_parts:
                            file_phase = "control"
                        else:
                            file_phase = phase

                        is_final_output = file_type in ("plot", "data", "code", "plan")
                        if 'context' in rel_parts or 'temp' in rel_parts:
                            is_final_output = False

                        file_repo.register_file(
                            run_id=self.run_id,
                            file_path=file_path,
                            file_type=file_type,
                            node_id=db_node_id,
                            step_id=db_step_id,
                            event_id=event_id,
                            workflow_phase=file_phase,
                            generating_agent=generating_agent,
                            is_final_output=is_final_output,
                        )
                        files_tracked += 1

            _safe_commit(self.db_session, "file_tracking")
            if files_tracked > 0:
                logger.debug("files_tracked", count=files_tracked)

                try:
                    effective_run_id = self.run_id or self.task_id
                    event_coro = self.send_event(
                        self.websocket,
                        "files_updated",
                        {
                            "run_id": effective_run_id,
                            "node_id": node_id,
                            "step_id": db_step_id,
                            "files_tracked": files_tracked
                        },
                        run_id=effective_run_id,
                        session_id=self.session_id
                    )
                    try:
                        loop = asyncio.get_running_loop()
                        asyncio.create_task(event_coro)
                    except RuntimeError:
                        # Called from sync thread - use stored event loop
                        if self._event_loop:
                            asyncio.run_coroutine_threadsafe(event_coro, self._event_loop)
                except Exception as ws_err:
                    logger.debug("files_updated_event_failed", error=str(ws_err))

            return files_tracked

        except Exception as e:
            logger.error("file_tracking_failed", error=str(e), exc_info=True)
            if self.db_session:
                try:
                    self.db_session.rollback()
                except Exception:
                    pass
            return 0

    @staticmethod
    def _classify_file_type(filename: str, rel_path: str) -> str:
        """Classify file type by name patterns, directory, and extension."""
        file_ext = os.path.splitext(filename)[1].lower()
        rel_parts = rel_path.lower().split(os.sep)

        # Explicit pattern matching first
        if filename == 'final_plan.json' or filename.endswith('_plan.json'):
            return "plan"
        if filename.startswith('timing_report') or filename.startswith('cost_report'):
            return "report"
        # Directory-based classification
        if 'codebase' in rel_parts:
            return "code"
        if 'chats' in rel_parts:
            return "chat"
        if 'context' in rel_parts:
            return "context"
        if 'time' in rel_parts or 'cost' in rel_parts:
            return "report"
        if 'planning' in rel_parts and file_ext == '.json':
            return "plan"
        # Extension-based classification
        if file_ext in (".py", ".js", ".ts", ".java", ".cpp", ".c", ".h", ".go", ".rs", ".rb", ".sh"):
            return "code"
        if file_ext in (".csv", ".json", ".pkl", ".pickle", ".npz", ".npy", ".parquet", ".yaml", ".yml", ".h5", ".hdf5", ".fits"):
            return "data"
        if file_ext in (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".svg", ".eps", ".bmp", ".tiff"):
            return "plot"
        if file_ext in (".txt", ".md", ".rst", ".html"):
            return "report"
        if file_ext == ".log":
            return "log"
        return "other"

    async def build_dag_from_plan(self, plan_output: Dict[str, Any]):
        """Build DAG from plan output after planning phase completes.

        DEPRECATED: Use add_step_nodes() directly. Kept as thin wrapper
        for backwards compatibility during migration.
        """
        number_of_steps = plan_output.get('number_of_steps_in_plan', 0)
        steps = plan_output.get('steps', [])
        if not steps and number_of_steps > 0:
            steps = [{"task": f"Execute step {i+1}", "agent": "engineer"}
                     for i in range(number_of_steps)]
        await self.add_step_nodes(steps)
        return {"nodes": self.nodes, "edges": self.edges, "levels": len(steps) + 2}

    async def add_branch_point(self, step_id: str, branch_names: List[str]):
        """Add a visual branch-point node to the DAG after a given step.

        Creates a ``branch_point`` node connected to *step_id* with metadata
        listing the branch names that were spawned.  This is purely for
        visualization – actual branch execution happens in separate DAGTracker
        instances.

        Args:
            step_id: The DAG node ID at which branching occurs (e.g. ``"step_2"``).
            branch_names: Human-readable names of the branches that were created.
        """
        node_id = f"branch_at_{step_id}"
        node = {
            "id": node_id,
            "type": "branch_point",
            "label": "Branch Point",
            "status": "completed",
            "step_number": -1,
            "description": f"Branches: {', '.join(branch_names)}",
            "branches": branch_names,
        }
        self.nodes.append(node)
        self.node_statuses[node_id] = "completed"
        self.edges.append({"source": step_id, "target": node_id})

        # Persist branch point node to database
        self._persist_dag_nodes_to_db()

        effective_run_id = self.run_id or self.task_id
        try:
            await self.send_event(
                self.websocket,
                "dag_updated",
                {
                    "run_id": effective_run_id,
                    "nodes": self.nodes,
                    "edges": self.edges,
                },
                run_id=effective_run_id,
                session_id=self.session_id,
            )
        except Exception as e:
            logger.warning("branch_point_event_failed", error=str(e))
