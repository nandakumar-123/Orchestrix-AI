from __future__ import annotations

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
    WorkflowExecutionStatus,
    WorkflowStatus,
    WorkflowStepStatus,
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
from app.services.flowforge.execution_engine import FlowForgeExecutionEngine
from app.services.flowforge.validator import WorkflowValidator


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


# =============================================================================
# Unit Tests: Workflow Validation
# =============================================================================


def test_validator_valid_workflow() -> None:
    validator = WorkflowValidator()
    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "dp1", "node_type": "DEVPILOT", "config": {"prompt": "Implement fix"}},
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "dp1"},
            {"source_node_id": "dp1", "target_node_id": "e1"},
        ],
    }
    res = validator.validate_graph(graph)
    assert res.is_valid is True
    assert len(res.issues) == 0
    assert res.node_count == 3
    assert res.connection_count == 2
    assert res.entry_node_id == "t1"


def test_validator_missing_trigger() -> None:
    validator = WorkflowValidator()
    graph = {
        "nodes": [
            {"id": "dp1", "node_type": "DEVPILOT", "config": {"prompt": "test"}},
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "dp1", "target_node_id": "e1"},
        ],
    }
    res = validator.validate_graph(graph)
    assert res.is_valid is False
    assert any(i.code == "MISSING_TRIGGER" for i in res.issues)


def test_validator_duplicate_node_id() -> None:
    validator = WorkflowValidator()
    graph = {
        "nodes": [
            {"id": "node_x", "node_type": "TRIGGER", "config": {}},
            {"id": "node_x", "node_type": "END", "config": {}},
        ],
        "connections": [],
    }
    res = validator.validate_graph(graph)
    assert res.is_valid is False
    assert any(i.code == "DUPLICATE_NODE_ID" for i in res.issues)


def test_validator_unsupported_node_type() -> None:
    validator = WorkflowValidator()
    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "bad1", "node_type": "CUSTOM_PYTHON_SHELL", "config": {}},
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "bad1"},
            {"source_node_id": "bad1", "target_node_id": "e1"},
        ],
    }
    res = validator.validate_graph(graph)
    assert res.is_valid is False
    assert any(i.code == "UNSUPPORTED_NODE_TYPE" for i in res.issues)


def test_validator_invalid_connections() -> None:
    validator = WorkflowValidator()
    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "nonexistent_node"},
        ],
    }
    res = validator.validate_graph(graph)
    assert res.is_valid is False
    assert any(i.code == "INVALID_TARGET_NODE" for i in res.issues)


def test_validator_cycle_detection() -> None:
    validator = WorkflowValidator()
    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "n1", "node_type": "NOTIFICATION", "config": {"message": "hi"}},
            {"id": "n2", "node_type": "NOTIFICATION", "config": {"message": "hi2"}},
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "n1"},
            {"source_node_id": "n1", "target_node_id": "n2"},
            {"source_node_id": "n2", "target_node_id": "n1"},  # Cycle!
            {"source_node_id": "n2", "target_node_id": "e1"},
        ],
    }
    res = validator.validate_graph(graph)
    assert res.is_valid is False
    assert any(i.code == "CYCLE_DETECTED" for i in res.issues)


def test_validator_unreachable_end() -> None:
    validator = WorkflowValidator()
    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "n1", "node_type": "NOTIFICATION", "config": {"message": "hi"}},
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "n1"},
            # n1 never connects to e1
        ],
    }
    res = validator.validate_graph(graph)
    assert res.is_valid is False
    assert any(i.code in {"CANNOT_REACH_END", "UNREACHABLE_NODE"} for i in res.issues)


def test_validator_node_config_requirements() -> None:
    validator = WorkflowValidator()
    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "cond1", "node_type": "CONDITION", "config": {}},  # Missing field and operator
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "cond1"},
            {"source_node_id": "cond1", "target_node_id": "e1", "condition_branch": "true"},
            {"source_node_id": "cond1", "target_node_id": "e1", "condition_branch": "false"},
        ],
    }
    res = validator.validate_graph(graph)
    assert res.is_valid is False
    assert any(i.code == "CONDITION_CONFIG_MISSING" for i in res.issues)


