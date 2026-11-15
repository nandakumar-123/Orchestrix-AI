from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_user
from app.db.base import Base, WorkspaceRole
from app.db.models.github_installation import GitHubInstallation
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.secureflow import (
    FindingSeverity,
    FindingStatus,
    SecureFlowFinding,
    SecureFlowScan,
    SecureFlowScanStatus,
)
from app.db.models.testpilot import (
    TestPilotSuite,
    TestSuiteStatus,
)
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db_session
from app.main import app
from app.services.auth import generate_csrf_token


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
async def rbac_env(test_db_session: AsyncSession) -> dict[str, Any]:
    # Workspaces
    ws_1_id = uuid.uuid4()
    ws_2_id = uuid.uuid4()

    ws_1 = Workspace(id=ws_1_id, name="Security Workspace 1", slug="security-ws-1")
    ws_2 = Workspace(id=ws_2_id, name="Security Workspace 2", slug="security-ws-2")

    # Users
    u_owner_id = uuid.uuid4()
    u_admin_id = uuid.uuid4()
    u_member_id = uuid.uuid4()
    u_viewer_id = uuid.uuid4()
    u_other_id = uuid.uuid4()
    u_inactive_id = uuid.uuid4()

    user_owner = User(id=u_owner_id, email="owner@example.com", full_name="Owner", is_active=True)
    user_admin = User(id=u_admin_id, email="admin@example.com", full_name="Admin", is_active=True)
    user_member = User(
        id=u_member_id, email="member@example.com", full_name="Member", is_active=True
    )
    user_viewer = User(
        id=u_viewer_id, email="viewer@example.com", full_name="Viewer", is_active=True
    )
    user_other = User(
        id=u_other_id, email="other@example.com", full_name="Other WS Member", is_active=True
    )
    user_inactive = User(
        id=u_inactive_id, email="inactive@example.com", full_name="Inactive", is_active=False
    )

    # Memberships
    m_owner = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_1_id, user_id=u_owner_id, role=WorkspaceRole.OWNER
    )
    m_admin = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_1_id, user_id=u_admin_id, role=WorkspaceRole.ADMIN
    )
    m_member = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_1_id, user_id=u_member_id, role=WorkspaceRole.MEMBER
    )
    m_viewer = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_1_id, user_id=u_viewer_id, role=WorkspaceRole.VIEWER
    )
    m_other = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_2_id, user_id=u_other_id, role=WorkspaceRole.ADMIN
    )

    # Repositories
    inst_1 = GitHubInstallation(
        id=uuid.uuid4(),
        workspace_id=ws_1_id,
        installation_id=990011,
        account_login="org-1",
        account_type="Organization",
        account_id=990011,
    )
    repo_1 = Repository(
        id=uuid.uuid4(),
        workspace_id=ws_1_id,
        installation_id=inst_1.id,
        github_repository_id=101,
        name="target-repo",
        full_name="org-1/target-repo",
        owner_login="org-1",
        html_url="https://github.com/org-1/target-repo",
        default_branch="main",
        is_active=True,
    )

    inst_2 = GitHubInstallation(
        id=uuid.uuid4(),
        workspace_id=ws_2_id,
        installation_id=990022,
        account_login="org-2",
        account_type="Organization",
        account_id=990022,
    )
    repo_2 = Repository(
        id=uuid.uuid4(),
        workspace_id=ws_2_id,
        installation_id=inst_2.id,
        github_repository_id=202,
        name="foreign-repo",
        full_name="org-2/foreign-repo",
        owner_login="org-2",
        html_url="https://github.com/org-2/foreign-repo",
        default_branch="main",
        is_active=True,
    )

    test_db_session.add_all(
        [
            ws_1,
            ws_2,
            user_owner,
            user_admin,
            user_member,
            user_viewer,
            user_other,
            user_inactive,
            m_owner,
            m_admin,
            m_member,
            m_viewer,
            m_other,
            inst_1,
            inst_2,
            repo_1,
            repo_2,
        ]
    )
    await test_db_session.flush()

    return {
        "ws_1_id": ws_1_id,
        "ws_2_id": ws_2_id,
        "repo_1": repo_1,
        "repo_2": repo_2,
        "owner": user_owner,
        "admin": user_admin,
        "member": user_member,
        "viewer": user_viewer,
        "other": user_other,
        "inactive": user_inactive,
    }


def _auth_headers(csrf: str | None = None) -> dict[str, str]:
    token = csrf or generate_csrf_token()
    return {
        "X-CSRF-Token": token,
        "Cookie": f"csrf_token={token}",
    }


