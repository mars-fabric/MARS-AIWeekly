"""
Database callback factory for workflow events.

Creates WorkflowCallbacks that persist workflow state changes
to the database for recovery and querying.
"""

import logging
from typing import Optional, Dict, Any

from cmbagent.callbacks import WorkflowCallbacks, PlanInfo, StepInfo

logger = logging.getLogger(__name__)


def create_database_callbacks(
    db_session,
    session_id: str,
    run_id: str
) -> WorkflowCallbacks:
    """
    Create WorkflowCallbacks that update database state.

    Args:
        db_session: SQLAlchemy database session
        session_id: CMBAgent session ID
        run_id: Workflow run ID

    Returns:
        WorkflowCallbacks configured for database updates
    """
    def on_planning_start(task: str, config: Dict[str, Any]) -> None:
        try:
            from cmbagent.database.models import DAGNode, WorkflowRun
            from cmbagent.database.states import WorkflowState

            # Update workflow status
            run = db_session.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
            if run:
                run.status = WorkflowState.PLANNING.value
                db_session.commit()

            # Update planning node
            planning_node = db_session.query(DAGNode).filter(
                DAGNode.run_id == run_id,
                DAGNode.node_type == "planning"
            ).first()
            if planning_node:
                planning_node.status = "running"
                db_session.commit()
        except Exception as e:
            logger.error(f"Error updating database on planning start: {e}")

    def on_planning_complete(plan_info: PlanInfo) -> None:
        try:
            from cmbagent.database.models import DAGNode, WorkflowRun
            from cmbagent.database.states import WorkflowState
            from cmbagent.database.dag_builder import DAGBuilder

            # Update workflow status
            run = db_session.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
            if run:
                run.status = WorkflowState.EXECUTING.value
                db_session.commit()

            # Update planning node
            planning_node = db_session.query(DAGNode).filter(
                DAGNode.run_id == run_id,
                DAGNode.node_type == "planning"
            ).first()
            if planning_node:
                planning_node.status = "completed"
                db_session.commit()

            # Build DAG nodes for steps in database
            try:
                dag_builder = DAGBuilder(db_session, session_id)
                steps = [{"task": s.get("sub_task_description", ""), "agent": s.get("sub_task_agent", "engineer")} for s in plan_info.steps]
                dag_builder.build_from_plan(run_id, {"steps": steps})
            except Exception as e:
                logger.warning(f"Could not build DAG in database: {e}")

        except Exception as e:
            logger.error(f"Error updating database on planning complete: {e}")

    def on_step_start(step_info: StepInfo) -> None:
        try:
            from cmbagent.database.models import DAGNode

            step_node = db_session.query(DAGNode).filter(
                DAGNode.run_id == run_id,
                DAGNode.order_index == step_info.step_number
            ).first()
            if step_node:
                step_node.status = "running"
                db_session.commit()
        except Exception as e:
            logger.error(f"Error updating database on step start: {e}")

    def on_step_complete(step_info: StepInfo) -> None:
        try:
            from cmbagent.database.models import DAGNode, WorkflowStep

            # Update DAGNode status
            step_node = db_session.query(DAGNode).filter(
                DAGNode.run_id == run_id,
                DAGNode.order_index == step_info.step_number
            ).first()
            if step_node:
                step_node.status = "completed"

            # Update WorkflowStep with summary
            workflow_step = db_session.query(WorkflowStep).filter(
                WorkflowStep.run_id == run_id,
                WorkflowStep.step_number == step_info.step_number
            ).first()
            if workflow_step and step_info.summary:
                workflow_step.summary = step_info.summary
                workflow_step.status = "completed"

            db_session.commit()
        except Exception as e:
            logger.error(f"Error updating database on step complete: {e}")

    def on_step_failed(step_info: StepInfo) -> None:
        try:
            from cmbagent.database.models import DAGNode

            step_node = db_session.query(DAGNode).filter(
                DAGNode.run_id == run_id,
                DAGNode.order_index == step_info.step_number
            ).first()
            if step_node:
                step_node.status = "failed"
                db_session.commit()
        except Exception as e:
            logger.error(f"Error updating database on step failed: {e}")

    def on_workflow_complete(final_context: Dict[str, Any], total_time: float) -> None:
        try:
            from cmbagent.database.models import DAGNode, WorkflowRun
            from cmbagent.database.states import WorkflowState

            run = db_session.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
            if run:
                run.status = WorkflowState.COMPLETED.value
                db_session.commit()

            # Update terminator node
            terminator = db_session.query(DAGNode).filter(
                DAGNode.run_id == run_id,
                DAGNode.node_type == "terminator"
            ).first()
            if terminator:
                terminator.status = "completed"
                db_session.commit()
        except Exception as e:
            logger.error(f"Error updating database on workflow complete: {e}")

    def on_workflow_failed(error: str, failed_step: Optional[int]) -> None:
        try:
            from cmbagent.database.models import WorkflowRun
            from cmbagent.database.states import WorkflowState

            run = db_session.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
            if run:
                run.status = WorkflowState.FAILED.value
                db_session.commit()
        except Exception as e:
            logger.error(f"Error updating database on workflow failed: {e}")

    return WorkflowCallbacks(
        on_planning_start=on_planning_start,
        on_planning_complete=on_planning_complete,
        on_step_start=on_step_start,
        on_step_complete=on_step_complete,
        on_step_failed=on_step_failed,
        on_workflow_complete=on_workflow_complete,
        on_workflow_failed=on_workflow_failed
    )
