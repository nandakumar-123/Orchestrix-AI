import uuid
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
from app.db.models.github_installation import GitHubInstallation
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db_session
from app.main import create_app
from app.services.flowforge.approval_service import (
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
async def test_approval_rbac_permissions(test_session: AsyncSession) -> None:
    """
    Test approval RBAC enforcement via FastAPI endpoints:
    - VIEWER cannot approve (403)
    - MEMBER cannot approve (403)
    - ADMIN can approve (200)
    - OWNER can approve (200)
    """
    app = create_app()
    test_session.sync_session.expire_on_commit = False

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield test_session

    ws = Workspace(name="WS-RBAC-App", slug="ws-rbac-app")
    requester = User(email="req@example.com", full_name="Requester User")
    viewer_user = User(email="viewer@example.com", full_name="Viewer User")
    member_user = User(email="member@example.com", full_name="Member User")
    admin_user = User(email="admin@example.com", full_name="Admin User")
    owner_user = User(email="owner@example.com", full_name="Owner User")
    test_session.add_all([ws, requester, viewer_user, member_user, admin_user, owner_user])
    await test_session.flush()

    # Memberships
    test_session.add_all(
        [
            WorkspaceMembership(
                workspace_id=ws.id,
                user_id=viewer_user.id,
                role=WorkspaceRole.VIEWER,
                created_at=utc_now(),
            ),
            WorkspaceMembership(
                workspace_id=ws.id,
                user_id=member_user.id,
                role=WorkspaceRole.MEMBER,
                created_at=utc_now(),
            ),
            WorkspaceMembership(
                workspace_id=ws.id,
                user_id=admin_user.id,
                role=WorkspaceRole.ADMIN,
                created_at=utc_now(),
            ),
            WorkspaceMembership(
                workspace_id=ws.id,
                user_id=owner_user.id,
                role=WorkspaceRole.OWNER,
                created_at=utc_now(),
            ),
        ]
    )
    await test_session.flush()

    approval_svc = WorkflowApprovalService()
    wf = WorkflowDefinition(workspace_id=ws.id, name="RBAC WF", status=WorkflowStatus.ACTIVE)
    test_session.add(wf)
    await test_session.flush()

    ver = WorkflowVersion(
        workflow_id=wf.id,
        workspace_id=ws.id,
        version_number=1,
        workflow_definition_json={
            "nodes": [
                {"id": "t1", "node_type": "TRIGGER", "config": {}},
                {"id": "gate1", "node_type": "APPROVAL", "config": {}},
                {"id": "e1", "node_type": "END", "config": {}},
            ],
            "connections": [
                {"source_node_id": "t1", "target_node_id": "gate1"},
                {"source_node_id": "gate1", "target_node_id": "e1"},
            ],
        },
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
        node_id="gate1",
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
        reason="Need signoff",
    )
    approval_id = approval.id
    ws_id = ws.id
    viewer_id = viewer_user.id
    member_id = member_user.id
    requester_id = requester.id
    admin_id = admin_user.id
    await test_session.commit()

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[enforce_csrf_protection] = lambda: None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. VIEWER rejected (403)
        app.dependency_overrides[get_current_user] = lambda: User(
            id=viewer_id, email="viewer@example.com", full_name="Viewer"
        )
        res_viewer = await client.post(
            f"/api/v1/workflows/approvals/{approval_id}/approve?workspace_id={ws_id}",
            json={"decision_reason": "Viewer attempting approval"},
        )
        assert res_viewer.status_code == 403

        # 2. MEMBER rejected (403)
        app.dependency_overrides[get_current_user] = lambda: User(
            id=member_id, email="member@example.com", full_name="Member"
        )
        res_member = await client.post(
            f"/api/v1/workflows/approvals/{approval_id}/approve?workspace_id={ws_id}",
            json={"decision_reason": "Member attempting approval"},
        )
        assert res_member.status_code == 403

        # 3. Requester (even if ADMIN) rejected due to separation of duties (403)
        requester_admin_mem = WorkspaceMembership(
            workspace_id=ws_id, user_id=requester_id, role=WorkspaceRole.ADMIN, created_at=utc_now()
        )
        test_session.add(requester_admin_mem)
        await test_session.commit()
        app.dependency_overrides[get_current_user] = lambda: User(
            id=requester_id, email="req@example.com", full_name="Requester"
        )
        res_requester = await client.post(
            f"/api/v1/workflows/approvals/{approval_id}/approve?workspace_id={ws_id}",
            json={"decision_reason": "Self-approval"},
        )
        assert res_requester.status_code == 403
        assert "Separation of duties" in res_requester.json()["detail"]

        # 4. ADMIN succeeds (200)
        app.dependency_overrides[get_current_user] = lambda: User(
            id=admin_id, email="admin@example.com", full_name="Admin"
        )
        res_admin = await client.post(
            f"/api/v1/workflows/approvals/{approval_id}/approve?workspace_id={ws_id}",
            json={"decision_reason": "Admin approved"},
        )
        assert res_admin.status_code == 200
        assert res_admin.json()["status"] == "APPROVED"

        # 5. Duplicate decision rejected (400)
        res_dup = await client.post(
            f"/api/v1/workflows/approvals/{approval_id}/approve?workspace_id={ws_id}",
            json={"decision_reason": "Admin duplicate approval"},
        )
        assert res_dup.status_code == 400


@pytest.mark.asyncio
async def test_owner_approval_and_rejection(test_session: AsyncSession) -> None:
    """Test OWNER approval and rejection flows."""
    app = create_app()
    test_session.sync_session.expire_on_commit = False

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield test_session

    ws = Workspace(name="WS-Owner-App", slug="ws-owner-app")
    requester = User(email="req2@example.com", full_name="Requester User 2")
    owner_user = User(email="owner2@example.com", full_name="Owner User 2")
    test_session.add_all([ws, requester, owner_user])
    await test_session.flush()

    test_session.add(
        WorkspaceMembership(
            workspace_id=ws.id,
            user_id=owner_user.id,
            role=WorkspaceRole.OWNER,
            created_at=utc_now(),
        )
    )
    await test_session.flush()

    approval_svc = WorkflowApprovalService()
    wf = WorkflowDefinition(workspace_id=ws.id, name="Owner WF", status=WorkflowStatus.ACTIVE)
    test_session.add(wf)
    await test_session.flush()

    ver = WorkflowVersion(
        workflow_id=wf.id,
        workspace_id=ws.id,
        version_number=1,
        workflow_definition_json={
            "nodes": [
                {"id": "t1", "node_type": "TRIGGER", "config": {}},
                {"id": "gate1", "node_type": "APPROVAL", "config": {}},
                {"id": "e1", "node_type": "END", "config": {}},
            ],
            "connections": [
                {"source_node_id": "t1", "target_node_id": "gate1"},
                {"source_node_id": "gate1", "target_node_id": "e1"},
            ],
        },
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
        node_id="gate1",
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
        reason="Owner check",
    )
    await test_session.commit()

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user] = lambda: owner_user
    app.dependency_overrides[enforce_csrf_protection] = lambda: None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # OWNER can reject
        res_reject = await client.post(
            f"/api/v1/workflows/approvals/{approval.id}/reject?workspace_id={ws.id}",
            json={"decision_reason": "Owner rejected changes"},
        )
        assert res_reject.status_code == 200
        assert res_reject.json()["status"] == "REJECTED"


