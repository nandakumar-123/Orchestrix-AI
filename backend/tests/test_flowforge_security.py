from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import enforce_csrf_protection, get_current_user
from app.db.base import Base, WorkspaceRole, utc_now
from app.db.models.flowforge import (
    WorkflowApprovalStatus,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionStatus,
    WorkflowStatus,
    WorkflowStepExecution,
    WorkflowStepStatus,
    WorkflowVersion,
)
from app.db.models.membership import WorkspaceMembership
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db_session
from app.main import create_app
from app.services.flowforge.approval_service import (
    InvalidApprovalStateError,
    UnauthorizedApprovalError,
    WorkflowApprovalService,
)
from app.services.flowforge.definition_service import WorkflowDefinitionService
from app.services.flowforge.execution_engine import FlowForgeExecutionEngine, WorkflowExecutionError


@pytest.fixture
async def test_session() -> AsyncGenerator[AsyncSession, None]:
    """Isolated SQLite in-memory async database session with PRAGMA foreign_keys = ON."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        await session.execute(text("PRAGMA foreign_keys = ON;"))
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_cross_workspace_workflow_isolation(test_session: AsyncSession) -> None:
    """Ensure workflows in Workspace A cannot be accessed or updated by Workspace B."""
    service = WorkflowDefinitionService()

    ws_a = Workspace(name="WS-Alpha", slug="ws-alpha")
    ws_b = Workspace(name="WS-Beta", slug="ws-beta")
    user_a = User(email="alpha@example.com", full_name="Alpha User")
    user_b = User(email="beta@example.com", full_name="Beta User")
    test_session.add_all([ws_a, ws_b, user_a, user_b])
    await test_session.flush()

    wf_a, _ = await service.create_workflow(
        db=test_session,
        workspace_id=ws_a.id,
        user_id=user_a.id,
        name="Alpha Private Pipeline",
    )

    # 1. Accessing workflow from ws_b returns None
    wf_fetch_cross = await service.get_workflow(test_session, wf_a.id, ws_b.id)
    assert wf_fetch_cross is None

    # 2. Updating workflow from ws_b raises error
    with pytest.raises(ValueError, match="not found in workspace"):
        await service.update_draft(
            db=test_session,
            workflow_id=wf_a.id,
            workspace_id=ws_b.id,
            user_id=user_b.id,
            name="Hijacked Name",
        )


@pytest.mark.asyncio
async def test_cross_workspace_execution_isolation(test_session: AsyncSession) -> None:
    """Ensure executions in Workspace A cannot be seen, cancelled, or resumed from Workspace B."""
    service = WorkflowDefinitionService()
    engine = FlowForgeExecutionEngine()

    ws_a = Workspace(name="WS-A", slug="ws-a")
    ws_b = Workspace(name="WS-B", slug="ws-b")
    test_session.add_all([ws_a, ws_b])
    await test_session.flush()

    wf_a, _ = await service.create_workflow(
        db=test_session,
        workspace_id=ws_a.id,
        user_id=None,
        name="Alpha Flow",
    )

    execution_a = await engine.start_execution(
        db=test_session,
        workflow_id=wf_a.id,
        workspace_id=ws_a.id,
    )

    # Attempting to cancel from ws_b raises error
    with pytest.raises(WorkflowExecutionError, match="not found in workspace"):
        await engine.cancel_execution(
            db=test_session,
            execution_id=execution_a.id,
            workspace_id=ws_b.id,
            reason="Malicious cancel attempt",
        )


@pytest.mark.asyncio
async def test_approval_separation_of_duties_enforced(test_session: AsyncSession) -> None:
    """Ensure requester cannot approve their own approval checkpoint when separation of duties is enforced."""
    approval_svc = WorkflowApprovalService()

    ws = Workspace(name="WS-Gov", slug="ws-gov")
    requester = User(email="req@example.com", full_name="Requester User")
    approver = User(email="appr@example.com", full_name="Approver User")
    test_session.add_all([ws, requester, approver])
    await test_session.flush()

    # Create dummy execution and step
    wf = WorkflowDefinition(workspace_id=ws.id, name="Gov Workflow", status=WorkflowStatus.ACTIVE)
    test_session.add(wf)
    await test_session.flush()

    ver = WorkflowVersion(
        workflow_id=wf.id,
        workspace_id=ws.id,
        version_number=1,
        workflow_definition_json={"nodes": [], "connections": []},
    )
    test_session.add(ver)
    await test_session.flush()

    execution = WorkflowExecution(
        workflow_id=wf.id,
        workflow_version_id=ver.id,
        workspace_id=ws.id,
        status=WorkflowExecutionStatus.WAITING_FOR_APPROVAL,
    )
    test_session.add(execution)
    await test_session.flush()

    step = WorkflowStepExecution(
        execution_id=execution.id,
        workspace_id=ws.id,
        node_id="gate",
        status=WorkflowStepStatus.WAITING_FOR_APPROVAL,
    )
    test_session.add(step)
    await test_session.flush()

    approval = await approval_svc.create_approval_request(
        db=test_session,
        execution_id=execution.id,
        step_execution_id=step.id,
        workspace_id=ws.id,
        requested_by=requester.id,
        reason="Prod deploy gate",
    )

    # Requester cannot approve when separation is enabled
    with pytest.raises(UnauthorizedApprovalError, match="Separation of duties"):
        await approval_svc.approve(
            db=test_session,
            approval_id=approval.id,
            workspace_id=ws.id,
            user_id=requester.id,
            enforce_separation_of_duties=True,
        )

    # Distinct approver succeeds
    appr_res = await approval_svc.approve(
        db=test_session,
        approval_id=approval.id,
        workspace_id=ws.id,
        user_id=approver.id,
        enforce_separation_of_duties=True,
    )
    assert appr_res.status == WorkflowApprovalStatus.APPROVED

    # Duplicate decision is rejected
    with pytest.raises(InvalidApprovalStateError, match="already in APPROVED status"):
        await approval_svc.approve(
            db=test_session,
            approval_id=approval.id,
            workspace_id=ws.id,
            user_id=approver.id,
        )


@pytest.mark.asyncio
async def test_fastapi_rbac_viewer_cannot_mutate(test_session: AsyncSession) -> None:
    """Ensure VIEWER role cannot execute or update workflows via API."""
    app = create_app()

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield test_session

    ws = Workspace(name="WS-RBAC", slug="ws-rbac")
    viewer_user = User(email="viewer@example.com", full_name="Viewer User")
    test_session.add_all([ws, viewer_user])
    await test_session.flush()

    membership = WorkspaceMembership(
        workspace_id=ws.id,
        user_id=viewer_user.id,
        role=WorkspaceRole.VIEWER,
        created_at=utc_now(),
    )
    test_session.add(membership)
    await test_session.flush()

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    app.dependency_overrides[enforce_csrf_protection] = lambda: None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create attempt by VIEWER must return 403 Forbidden
        create_res = await client.post(
            f"/api/v1/workflows?workspace_id={ws.id}",
            json={"name": "Forbidden Flow"},
        )
        assert create_res.status_code == 403
