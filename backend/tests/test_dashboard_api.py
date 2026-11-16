from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_user
from app.db.base import Base, IndexingJobStatus, WorkspaceRole
from app.db.models.devmemory import (
    EngineeringMemory,
    MemoryType,
    MemoryVerificationStatus,
)
from app.db.models.devpilot import DevPilotTask
from app.db.models.flowforge import (
    WorkflowApproval,
    WorkflowApprovalStatus,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionStatus,
    WorkflowStepExecution,
    WorkflowVersion,
)
from app.db.models.github_installation import GitHubInstallation
from app.db.models.impactmind import ImpactAssessment
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.repository_intelligence import IndexingJob
from app.db.models.secureflow import (
    FindingSeverity,
    FindingStatus,
    SecureFlowFinding,
    SecureFlowScan,
    SecureFlowScanStatus,
)
from app.db.models.testpilot import (
    TestExecutionStatus,
    TestPilotExecution,
    TestPilotSuite,
    TestSuiteStatus,
)
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db_session
from app.main import app


@pytest_asyncio.fixture
async def test_db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def api_client(test_db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield test_db_session

    app.dependency_overrides[get_db_session] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def setup_dashboard_data(test_db_session: AsyncSession) -> dict[str, Any]:
    # Workspaces
    ws1 = Workspace(id=uuid.uuid4(), name="Workspace Alpha", slug="ws-alpha")
    ws2 = Workspace(id=uuid.uuid4(), name="Workspace Beta", slug="ws-beta")
    test_db_session.add_all([ws1, ws2])

    # Users
    u_owner = User(id=uuid.uuid4(), email="owner@test.com", full_name="Owner Alpha", is_active=True)
    u_viewer = User(id=uuid.uuid4(), email="viewer@test.com", full_name="Viewer Alpha", is_active=True)
    u_other = User(id=uuid.uuid4(), email="other@test.com", full_name="Other User", is_active=True)
    test_db_session.add_all([u_owner, u_viewer, u_other])

    # Memberships
    m_owner = WorkspaceMembership(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        user_id=u_owner.id,
        role=WorkspaceRole.OWNER,
    )
    m_viewer = WorkspaceMembership(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        user_id=u_viewer.id,
        role=WorkspaceRole.VIEWER,
    )
    test_db_session.add_all([m_owner, m_viewer])

    # GitHub Installation & Repositories
    inst = GitHubInstallation(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        installation_id=12345,
        account_login="test-org",
        account_id=67890,
        account_type="Organization",
        is_active=True,
    )
    test_db_session.add(inst)

    repo1 = Repository(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        installation_id=inst.id,
        github_repository_id=101,
        name="alpha-api",
        full_name="test-org/alpha-api",
        owner_login="test-org",
        default_branch="main",
        visibility="private",
        html_url="https://github.com/test-org/alpha-api",
        language="Python",
    )
    repo2 = Repository(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        installation_id=inst.id,
        github_repository_id=102,
        name="alpha-ui",
        full_name="test-org/alpha-ui",
        owner_login="test-org",
        default_branch="main",
        visibility="public",
        html_url="https://github.com/test-org/alpha-ui",
        language="TypeScript",
    )
    # Repo in ws2 (isolated)
    repo_ws2 = Repository(
        id=uuid.uuid4(),
        workspace_id=ws2.id,
        installation_id=inst.id,
        github_repository_id=201,
        name="beta-repo",
        full_name="test-org/beta-repo",
        owner_login="test-org",
        default_branch="main",
        visibility="private",
        html_url="https://github.com/test-org/beta-repo",
        language="Rust",
    )
    test_db_session.add_all([repo1, repo2, repo_ws2])

    # FlowForge Workflow & Execution in ws1
    wf = WorkflowDefinition(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        created_by=u_owner.id,
        name="Alpha CI Pipeline",
        description="Main pipeline",
        status="ACTIVE",
    )
    test_db_session.add(wf)

    wf_ver = WorkflowVersion(
        id=uuid.uuid4(),
        workflow_id=wf.id,
        workspace_id=ws1.id,
        version_number=1,
        workflow_definition_json={"nodes": [], "edges": []},
        description="v1",
    )
    test_db_session.add(wf_ver)

    wf_exec = WorkflowExecution(
        id=uuid.uuid4(),
        workflow_id=wf.id,
        workflow_version_id=wf_ver.id,
        workspace_id=ws1.id,
        status=WorkflowExecutionStatus.RUNNING,
    )
    test_db_session.add(wf_exec)

    step_exec = WorkflowStepExecution(
        id=uuid.uuid4(),
        execution_id=wf_exec.id,
        workspace_id=ws1.id,
        node_id="approval_1",
        node_name="Prod Deploy Approval",
        status="RUNNING",
    )
    test_db_session.add(step_exec)

    wf_appr = WorkflowApproval(
        id=uuid.uuid4(),
        execution_id=wf_exec.id,
        step_execution_id=step_exec.id,
        workspace_id=ws1.id,
        status=WorkflowApprovalStatus.PENDING,
    )
    test_db_session.add(wf_appr)

    # DevMemory in ws1
    mem1 = EngineeringMemory(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        repository_id=repo1.id,
        memory_type=MemoryType.ARCHITECTURE_DECISION,
        title="ADR 001: Async Architecture",
        content="Decided to use async SQLAlchemy",
        source_type="USER_INPUT",
        content_hash="hash1",
        verification_status=MemoryVerificationStatus.UNVERIFIED,
        confidence_score=0.95,
    )
    mem2 = EngineeringMemory(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        repository_id=repo2.id,
        memory_type=MemoryType.ENGINEERING_CONVENTION,
        title="Next.js Client Components",
        content="Use server components whenever possible",
        source_type="USER_INPUT",
        content_hash="hash2",
        verification_status=MemoryVerificationStatus.VERIFIED,
        confidence_score=0.99,
    )
    test_db_session.add_all([mem1, mem2])

    # SecureFlow in ws1
    scan1 = SecureFlowScan(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        repository_id=repo1.id,
        scan_type="STATIC_ANALYSIS",
        status=SecureFlowScanStatus.COMPLETED,
    )
    test_db_session.add(scan1)

    find_crit = SecureFlowFinding(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        repository_id=repo1.id,
        scan_id=scan1.id,
        scanner="semgrep",
        category="security",
        rule_id="SEC-001",
        title="SQL Injection Vulnerability",
        description="Possible SQL injection in query builder",
        fingerprint="fp001",
        severity=FindingSeverity.CRITICAL,
        status=FindingStatus.OPEN,
        file_path="app/db/query.py",
        line_start=42,
    )
    find_high = SecureFlowFinding(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        repository_id=repo1.id,
        scan_id=scan1.id,
        scanner="semgrep",
        category="security",
        rule_id="SEC-002",
        title="Insecure Cookie Flag",
        description="Missing secure cookie flag",
        fingerprint="fp002",
        severity=FindingSeverity.HIGH,
        status=FindingStatus.RESOLVED,
        file_path="app/auth/cookie.py",
        line_start=15,
    )
    test_db_session.add_all([find_crit, find_high])

    # DevPilot Task
    dp_task = DevPilotTask(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        repository_id=repo1.id,
        title="Refactor Session Cookies",
        prompt="Fix cookie security",
        task_type="SECURITY",
        status="IN_PROGRESS",
    )
    test_db_session.add(dp_task)

    # TestPilot Suite & Execution
    tp_suite = TestPilotSuite(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        repository_id=repo1.id,
        framework="pytest",
        test_type="unit",
        status=TestSuiteStatus.APPROVED,
        target_files=["tests/test_api.py"],
    )
    test_db_session.add(tp_suite)

    tp_exec = TestPilotExecution(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        repository_id=repo1.id,
        suite_id=tp_suite.id,
        command="pytest tests/",
        status=TestExecutionStatus.RUNNING,
    )
    test_db_session.add(tp_exec)

    # Impact Assessment
    impact = ImpactAssessment(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        repository_id=repo1.id,
        status="completed",
        structural_exposure_score=78.5,
        exposure_tier="HIGH",
    )
    test_db_session.add(impact)

    await test_db_session.commit()

    return {
        "ws1": ws1,
        "ws2": ws2,
        "u_owner": u_owner,
        "u_viewer": u_viewer,
        "u_other": u_other,
        "repo1": repo1,
        "repo2": repo2,
    }


@pytest.mark.asyncio
async def test_dashboard_overview_success_workspace_scoping(
    api_client: AsyncClient,
    setup_dashboard_data: dict[str, Any],
) -> None:
    data = setup_dashboard_data
    ws1 = data["ws1"]
    u_viewer = data["u_viewer"]

    app.dependency_overrides[get_current_user] = lambda: u_viewer

    response = await api_client.get(f"/api/v1/dashboard/overview?workspace_id={ws1.id}")
    assert response.status_code == 200
    res = response.json()

    assert res["workspace_id"] == str(ws1.id)
    assert res["repository_filter_id"] is None

    # Check metrics
    metrics = res["metrics"]
    assert metrics["connected_repositories"] == 2
    assert metrics["open_security_findings"] == 1  # 1 critical OPEN, 1 HIGH resolved
    assert metrics["pending_approvals"] == 1
    assert metrics["running_tasks"] >= 1
    assert metrics["total_memories"] == 2

    # Check repositories
    repos = res["repositories"]
    assert len(repos) == 2
    repo_names = [r["name"] for r in repos]
    assert "alpha-api" in repo_names
    assert "alpha-ui" in repo_names

    # Check agent status
    agents = res["agents"]
    assert len(agents) == 6
    agent_names = {a["name"]: a for a in agents}
    assert "DevPilot" in agent_names
    assert "FlowForge" in agent_names
    assert "DevMemory" in agent_names
    assert "SecureFlow" in agent_names
    assert "TestPilot" in agent_names
    assert "ImpactMind" in agent_names

    # DevPilot has 1 IN_PROGRESS task
    assert agent_names["DevPilot"]["status"] == "RUNNING"
    assert agent_names["DevPilot"]["active_executions"] == 1

    # FlowForge has 1 RUNNING execution
    assert agent_names["FlowForge"]["status"] == "RUNNING"
    assert agent_names["FlowForge"]["active_executions"] == 1

    # Check tasks
    tasks = res["tasks"]
    assert len(tasks) >= 1
    assert any("Refactor Session Cookies" in t["title"] for t in tasks)

    # Check activities
    activities = res["activities"]
    assert isinstance(activities, list)
    assert len(activities) > 0


@pytest.mark.asyncio
async def test_dashboard_overview_repository_filter(
    api_client: AsyncClient,
    setup_dashboard_data: dict[str, Any],
) -> None:
    data = setup_dashboard_data
    ws1 = data["ws1"]
    repo1 = data["repo1"]
    u_owner = data["u_owner"]

    app.dependency_overrides[get_current_user] = lambda: u_owner

    response = await api_client.get(
        f"/api/v1/dashboard/overview?workspace_id={ws1.id}&repository_id={repo1.id}"
    )
    assert response.status_code == 200
    res = response.json()

    assert res["repository_filter_id"] == str(repo1.id)
    # Repo 1 has 1 memory
    assert res["memory"]["total_count"] == 1
    # Repo 1 has 1 security finding
    assert res["security"]["open_findings"] == 1


@pytest.mark.asyncio
async def test_dashboard_overview_empty_workspace(
    api_client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    ws_empty = Workspace(id=uuid.uuid4(), name="Empty WS", slug="empty-ws")
    user = User(id=uuid.uuid4(), email="user@empty.com", full_name="User Empty", is_active=True)
    membership = WorkspaceMembership(
        id=uuid.uuid4(),
        workspace_id=ws_empty.id,
        user_id=user.id,
        role=WorkspaceRole.VIEWER,
    )
    test_db_session.add_all([ws_empty, user, membership])
    await test_db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: user

    response = await api_client.get(f"/api/v1/dashboard/overview?workspace_id={ws_empty.id}")
    assert response.status_code == 200
    res = response.json()

    assert res["metrics"]["connected_repositories"] == 0
    assert res["metrics"]["running_tasks"] == 0
    assert res["metrics"]["open_security_findings"] == 0
    assert res["repositories"] == []
    assert res["tasks"] == []
    assert res["activities"] == []


@pytest.mark.asyncio
async def test_dashboard_overview_unauthorized_user_forbidden(
    api_client: AsyncClient,
    setup_dashboard_data: dict[str, Any],
) -> None:
    data = setup_dashboard_data
    ws1 = data["ws1"]
    u_other = data["u_other"]

    # u_other is not a member of ws1
    app.dependency_overrides[get_current_user] = lambda: u_other

    response = await api_client.get(f"/api/v1/dashboard/overview?workspace_id={ws1.id}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_dashboard_overview_unauthenticated(
    api_client: AsyncClient,
    setup_dashboard_data: dict[str, Any],
) -> None:
    data = setup_dashboard_data
    ws1 = data["ws1"]

    # Without dependency override, should return 401
    response = await api_client.get(f"/api/v1/dashboard/overview?workspace_id={ws1.id}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_overview_excludes_deactivated_repositories(
    api_client: AsyncClient,
    test_db_session: AsyncSession,
    setup_dashboard_data: dict[str, Any],
) -> None:
    data = setup_dashboard_data
    ws1 = data["ws1"]
    repo1 = data["repo1"]
    repo2 = data["repo2"]
    u_owner = data["u_owner"]

    app.dependency_overrides[get_current_user] = lambda: u_owner

    # Verify initial state: 2 active repos
    resp_initial = await api_client.get(f"/api/v1/dashboard/overview?workspace_id={ws1.id}")
    assert resp_initial.status_code == 200
    assert resp_initial.json()["metrics"]["connected_repositories"] == 2
    assert len(resp_initial.json()["repositories"]) == 2

    # Add completed indexing job for repo2
    idx_job_repo2 = IndexingJob(
        id=uuid.uuid4(),
        repository_id=repo2.id,
        workspace_id=ws1.id,
        commit_sha="abcdef1234567890",
        branch="main",
        status=IndexingJobStatus.COMPLETED,
    )
    test_db_session.add(idx_job_repo2)

    # Deactivate repo2 (soft delete via disconnect)
    repo2.is_active = False
    await test_db_session.commit()

    # Query overview again
    resp_after = await api_client.get(f"/api/v1/dashboard/overview?workspace_id={ws1.id}")
    assert resp_after.status_code == 200
    res_after = resp_after.json()

    # 1. Connected repositories count must be 1 (repo2 excluded)
    assert res_after["metrics"]["connected_repositories"] == 1

    # 2. Indexed repositories count must NOT include repo2's completed indexing job
    assert res_after["metrics"]["indexed_repositories"] == 0

    # 3. Repositories list must only contain active repo1
    repo_list = res_after["repositories"]
    assert len(repo_list) == 1
    assert repo_list[0]["id"] == str(repo1.id)
    assert repo_list[0]["name"] == "alpha-api"

    # 4. Activities must not include repo2's indexing activities
    idx_activities = [
        a for a in res_after["activities"]
        if a["event_type"] == "repo_index" and a.get("repository_id") == str(repo2.id)
    ]
    assert len(idx_activities) == 0

    # 5. Reactivate repo2 (reconnect)
    repo2.is_active = True
    await test_db_session.commit()

    resp_reconnect = await api_client.get(f"/api/v1/dashboard/overview?workspace_id={ws1.id}")
    assert resp_reconnect.status_code == 200
    res_reconnect = resp_reconnect.json()
    assert res_reconnect["metrics"]["connected_repositories"] == 2
    assert res_reconnect["metrics"]["indexed_repositories"] == 1
    assert len(res_reconnect["repositories"]) == 2