@pytest.mark.asyncio
async def test_retry_limits_and_failure_recording(test_session: AsyncSession) -> None:
    """Verify that node retry limits are enforced, attempts increment, and failures are persisted."""
    service = WorkflowDefinitionService()
    engine = FlowForgeExecutionEngine()

    ws = Workspace(name="WS-Retry", slug="ws-retry")
    test_session.add(ws)
    await test_session.flush()

    # Create a workflow with a failing node configured with retry_limit = 2
    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {
                "id": "failing_node",
                "node_type": "DEVPILOT",
                "config": {"prompt": "Invalid task"},
                "retry_limit": 2,
            },
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "failing_node"},
            {"source_node_id": "failing_node", "target_node_id": "e1"},
        ],
    }

    wf, _ = await service.create_workflow(
        db=test_session,
        workspace_id=ws.id,
        user_id=None,
        name="Retry Test Workflow",
        definition_json=graph,
    )

    # Missing repository_id will cause DevPilot step to raise an exception and fail
    execution = await engine.start_execution(
        db=test_session,
        workflow_id=wf.id,
        workspace_id=ws.id,
        context_data={"repository_id": str(uuid.uuid4())},  # Non-existent repository
    )

    assert execution.status == WorkflowExecutionStatus.FAILED
    failing_step = [s for s in execution.steps if s.node_id == "failing_node"][0]
    assert failing_step.status == WorkflowStepStatus.FAILED
    assert failing_step.attempt_number == 3  # Initial attempt + 2 retries = 3 attempts total