# =============================================================================
# 1. VIEWER Role Permission Tests
# =============================================================================


@pytest.mark.asyncio
async def test_viewer_can_view_but_not_mutate(
    api_client: AsyncClient, rbac_env: dict[str, Any], test_db_session: AsyncSession
) -> None:
    repo = rbac_env["repo_1"]
    ws_id = rbac_env["ws_1_id"]
    viewer = rbac_env["viewer"]
    app.dependency_overrides[get_current_user] = lambda: viewer
    headers = _auth_headers()

    # 1. ALLOWED: Detect framework
    detect_res = await api_client.post(
        f"/api/v1/repositories/{repo.id}/testpilot/detect?workspace_id={ws_id}",
        json={},
        headers=headers,
    )
    assert detect_res.status_code == 200

    # 2. ALLOWED: List test suites
    suites_res = await api_client.get(
        f"/api/v1/repositories/{repo.id}/testpilot/suites?workspace_id={ws_id}"
    )
    assert suites_res.status_code == 200

    # 3. ALLOWED: List scans
    scans_res = await api_client.get(
        f"/api/v1/repositories/{repo.id}/secureflow/scans?workspace_id={ws_id}"
    )
    assert scans_res.status_code == 200

    # 4. ALLOWED: List findings
    findings_res = await api_client.get(
        f"/api/v1/repositories/{repo.id}/secureflow/findings?workspace_id={ws_id}"
    )
    assert findings_res.status_code == 200

    # 5. DENIED (403): Generate proposed test suite (requires MEMBER)
    gen_res = await api_client.post(
        f"/api/v1/repositories/{repo.id}/testpilot/suites?workspace_id={ws_id}",
        json={
            "framework": "pytest",
            "target_files": ["math.py"],
            "source_context": "def add(a, b): return a + b",
            "test_type": "unit",
        },
        headers=headers,
    )
    assert gen_res.status_code == 403
    assert "at least MEMBER" in gen_res.json()["detail"]

    # 6. DENIED (403): Start security scan (requires MEMBER)
    scan_res = await api_client.post(
        f"/api/v1/repositories/{repo.id}/secureflow/scans?workspace_id={ws_id}",
        json={"scan_type": "FULL"},
        headers=headers,
    )
    assert scan_res.status_code == 403
    assert "at least MEMBER" in scan_res.json()["detail"]


@pytest.mark.asyncio
async def test_viewer_cannot_approve_or_execute(
    api_client: AsyncClient, rbac_env: dict[str, Any], test_db_session: AsyncSession
) -> None:
    repo = rbac_env["repo_1"]
    ws_id = rbac_env["ws_1_id"]
    viewer = rbac_env["viewer"]
    app.dependency_overrides[get_current_user] = lambda: viewer
    headers = _auth_headers()

    suite = TestPilotSuite(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo.id,
        framework="pytest",
        target_files=["math.py"],
        test_type="unit",
        status=TestSuiteStatus.GENERATED,
    )
    test_db_session.add(suite)
    await test_db_session.flush()

    # DENIED (403): Approve suite (requires ADMIN or OWNER)
    appr_res = await api_client.post(
        f"/api/v1/repositories/{repo.id}/testpilot/suites/{suite.id}/approve?workspace_id={ws_id}",
        headers=headers,
    )
    assert appr_res.status_code == 403
    assert "at least ADMIN" in appr_res.json()["detail"]

    # DENIED (403): Reject suite (requires ADMIN or OWNER)
    rej_res = await api_client.post(
        f"/api/v1/repositories/{repo.id}/testpilot/suites/{suite.id}/reject?workspace_id={ws_id}",
        headers=headers,
    )
    assert rej_res.status_code == 403
    assert "at least ADMIN" in rej_res.json()["detail"]

    # DENIED (403): Execute suite (requires MEMBER)
    exec_res = await api_client.post(
        f"/api/v1/repositories/{repo.id}/testpilot/suites/{suite.id}/execute?workspace_id={ws_id}",
        json={"timeout_seconds": 60},
        headers=headers,
    )
    assert exec_res.status_code == 403
    assert "at least MEMBER" in exec_res.json()["detail"]


# =============================================================================
# 2. MEMBER Role Permission Tests
# =============================================================================


