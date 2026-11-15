from __future__ import annotations

import logging
import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import utc_now
from app.db.models.devpilot import (
    CodeGenerationResult,
    DevPilotApproval,
    DevPilotEvent,
    DevPilotTask,
    EngineeringPlan,
)
from app.db.models.repository_intelligence import RepositorySnapshot
from app.services.devpilot.code_generator import CodeGenerationEngine
from app.services.devpilot.code_reviewer import CodeReviewEngine
from app.services.devpilot.context_builder import RepositoryContextBuilder
from app.services.devpilot.llm_provider import LLMProviderManager
from app.services.devpilot.planner import EngineeringPlanningEngine
from app.services.devpilot.validation_coordinator import ValidationCoordinator
from app.services.devpilot.workspace_manager import TaskWorkspaceManager

logger = logging.getLogger("orchestrix.devpilot.orchestrator")


class DevPilotOrchestrator:
    """
    Coordinates the autonomous software engineering workflow lifecycle:
    CREATED -> ANALYZING -> PLANNING -> AWAITING_APPROVAL -> GENERATING ->
    REVIEWING -> AWAITING_MODIFICATION_APPROVAL -> APPLYING -> VALIDATING -> COMPLETED
    """

    def __init__(
        self,
        llm_manager: LLMProviderManager | None = None,
        context_builder: RepositoryContextBuilder | None = None,
        planner: EngineeringPlanningEngine | None = None,
        code_generator: CodeGenerationEngine | None = None,
        code_reviewer: CodeReviewEngine | None = None,
        validation_coordinator: ValidationCoordinator | None = None,
        workspace_manager: TaskWorkspaceManager | None = None,
    ) -> None:
        self.llm_manager = llm_manager or LLMProviderManager()
        self.context_builder = context_builder or RepositoryContextBuilder()
        self.planner = planner or EngineeringPlanningEngine(llm_manager=self.llm_manager)
        self.workspace_manager = workspace_manager or TaskWorkspaceManager()
        self.code_generator = code_generator or CodeGenerationEngine(
            llm_manager=self.llm_manager, workspace_manager=self.workspace_manager
        )
        self.code_reviewer = code_reviewer or CodeReviewEngine(llm_manager=self.llm_manager)
        self.validation_coordinator = validation_coordinator or ValidationCoordinator()

    async def create_task(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        user_id: uuid.UUID | None,
        title: str,
        prompt: str,
        task_type: str = "FEATURE",
        base_commit_sha: str | None = None,
    ) -> DevPilotTask:
        """Initialize a new DevPilot engineering task."""
        # Resolve snapshot
        snap_stmt = (
            select(RepositorySnapshot)
            .where(RepositorySnapshot.repository_id == repository_id)
            .order_by(desc(RepositorySnapshot.created_at))
            .limit(1)
        )
        snap_res = await db.execute(snap_stmt)
        snap = snap_res.scalar_one_or_none()

        task = DevPilotTask(
            workspace_id=workspace_id,
            repository_id=repository_id,
            created_by=user_id,
            title=title.strip(),
            prompt=prompt.strip(),
            task_type=task_type.upper(),
            status="CREATED",
            snapshot_id=snap.id if snap else None,
            base_commit_sha=base_commit_sha or (snap.commit_sha if snap else None),
            created_at=utc_now(),
        )
        db.add(task)
        await db.flush()

        db.add(
            DevPilotEvent(
                task_id=task.id,
                workspace_id=workspace_id,
                event_type="TASK_CREATED",
                message=f"Engineering task '{title}' created.",
                details={"task_type": task_type, "repository_id": str(repository_id)},
            )
        )
        await db.commit()
        await db.refresh(task)
        return task

    async def start_planning(
        self,
        db: AsyncSession,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> EngineeringPlan:
        """
        Transition task to ANALYZING and PLANNING, assemble context, and draft plan.
        """
        task = await self.get_task(db, task_id, workspace_id)
        if not task:
            raise ValueError(f"Task {task_id} not found in workspace")

        task.status = "ANALYZING"
        db.add(
            DevPilotEvent(
                task_id=task.id,
                workspace_id=task.workspace_id,
                event_type="ANALYSIS_STARTED",
                message="DevPilot is analyzing repository structure and semantic context.",
            )
        )
        await db.commit()

        context = await self.context_builder.build_context(
            db=db,
            workspace_id=workspace_id,
            repository_id=task.repository_id,
            prompt=task.prompt,
            snapshot_id=task.snapshot_id,
        )

        plan = await self.planner.generate_plan(
            db=db,
            task=task,
            context=context,
        )
        return plan

    async def approve_plan(
        self,
        db: AsyncSession,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        decision: str,  # APPROVED | REJECTED
        feedback: str | None = None,
    ) -> EngineeringPlan:
        """Process human approval or rejection of the implementation plan."""
        task = await self.get_task(db, task_id, workspace_id)
        if not task:
            raise ValueError("Task not found")

        plan_stmt = (
            select(EngineeringPlan)
            .where(EngineeringPlan.task_id == task_id)
            .order_by(desc(EngineeringPlan.created_at))
            .limit(1)
        )
        plan_res = await db.execute(plan_stmt)
        plan = plan_res.scalar_one_or_none()
        if not plan:
            raise ValueError("No engineering plan found for task")

        approval = DevPilotApproval(
            task_id=task.id,
            workspace_id=workspace_id,
            user_id=user_id,
            approval_type="PLAN_APPROVAL",
            decision=decision.upper(),
            feedback=feedback,
            created_at=utc_now(),
        )
        db.add(approval)

        if decision.upper() == "APPROVED":
            plan.status = "APPROVED"
            plan.approved_at = utc_now()
            plan.approval_comment = feedback
            db.add(
                DevPilotEvent(
                    task_id=task.id,
                    workspace_id=workspace_id,
                    event_type="PLAN_APPROVED",
                    message="Engineering plan approved by user. Ready for code generation.",
                )
            )
        else:
            plan.status = "REJECTED"
            plan.approval_comment = feedback
            task.status = "BLOCKED"
            db.add(
                DevPilotEvent(
                    task_id=task.id,
                    workspace_id=workspace_id,
                    event_type="PLAN_REJECTED",
                    message=f"Plan rejected by user: {feedback or 'No comment'}",
                )
            )

        await db.commit()
        await db.refresh(plan)
        return plan

    async def generate_and_review(
        self,
        db: AsyncSession,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        base_files: dict[str, str] | None = None,
    ) -> CodeGenerationResult:
        """
        Execute code generation and automated review.
        Enforces that plan was explicitly approved!
        """
        task = await self.get_task(db, task_id, workspace_id)
        if not task:
            raise ValueError("Task not found")

        plan_stmt = (
            select(EngineeringPlan)
            .where(EngineeringPlan.task_id == task_id, EngineeringPlan.status == "APPROVED")
            .options(selectinload(EngineeringPlan.steps))
            .limit(1)
        )
        plan_res = await db.execute(plan_stmt)
        plan = plan_res.scalar_one_or_none()
        if not plan:
            raise PermissionError(
                "Cannot generate code: Implementation plan has not been approved by user."
            )

        # Re-fetch context
        context = await self.context_builder.build_context(
            db=db,
            workspace_id=workspace_id,
            repository_id=task.repository_id,
            prompt=task.prompt,
            snapshot_id=task.snapshot_id,
        )

        # 1. Code Generation
        gen_result = await self.code_generator.generate_code(
            db=db,
            task=task,
            plan=plan,
            context=context,
            base_files=base_files or {},
        )

        # 2. Automated Code Review
        await self.code_reviewer.review_changes(
            db=db,
            task=task,
            plan=plan,
            generation_result=gen_result,
        )

        return gen_result

    async def approve_modifications(
        self,
        db: AsyncSession,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        decision: str,  # APPROVED | REJECTED
        feedback: str | None = None,
    ) -> DevPilotTask:
        """Approve or reject proposed code modifications before validation."""
        task = await self.get_task(db, task_id, workspace_id)
        if not task:
            raise ValueError("Task not found")

        approval = DevPilotApproval(
            task_id=task.id,
            workspace_id=workspace_id,
            user_id=user_id,
            approval_type="MODIFICATION_APPROVAL",
            decision=decision.upper(),
            feedback=feedback,
            created_at=utc_now(),
        )
        db.add(approval)

        if decision.upper() == "APPROVED":
            task.status = "VALIDATING"
            db.add(
                DevPilotEvent(
                    task_id=task.id,
                    workspace_id=workspace_id,
                    event_type="MODIFICATIONS_APPROVED",
                    message="Proposed code modifications approved by user. Ready for validation.",
                )
            )
        else:
            task.status = "BLOCKED"
            db.add(
                DevPilotEvent(
                    task_id=task.id,
                    workspace_id=workspace_id,
                    event_type="MODIFICATIONS_REJECTED",
                    message=f"Proposed code modifications rejected: {feedback or 'No comment'}",
                )
            )

        await db.commit()
        await db.refresh(task)
        return task

    async def validate_task(
        self,
        db: AsyncSession,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        run_approved: bool = False,
        test_command: str | None = None,
    ) -> DevPilotTask:
        """
        Execute multi-stage validation in the isolated workspace.
        """
        task = await self.get_task(db, task_id, workspace_id)
        if not task:
            raise ValueError("Task not found")

        gen_stmt = (
            select(CodeGenerationResult)
            .where(CodeGenerationResult.task_id == task_id)
            .options(selectinload(CodeGenerationResult.changes))
            .order_by(desc(CodeGenerationResult.created_at))
            .limit(1)
        )
        gen_res = await db.execute(gen_stmt)
        generation_result = gen_res.scalar_one_or_none()
        if not generation_result:
            raise ValueError("No code generation result found for task")

        # 1. Syntax & AST Validation
        syntax_run = await self.validation_coordinator.run_syntax_validation(
            db=db,
            task=task,
            generation_result=generation_result,
        )

        # 2. ImpactMind Regression Assessment
        await self.validation_coordinator.run_impact_assessment(
            db=db,
            task=task,
            generation_result=generation_result,
        )

        # 3. Controlled Regression Tests (if approved)
        if run_approved:
            await self.validation_coordinator.execute_controlled_tests(
                db=db,
                task=task,
                run_approved=run_approved,
                test_command=test_command,
            )

        # Mark COMPLETED if syntax validation passed
        if syntax_run.status == "PASSED":
            task.status = "COMPLETED"
            task.completed_at = utc_now()
            db.add(
                DevPilotEvent(
                    task_id=task.id,
                    workspace_id=workspace_id,
                    event_type="TASK_COMPLETED",
                    message="DevPilot task completed successfully with validated changes.",
                )
            )
        else:
            task.status = "FAILED"
            task.error_message = syntax_run.stderr
            db.add(
                DevPilotEvent(
                    task_id=task.id,
                    workspace_id=workspace_id,
                    event_type="TASK_FAILED",
                    message=f"Validation failed: {syntax_run.stderr}",
                )
            )

        await db.commit()
        await db.refresh(task)
        return task

    async def cancel_task(
        self,
        db: AsyncSession,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> DevPilotTask:
        """Cancel task and clean up isolated workspace."""
        task = await self.get_task(db, task_id, workspace_id)
        if not task:
            raise ValueError("Task not found")

        task.status = "CANCELLED"
        self.workspace_manager.cleanup_workspace(task_id=task_id, repository_id=task.repository_id)

        db.add(
            DevPilotEvent(
                task_id=task.id,
                workspace_id=workspace_id,
                event_type="TASK_CANCELLED",
                message="DevPilot task was cancelled by user. Workspace discarded.",
            )
        )
        await db.commit()
        await db.refresh(task)
        return task

    async def get_task(
        self,
        db: AsyncSession,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> DevPilotTask | None:
        """Retrieve task enforcing tenant workspace isolation."""
        stmt = (
            select(DevPilotTask)
            .where(DevPilotTask.id == task_id, DevPilotTask.workspace_id == workspace_id)
            .options(
                selectinload(DevPilotTask.plans).selectinload(EngineeringPlan.steps),
                selectinload(DevPilotTask.generation_results).selectinload(
                    CodeGenerationResult.changes
                ),
                selectinload(DevPilotTask.review_findings),
                selectinload(DevPilotTask.validation_runs),
                selectinload(DevPilotTask.approvals),
                selectinload(DevPilotTask.events),
            )
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_tasks(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        limit: int = 50,
    ) -> list[DevPilotTask]:
        """List tasks for repository in workspace."""
        stmt = (
            select(DevPilotTask)
            .where(
                DevPilotTask.workspace_id == workspace_id,
                DevPilotTask.repository_id == repository_id,
            )
            .options(
                selectinload(DevPilotTask.plans),
                selectinload(DevPilotTask.events),
            )
            .order_by(desc(DevPilotTask.created_at))
            .limit(limit)
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())