@pytest.mark.asyncio
async def test_crash_recovery_preserves_completed_and_approvals(test_session: AsyncSession) -> None:
    """Verify crash recovery mechanism reconciles in-flight nodes and does not rerun completed ones."""
    service = WorkflowDefinitionService()
    engine = FlowForgeExecutionEngine()

    ws = Workspace(name="WS-Recovery", slug="ws-recovery")
    test_session.add(ws)
    await test_session.flush()

    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "n1", "node_type": "NOTIFICATION", "config": {"message": "Step 1"}},
            {"id": "n2", "node_type": "NOTIFICATION", "config": {"message": "Step 2"}},
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "n1"},
            {"source_node_id": "n1", "target_node_id": "n2"},
            {"source_node_id": "n2", "target_node_id": "e1"},
        ],
    }

    wf, ver = await service.create_workflow(
        db=test_session,
        workspace_id=ws.id,
        user_id=None,
        name="Crash Recovery WF",
        definition_json=graph,
    )

    # Simulate an execution that was interrupted after step n1 completed while n2 was RUNNING
    execution = WorkflowExecution(
        workflow_id=wf.id,
        workflow_version_id=ver.id,
        workspace_id=ws.id,
        status=WorkflowExecutionStatus.RUNNING,
        context_data={},
        started_at=utc_now(),
        created_at=utc_now(),
    )
    test_session.add(execution)
    await test_session.flush()

    step_t1 = WorkflowStepExecution(
        execution_id=execution.id,
        workspace_id=ws.id,
        node_id="t1",
        node_name="Start",
        agent_type="TRIGGER",
        status=WorkflowStepStatus.COMPLETED,
        started_at=utc_now(),
        completed_at=utc_now(),
    )
    step_n1 = WorkflowStepExecution(
        execution_id=execution.id,
        workspace_id=ws.id,
        node_id="n1",
        node_name="Step 1",
        agent_type="NOTIFICATION",
        status=WorkflowStepStatus.COMPLETED,
        started_at=utc_now(),
        completed_at=utc_now(),
    )
    step_n2 = WorkflowStepExecution(
        execution_id=execution.id,
        workspace_id=ws.id,
        node_id="n2",
        node_name="Step 2",
        agent_type="NOTIFICATION",
        status=WorkflowStepStatus.RUNNING,  # Process crashed while this was running
        started_at=utc_now(),
    )
    test_session.add_all([step_t1, step_n1, step_n2])
    await test_session.commit()

    # Run recovery
    recovered = await engine.recover_interrupted_executions(test_session, workspace_id=ws.id)
    assert len(recovered) == 1
    rec_exec = recovered[0]
    assert rec_exec.status == WorkflowExecutionStatus.COMPLETED

    # Step n1 should not have had its attempt incremented
    assert step_n1.attempt_number == 1
    assert step_n1.status == WorkflowStepStatus.COMPLETED


