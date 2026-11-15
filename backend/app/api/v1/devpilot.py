from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    enforce_csrf_protection,
    get_current_user,
    require_workspace_membership,
)
from app.api.v1.schemas import (
    DevPilotApproveChangesRequest,
    DevPilotApprovePlanRequest,
    DevPilotCodeChangeItem,
    DevPilotDiffResponse,
    DevPilotEventItem,
    DevPilotPlanResponse,
    DevPilotPlanStepItem,
    DevPilotReviewFindingItem,
    DevPilotReviewResponse,
    DevPilotTaskCreateRequest,
    DevPilotTaskListResponse,
    DevPilotTaskResponse,
    DevPilotValidateRequest,
)
from app.db.base import WorkspaceRole
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.devpilot.orchestrator import DevPilotOrchestrator

devpilot_router = APIRouter(prefix="/repositories", tags=["devpilot"])
logger = logging.getLogger("orchestrix.api.devpilot")

_devpilot_orchestrator: DevPilotOrchestrator | None = None


def get_devpilot_orchestrator() -> DevPilotOrchestrator:
    global _devpilot_orchestrator
    if _devpilot_orchestrator is None:
        _devpilot_orchestrator = DevPilotOrchestrator()
    return _devpilot_orchestrator


def _format_task_response(task: Any) -> DevPilotTaskResponse:
    latest_plan = None
    if task.plans:
        p = task.plans[0]
        latest_plan = DevPilotPlanResponse(
            id=p.id,
            task_id=p.task_id,
            workspace_id=p.workspace_id,
            summary=p.summary,
            task_understanding=p.task_understanding,
            existing_implementation_analysis=p.existing_implementation_analysis,
            security_implications=p.security_implications,
            exposure_score=p.exposure_score,
            exposure_tier=p.exposure_tier,
            status=p.status,
            approval_comment=p.approval_comment,
            steps=[
                DevPilotPlanStepItem(
                    step_number=s.step_number,
                    title=s.title,
                    description=s.description,
                    target_files=s.target_files or [],
                    affected_symbols=s.affected_symbols or [],
                    action_type=s.action_type,
                    reason=s.reason,
                    risk_level=s.risk_level,
                    status=s.status,
                )
                for s in (p.steps or [])
            ],
            created_at=p.created_at,
            approved_at=p.approved_at,
        )

    events = [
        DevPilotEventItem(
            id=e.id,
            event_type=e.event_type,
            message=e.message,
            details=e.details,
            created_at=e.created_at,
        )
        for e in (task.events or [])
    ]

    return DevPilotTaskResponse(
        id=task.id,
        workspace_id=task.workspace_id,
        repository_id=task.repository_id,
        created_by=task.created_by,
        title=task.title,
        prompt=task.prompt,
        task_type=task.task_type,
        status=task.status,
        base_commit_sha=task.base_commit_sha,
        target_commit_sha=task.target_commit_sha,
        error_message=task.error_message,
        clarification_prompt=task.clarification_prompt,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        latest_plan=latest_plan,
        events=events,
    )


@devpilot_router.post(
    "/{repository_id}/devpilot/tasks",
    response_model=DevPilotTaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new DevPilot autonomous engineering task",
)
async def create_engineering_task(
    repository_id: uuid.UUID,
    payload: DevPilotTaskCreateRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
    orchestrator: DevPilotOrchestrator = Depends(get_devpilot_orchestrator),
) -> DevPilotTaskResponse:
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace",
        )

    task = await orchestrator.create_task(
        db=db,
        workspace_id=workspace_id,
        repository_id=repository_id,
        user_id=current_user.id,
        title=payload.title,
        prompt=payload.prompt,
        task_type=payload.task_type,
        base_commit_sha=payload.base_commit_sha,
    )

    # Immediately trigger planning
    try:
        await orchestrator.start_planning(db=db, task_id=task.id, workspace_id=workspace_id)
    except Exception as e:
        logger.warning(f"Initial planning notice: {e}")

    refreshed_task = await orchestrator.get_task(db=db, task_id=task.id, workspace_id=workspace_id)
    return _format_task_response(refreshed_task or task)


