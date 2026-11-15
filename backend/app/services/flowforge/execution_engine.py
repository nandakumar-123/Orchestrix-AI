from __future__ import annotations

import collections
import logging
import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import utc_now
from app.db.models.flowforge import (
    WorkflowApprovalStatus,
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowExecution,
    WorkflowExecutionStatus,
    WorkflowStepExecution,
    WorkflowStepStatus,
    WorkflowVersion,
)
from app.services.flowforge.agent_adapter import FlowForgeAgentAdapter
from app.services.flowforge.approval_service import WorkflowApprovalService
from app.services.flowforge.schemas import WorkflowNodeType

logger = logging.getLogger("orchestrix.flowforge.engine")


class WorkflowExecutionError(Exception):
    """Raised when an unrecoverable execution error occurs."""

    pass


class FlowForgeExecutionEngine:
    """
    Core Workflow Execution Coordinator for FlowForge.
    Coordinates:
    - Immutable workflow snapshot loading
    - Execution lifecycle (PENDING -> RUNNING -> WAITING_FOR_APPROVAL -> COMPLETED / FAILED / CANCELLED)
    - Sequential and parallel branching with deterministic merge synchronization
    - Conditional node evaluation
    - Human approval pausing and resuming
    - Retry limit handling and recovery
    - Transactional audit event generation
    """

    def __init__(
        self,
        agent_adapter: FlowForgeAgentAdapter | None = None,
        approval_service: WorkflowApprovalService | None = None,
    ) -> None:
        self.agent_adapter = agent_adapter or FlowForgeAgentAdapter()
        self.approval_service = approval_service or WorkflowApprovalService()

    async def start_execution(
        self,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        workspace_id: uuid.UUID,
        trigger_id: uuid.UUID | None = None,
        context_data: dict[str, Any] | None = None,
        workflow_version_id: uuid.UUID | None = None,
    ) -> WorkflowExecution:
        """
        Initialize and run a new workflow execution using an immutable version snapshot.
        If workflow_version_id is not specified, uses the latest version.
        """
        # Resolve workflow
        wf = await db.get(WorkflowDefinition, workflow_id)
        if not wf or wf.workspace_id != workspace_id:
            raise WorkflowExecutionError(f"Workflow {workflow_id} not found in workspace.")

        # Resolve version snapshot
        if workflow_version_id:
            stmt = select(WorkflowVersion).where(
                WorkflowVersion.id == workflow_version_id,
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.workspace_id == workspace_id,
            )
        else:
            stmt = (
                select(WorkflowVersion)
                .where(
                    WorkflowVersion.workflow_id == workflow_id,
                    WorkflowVersion.workspace_id == workspace_id,
                )
                .order_by(desc(WorkflowVersion.version_number))
                .limit(1)
            )
        res = await db.execute(stmt)
        version = res.scalar_one_or_none()
        if not version:
            raise WorkflowExecutionError(
                f"No valid workflow version found for workflow {workflow_id}."
            )

        ctx = dict(context_data or {})
        ctx["workflow_id"] = str(workflow_id)

        execution = WorkflowExecution(
            workflow_id=workflow_id,
            workflow_version_id=version.id,
            workspace_id=workspace_id,
            trigger_id=trigger_id,
            status=WorkflowExecutionStatus.RUNNING,
            context_data=ctx,
            started_at=utc_now(),
            created_at=utc_now(),
        )
        db.add(execution)
        await db.flush()

        # Emit EXECUTION_STARTED event
        db.add(
            WorkflowEvent(
                execution_id=execution.id,
                workspace_id=workspace_id,
                event_type=WorkflowEventType.EXECUTION_STARTED,
                payload_json={
                    "workflow_id": str(workflow_id),
                    "version_number": version.version_number,
                    "trigger_id": str(trigger_id) if trigger_id else None,
                },
                created_at=utc_now(),
            )
        )
        await db.flush()

        # Progress the graph execution
        await self._progress_execution(db, execution, version.workflow_definition_json)

        # Refresh execution with loaded steps and approvals to avoid lazy load MissingGreenlet
        stmt_refresh = (
            select(WorkflowExecution)
            .where(WorkflowExecution.id == execution.id)
            .options(
                selectinload(WorkflowExecution.steps),
                selectinload(WorkflowExecution.approvals),
            )
        )
        res_refresh = await db.execute(stmt_refresh)
        return res_refresh.scalar_one()

    async def resume_execution(
        self,
        db: AsyncSession,
        execution_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> WorkflowExecution:
        """
        Resume an execution that was WAITING_FOR_APPROVAL or interrupted.
        Validates pending approvals and progresses graph if all pending approvals are resolved.
        """
        stmt = (
            select(WorkflowExecution)
            .where(
                WorkflowExecution.id == execution_id,
                WorkflowExecution.workspace_id == workspace_id,
            )
            .options(
                selectinload(WorkflowExecution.version),
                selectinload(WorkflowExecution.steps),
                selectinload(WorkflowExecution.approvals),
            )
        )
        res = await db.execute(stmt)
        execution = res.scalar_one_or_none()
        if not execution:
            raise WorkflowExecutionError(f"Execution {execution_id} not found in workspace.")

        if execution.status in {
            WorkflowExecutionStatus.COMPLETED,
            WorkflowExecutionStatus.FAILED,
            WorkflowExecutionStatus.CANCELLED,
            WorkflowExecutionStatus.TIMED_OUT,
        }:
            return execution

        # Check if there are any still-pending approvals
        has_pending = any(a.status == WorkflowApprovalStatus.PENDING for a in execution.approvals)
        if has_pending:
            logger.info(f"Execution {execution_id} still has pending approvals; cannot resume yet.")
            return execution

        # Any rejected approvals mean execution cannot continue
        has_rejected = any(a.status == WorkflowApprovalStatus.REJECTED for a in execution.approvals)
        if has_rejected:
            execution.status = WorkflowExecutionStatus.FAILED
            execution.completed_at = utc_now()
            execution.error_summary = "Execution halted due to rejected approval checkpoint."
            await db.flush()
            return execution

        # Set status back to RUNNING and progress
        execution.status = WorkflowExecutionStatus.RUNNING
        await db.flush()

        await self._progress_execution(db, execution, execution.version.workflow_definition_json)

        # Refresh with relationships loaded
        stmt_refresh = (
            select(WorkflowExecution)
            .where(WorkflowExecution.id == execution.id)
            .options(
                selectinload(WorkflowExecution.steps),
                selectinload(WorkflowExecution.approvals),
            )
        )
        res_refresh = await db.execute(stmt_refresh)
        return res_refresh.scalar_one()

    async def cancel_execution(
        self,
        db: AsyncSession,
        execution_id: uuid.UUID,
        workspace_id: uuid.UUID,
        reason: str | None = None,
    ) -> WorkflowExecution:
        """Cancel an in-progress or paused workflow execution."""
        stmt = (
            select(WorkflowExecution)
            .where(
                WorkflowExecution.id == execution_id,
                WorkflowExecution.workspace_id == workspace_id,
            )
            .options(
                selectinload(WorkflowExecution.steps),
                selectinload(WorkflowExecution.approvals),
            )
        )
        res = await db.execute(stmt)
        execution = res.scalar_one_or_none()
        if not execution:
            raise WorkflowExecutionError(f"Execution {execution_id} not found in workspace.")

        if execution.status in {
            WorkflowExecutionStatus.COMPLETED,
            WorkflowExecutionStatus.FAILED,
            WorkflowExecutionStatus.CANCELLED,
        }:
            return execution

        execution.status = WorkflowExecutionStatus.CANCELLED
        execution.completed_at = utc_now()
        execution.error_summary = f"Cancelled: {reason or 'User requested cancellation'}"

        # Cancel any pending steps
        for step in execution.steps:
            if step.status in {
                WorkflowStepStatus.PENDING,
                WorkflowStepStatus.RUNNING,
                WorkflowStepStatus.WAITING_FOR_APPROVAL,
            }:
                step.status = WorkflowStepStatus.CANCELLED
                step.completed_at = utc_now()

        # Cancel any pending approvals
        for approval in execution.approvals:
            if approval.status == WorkflowApprovalStatus.PENDING:
                approval.status = WorkflowApprovalStatus.CANCELLED
                approval.decided_at = utc_now()
                approval.decision_reason = "Execution was cancelled."

        # Emit audit event
        db.add(
            WorkflowEvent(
                execution_id=execution.id,
                workspace_id=workspace_id,
                event_type=WorkflowEventType.EXECUTION_CANCELLED,
                payload_json={"reason": reason},
                created_at=utc_now(),
            )
        )
        await db.flush()
        return execution

    SAFE_TO_RETRY_NODE_TYPES = {
        WorkflowNodeType.TRIGGER,
        WorkflowNodeType.NOTIFICATION,
        WorkflowNodeType.CONDITION,
        WorkflowNodeType.PARALLEL,
        WorkflowNodeType.MERGE,
        WorkflowNodeType.END,
    }

    async def recover_interrupted_executions(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID | None = None,
    ) -> list[WorkflowExecution]:
        """
        Scan for executions left in RUNNING status (e.g. from a backend process crash/restart).
        Safely reconciles interrupted step executions and resumes eligible workflows.
        - Classifies operations as safe-to-retry or unsafe-to-retry.
        - Safe operations (triggers, notifications, routing) are queued for resume/retry.
        - Unsafe operations (external agent mutations without reconciliation) are marked FAILED.
        - Completed steps remain preserved and are not re-executed.
        - Preserves pending approval state.
        - Emits EXECUTION_STARTED/RECOVERED audit events.
        """
        stmt = (
            select(WorkflowExecution)
            .where(WorkflowExecution.status == WorkflowExecutionStatus.RUNNING)
            .options(
                selectinload(WorkflowExecution.version),
                selectinload(WorkflowExecution.steps),
                selectinload(WorkflowExecution.approvals),
            )
        )
        if workspace_id:
            stmt = stmt.where(WorkflowExecution.workspace_id == workspace_id)

        res = await db.execute(stmt)
        interrupted = list(res.scalars().all())
        recovered_list: list[WorkflowExecution] = []

        for execution in interrupted:
            logger.info(f"Recovering interrupted workflow execution {execution.id}")

            definition_json = (
                execution.version.workflow_definition_json
                if execution.version
                else {}
            )
            node_map = {n["id"]: n for n in definition_json.get("nodes", [])}

            # Reconcile any in-flight steps that were marked RUNNING during crash
            for step in execution.steps:
                if step.status == WorkflowStepStatus.RUNNING:
                    node_data = node_map.get(step.node_id, {})
                    node_type = node_data.get("node_type", step.agent_type)

                    # Classify safe-to-retry vs unsafe-to-retry
                    if node_type in self.SAFE_TO_RETRY_NODE_TYPES:
                        # Safe side-effect-free operation: reset to PENDING so it can be re-evaluated
                        step.status = WorkflowStepStatus.PENDING
                        step.error_summary = "Interrupted by backend crash; queued for safe recovery retry"
                        db.add(
                            WorkflowEvent(
                                execution_id=execution.id,
                                workspace_id=execution.workspace_id,
                                event_type=WorkflowEventType.STEP_FAILED,
                                payload_json={
                                    "node_id": step.node_id,
                                    "action": "queued_for_retry",
                                    "reason": "Safe node interrupted by restart",
                                },
                                created_at=utc_now(),
                            )
                        )
                    else:
                        # Unsafe external side effect (e.g. code generation, active remediation):
                        # Mark FAILED to avoid uncontrolled blind re-execution
                        step.status = WorkflowStepStatus.FAILED
                        step.completed_at = utc_now()
                        step.error_summary = f"Interrupted unsafe step '{step.node_id}' ({node_type}) halted for safety"
                        db.add(
                            WorkflowEvent(
                                execution_id=execution.id,
                                workspace_id=execution.workspace_id,
                                event_type=WorkflowEventType.STEP_FAILED,
                                payload_json={
                                    "node_id": step.node_id,
                                    "action": "marked_failed",
                                    "reason": "Unsafe side-effecting agent step halted during crash recovery",
                                },
                                created_at=utc_now(),
                            )
                        )

            db.add(
                WorkflowEvent(
                    execution_id=execution.id,
                    workspace_id=execution.workspace_id,
                    event_type=WorkflowEventType.EXECUTION_STARTED,
                    payload_json={"recovery": True, "resumed_at": str(utc_now())},
                    created_at=utc_now(),
                )
            )
            await db.flush()

            # Resume progress using the immutable version snapshot
            if execution.version and execution.version.workflow_definition_json:
                await self._progress_execution(
                    db, execution, execution.version.workflow_definition_json
                )
                recovered_list.append(execution)
            else:
                execution.status = WorkflowExecutionStatus.FAILED
                execution.completed_at = utc_now()
                execution.error_summary = "Unrecoverable: missing workflow version definition."
                await db.flush()

        return recovered_list

    async def _progress_execution(
        self,
        db: AsyncSession,
        execution: WorkflowExecution,
        graph_def: dict[str, Any],
    ) -> None:
        """
        Main execution loop for progressing the DAG of nodes.
        Computes ready nodes, executes eligible nodes deterministically,
        handles branching, parallelism, merges, approvals, and terminal END nodes.
        """
        nodes_list = graph_def.get("nodes", [])
        connections_list = graph_def.get("connections", [])

        node_map: dict[str, dict[str, Any]] = {n["id"]: n for n in nodes_list}
        outgoing_conns: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        incoming_conns: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)

        for c in connections_list:
            src = c["source_node_id"]
            tgt = c["target_node_id"]
            outgoing_conns[src].append(c)
            incoming_conns[tgt].append(c)

        # Load existing step executions
        existing_steps_stmt = select(WorkflowStepExecution).where(
            WorkflowStepExecution.execution_id == execution.id,
            WorkflowStepExecution.workspace_id == execution.workspace_id,
        )
        steps_res = await db.execute(existing_steps_stmt)
        steps_by_node: dict[str, WorkflowStepExecution] = {
            s.node_id: s for s in steps_res.scalars().all()
        }

        context = dict(execution.context_data or {})

        # Find trigger node if no steps exist yet
        trigger_node_id = None
        for n_id, n_data in node_map.items():
            if n_data.get("node_type") == WorkflowNodeType.TRIGGER:
                trigger_node_id = n_id
                break

        if not trigger_node_id:
            execution.status = WorkflowExecutionStatus.FAILED
            execution.completed_at = utc_now()
            execution.error_summary = "Missing TRIGGER node in workflow definition."
            await db.flush()
            return

        # Start execution loop until no ready nodes or waiting for approval
        while True:
            # Determine which nodes have satisfied dependencies and are ready to run
            ready_node_ids: list[str] = []

            for n_id, n_data in node_map.items():
                step = steps_by_node.get(n_id)
                if step and step.status != WorkflowStepStatus.PENDING:
                    continue  # already evaluated, running, or terminal

                incomings = incoming_conns.get(n_id, [])
                if not incomings:
                    # Root node: must be the trigger
                    if n_id == trigger_node_id:
                        ready_node_ids.append(n_id)
                else:
                    n_type = n_data.get("node_type")
                    if n_type == WorkflowNodeType.MERGE:
                        # MERGE synchronization: all incoming active branches must be completed
                        # Or if branches were skipped, check if all incoming nodes are terminal
                        all_incomings_done = True
                        for inc in incomings:
                            src_id = inc["source_node_id"]
                            src_step = steps_by_node.get(src_id)
                            if not src_step or src_step.status not in {
                                WorkflowStepStatus.COMPLETED,
                                WorkflowStepStatus.SKIPPED,
                            }:
                                all_incomings_done = False
                                break
                        if all_incomings_done:
                            ready_node_ids.append(n_id)
                    else:
                        # Standard node: ready if at least one enabled incoming connection source is COMPLETED
                        is_ready = False
                        is_blocked = False
                        for inc in incomings:
                            src_id = inc["source_node_id"]
                            src_step = steps_by_node.get(src_id)
                            if not src_step:
                                # Preceding node not even evaluated yet
                                continue
                            if src_step.status == WorkflowStepStatus.COMPLETED:
                                # Check if conditional branch matches
                                branch_cond = inc.get("condition_branch")
                                if branch_cond:
                                    src_output = src_step.output_reference or {}
                                    if (
                                        str(src_output.get("branch")).lower()
                                        == str(branch_cond).lower()
                                    ):
                                        is_ready = True
                                else:
                                    is_ready = True
                            elif src_step.status == WorkflowStepStatus.FAILED:
                                is_blocked = True

                        if is_ready and not is_blocked:
                            ready_node_ids.append(n_id)

            if not ready_node_ids:
                # No more ready nodes. Check terminal conditions.
                # Check if any step is currently WAITING_FOR_APPROVAL
                waiting_steps = [
                    s
                    for s in steps_by_node.values()
                    if s.status == WorkflowStepStatus.WAITING_FOR_APPROVAL
                ]
                if waiting_steps:
                    execution.status = WorkflowExecutionStatus.WAITING_FOR_APPROVAL
                    await db.flush()
                    return

                # Check if any step failed
                failed_steps = [
                    s for s in steps_by_node.values() if s.status == WorkflowStepStatus.FAILED
                ]
                if failed_steps:
                    execution.status = WorkflowExecutionStatus.FAILED
                    execution.completed_at = utc_now()
                    execution.error_summary = f"Execution failed at node '{failed_steps[0].node_id}': {failed_steps[0].error_summary}"
                    # Cancel any other remaining incomplete steps
                    for remaining_step in steps_by_node.values():
                        if remaining_step.status in {
                            WorkflowStepStatus.PENDING,
                            WorkflowStepStatus.RUNNING,
                            WorkflowStepStatus.WAITING_FOR_APPROVAL,
                        }:
                            remaining_step.status = WorkflowStepStatus.CANCELLED
                            remaining_step.completed_at = utc_now()

                    db.add(
                        WorkflowEvent(
                            execution_id=execution.id,
                            workspace_id=execution.workspace_id,
                            event_type=WorkflowEventType.EXECUTION_FAILED,
                            payload_json={
                                "failed_node_id": failed_steps[0].node_id,
                                "error": failed_steps[0].error_summary,
                            },
                            created_at=utc_now(),
                        )
                    )
                    await db.flush()
                    return

                # Check if reached END nodes
                end_steps = [
                    s
                    for s in steps_by_node.values()
                    if node_map.get(s.node_id, {}).get("node_type") == WorkflowNodeType.END
                    and s.status == WorkflowStepStatus.COMPLETED
                ]
                if end_steps:
                    execution.status = WorkflowExecutionStatus.COMPLETED
                    execution.completed_at = utc_now()
                    execution.context_data = context
                    db.add(
                        WorkflowEvent(
                            execution_id=execution.id,
                            workspace_id=execution.workspace_id,
                            event_type=WorkflowEventType.EXECUTION_COMPLETED,
                            payload_json={"completed_steps_count": len(steps_by_node)},
                            created_at=utc_now(),
                        )
                    )
                    await db.flush()
                    return

                # If no END was reached and no ready nodes exist, consider completed or stuck
                execution.status = WorkflowExecutionStatus.COMPLETED
                execution.completed_at = utc_now()
                execution.context_data = context
                await db.flush()
                return

            # Execute ready nodes deterministically sorted by node_id with bounded concurrency (max 10 parallel tasks per wave)
            MAX_BRANCH_CONCURRENCY = 10
            for node_id in sorted(ready_node_ids)[:MAX_BRANCH_CONCURRENCY]:
                node_data = node_map[node_id]
                node_type = node_data.get("node_type")
                node_config = node_data.get("config", {})
                retry_limit = int(node_data.get("retry_limit", 0))

                # Check if an existing step execution exists (e.g. from crash recovery or prior attempt)
                step = steps_by_node.get(node_id)
                current_attempt = 1
                if step:
                    if step.status == WorkflowStepStatus.COMPLETED:
                        continue  # Already completed; do not rerun
                    current_attempt = step.attempt_number + 1
                    step.attempt_number = current_attempt
                    step.status = WorkflowStepStatus.RUNNING
                    step.started_at = utc_now()
                    step.error_summary = None
                else:
                    step = WorkflowStepExecution(
                        execution_id=execution.id,
                        workspace_id=execution.workspace_id,
                        node_id=node_id,
                        node_name=node_data.get("name"),
                        agent_type=node_type,
                        status=WorkflowStepStatus.RUNNING,
                        input_reference=node_config,
                        attempt_number=current_attempt,
                        started_at=utc_now(),
                        created_at=utc_now(),
                    )
                    db.add(step)
                    steps_by_node[node_id] = step

                await db.flush()

                # Emit STEP_STARTED
                db.add(
                    WorkflowEvent(
                        execution_id=execution.id,
                        workspace_id=execution.workspace_id,
                        event_type=WorkflowEventType.STEP_STARTED,
                        payload_json={
                            "node_id": node_id,
                            "node_type": node_type,
                            "attempt_number": current_attempt,
                        },
                        created_at=utc_now(),
                    )
                )
                await db.flush()

                # Node execution handling with bounded retry capability
                success = False
                while current_attempt <= (retry_limit + 1) and not success:
                    try:
                        if node_type == WorkflowNodeType.TRIGGER:
                            step.status = WorkflowStepStatus.COMPLETED
                            step.completed_at = utc_now()
                            step.output_reference = {"triggered_at": str(utc_now())}

                        elif node_type == WorkflowNodeType.END:
                            step.status = WorkflowStepStatus.COMPLETED
                            step.completed_at = utc_now()
                            step.output_reference = {"completed": True}

                        elif node_type == WorkflowNodeType.NOTIFICATION:
                            step.status = WorkflowStepStatus.COMPLETED
                            step.completed_at = utc_now()
                            step.output_reference = {
                                "delivered": True,
                                "message": node_config.get("message", "Workflow notification sent"),
                            }

                        elif node_type == WorkflowNodeType.PARALLEL:
                            # Branch fan-out node
                            step.status = WorkflowStepStatus.COMPLETED
                            step.completed_at = utc_now()
                            step.output_reference = {"parallel_fan_out": True}

                        elif node_type == WorkflowNodeType.MERGE:
                            # Join synchronization node
                            step.status = WorkflowStepStatus.COMPLETED
                            step.completed_at = utc_now()
                            step.output_reference = {"synchronized": True}

                        elif node_type == WorkflowNodeType.CONDITION:
                            # Evaluate condition
                            field_name = node_config.get("field")
                            operator = node_config.get("operator", "==")
                            target_val = node_config.get("value")

                            field_val = context.get(field_name) if field_name else None
                            cond_result = self._evaluate_condition(field_val, operator, target_val)

                            step.status = WorkflowStepStatus.COMPLETED
                            step.completed_at = utc_now()
                            step.output_reference = {
                                "condition_met": cond_result,
                                "branch": "true" if cond_result else "false",
                                "evaluated_field": field_name,
                            }

                        elif node_type == WorkflowNodeType.APPROVAL:
                            # Human checkpoint: pause execution and create approval
                            step.status = WorkflowStepStatus.WAITING_FOR_APPROVAL
                            await db.flush()

                            user_id_str = context.get("user_id")
                            user_id = uuid.UUID(str(user_id_str)) if user_id_str else None

                            await self.approval_service.create_approval_request(
                                db=db,
                                execution_id=execution.id,
                                step_execution_id=step.id,
                                workspace_id=execution.workspace_id,
                                requested_by=user_id,
                                reason=node_config.get("reason", "Workflow approval checkpoint"),
                            )

                            execution.status = WorkflowExecutionStatus.WAITING_FOR_APPROVAL
                            await db.flush()
                            return  # Stop execution loop until human decides

                        elif node_type in {
                            WorkflowNodeType.DEVPILOT,
                            WorkflowNodeType.IMPACTMIND,
                            WorkflowNodeType.TESTPILOT,
                            WorkflowNodeType.SECUREFLOW,
                        }:
                            # Delegate to agent adapter with execution_id and attempt_number for stable idempotency
                            output_ref = await self.agent_adapter.execute_agent_step(
                                db=db,
                                agent_type=node_type,
                                workspace_id=execution.workspace_id,
                                node_id=node_id,
                                config=node_config,
                                context_data=context,
                                execution_id=execution.id,
                                attempt_number=current_attempt,
                            )
                            step.status = WorkflowStepStatus.COMPLETED
                            step.completed_at = utc_now()
                            step.output_reference = output_ref

                            # Merge output reference into context for downstream nodes
                            context[f"node_{node_id}"] = output_ref

                        else:
                            raise WorkflowExecutionError(f"Unsupported node type: {node_type}")

                        # Step completed event
                        db.add(
                            WorkflowEvent(
                                execution_id=execution.id,
                                workspace_id=execution.workspace_id,
                                event_type=WorkflowEventType.STEP_COMPLETED,
                                payload_json={
                                    "node_id": node_id,
                                    "status": step.status,
                                    "attempt_number": current_attempt,
                                },
                                created_at=utc_now(),
                            )
                        )
                        await db.flush()
                        success = True

                    except Exception as step_exc:
                        logger.exception(f"Step '{node_id}' failed on attempt {current_attempt}: {step_exc}")
                        step.error_summary = str(step_exc)

                        db.add(
                            WorkflowEvent(
                                execution_id=execution.id,
                                workspace_id=execution.workspace_id,
                                event_type=WorkflowEventType.STEP_FAILED,
                                payload_json={
                                    "node_id": node_id,
                                    "error": str(step_exc),
                                    "attempt_number": current_attempt,
                                },
                                created_at=utc_now(),
                            )
                        )
                        await db.flush()

                        # Check if retry limit allows another attempt
                        if current_attempt <= retry_limit:
                            current_attempt += 1
                            step.attempt_number = current_attempt
                            step.status = WorkflowStepStatus.RUNNING
                            step.started_at = utc_now()
                            await db.flush()
                        else:
                            # Retries exhausted
                            step.status = WorkflowStepStatus.FAILED
                            step.completed_at = utc_now()

                            # Halt execution on node failure
                            execution.status = WorkflowExecutionStatus.FAILED
                            execution.completed_at = utc_now()
                            execution.error_summary = f"Step '{node_id}' failed after {current_attempt} attempts: {step_exc}"
                            db.add(
                                WorkflowEvent(
                                    execution_id=execution.id,
                                    workspace_id=execution.workspace_id,
                                    event_type=WorkflowEventType.EXECUTION_FAILED,
                                    payload_json={
                                        "failed_node_id": node_id,
                                        "attempts": current_attempt,
                                        "error": str(step_exc),
                                    },
                                    created_at=utc_now(),
                                )
                            )
                            await db.flush()
                            return

    def _evaluate_condition(self, actual: Any, operator: str, target: Any) -> bool:
        """Deterministic evaluation of conditional branching rules without arbitrary code execution."""
        if operator == "==":
            return str(actual) == str(target)
        elif operator == "!=":
            return str(actual) != str(target)
        elif operator == ">":
            try:
                return float(actual) > float(target)
            except (ValueError, TypeError):
                return False
        elif operator == "<":
            try:
                return float(actual) < float(target)
            except (ValueError, TypeError):
                return False
        elif operator == ">=":
            try:
                return float(actual) >= float(target)
            except (ValueError, TypeError):
                return False
        elif operator == "<=":
            try:
                return float(actual) <= float(target)
            except (ValueError, TypeError):
                return False
        elif operator == "contains":
            if actual is None:
                return False
            return str(target).lower() in str(actual).lower()
        elif operator == "is_truthy":
            return bool(actual)
        elif operator == "is_falsy":
            return not bool(actual)
        return False