# =============================================================================
# Async Integration Tests: Definition & Versioning
# =============================================================================


@pytest.mark.asyncio
async def test_workflow_definition_lifecycle(test_session) -> None:
    service = WorkflowDefinitionService()

    ws = Workspace(name=f"FF-WS-{uuid.uuid4().hex[:6]}", slug=f"ff-ws-{uuid.uuid4().hex[:6]}")
    user = User(email=f"ff_{uuid.uuid4().hex[:6]}@example.com", full_name="FF User")
    test_session.add_all([ws, user])
    await test_session.flush()

    wf_name = f"Test Pipeline {uuid.uuid4().hex[:6]}"
    wf, ver = await service.create_workflow(
        db=test_session,
        workspace_id=ws.id,
        user_id=user.id,
        name=wf_name,
        description="Testing lifecycle",
    )
    assert wf.id is not None
    assert wf.status == WorkflowStatus.DRAFT
    assert ver.version_number == 1

    # Update draft
    updated_graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "notif1", "node_type": "NOTIFICATION", "config": {"message": "hello"}},
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "notif1"},
            {"source_node_id": "notif1", "target_node_id": "e1"},
        ],
    }
    wf, ver2 = await service.update_draft(
        db=test_session,
        workflow_id=wf.id,
        workspace_id=ws.id,
        user_id=user.id,
        name=f"{wf_name} Updated",
        definition_json=updated_graph,
    )
    assert ver2 is not None
    assert ver2.version_number == 2

    # Activate
    wf = await service.activate_workflow(test_session, wf.id, ws.id)
    assert wf.status == WorkflowStatus.ACTIVE

    # Pause
    wf = await service.pause_workflow(test_session, wf.id, ws.id)
    assert wf.status == WorkflowStatus.PAUSED

    # Archive
    wf = await service.archive_workflow(test_session, wf.id, ws.id)
    assert wf.status == WorkflowStatus.ARCHIVED


# =============================================================================
# Async Integration Tests: Execution, Branching & Merge
# =============================================================================


@pytest.mark.asyncio
async def test_workflow_sequential_execution(test_session) -> None:
    service = WorkflowDefinitionService()
    engine = FlowForgeExecutionEngine()

    ws = Workspace(name=f"FF-WS-{uuid.uuid4().hex[:6]}", slug=f"ff-ws-{uuid.uuid4().hex[:6]}")
    test_session.add(ws)
    await test_session.flush()

    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "n1", "node_type": "NOTIFICATION", "config": {"message": "Step 1 done"}},
            {"id": "n2", "node_type": "NOTIFICATION", "config": {"message": "Step 2 done"}},
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "n1"},
            {"source_node_id": "n1", "target_node_id": "n2"},
            {"source_node_id": "n2", "target_node_id": "e1"},
        ],
    }

    wf, _ = await service.create_workflow(
        db=test_session,
        workspace_id=ws.id,
        user_id=None,
        name=f"Sequential Run {uuid.uuid4().hex[:6]}",
        definition_json=graph,
    )

    execution = await engine.start_execution(
        db=test_session,
        workflow_id=wf.id,
        workspace_id=ws.id,
    )

    assert execution.status == WorkflowExecutionStatus.COMPLETED
    assert len(execution.steps) == 4
    for step in execution.steps:
        assert step.status == WorkflowStepStatus.COMPLETED