@pytest.mark.asyncio
async def test_member_can_generate_and_scan_but_cannot_approve(
    api_client: AsyncClient, rbac_env: dict[str, Any], test_db_session: AsyncSession
) -> None:
    repo = rbac_env["repo_1"]
    ws_id = rbac_env["ws_1_id"]
    member = rbac_env["member"]
    app.dependency_overrides[get_current_user] = lambda: member
    headers = _auth_headers()

    # 1. ALLOWED: Generate test suite
    with patch(
        "app.services.testpilot.generator.TestGenerator.generate_suite",
        new_callable=AsyncMock,
    ) as mock_gen:
        from app.services.testpilot.schemas import GeneratedTestCase, GeneratedTestSuite

        mock_gen.return_value = GeneratedTestSuite(
            framework="pytest",
            target_files=["math.py"],
            test_type="unit",
            cases=[
                GeneratedTestCase(
                    name="test_math",
                    description="math test",
                    test_type="unit",
                    target_symbol="add",
                    code="assert True",
                )
            ],
        )
        gen_res = await api_client.post(
            f"/api/v1/repositories/{repo.id}/testpilot/suites?workspace_id={ws_id}",
            json={
                "framework": "pytest",
                "target_files": ["math.py"],
                "source_context": "def add(): pass",
                "test_type": "unit",
            },
            headers=headers,
        )
        assert gen_res.status_code == 201
        suite_id = gen_res.json()["id"]

    # 2. DENIED (403): Member CANNOT approve generated test suite (requires ADMIN or OWNER)
    appr_res = await api_client.post(
        f"/api/v1/repositories/{repo.id}/testpilot/suites/{suite_id}/approve?workspace_id={ws_id}",
        headers=headers,
    )
    assert appr_res.status_code == 403
    assert "at least ADMIN" in appr_res.json()["detail"]

    # 3. DENIED (403): Member CANNOT reject test suite (requires ADMIN or OWNER)
    rej_res = await api_client.post(
        f"/api/v1/repositories/{repo.id}/testpilot/suites/{suite_id}/reject?workspace_id={ws_id}",
        headers=headers,
    )
    assert rej_res.status_code == 403
    assert "at least ADMIN" in rej_res.json()["detail"]

    # 4. DENIED (403): Member CANNOT access security admin policy (requires ADMIN or OWNER)
    policy_res = await api_client.get(
        f"/api/v1/repositories/{repo.id}/secureflow/admin/policy?workspace_id={ws_id}",
    )
    assert policy_res.status_code == 403
    assert "at least ADMIN" in policy_res.json()["detail"]


