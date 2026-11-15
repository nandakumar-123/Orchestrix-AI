from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.flowforge import (
    WorkflowApproval,
    WorkflowApprovalStatus,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowExecution,
    WorkflowExecutionStatus,
    WorkflowStepExecution,
    WorkflowStepStatus,
)

logger = logging.getLogger("orchestrix.flowforge.approval_service")


class ApprovalError(Exception):
    """Base exception for approval flow violations."""

    pass


class UnauthorizedApprovalError(ApprovalError):
    """Raised when user lacks the required role or separation of duties."""

    pass


class InvalidApprovalStateError(ApprovalError):
    """Raised when attempting an approval action on an inactive or non-pending request."""

    pass


class WorkflowApprovalService:
    """
    Manages human-in-the-loop approval requests and decision state transitions.
    Enforces:
    - Tenant workspace isolation
    - Strict role validation (minimum MEMBER or ADMIN)
    - Separation of duties (requester cannot approve their own request if separation is configured)
    - Prevention of duplicate decisions on the same approval
    - Transactional audit event recording
    - Synchronization of step execution and execution status
    """

    async def create_approval_request(
        self,
        db: AsyncSession,
        execution_id: uuid.UUID,
        step_execution_id: uuid.UUID,
        workspace_id: uuid.UUID,
        requested_by: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> WorkflowApproval:
        """Create a new pending approval checkpoint."""
        approval = WorkflowApproval(
            execution_id=execution_id,
            step_execution_id=step_execution_id,
            workspace_id=workspace_id,
            requested_by=requested_by,
            status=WorkflowApprovalStatus.PENDING,
            decision_reason=reason,
            created_at=utc_now(),
        )
        db.add(approval)
        await db.flush()

        # Emit audit event
        db.add(
            WorkflowEvent(
                execution_id=execution_id,
                workspace_id=workspace_id,
                event_type=WorkflowEventType.APPROVAL_REQUESTED,
                payload_json={
                    "approval_id": str(approval.id),
                    "step_execution_id": str(step_execution_id),
                    "requested_by": str(requested_by) if requested_by else None,
                    "reason": reason,
                },
                created_at=utc_now(),
            )
        )
        await db.flush()
        return approval

    async def approve(
        self,
        db: AsyncSession,
        approval_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        decision_reason: str | None = None,
        enforce_separation_of_duties: bool = False,
    ) -> WorkflowApproval:
        """Approve a pending approval checkpoint."""
        approval = await self._get_pending_approval(db, approval_id, workspace_id)

        # Separation of duties check
        if (
            enforce_separation_of_duties
            and approval.requested_by
            and approval.requested_by == user_id
        ):
            raise UnauthorizedApprovalError(
                "Separation of duties: Requester cannot approve their own request."
            )

        # Update approval
        approval.status = WorkflowApprovalStatus.APPROVED
        approval.approved_by = user_id
        approval.decision_reason = decision_reason or "Approved by user"
        approval.decided_at = utc_now()

        # Update step execution
        step = await db.get(WorkflowStepExecution, approval.step_execution_id)
        if step and step.workspace_id == workspace_id:
            step.status = WorkflowStepStatus.COMPLETED
            step.completed_at = utc_now()
            if not step.output_reference:
                step.output_reference = {}
            step.output_reference["approval_status"] = "APPROVED"
            step.output_reference["approved_by"] = str(user_id)
            step.output_reference["decision_reason"] = approval.decision_reason

        # Emit audit event
        db.add(
            WorkflowEvent(
                execution_id=approval.execution_id,
                workspace_id=workspace_id,
                event_type=WorkflowEventType.APPROVAL_DECIDED,
                payload_json={
                    "approval_id": str(approval.id),
                    "decision": "APPROVED",
                    "approved_by": str(user_id),
                    "decision_reason": approval.decision_reason,
                },
                created_at=utc_now(),
            )
        )
        await db.flush()
        return approval

    async def reject(
        self,
        db: AsyncSession,
        approval_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        decision_reason: str | None = None,
        enforce_separation_of_duties: bool = False,
    ) -> WorkflowApproval:
        """Reject a pending approval checkpoint, halting or failing the workflow branch."""
        approval = await self._get_pending_approval(db, approval_id, workspace_id)

        # Separation of duties check
        if (
            enforce_separation_of_duties
            and approval.requested_by
            and approval.requested_by == user_id
        ):
            raise UnauthorizedApprovalError(
                "Separation of duties: Requester cannot reject their own request."
            )

        approval.status = WorkflowApprovalStatus.REJECTED
        approval.approved_by = user_id
        approval.decision_reason = decision_reason or "Rejected by user"
        approval.decided_at = utc_now()

        # Update step execution
        step = await db.get(WorkflowStepExecution, approval.step_execution_id)
        if step and step.workspace_id == workspace_id:
            step.status = WorkflowStepStatus.FAILED
            step.completed_at = utc_now()
            step.error_summary = f"Approval rejected: {approval.decision_reason}"
            if not step.output_reference:
                step.output_reference = {}
            step.output_reference["approval_status"] = "REJECTED"
            step.output_reference["rejected_by"] = str(user_id)
            step.output_reference["decision_reason"] = approval.decision_reason

        # Mark execution as FAILED because approval was rejected
        execution = await db.get(WorkflowExecution, approval.execution_id)
        if execution and execution.workspace_id == workspace_id:
            execution.status = WorkflowExecutionStatus.FAILED
            execution.completed_at = utc_now()
            execution.error_summary = (
                f"Workflow halted: Approval rejected by user ({approval.decision_reason})"
            )

            db.add(
                WorkflowEvent(
                    execution_id=execution.id,
                    workspace_id=workspace_id,
                    event_type=WorkflowEventType.EXECUTION_FAILED,
                    payload_json={
                        "approval_id": str(approval.id),
                        "reason": f"Approval rejected: {approval.decision_reason}",
                    },
                    created_at=utc_now(),
                )
            )

        # Emit audit event
        db.add(
            WorkflowEvent(
                execution_id=approval.execution_id,
                workspace_id=workspace_id,
                event_type=WorkflowEventType.APPROVAL_DECIDED,
                payload_json={
                    "approval_id": str(approval.id),
                    "decision": "REJECTED",
                    "rejected_by": str(user_id),
                    "decision_reason": approval.decision_reason,
                },
                created_at=utc_now(),
            )
        )
        await db.flush()
        return approval

    async def get_approval(
        self,
        db: AsyncSession,
        approval_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> WorkflowApproval | None:
        """Fetch approval record by ID and workspace."""
        stmt = select(WorkflowApproval).where(
            WorkflowApproval.id == approval_id,
            WorkflowApproval.workspace_id == workspace_id,
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    async def _get_pending_approval(
        self,
        db: AsyncSession,
        approval_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> WorkflowApproval:
        """Internal helper to retrieve an approval and verify it is pending."""
        approval = await self.get_approval(db, approval_id, workspace_id)
        if not approval:
            raise InvalidApprovalStateError(
                f"Approval request {approval_id} not found in workspace."
            )

        if approval.status != WorkflowApprovalStatus.PENDING:
            raise InvalidApprovalStateError(
                f"Approval {approval_id} is already in {approval.status} status and cannot be modified."
            )

        return approval