@pytest.mark.asyncio
async def test_workflow_conditional_branching_execution(test_session) -> None:
    service = WorkflowDefinitionService()
    engine = FlowForgeExecutionEngine()

    ws = Workspace(name=f"FF-WS-{uuid.uuid4().hex[:6]}", slug=f"ff-ws-{uuid.uuid4().hex[:6]}")
    test_session.add(ws)
    await test_session.flush()

    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {
                "id": "cond1",
                "node_type": "CONDITION",
                "config": {"field": "is_production", "operator": "==", "value": "True"},
            },
            {
                "id": "prod_notif",
                "node_type": "NOTIFICATION",
                "config": {"message": "Deploying to prod"},
            },
            {
                "id": "staging_notif",
                "node_type": "NOTIFICATION",
                "config": {"message": "Deploying to staging"},
            },
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "cond1"},
            {"source_node_id": "cond1", "target_node_id": "prod_notif", "condition_branch": "true"},
            {
                "source_node_id": "cond1",
                "target_node_id": "staging_notif",
                "condition_branch": "false",
            },
            {"source_node_id": "prod_notif", "target_node_id": "e1"},
            {"source_node_id": "staging_notif", "target_node_id": "e1"},
        ],
    }

    wf, _ = await service.create_workflow(
        db=test_session,
        workspace_id=ws.id,
        user_id=None,
        name=f"Condition Run {uuid.uuid4().hex[:6]}",
        definition_json=graph,
    )

    # Run with is_production = True
    exec_true = await engine.start_execution(
        db=test_session,
        workflow_id=wf.id,
        workspace_id=ws.id,
        context_data={"is_production": "True"},
    )
    assert exec_true.status == WorkflowExecutionStatus.COMPLETED
    executed_nodes_true = {s.node_id for s in exec_true.steps}
    assert "prod_notif" in executed_nodes_true
    assert "staging_notif" not in executed_nodes_true


@pytest.mark.asyncio
async def test_workflow_parallel_merge_execution(test_session) -> None:
    service = WorkflowDefinitionService()
    engine = FlowForgeExecutionEngine()

    ws = Workspace(name=f"FF-WS-{uuid.uuid4().hex[:6]}", slug=f"ff-ws-{uuid.uuid4().hex[:6]}")
    test_session.add(ws)
    await test_session.flush()

    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "par1", "node_type": "PARALLEL", "config": {}},
            {"id": "branch_a", "node_type": "NOTIFICATION", "config": {"message": "Branch A"}},
            {"id": "branch_b", "node_type": "NOTIFICATION", "config": {"message": "Branch B"}},
            {"id": "merge1", "node_type": "MERGE", "config": {}},
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "par1"},
            {"source_node_id": "par1", "target_node_id": "branch_a"},
            {"source_node_id": "par1", "target_node_id": "branch_b"},
            {"source_node_id": "branch_a", "target_node_id": "merge1"},
            {"source_node_id": "branch_b", "target_node_id": "merge1"},
            {"source_node_id": "merge1", "target_node_id": "e1"},
        ],
    }

    wf, _ = await service.create_workflow(
        db=test_session,
        workspace_id=ws.id,
        user_id=None,
        name=f"Parallel Merge Run {uuid.uuid4().hex[:6]}",
        definition_json=graph,
    )

    execution = await engine.start_execution(
        db=test_session,
        workflow_id=wf.id,
        workspace_id=ws.id,
    )
    assert execution.status == WorkflowExecutionStatus.COMPLETED
    assert len(execution.steps) == 6


# =============================================================================
# Async Integration Tests: Approval Pausing & Resuming
# =============================================================================