@pytest.mark.asyncio
async def test_member_can_update_finding_and_request_remediation(
    api_client: AsyncClient, rbac_env: dict[str, Any], test_db_session: AsyncSession
) -> None:
    repo = rbac_env["repo_1"]
    ws_id = rbac_env["ws_1_id"]
    member = rbac_env["member"]
    app.dependency_overrides[get_current_user] = lambda: member
    headers = _auth_headers()

    scan = SecureFlowScan(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo.id,
        scan_type="FULL",
        status=SecureFlowScanStatus.COMPLETED,
        scanners_used=[],
        total_findings=1,
        critical_count=1,
        high_count=0,
        medium_count=0,
        low_count=0,
    )
    finding = SecureFlowFinding(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo.id,
        scan_id=scan.id,
        scanner="secret-scanner",
        category="SECRET",
        severity=FindingSeverity.CRITICAL,
        confidence=1.0,
        rule_id="SEC001",
        title="Test Secret",
        description="Leak",
        fingerprint="sha256_rbac_test",
        status=FindingStatus.OPEN,
    )
    test_db_session.add_all([scan, finding])
    await test_db_session.flush()

    # 1. ALLOWED: Update finding status
    patch_res = await api_client.patch(
        f"/api/v1/repositories/{repo.id}/secureflow/findings/{finding.id}/status?workspace_id={ws_id}",
        json={"status": "CONFIRMED", "note": "Verified by member"},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "CONFIRMED"

    # 2. ALLOWED: Request DevPilot remediation
    with patch(
        "app.services.secureflow.remediation_bridge.DevPilotRemediationBridge.create_remediation_task",
        new_callable=AsyncMock,
    ) as mock_rem:
        from app.services.secureflow.schemas import RemediationTaskResult

        mock_rem.return_value = RemediationTaskResult(
            finding_id=finding.id,
            devpilot_task_id=uuid.uuid4(),
            task_title="[Security Remediation] Test Secret",
            task_status="CREATED",
            requires_plan_approval=True,
            requires_code_approval=True,
        )
        rem_res = await api_client.post(
            f"/api/v1/repositories/{repo.id}/secureflow/findings/{finding.id}/remediate?workspace_id={ws_id}",
            headers=headers,
        )
        assert rem_res.status_code == 200
        assert rem_res.json()["finding_id"] == str(finding.id)


# =============================================================================
# 3. ADMIN & OWNER Role Tests
# =============================================================================


@pytest.mark.asyncio
async def test_admin_and_owner_can_approve_and_administer(
    api_client: AsyncClient, rbac_env: dict[str, Any], test_db_session: AsyncSession
) -> None:
    repo = rbac_env["repo_1"]
    ws_id = rbac_env["ws_1_id"]
    admin = rbac_env["admin"]
    owner = rbac_env["owner"]
    headers = _auth_headers()

    suite_1 = TestPilotSuite(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo.id,
        framework="pytest",
        target_files=["app.py"],
        test_type="unit",
        status=TestSuiteStatus.GENERATED,
    )
    suite_2 = TestPilotSuite(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo.id,
        framework="pytest",
        target_files=["app.py"],
        test_type="unit",
        status=TestSuiteStatus.GENERATED,
    )
    test_db_session.add_all([suite_1, suite_2])
    await test_db_session.flush()

    # 1. ADMIN approves suite_1
    app.dependency_overrides[get_current_user] = lambda: admin
    appr_admin_res = await api_client.post(
        f"/api/v1/repositories/{repo.id}/testpilot/suites/{suite_1.id}/approve?workspace_id={ws_id}",
        headers=headers,
    )
    assert appr_admin_res.status_code == 200
    assert appr_admin_res.json()["status"] in ("APPROVED", "approved")
    assert appr_admin_res.json()["approved_by"] == str(admin.id)

    # 2. OWNER rejects suite_2
    app.dependency_overrides[get_current_user] = lambda: owner
    rej_owner_res = await api_client.post(
        f"/api/v1/repositories/{repo.id}/testpilot/suites/{suite_2.id}/reject?workspace_id={ws_id}",
        json={"reason": "Owner rejection"},
        headers=headers,
    )
    assert rej_owner_res.status_code == 200
    assert rej_owner_res.json()["status"] in ("REJECTED", "rejected")

    # 3. ADMIN accesses security administration policy
    app.dependency_overrides[get_current_user] = lambda: admin
    policy_res = await api_client.get(
        f"/api/v1/repositories/{repo.id}/secureflow/admin/policy?workspace_id={ws_id}",
    )
    assert policy_res.status_code == 200
    assert policy_res.json()["effective_role"] == "ADMIN"


# =============================================================================
# 4. Cross-Workspace IDOR Attacks
# =============================================================================


@pytest.mark.asyncio
async def test_cross_workspace_idor_and_foreign_repository_rejection(
    api_client: AsyncClient, rbac_env: dict[str, Any], test_db_session: AsyncSession
) -> None:
    repo_1 = rbac_env["repo_1"]
    repo_2 = rbac_env["repo_2"]
    ws_1_id = rbac_env["ws_1_id"]
    ws_2_id = rbac_env["ws_2_id"]
    admin_1 = rbac_env["admin"]

    # Admin 1 is an admin in Workspace 1, NOT in Workspace 2
    app.dependency_overrides[get_current_user] = lambda: admin_1

    # 1. Attacking repo_2 in foreign workspace 2: rejected with 403
    cross_res = await api_client.get(
        f"/api/v1/repositories/{repo_2.id}/testpilot/suites?workspace_id={ws_2_id}"
    )
    assert cross_res.status_code == 403
    assert "not a member" in cross_res.json()["detail"].lower()

    # 2. Manipulating workspace_id parameter: claiming repo_2 is in ws_1
    manip_res = await api_client.get(
        f"/api/v1/repositories/{repo_2.id}/testpilot/suites?workspace_id={ws_1_id}"
    )
    assert manip_res.status_code == 404
    assert "not found in workspace" in manip_res.json()["detail"].lower()

    # 3. Seed resources in foreign workspace 2 and attempt access
    suite_foreign = TestPilotSuite(
        id=uuid.uuid4(),
        workspace_id=ws_2_id,
        repository_id=repo_2.id,
        framework="pytest",
        target_files=["math.py"],
        test_type="unit",
        status=TestSuiteStatus.GENERATED,
    )
    scan_foreign = SecureFlowScan(
        id=uuid.uuid4(),
        workspace_id=ws_2_id,
        repository_id=repo_2.id,
        scan_type="FULL",
        status=SecureFlowScanStatus.COMPLETED,
        scanners_used=[],
        total_findings=0,
        critical_count=0,
        high_count=0,
        medium_count=0,
        low_count=0,
    )
    test_db_session.add_all([suite_foreign, scan_foreign])
    await test_db_session.flush()

    # Foreign suite access through repo_1 route: 404
    foreign_suite_res = await api_client.get(
        f"/api/v1/repositories/{repo_1.id}/testpilot/suites/{suite_foreign.id}?workspace_id={ws_1_id}"
    )
    assert foreign_suite_res.status_code == 404

    # Foreign scan access through repo_1 route: 404
    foreign_scan_res = await api_client.get(
        f"/api/v1/repositories/{repo_1.id}/secureflow/scans/{scan_foreign.id}?workspace_id={ws_1_id}"
    )
    assert foreign_scan_res.status_code == 404


# =============================================================================
# 5. CSRF & Inactive User Security Boundaries
# =============================================================================


@pytest.mark.asyncio
async def test_csrf_protection_and_inactive_users(
    api_client: AsyncClient, rbac_env: dict[str, Any]
) -> None:
    repo = rbac_env["repo_1"]
    ws_id = rbac_env["ws_1_id"]
    admin = rbac_env["admin"]

    # 1. State-changing request missing CSRF token when session cookie is provided: 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: admin
    res_no_csrf = await api_client.post(
        f"/api/v1/repositories/{repo.id}/secureflow/scans?workspace_id={ws_id}",
        json={"scan_type": "FULL"},
        cookies={"orchestrix_session": "dummy_cookie"},
    )
    assert res_no_csrf.status_code == 403
    assert "CSRF" in res_no_csrf.json()["detail"]

    # 2. Inactive user session rejected by auth: 401 Unauthorized
    app.dependency_overrides[get_current_user] = lambda: (
        None
    )  # Inactive users fail validate_session_token
    res_inactive = await api_client.get(
        f"/api/v1/repositories/{repo.id}/testpilot/suites?workspace_id={ws_id}"
    )
    assert res_inactive.status_code == 401


# =============================================================================
# 6. DevMemory RBAC and Tenant Isolation Verification
# =============================================================================


@pytest.mark.asyncio
async def test_devmemory_rbac_and_tenant_isolation(
    api_client: AsyncClient, rbac_env: dict[str, Any]
) -> None:
    """Comprehensive check of DevMemory RBAC policies and workspace tenant boundary isolation."""
    ws_1_id = rbac_env["ws_1_id"]
    ws_2_id = rbac_env["ws_2_id"]
    viewer = rbac_env["viewer"]
    member = rbac_env["member"]
    admin = rbac_env["admin"]

    # 1. VIEWER cannot create memory (Requires MEMBER+) -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: viewer
    create_viewer_res = await api_client.post(
        f"/api/v1/devmemory/memories?workspace_id={ws_1_id}",
        json={
            "memory_type": "ARCHITECTURE_DECISION",
            "title": "Viewer Prohibited Memory",
            "content": "This should be forbidden for viewers",
        },
    )
    assert create_viewer_res.status_code == 403

    # 2. MEMBER can create memory -> 201 Created
    app.dependency_overrides[get_current_user] = lambda: member
    create_member_res = await api_client.post(
        f"/api/v1/devmemory/memories?workspace_id={ws_1_id}",
        json={
            "memory_type": "ARCHITECTURE_DECISION",
            "title": "Member Valid Memory",
            "content": "Architecture decision made by member",
        },
    )
    assert create_member_res.status_code == 201
    memory_id = create_member_res.json()["id"]

    # 3. VIEWER can read memory catalog & detail -> 200 OK
    app.dependency_overrides[get_current_user] = lambda: viewer
    get_viewer_res = await api_client.get(
        f"/api/v1/devmemory/memories/{memory_id}?workspace_id={ws_1_id}"
    )
    assert get_viewer_res.status_code == 200
    assert get_viewer_res.json()["id"] == memory_id

    # 4. Cross-workspace tenant isolation: Member of WS1 attempting access with WS2 workspace_id -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: member
    cross_tenant_res = await api_client.get(
        f"/api/v1/devmemory/memories/{memory_id}?workspace_id={ws_2_id}"
    )
    assert cross_tenant_res.status_code == 403

    # 5. MEMBER cannot archive memory (Requires ADMIN+) -> 403 Forbidden
    archive_member_res = await api_client.post(
        f"/api/v1/devmemory/memories/{memory_id}/archive?workspace_id={ws_1_id}&reason=Deprecate",
    )
    assert archive_member_res.status_code == 403

    # 6. ADMIN can archive memory -> 200 OK
    app.dependency_overrides[get_current_user] = lambda: admin
    archive_admin_res = await api_client.post(
        f"/api/v1/devmemory/memories/{memory_id}/archive?workspace_id={ws_1_id}&reason=Deprecate",
    )
    assert archive_admin_res.status_code == 200
    assert archive_admin_res.json()["verification_status"] == "ARCHIVED"
