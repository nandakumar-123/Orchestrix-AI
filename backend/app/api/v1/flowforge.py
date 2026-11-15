from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    enforce_csrf_protection,
    get_current_user,
    require_workspace_membership,
)
from app.api.v1.schemas_flowforge import (
    WorkflowApprovalDecisionRequest,
    WorkflowApprovalResponse,
    WorkflowCreateRequest,
    WorkflowEventResponse,
    WorkflowExecuteRequest,
    WorkflowExecutionCancelRequest,
    WorkflowExecutionListResponse,
    WorkflowExecutionResponse,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowUpdateRequest,
    WorkflowValidateRequest,
    WorkflowVersionCreateRequest,
    WorkflowVersionResponse,
)
from app.db.base import WorkspaceRole
from app.db.models.flowforge import (
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowExecution,
)
from app.db.models.membership import WorkspaceMembership
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.flowforge.approval_service import (
    InvalidApprovalStateError,
    UnauthorizedApprovalError,
    WorkflowApprovalService,
)
from app.services.flowforge.definition_service import WorkflowDefinitionService
from app.services.flowforge.execution_engine import FlowForgeExecutionEngine, WorkflowExecutionError
from app.services.flowforge.schemas import WorkflowValidationResult
from app.services.flowforge.validator import WorkflowValidationError, WorkflowValidator

logger = logging.getLogger("orchestrix.api.flowforge")

flowforge_router = APIRouter(prefix="/workflows", tags=["flowforge"])

# Singleton instances
_definition_service = WorkflowDefinitionService()
_execution_engine = FlowForgeExecutionEngine()
_approval_service = WorkflowApprovalService()
_validator = WorkflowValidator()


def _to_workflow_response(wf: WorkflowDefinition) -> WorkflowResponse:
    latest_ver = None
    if wf.versions:
        sorted_vers = sorted(wf.versions, key=lambda v: v.version_number, reverse=True)
        latest = sorted_vers[0]
        latest_ver = WorkflowVersionResponse(
            id=latest.id,
            workflow_id=latest.workflow_id,
            workspace_id=latest.workspace_id,
            version_number=latest.version_number,
            workflow_definition_json=latest.workflow_definition_json,
            description=latest.description,
            created_by=latest.created_by,
            created_at=latest.created_at,
        )

    return WorkflowResponse(
        id=wf.id,
        workspace_id=wf.workspace_id,
        name=wf.name,
        description=wf.description,
        status=wf.status,
        created_by=wf.created_by,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
        latest_version=latest_ver,
    )


# =============================================================================
# Workflow CRUD & Lifecycle Endpoints
# =============================================================================