@pytest.mark.asyncio
async def test_workflow_approval_lifecycle_and_rejection(test_session) -> None:
    service = WorkflowDefinitionService()
    engine = FlowForgeExecutionEngine()
    approval_svc = WorkflowApprovalService()

    ws = Workspace(name=f"FF-WS-{uuid.uuid4().hex[:6]}", slug=f"ff-ws-{uuid.uuid4().hex[:6]}")
    user = User(email=f"approver_{uuid.uuid4().hex[:6]}@example.com", full_name="Approver User")
    test_session.add_all([ws, user])
    await test_session.flush()

    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "gate1", "node_type": "APPROVAL", "config": {"reason": "Authorize deployment"}},
            {
                "id": "post_app_notif",
                "node_type": "NOTIFICATION",
                "config": {"message": "Proceeding"},
            },
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "gate1"},
            {"source_node_id": "gate1", "target_node_id": "post_app_notif"},
            {"source_node_id": "post_app_notif", "target_node_id": "e1"},
        ],
    }

    wf, _ = await service.create_workflow(
        db=test_session,
        workspace_id=ws.id,
        user_id=user.id,
        name=f"Approval Run {uuid.uuid4().hex[:6]}",
        definition_json=graph,
    )

    # 1. Execution pauses on APPROVAL node
    execution = await engine.start_execution(
        db=test_session,
        workflow_id=wf.id,
        workspace_id=ws.id,
    )
    assert execution.status == WorkflowExecutionStatus.WAITING_FOR_APPROVAL
    assert len(execution.approvals) == 1
    approval = execution.approvals[0]
    assert approval.status == WorkflowApprovalStatus.PENDING

    # 2. Approve checkpoint resumes execution to COMPLETED
    await approval_svc.approve(
        db=test_session,
        approval_id=approval.id,
        workspace_id=ws.id,
        user_id=user.id,
        decision_reason="Production verified",
    )
    execution = await engine.resume_execution(
        db=test_session,
        execution_id=execution.id,
        workspace_id=ws.id,
    )
    assert execution.status == WorkflowExecutionStatus.COMPLETED

    # 3. Test Rejection flow on second execution
    exec2 = await engine.start_execution(
        db=test_session,
        workflow_id=wf.id,
        workspace_id=ws.id,
    )
    assert exec2.status == WorkflowExecutionStatus.WAITING_FOR_APPROVAL
    app2 = exec2.approvals[0]

    await approval_svc.reject(
        db=test_session,
        approval_id=app2.id,
        workspace_id=ws.id,
        user_id=user.id,
        decision_reason="Failed validation gate",
    )
    exec2 = await engine.resume_execution(
        db=test_session,
        execution_id=exec2.id,
        workspace_id=ws.id,
    )
    assert exec2.status == WorkflowExecutionStatus.FAILED


# =============================================================================
# Async Integration Tests: Cancellation & Tenant Isolation
# =============================================================================


@pytest.mark.asyncio
async def test_workflow_cancellation(test_session) -> None:
    service = WorkflowDefinitionService()
    engine = FlowForgeExecutionEngine()

    ws = Workspace(name=f"FF-WS-{uuid.uuid4().hex[:6]}", slug=f"ff-ws-{uuid.uuid4().hex[:6]}")
    test_session.add(ws)
    await test_session.flush()

    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "gate1", "node_type": "APPROVAL", "config": {}},
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "gate1"},
            {"source_node_id": "gate1", "target_node_id": "e1"},
        ],
    }

    wf, _ = await service.create_workflow(
        db=test_session,
        workspace_id=ws.id,
        user_id=None,
        name=f"Cancel Run {uuid.uuid4().hex[:6]}",
        definition_json=graph,
    )

    execution = await engine.start_execution(
        db=test_session,
        workflow_id=wf.id,
        workspace_id=ws.id,
    )
    assert execution.status == WorkflowExecutionStatus.WAITING_FOR_APPROVAL

    cancelled = await engine.cancel_execution(
        db=test_session,
        execution_id=execution.id,
        workspace_id=ws.id,
        reason="Operator abort",
    )
    assert cancelled.status == WorkflowExecutionStatus.CANCELLED


@pytest.mark.asyncio
async def test_agent_integration_nodes(test_session) -> None:
    service = WorkflowDefinitionService()
    engine = FlowForgeExecutionEngine()

    ws = Workspace(name=f"FF-WS-{uuid.uuid4().hex[:6]}", slug=f"ff-ws-{uuid.uuid4().hex[:6]}")
    test_session.add(ws)
    await test_session.flush()

    installation = GitHubInstallation(
        workspace_id=ws.id,
        installation_id=1234567,
        account_login="org",
        account_type="Organization",
        account_id=987654,
    )
    test_session.add(installation)
    await test_session.flush()

    repo = Repository(
        workspace_id=ws.id,
        installation_id=installation.id,
        name=f"repo-{uuid.uuid4().hex[:6]}",
        full_name=f"org/repo-{uuid.uuid4().hex[:6]}",
        owner_login="org",
        html_url="https://github.com/org/repo",
        github_repository_id=12345678,
        default_branch="main",
    )
    test_session.add_all([ws, repo])
    await test_session.flush()

    graph = {
        "nodes": [
            {"id": "t1", "node_type": "TRIGGER", "config": {}},
            {"id": "devp", "node_type": "DEVPILOT", "config": {"prompt": "Create test feature"}},
            {"id": "impact", "node_type": "IMPACTMIND", "config": {}},
            {"id": "tp", "node_type": "TESTPILOT", "config": {"action": "detect"}},
            {"id": "sec", "node_type": "SECUREFLOW", "config": {"scan_type": "FULL"}},
            {"id": "e1", "node_type": "END", "config": {}},
        ],
        "connections": [
            {"source_node_id": "t1", "target_node_id": "devp"},
            {"source_node_id": "devp", "target_node_id": "impact"},
            {"source_node_id": "impact", "target_node_id": "tp"},
            {"source_node_id": "tp", "target_node_id": "sec"},
            {"source_node_id": "sec", "target_node_id": "e1"},
        ],
    }

    wf, _ = await service.create_workflow(
        db=test_session,
        workspace_id=ws.id,
        user_id=None,
        name=f"Agent Pipeline {uuid.uuid4().hex[:6]}",
        definition_json=graph,
    )

    execution = await engine.start_execution(
        db=test_session,
        workflow_id=wf.id,
        workspace_id=ws.id,
        context_data={"repository_id": str(repo.id)},
    )
    assert execution.status == WorkflowExecutionStatus.COMPLETED
    assert len(execution.steps) == 6