@devpilot_router.get(
    "/{repository_id}/devpilot/tasks",
    response_model=DevPilotTaskListResponse,
    status_code=status.HTTP_200_OK,
    summary="List engineering tasks for a repository",
)
async def list_engineering_tasks(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
    orchestrator: DevPilotOrchestrator = Depends(get_devpilot_orchestrator),
) -> DevPilotTaskListResponse:
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace",
        )

    tasks = await orchestrator.list_tasks(
        db=db, workspace_id=workspace_id, repository_id=repository_id, limit=limit
    )
    return DevPilotTaskListResponse(
        tasks=[_format_task_response(t) for t in tasks],
        total=len(tasks),
    )


@devpilot_router.get(
    "/{repository_id}/devpilot/tasks/{task_id}",
    response_model=DevPilotTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve task status and details",
)
async def get_task_details(
    repository_id: uuid.UUID,
    task_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
    orchestrator: DevPilotOrchestrator = Depends(get_devpilot_orchestrator),
) -> DevPilotTaskResponse:
    task = await orchestrator.get_task(db=db, task_id=task_id, workspace_id=workspace_id)
    if not task or task.repository_id != repository_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Engineering task not found"
        )
    return _format_task_response(task)


@devpilot_router.get(
    "/{repository_id}/devpilot/tasks/{task_id}/plan",
    response_model=DevPilotPlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve the engineering implementation plan",
)
async def get_task_plan(
    repository_id: uuid.UUID,
    task_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
    orchestrator: DevPilotOrchestrator = Depends(get_devpilot_orchestrator),
) -> DevPilotPlanResponse:
    task = await orchestrator.get_task(db=db, task_id=task_id, workspace_id=workspace_id)
    if not task or task.repository_id != repository_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Engineering task not found"
        )

    if not task.plans:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No plan generated yet")

    p = task.plans[0]
    return DevPilotPlanResponse(
        id=p.id,
        task_id=p.task_id,
        workspace_id=p.workspace_id,
        summary=p.summary,
        task_understanding=p.task_understanding,
        existing_implementation_analysis=p.existing_implementation_analysis,
        security_implications=p.security_implications,
        exposure_score=p.exposure_score,
        exposure_tier=p.exposure_tier,
        status=p.status,
        approval_comment=p.approval_comment,
        steps=[
            DevPilotPlanStepItem(
                step_number=s.step_number,
                title=s.title,
                description=s.description,
                target_files=s.target_files or [],
                affected_symbols=s.affected_symbols or [],
                action_type=s.action_type,
                reason=s.reason,
                risk_level=s.risk_level,
                status=s.status,
            )
            for s in (p.steps or [])
        ],
        created_at=p.created_at,
        approved_at=p.approved_at,
    )