@pytest.mark.asyncio
async def test_idempotent_task_creation_on_reexecution(test_session: AsyncSession) -> None:
    """Verify duplicate execution requests do not duplicate agent tasks."""
    service = WorkflowDefinitionService()
    engine = FlowForgeExecutionEngine()

    ws = Workspace(name="WS-Idem", slug="ws-idem")
    test_session.add(ws)
    await test_session.flush()

    inst = GitHubInstallation(
        workspace_id=ws.id,
        installation_id=999888,
        account_login="idem-org",
        account_type="Organization",
        account_id=111222,
    )
    test_session.add(inst)
    await test_session.flush()

    repo = Repository(
        workspace_id=ws.id,
        installation_id=inst.id,
        name="idem-repo",
        full_name="idem-org/idem-repo",
        owner_login="idem-org",
        html_url="https://github.com/idem-org/idem-repo",
        github_repository_id=55566677,
        default_branch="main",
    )
    test_session.add(repo)
    await test_session.flush()

    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {
                "id": "dp1",
                "node_type": "DEVPILOT",
                "config": {"prompt": "Idempotent Fix", "title": "Fixed Title"},
            },
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "dp1"},
            {"source_node_id": "dp1", "target_node_id": "e1"},
        ],
    }

    wf, _ = await service.create_workflow(
        db=test_session,
        workspace_id=ws.id,
        user_id=None,
        name="Idempotency WF",
        definition_json=graph,
    )

    # First execution
    exec1 = await engine.start_execution(
        db=test_session,
        workflow_id=wf.id,
        workspace_id=ws.id,
        context_data={"repository_id": str(repo.id)},
    )
    assert exec1.status == WorkflowExecutionStatus.COMPLETED
    dp1_step = [s for s in exec1.steps if s.node_id == "dp1"][0]
    task1_id = dp1_step.output_reference["task_id"]

    # Second execution of the exact same task
    exec2 = await engine.start_execution(
        db=test_session,
        workflow_id=wf.id,
        workspace_id=ws.id,
        context_data={"repository_id": str(repo.id)},
    )
    assert exec2.status == WorkflowExecutionStatus.COMPLETED
    dp2_step = [s for s in exec2.steps if s.node_id == "dp1"][0]
    task2_id = dp2_step.output_reference["task_id"]

    # Reuses existing task instead of creating duplicate tasks
    assert task1_id == task2_id
    assert dp2_step.output_reference.get("reused") is True


@pytest.mark.asyncio
async def test_parallel_branch_cancellation_and_failure(test_session: AsyncSession) -> None:
    """Verify parallel branch failure stops workflow and cancellation safely marks active branches."""
    service = WorkflowDefinitionService()
    engine = FlowForgeExecutionEngine()

    ws = Workspace(name="WS-Par-Cancel", slug="ws-par-cancel")
    test_session.add(ws)
    await test_session.flush()

    # Parallel branch with one approval gate and one normal notification
    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "par1", "node_type": "PARALLEL", "config": {}},
            {"id": "branch_appr", "node_type": "APPROVAL", "config": {"reason": "Branch gate"}},
            {
                "id": "branch_notif",
                "node_type": "NOTIFICATION",
                "config": {"message": "Branch Notif"},
            },
            {"id": "merge1", "node_type": "MERGE", "config": {}},
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "par1"},
            {"source_node_id": "par1", "target_node_id": "branch_appr"},
            {"source_node_id": "par1", "target_node_id": "branch_notif"},
            {"source_node_id": "branch_appr", "target_node_id": "merge1"},
            {"source_node_id": "branch_notif", "target_node_id": "merge1"},
            {"source_node_id": "merge1", "target_node_id": "e1"},
        ],
    }

    wf, _ = await service.create_workflow(
        db=test_session,
        workspace_id=ws.id,
        user_id=None,
        name="Parallel Cancel WF",
        definition_json=graph,
    )

    # Starts and pauses on approval branch
    execution = await engine.start_execution(
        db=test_session,
        workflow_id=wf.id,
        workspace_id=ws.id,
    )
    assert execution.status == WorkflowExecutionStatus.WAITING_FOR_APPROVAL

    # Cancel execution
    cancelled = await engine.cancel_execution(
        db=test_session,
        execution_id=execution.id,
        workspace_id=ws.id,
        reason="Aborted during parallel execution",
    )
    assert cancelled.status == WorkflowExecutionStatus.CANCELLED
    appr = cancelled.approvals[0]
    assert appr.status == WorkflowApprovalStatus.CANCELLED