# =============================================================================
# FastAPI Router Endpoints Tests
# =============================================================================


@pytest.mark.asyncio
async def test_fastapi_workflow_endpoints(test_session) -> None:
    app = create_app()

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield test_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[enforce_csrf_protection] = lambda: None

    ws = Workspace(name=f"API-WS-{uuid.uuid4().hex[:6]}", slug=f"api-ws-{uuid.uuid4().hex[:6]}")
    user = User(email=f"api_u_{uuid.uuid4().hex[:6]}@example.com", full_name="API User")
    test_session.add_all([ws, user])
    await test_session.flush()

    membership = WorkspaceMembership(
        workspace_id=ws.id,
        user_id=user.id,
        role=WorkspaceRole.ADMIN,
        created_at=utc_now(),
    )
    test_session.add(membership)
    await test_session.flush()

    headers: dict[str, str] = {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Create Workflow
        create_res = await client.post(
            f"/api/v1/workflows?workspace_id={ws.id}",
            json={"name": f"Workflow-{uuid.uuid4().hex[:6]}", "description": "API Test Workflow"},
            headers=headers,
        )
        assert create_res.status_code == 201
        wf_data = create_res.json()
        wf_id = wf_data["id"]

        # 2. Get Workflow
        get_res = await client.get(
            f"/api/v1/workflows/{wf_id}?workspace_id={ws.id}",
            headers=headers,
        )
        assert get_res.status_code == 200
        assert get_res.json()["name"] == wf_data["name"]

        # 3. List Workflows
        list_res = await client.get(
            f"/api/v1/workflows?workspace_id={ws.id}",
            headers=headers,
        )
        assert list_res.status_code == 200
        assert list_res.json()["total"] >= 1

        # 4. Validate Workflow
        val_res = await client.post(
            f"/api/v1/workflows/{wf_id}/validate?workspace_id={ws.id}",
            json={"definition": wf_data["latest_version"]["workflow_definition_json"]},
            headers=headers,
        )
        assert val_res.status_code == 200
        assert val_res.json()["is_valid"] is True

        # 5. Execute Workflow
        exec_res = await client.post(
            f"/api/v1/workflows/{wf_id}/execute?workspace_id={ws.id}",
            json={"context_data": {"test_run": True}},
            headers=headers,
        )
        assert exec_res.status_code == 201
        exec_data = exec_res.json()
        exec_id = exec_data["id"]

        # 6. Get Execution
        get_exec_res = await client.get(
            f"/api/v1/workflows/executions/{exec_id}?workspace_id={ws.id}",
            headers=headers,
        )
        assert get_exec_res.status_code == 200
        assert get_exec_res.json()["status"] == "COMPLETED"

        # 7. Get Execution Events
        events_res = await client.get(
            f"/api/v1/workflows/executions/{exec_id}/events?workspace_id={ws.id}",
            headers=headers,
        )
        assert events_res.status_code == 200
        assert len(events_res.json()) >= 2