@devpilot_router.post(
    "/{repository_id}/devpilot/tasks/{task_id}/approve-plan",
    response_model=DevPilotPlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve or reject the implementation plan",
)
async def approve_or_reject_plan(
    repository_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: DevPilotApprovePlanRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
    orchestrator: DevPilotOrchestrator = Depends(get_devpilot_orchestrator),
) -> DevPilotPlanResponse:
    try:
        plan = await orchestrator.approve_plan(
            db=db,
            task_id=task_id,
            workspace_id=workspace_id,
            user_id=current_user.id,
            decision=payload.decision,
            feedback=payload.feedback,
        )

        # If approved, automatically trigger code generation and review
        if payload.decision.upper() == "APPROVED":
            try:
                await orchestrator.generate_and_review(
                    db=db,
                    task_id=task_id,
                    workspace_id=workspace_id,
                )
            except Exception as e:
                logger.warning(f"Generation following plan approval notice: {e}")

        return DevPilotPlanResponse(
            id=plan.id,
            task_id=plan.task_id,
            workspace_id=plan.workspace_id,
            summary=plan.summary,
            task_understanding=plan.task_understanding,
            existing_implementation_analysis=plan.existing_implementation_analysis,
            security_implications=plan.security_implications,
            exposure_score=plan.exposure_score,
            exposure_tier=plan.exposure_tier,
            status=plan.status,
            approval_comment=plan.approval_comment,
            steps=[
                DevPilotPlanStepItem(
                    step_number=s.step_number,
                    title=s.title,
                    description=s.description,
                    target_files=s.target_files or [],
                    affected_symbols=s.affected_symbols or [],
                    action_type=s.action_type,
                    reason=s.reason,
                    risk_level=s.risk_level,
                    status=s.status,
                )
                for s in (plan.steps or [])
            ],
            created_at=plan.created_at,
            approved_at=plan.approved_at,
        )
    except Exception as e:
        logger.exception(f"Error approving plan: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@devpilot_router.post(
    "/{repository_id}/devpilot/tasks/{task_id}/approve-changes",
    response_model=DevPilotTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve or reject proposed code modifications",
)
async def approve_or_reject_changes(
    repository_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: DevPilotApproveChangesRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
    orchestrator: DevPilotOrchestrator = Depends(get_devpilot_orchestrator),
) -> DevPilotTaskResponse:
    try:
        task = await orchestrator.approve_modifications(
            db=db,
            task_id=task_id,
            workspace_id=workspace_id,
            user_id=current_user.id,
            decision=payload.decision,
            feedback=payload.feedback,
        )
        return _format_task_response(task)
    except Exception as e:
        logger.exception(f"Error approving modifications: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@devpilot_router.get(
    "/{repository_id}/devpilot/tasks/{task_id}/diff",
    response_model=DevPilotDiffResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve generated changes and unified diff",
)
async def get_task_diff(
    repository_id: uuid.UUID,
    task_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
    orchestrator: DevPilotOrchestrator = Depends(get_devpilot_orchestrator),
) -> DevPilotDiffResponse:
    task = await orchestrator.get_task(db=db, task_id=task_id, workspace_id=workspace_id)
    if not task or task.repository_id != repository_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Engineering task not found"
        )

    if not task.generation_results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No code generation results yet"
        )

    gr = task.generation_results[0]
    return DevPilotDiffResponse(
        task_id=task.id,
        total_files_changed=gr.total_files_changed,
        unified_diff=gr.unified_diff,
        changes=[
            DevPilotCodeChangeItem(
                id=c.id,
                file_path=c.file_path,
                change_type=c.change_type,
                old_content=c.old_content,
                new_content=c.new_content,
                diff_hunk=c.diff_hunk,
            )
            for c in (gr.changes or [])
        ],
        provider_used=gr.provider_used,
        model_used=gr.model_used,
    )


@devpilot_router.get(
    "/{repository_id}/devpilot/tasks/{task_id}/review",
    response_model=DevPilotReviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve code review findings",
)
async def get_task_review(
    repository_id: uuid.UUID,
    task_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
    orchestrator: DevPilotOrchestrator = Depends(get_devpilot_orchestrator),
) -> DevPilotReviewResponse:
    task = await orchestrator.get_task(db=db, task_id=task_id, workspace_id=workspace_id)
    if not task or task.repository_id != repository_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Engineering task not found"
        )

    findings = [
        DevPilotReviewFindingItem(
            id=f.id,
            file_path=f.file_path,
            line_start=f.line_start,
            line_end=f.line_end,
            severity=f.severity,
            category=f.category,
            description=f.description,
            evidence=f.evidence,
            suggested_correction=f.suggested_correction,
        )
        for f in (task.review_findings or [])
    ]
    return DevPilotReviewResponse(
        task_id=task.id,
        findings=findings,
        total_findings=len(findings),
    )


@devpilot_router.post(
    "/{repository_id}/devpilot/tasks/{task_id}/validate",
    response_model=DevPilotTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute multi-stage validation in isolated workspace",
)
async def validate_engineering_task(
    repository_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: DevPilotValidateRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
    orchestrator: DevPilotOrchestrator = Depends(get_devpilot_orchestrator),
) -> DevPilotTaskResponse:
    try:
        task = await orchestrator.validate_task(
            db=db,
            task_id=task_id,
            workspace_id=workspace_id,
            run_approved=payload.run_approved,
            test_command=payload.test_command,
        )
        return _format_task_response(task)
    except Exception as e:
        logger.exception(f"Error during validation: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@devpilot_router.post(
    "/{repository_id}/devpilot/tasks/{task_id}/cancel",
    response_model=DevPilotTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel task and discard isolated workspace",
)
async def cancel_engineering_task(
    repository_id: uuid.UUID,
    task_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
    orchestrator: DevPilotOrchestrator = Depends(get_devpilot_orchestrator),
) -> DevPilotTaskResponse:
    try:
        task = await orchestrator.cancel_task(db=db, task_id=task_id, workspace_id=workspace_id)
        return _format_task_response(task)
    except Exception as e:
        logger.exception(f"Error cancelling task: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