@flowforge_router.post(
    "",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new workflow definition",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def create_workflow(
    payload: WorkflowCreateRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowResponse:
    try:
        wf, _ = await _definition_service.create_workflow(
            db=db,
            workspace_id=workspace_id,
            user_id=current_user.id,
            name=payload.name,
            description=payload.description,
            definition_json=payload.definition,
        )
        await db.commit()
        await db.refresh(wf, ["versions"])
        return _to_workflow_response(wf)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except WorkflowValidationError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e


@flowforge_router.get(
    "",
    response_model=WorkflowListResponse,
    summary="List workflows in workspace",
)
async def list_workflows(
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Filter by status (DRAFT, ACTIVE, PAUSED, ARCHIVED)",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowListResponse:
    items, total = await _definition_service.list_workflows(
        db=db,
        workspace_id=workspace_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return WorkflowListResponse(
        items=[_to_workflow_response(w) for w in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@flowforge_router.get(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    summary="Get workflow definition details",
)
async def get_workflow(
    workflow_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowResponse:
    wf = await _definition_service.get_workflow(db, workflow_id, workspace_id)
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found in workspace",
        )
    return _to_workflow_response(wf)


@flowforge_router.patch(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    summary="Update workflow draft metadata or definition",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def update_workflow(
    workflow_id: uuid.UUID,
    payload: WorkflowUpdateRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowResponse:
    try:
        wf, _ = await _definition_service.update_draft(
            db=db,
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            user_id=current_user.id,
            name=payload.name,
            description=payload.description,
            definition_json=payload.definition,
        )
        await db.commit()
        await db.refresh(wf, ["versions"])
        return _to_workflow_response(wf)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except WorkflowValidationError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e


@flowforge_router.post(
    "/{workflow_id}/validate",
    response_model=WorkflowValidationResult,
    summary="Validate workflow graph definition",
)
async def validate_workflow(
    workflow_id: uuid.UUID,
    payload: WorkflowValidateRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowValidationResult:
    wf = await _definition_service.get_workflow(db, workflow_id, workspace_id)
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found in workspace",
        )
    return _validator.validate_graph(payload.definition)


@flowforge_router.post(
    "/{workflow_id}/activate",
    response_model=WorkflowResponse,
    summary="Activate a workflow",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def activate_workflow(
    workflow_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowResponse:
    try:
        wf = await _definition_service.activate_workflow(db, workflow_id, workspace_id)
        await db.commit()
        await db.refresh(wf, ["versions"])
        return _to_workflow_response(wf)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except WorkflowValidationError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e


@flowforge_router.post(
    "/{workflow_id}/pause",
    response_model=WorkflowResponse,
    summary="Pause an active workflow",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def pause_workflow(
    workflow_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowResponse:
    try:
        wf = await _definition_service.pause_workflow(db, workflow_id, workspace_id)
        await db.commit()
        await db.refresh(wf, ["versions"])
        return _to_workflow_response(wf)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@flowforge_router.post(
    "/{workflow_id}/versions",
    response_model=WorkflowVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Publish an immutable version of the workflow",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def create_workflow_version(
    workflow_id: uuid.UUID,
    payload: WorkflowVersionCreateRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowVersionResponse:
    try:
        ver = await _definition_service.create_version(
            db=db,
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            user_id=current_user.id,
            definition_json=payload.definition,
            description=payload.description,
        )
        await db.commit()
        await db.refresh(ver)
        return WorkflowVersionResponse.model_validate(ver)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except WorkflowValidationError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e


@flowforge_router.get(
    "/{workflow_id}/versions",
    response_model=list[WorkflowVersionResponse],
    summary="List all published versions for a workflow",
)
async def list_workflow_versions(
    workflow_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> list[WorkflowVersionResponse]:
    wf = await _definition_service.get_workflow(db, workflow_id, workspace_id)
    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found in workspace",
        )
    versions = await _definition_service.list_versions(db, workflow_id, workspace_id)
    return [WorkflowVersionResponse.model_validate(v) for v in versions]


# =============================================================================
# Execution Endpoints
# =============================================================================


@flowforge_router.post(
    "/{workflow_id}/execute",
    response_model=WorkflowExecutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start execution of a workflow",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def execute_workflow(
    workflow_id: uuid.UUID,
    payload: WorkflowExecuteRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowExecutionResponse:
    ctx = dict(payload.context_data or {})
    ctx["user_id"] = str(current_user.id)
    ctx["workspace_id"] = str(workspace_id)

    try:
        execution = await _execution_engine.start_execution(
            db=db,
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            trigger_id=payload.trigger_id,
            context_data=ctx,
            workflow_version_id=payload.workflow_version_id,
        )
        await db.commit()

        # Re-fetch with relationships
        stmt = (
            select(WorkflowExecution)
            .where(WorkflowExecution.id == execution.id)
            .options(
                selectinload(WorkflowExecution.steps),
                selectinload(WorkflowExecution.approvals),
            )
        )
        res = await db.execute(stmt)
        refreshed = res.scalar_one()
        return WorkflowExecutionResponse.model_validate(refreshed)
    except WorkflowExecutionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@flowforge_router.get(
    "/executions",
    response_model=WorkflowExecutionListResponse,
    summary="List workflow executions across workspace",
)
async def list_executions(
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    workflow_id: uuid.UUID | None = Query(default=None, description="Optional workflow filter"),
    status_filter: str | None = Query(
        default=None, alias="status", description="Filter by execution status"
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowExecutionListResponse:
    base_query = select(WorkflowExecution).where(WorkflowExecution.workspace_id == workspace_id)
    count_query = select(func.count(WorkflowExecution.id)).where(
        WorkflowExecution.workspace_id == workspace_id
    )

    if workflow_id:
        base_query = base_query.where(WorkflowExecution.workflow_id == workflow_id)
        count_query = count_query.where(WorkflowExecution.workflow_id == workflow_id)
    if status_filter:
        base_query = base_query.where(WorkflowExecution.status == status_filter.upper())
        count_query = count_query.where(WorkflowExecution.status == status_filter.upper())

    total = (await db.execute(count_query)).scalar_one()

    stmt = (
        base_query.order_by(desc(WorkflowExecution.created_at))
        .limit(limit)
        .offset(offset)
        .options(
            selectinload(WorkflowExecution.steps),
            selectinload(WorkflowExecution.approvals),
        )
    )
    items = list((await db.execute(stmt)).scalars().all())

    return WorkflowExecutionListResponse(
        items=[WorkflowExecutionResponse.model_validate(x) for x in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@flowforge_router.get(
    "/executions/{execution_id}",
    response_model=WorkflowExecutionResponse,
    summary="Get execution details",
)
async def get_execution(
    execution_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowExecutionResponse:
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found in workspace",
        )
    return WorkflowExecutionResponse.model_validate(execution)


@flowforge_router.post(
    "/executions/{execution_id}/cancel",
    response_model=WorkflowExecutionResponse,
    summary="Cancel an active workflow execution",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def cancel_execution(
    execution_id: uuid.UUID,
    payload: WorkflowExecutionCancelRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowExecutionResponse:
    try:
        execution = await _execution_engine.cancel_execution(
            db=db,
            execution_id=execution_id,
            workspace_id=workspace_id,
            reason=payload.reason,
        )
        await db.commit()

        stmt = (
            select(WorkflowExecution)
            .where(WorkflowExecution.id == execution.id)
            .options(
                selectinload(WorkflowExecution.steps),
                selectinload(WorkflowExecution.approvals),
            )
        )
        res = await db.execute(stmt)
        refreshed = res.scalar_one()
        return WorkflowExecutionResponse.model_validate(refreshed)
    except WorkflowExecutionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@flowforge_router.get(
    "/executions/{execution_id}/events",
    response_model=list[WorkflowEventResponse],
    summary="Get execution audit event history",
)
async def get_execution_events(
    execution_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> list[WorkflowEventResponse]:
    # Check execution existence in workspace
    chk = await db.execute(
        select(WorkflowExecution.id).where(
            WorkflowExecution.id == execution_id,
            WorkflowExecution.workspace_id == workspace_id,
        )
    )
    if not chk.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found in workspace",
        )

    stmt = (
        select(WorkflowEvent)
        .where(
            WorkflowEvent.execution_id == execution_id,
            WorkflowEvent.workspace_id == workspace_id,
        )
        .order_by(WorkflowEvent.created_at)
    )
    res = await db.execute(stmt)
    events = res.scalars().all()
    return [WorkflowEventResponse.model_validate(e) for e in events]


# =============================================================================
# Human Approval Endpoints
# =============================================================================


@flowforge_router.post(
    "/approvals/{approval_id}/approve",
    response_model=WorkflowApprovalResponse,
    summary="Approve a pending workflow approval request",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def approve_workflow_checkpoint(
    approval_id: uuid.UUID,
    payload: WorkflowApprovalDecisionRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.ADMIN)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowApprovalResponse:
    try:
        approval = await _approval_service.approve(
            db=db,
            approval_id=approval_id,
            workspace_id=workspace_id,
            user_id=current_user.id,
            decision_reason=payload.decision_reason,
            enforce_separation_of_duties=True,
        )
        await db.commit()

        # Resume execution
        await _execution_engine.resume_execution(
            db=db,
            execution_id=approval.execution_id,
            workspace_id=workspace_id,
        )
        await db.commit()

        await db.refresh(approval)
        return WorkflowApprovalResponse.model_validate(approval)
    except InvalidApprovalStateError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except UnauthorizedApprovalError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e


@flowforge_router.post(
    "/approvals/{approval_id}/reject",
    response_model=WorkflowApprovalResponse,
    summary="Reject a pending workflow approval request",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def reject_workflow_checkpoint(
    approval_id: uuid.UUID,
    payload: WorkflowApprovalDecisionRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.ADMIN)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkflowApprovalResponse:
    try:
        approval = await _approval_service.reject(
            db=db,
            approval_id=approval_id,
            workspace_id=workspace_id,
            user_id=current_user.id,
            decision_reason=payload.decision_reason,
            enforce_separation_of_duties=True,
        )
        await db.commit()

        # Update execution state
        await _execution_engine.resume_execution(
            db=db,
            execution_id=approval.execution_id,
            workspace_id=workspace_id,
        )
        await db.commit()

        await db.refresh(approval)
        return WorkflowApprovalResponse.model_validate(approval)
    except InvalidApprovalStateError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except UnauthorizedApprovalError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
