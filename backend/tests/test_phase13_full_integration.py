from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_user
from app.db.base import Base, WorkspaceRole
from app.db.models.devpilot import DevPilotTask
from app.db.models.github_installation import GitHubInstallation
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.secureflow import (
    FindingStatus,
    SecureFlowFinding,
)
from app.db.models.testpilot import (
    TestPilotCoverageReport,
    TestPilotExecution,
    TestPilotSuite,
    TestSuiteStatus,
)
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db_session
from app.main import app
from app.services.auth import generate_csrf_token
from app.services.graph_service import get_graph_provider
from app.services.secureflow.redaction import redact_secrets


@pytest_asyncio.fixture
async def integration_db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def integration_client(
    integration_db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield integration_db_session

    app.dependency_overrides[get_db_session] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def integration_env(integration_db_session: AsyncSession) -> dict[str, Any]:
    # Tenant Alpha
    ws_alpha_id = uuid.uuid4()
    ws_beta_id = uuid.uuid4()

    owner_a_id = uuid.uuid4()
    admin_a_id = uuid.uuid4()
    member_a_id = uuid.uuid4()
    viewer_a_id = uuid.uuid4()

    user_b_id = uuid.uuid4()

    owner_a = User(id=owner_a_id, email="owner@alpha.com", full_name="Alpha Owner", is_active=True)
    admin_a = User(id=admin_a_id, email="admin@alpha.com", full_name="Alpha Admin", is_active=True)
    member_a = User(
        id=member_a_id, email="member@alpha.com", full_name="Alpha Member", is_active=True
    )
    viewer_a = User(
        id=viewer_a_id, email="viewer@alpha.com", full_name="Alpha Viewer", is_active=True
    )

    user_b = User(id=user_b_id, email="intruder@beta.com", full_name="Beta User", is_active=True)

    ws_alpha = Workspace(id=ws_alpha_id, name="Workspace Alpha", slug="workspace-alpha")
    ws_beta = Workspace(id=ws_beta_id, name="Workspace Beta", slug="workspace-beta")

    mem_owner_a = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_alpha_id, user_id=owner_a_id, role=WorkspaceRole.OWNER
    )
    mem_admin_a = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_alpha_id, user_id=admin_a_id, role=WorkspaceRole.ADMIN
    )
    mem_member_a = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_alpha_id, user_id=member_a_id, role=WorkspaceRole.MEMBER
    )
    mem_viewer_a = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_alpha_id, user_id=viewer_a_id, role=WorkspaceRole.VIEWER
    )

    mem_b = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_beta_id, user_id=user_b_id, role=WorkspaceRole.ADMIN
    )

    inst = GitHubInstallation(
        id=uuid.uuid4(),
        workspace_id=ws_alpha_id,
        installation_id=556677,
        account_login="alpha-corp",
        account_type="Organization",
        account_id=556677,
    )

    repo_alpha_id = uuid.uuid4()
    repo_beta_id = uuid.uuid4()

    repo_alpha = Repository(
        id=repo_alpha_id,
        workspace_id=ws_alpha_id,
        installation_id=inst.id,
        github_repository_id=10101,
        name="core-service",
        full_name="alpha-corp/core-service",
        owner_login="alpha-corp",
        html_url="https://github.com/alpha-corp/core-service",
        default_branch="main",
        visibility="private",
        language="Python",
        is_active=True,
    )

    repo_beta = Repository(
        id=repo_beta_id,
        workspace_id=ws_beta_id,
        installation_id=inst.id,
        github_repository_id=20202,
        name="beta-service",
        full_name="beta-corp/beta-service",
        owner_login="beta-corp",
        html_url="https://github.com/beta-corp/beta-service",
        default_branch="main",
        visibility="private",
        language="Python",
        is_active=True,
    )

    integration_db_session.add_all(
        [
            owner_a,
            admin_a,
            member_a,
            viewer_a,
            user_b,
            ws_alpha,
            ws_beta,
            mem_owner_a,
            mem_admin_a,
            mem_member_a,
            mem_viewer_a,
            mem_b,
            inst,
            repo_alpha,
            repo_beta,
        ]
    )
    await integration_db_session.commit()

    csrf_token = generate_csrf_token()

    return {
        "ws_alpha_id": ws_alpha_id,
        "ws_beta_id": ws_beta_id,
        "repo_alpha_id": repo_alpha_id,
        "repo_beta_id": repo_beta_id,
        "owner_a": owner_a,
        "admin_a": admin_a,
        "member_a": member_a,
        "viewer_a": viewer_a,
        "user_b": user_b,
        "csrf_token": csrf_token,
    }


# =============================================================================
# 1. Environment and Infrastructure Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_neo4j_provider_graceful_degradation():
    """Verify Neo4j provider health check handles unreachable Aura instance gracefully."""
    provider = get_graph_provider()
    health = await provider.health_check()
    assert isinstance(health, bool)
    assert health is False or health is True


@pytest.mark.asyncio
async def test_secret_redaction_engine_comprehensive():
    """Verify secret redaction engine masks credentials across patterns."""
    fake_aws_key = "AKIA" + "IOSFODNN7EXAMPLE"
    fake_gh_token = "ghp_" + "1234567890abcdefghijklmnopqrstuvwxyz"
    fake_slack_token = "xoxb-" + "123456789012-1234567890123-abcdefghijklmnopqrstuvwx"

    text = f"Config key={fake_aws_key} and github={fake_gh_token} and slack={fake_slack_token}"
    redacted = redact_secrets(text)

    assert fake_aws_key not in redacted
    assert fake_gh_token not in redacted
    assert fake_slack_token not in redacted
    assert "[REDACTED_AWS_KEY]" in redacted or "[REDACTED" in redacted
    assert "[REDACTED_GITHUB_TOKEN]" in redacted or "[REDACTED" in redacted


# =============================================================================
# 2. TestPilot End-to-End Workflows
# =============================================================================


@pytest.mark.asyncio
async def test_testpilot_workflow_a_to_e(
    integration_client: AsyncClient,
    integration_env: dict[str, Any],
    integration_db_session: AsyncSession,
):
    repo_id = integration_env["repo_alpha_id"]
    ws_id = integration_env["ws_alpha_id"]
    csrf = integration_env["csrf_token"]
    cookies = {"orchestrix_csrf": csrf}
    headers = {"X-CSRF-Token": csrf}

    # -------------------------------------------------------------------------
    # Workflow A: Framework Detection & Path Traversal Guard
    # -------------------------------------------------------------------------
    app.dependency_overrides[get_current_user] = lambda: integration_env["viewer_a"]

    # Valid detection
    res = await integration_client.post(
        f"/api/v1/repositories/{repo_id}/testpilot/detect?workspace_id={ws_id}",
        json={},
        cookies=cookies,
        headers=headers,
    )
    assert res.status_code == 200
    det = res.json()
    assert "framework" in det
    assert "language" in det
    assert "is_available" in det

    # Path traversal attack in subpath must be rejected
    res_traversal = await integration_client.post(
        f"/api/v1/repositories/{repo_id}/testpilot/detect?workspace_id={ws_id}",
        json={"subpath": "../../etc/shadow"},
        cookies=cookies,
        headers=headers,
    )
    assert res_traversal.status_code == 400
    assert "Path traversal" in res_traversal.json()["detail"]

    # -------------------------------------------------------------------------
    # Workflow B: AI Test Generation (MEMBER)
    # -------------------------------------------------------------------------
    app.dependency_overrides[get_current_user] = lambda: integration_env["member_a"]

    generate_payload = {
        "framework": "pytest",
        "target_files": ["app/services/calculator.py"],
        "source_context": "def add(a, b):\n    return a + b\n\ndef divide(a, b):\n    if b == 0: raise ValueError('Zero division')\n    return a / b",
        "test_type": "unit",
    }

    res_gen = await integration_client.post(
        f"/api/v1/repositories/{repo_id}/testpilot/suites?workspace_id={ws_id}",
        json=generate_payload,
        cookies=cookies,
        headers=headers,
    )
    assert res_gen.status_code == 201
    suite_data = res_gen.json()
    suite_id = suite_data["id"]
    assert suite_data["status"].upper() == "GENERATED"
    assert len(suite_data["test_cases"]) > 0

    # Verify suite persisted in database
    db_suite = await integration_db_session.get(TestPilotSuite, uuid.UUID(suite_id))
    assert db_suite is not None
    assert db_suite.status == TestSuiteStatus.GENERATED

    # -------------------------------------------------------------------------
    # Workflow C: Premature Execution Blocked (Requires Approval Gate)
    # -------------------------------------------------------------------------
    res_exec_unapproved = await integration_client.post(
        f"/api/v1/repositories/{repo_id}/testpilot/suites/{suite_id}/execute?workspace_id={ws_id}",
        json={"timeout_seconds": 30},
        cookies=cookies,
        headers=headers,
    )
    assert res_exec_unapproved.status_code == 403
    assert "approval" in res_exec_unapproved.json()["detail"].lower()

    # -------------------------------------------------------------------------
    # Workflow C (cont.): Approval by ADMIN
    # -------------------------------------------------------------------------
    app.dependency_overrides[get_current_user] = lambda: integration_env["admin_a"]

    res_approve = await integration_client.post(
        f"/api/v1/repositories/{repo_id}/testpilot/suites/{suite_id}/approve?workspace_id={ws_id}",
        cookies=cookies,
        headers=headers,
    )
    assert res_approve.status_code == 200
    assert res_approve.json()["status"].upper() == "APPROVED"
    assert res_approve.json()["approved_by"] == str(integration_env["admin_a"].id)

    # -------------------------------------------------------------------------
    # Workflow C (cont.): Execution of Approved Suite (Controlled Execution)
    # -------------------------------------------------------------------------
    app.dependency_overrides[get_current_user] = lambda: integration_env["member_a"]

    res_exec = await integration_client.post(
        f"/api/v1/repositories/{repo_id}/testpilot/suites/{suite_id}/execute?workspace_id={ws_id}",
        json={"timeout_seconds": 60},
        cookies=cookies,
        headers=headers,
    )
    assert res_exec.status_code == 200
    exec_data = res_exec.json()
    exec_id = exec_data["id"]
    assert exec_data["status"] in ("PASSED", "FAILED", "RUNNING", "COMPLETED")

    # Verify execution record persisted in DB
    db_exec = await integration_db_session.get(TestPilotExecution, uuid.UUID(exec_id))
    assert db_exec is not None
    assert db_exec.suite_id == uuid.UUID(suite_id)

    # Retrieve individual test results
    res_results = await integration_client.get(
        f"/api/v1/repositories/{repo_id}/testpilot/executions/{exec_id}/results?workspace_id={ws_id}",
        cookies=cookies,
    )
    assert res_results.status_code == 200
    assert isinstance(res_results.json(), list)

    # -------------------------------------------------------------------------
    # Workflow D: Failure Diagnosis with Secret Redaction
    # -------------------------------------------------------------------------
    fake_token = "ghp_" + "99887766554433221100aabbccddeeff"
    mock_failing_context = f"Token validation failed for secret: {fake_token}"

    res_diag = await integration_client.post(
        f"/api/v1/repositories/{repo_id}/testpilot/executions/{exec_id}/diagnose?workspace_id={ws_id}",
        json={"source_context": mock_failing_context},
        cookies=cookies,
        headers=headers,
    )
    assert res_diag.status_code == 200
    diag_data = res_diag.json()
    assert "root_cause_analysis" in diag_data
    assert "fix_suggestions" in diag_data
    assert fake_token not in str(diag_data)

    # -------------------------------------------------------------------------
    # Workflow E: Coverage Retrieval
    # -------------------------------------------------------------------------
    # Seed a coverage report in DB
    cov_id = uuid.uuid4()
    cov_report = TestPilotCoverageReport(
        id=cov_id,
        workspace_id=ws_id,
        repository_id=repo_id,
        execution_id=uuid.UUID(exec_id),
        line_coverage_pct=92.4,
        branch_coverage_pct=None,  # Not measured
        uncovered_files=["app/legacy.py"],
        uncovered_functions=[],
        raw_report={},
    )
    integration_db_session.add(cov_report)
    await integration_db_session.commit()

    res_cov = await integration_client.get(
        f"/api/v1/repositories/{repo_id}/testpilot/coverage?workspace_id={ws_id}",
        cookies=cookies,
    )
    assert res_cov.status_code == 200
    cov_list = res_cov.json()
    assert cov_list["total"] >= 1
    latest = cov_list["items"][0]
    assert latest["line_coverage_pct"] == 92.4
    assert latest["branch_coverage_pct"] is None  # Missing branch remains null


# =============================================================================
# 3. SecureFlow End-to-End Workflows
# =============================================================================


@pytest.mark.asyncio
async def test_secureflow_workflow_a_to_d(
    integration_client: AsyncClient,
    integration_env: dict[str, Any],
    integration_db_session: AsyncSession,
):
    repo_id = integration_env["repo_alpha_id"]
    ws_id = integration_env["ws_alpha_id"]
    csrf = integration_env["csrf_token"]
    cookies = {"orchestrix_csrf": csrf}
    headers = {"X-CSRF-Token": csrf}

    # -------------------------------------------------------------------------
    # Workflow A: Scanner Availability
    # -------------------------------------------------------------------------
    app.dependency_overrides[get_current_user] = lambda: integration_env["viewer_a"]

    res_scanners = await integration_client.get(
        f"/api/v1/repositories/{repo_id}/secureflow/scanners?workspace_id={ws_id}",
        cookies=cookies,
    )
    assert res_scanners.status_code == 200
    scanners_data = res_scanners.json()
    assert "scanners" in scanners_data
    scanner_names = [s["scanner"] for s in scanners_data["scanners"]]
    assert "secret-scanner" in scanner_names

    # -------------------------------------------------------------------------
    # Workflow B: Security Scan on Synthetic Repository
    # -------------------------------------------------------------------------
    app.dependency_overrides[get_current_user] = lambda: integration_env["member_a"]

    with tempfile.TemporaryDirectory() as tmp_repo:
        # 1. Fake GitHub Token
        fake_gh_token = "ghp_" + "1234567890abcdefghijklmnopqrstuvwxyz"
        with open(os.path.join(tmp_repo, "config.py"), "w", encoding="utf-8") as f:
            f.write(f"GITHUB_TOKEN = '{fake_gh_token}'\n")

        # 2. Fake AWS Key
        fake_aws_key = "AKIA" + "IOSFODNN7EXAMPLE"
        with open(os.path.join(tmp_repo, "aws.py"), "w", encoding="utf-8") as f:
            f.write(f"AWS_KEY = '{fake_aws_key}'\n")

        # 3. Controlled SAST example
        with open(os.path.join(tmp_repo, "query.py"), "w", encoding="utf-8") as f:
            f.write("def run_query(user_input):\n    return eval(user_input)\n")

        with patch(
            "app.services.devpilot.workspace_manager.TaskWorkspaceManager.get_task_workspace_dir",
            return_value=tmp_repo,
        ):
            res_scan = await integration_client.post(
                f"/api/v1/repositories/{repo_id}/secureflow/scans?workspace_id={ws_id}",
                json={"scan_type": "FULL"},
                cookies=cookies,
                headers=headers,
            )
            assert res_scan.status_code == 201
            scan_data = res_scan.json()
            scan_id = scan_data["id"]
            assert scan_data["total_findings"] >= 1
            assert scan_data["status"] in ("COMPLETED", "PARTIALLY_COMPLETED")

    # Verify audit events were recorded in Neon
    res_events = await integration_client.get(
        f"/api/v1/repositories/{repo_id}/secureflow/scans/{scan_id}/events?workspace_id={ws_id}",
        cookies=cookies,
    )
    assert res_events.status_code == 200
    events_data = res_events.json()
    assert events_data["total"] >= 1
    event_types = [e["event_type"] for e in events_data["items"]]
    assert "SCAN_STARTED" in event_types

    # -------------------------------------------------------------------------
    # Workflow C: Finding Management & Status Triage
    # -------------------------------------------------------------------------
    res_findings = await integration_client.get(
        f"/api/v1/repositories/{repo_id}/secureflow/findings?workspace_id={ws_id}",
        cookies=cookies,
    )
    assert res_findings.status_code == 200
    findings_list = res_findings.json()
    assert findings_list["total"] >= 1
    target_finding = findings_list["items"][0]
    finding_id = target_finding["id"]

    # Verify secrets are redacted in finding title, description, and evidence
    assert fake_gh_token not in str(target_finding)
    assert fake_aws_key not in str(target_finding)

    # Update finding status to CONFIRMED
    res_triage = await integration_client.patch(
        f"/api/v1/repositories/{repo_id}/secureflow/findings/{finding_id}/status?workspace_id={ws_id}",
        json={"status": "CONFIRMED", "note": "Verified by Security Lead during audit"},
        cookies=cookies,
        headers=headers,
    )
    assert res_triage.status_code == 200
    assert res_triage.json()["status"] == "CONFIRMED"

    # Verify status persisted in database
    db_finding = await integration_db_session.get(SecureFlowFinding, uuid.UUID(finding_id))
    assert db_finding is not None
    assert db_finding.status == FindingStatus.CONFIRMED

    # -------------------------------------------------------------------------
    # Workflow D: DevPilot Autonomous Remediation Bridge
    # -------------------------------------------------------------------------
    res_rem = await integration_client.post(
        f"/api/v1/repositories/{repo_id}/secureflow/findings/{finding_id}/remediate?workspace_id={ws_id}",
        cookies=cookies,
        headers=headers,
    )
    assert res_rem.status_code == 200
    rem_data = res_rem.json()
    assert rem_data["finding_id"] == finding_id
    devpilot_task_id = rem_data["devpilot_task_id"]
    assert rem_data["requires_plan_approval"] is True
    assert rem_data["requires_code_approval"] is True

    # Verify task persisted in DevPilot tasks table
    db_task = await integration_db_session.get(DevPilotTask, uuid.UUID(devpilot_task_id))
    assert db_task is not None
    assert db_task.repository_id == repo_id
    assert db_task.workspace_id == ws_id
    assert db_task.status in ("CREATED", "PLANNING", "AWAITING_APPROVAL")

    # Fetch remediation link
    res_get_rem = await integration_client.get(
        f"/api/v1/repositories/{repo_id}/secureflow/findings/{finding_id}/remediation?workspace_id={ws_id}",
        cookies=cookies,
    )
    assert res_get_rem.status_code == 200
    assert res_get_rem.json()["devpilot_task_id"] == devpilot_task_id


# =============================================================================
# 4. RBAC and Cross-Workspace Tenant-Isolation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_rbac_permissions_and_tenant_isolation(
    integration_client: AsyncClient,
    integration_env: dict[str, Any],
    integration_db_session: AsyncSession,
):
    repo_a = integration_env["repo_alpha_id"]
    repo_b = integration_env["repo_beta_id"]
    ws_a = integration_env["ws_alpha_id"]
    ws_b = integration_env["ws_beta_id"]
    csrf = integration_env["csrf_token"]
    cookies = {"orchestrix_csrf": csrf}
    headers = {"X-CSRF-Token": csrf}

    # 1. VIEWER cannot generate test suite (Requires MEMBER)
    app.dependency_overrides[get_current_user] = lambda: integration_env["viewer_a"]
    res_viewer_post = await integration_client.post(
        f"/api/v1/repositories/{repo_a}/testpilot/suites?workspace_id={ws_a}",
        json={"framework": "pytest", "target_files": ["a.py"], "source_context": "x=1"},
        cookies=cookies,
        headers=headers,
    )
    assert res_viewer_post.status_code == 403

    # 2. MEMBER cannot approve test suite (Requires ADMIN/OWNER)
    suite = TestPilotSuite(
        id=uuid.uuid4(),
        workspace_id=ws_a,
        repository_id=repo_a,
        framework="pytest",
        target_files=["a.py"],
        test_type="unit",
        status=TestSuiteStatus.GENERATED,
    )
    integration_db_session.add(suite)
    await integration_db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: integration_env["member_a"]
    res_member_approve = await integration_client.post(
        f"/api/v1/repositories/{repo_a}/testpilot/suites/{suite.id}/approve?workspace_id={ws_a}",
        cookies=cookies,
        headers=headers,
    )
    assert res_member_approve.status_code == 403

    # 3. Cross-Tenant Repository Access is Forbidden
    # User from Workspace B attempts to access Workspace A repository
    app.dependency_overrides[get_current_user] = lambda: integration_env["user_b"]
    res_cross_repo = await integration_client.get(
        f"/api/v1/repositories/{repo_a}/testpilot/suites?workspace_id={ws_a}",
        cookies=cookies,
    )
    assert res_cross_repo.status_code in (403, 404)

    # 4. Cross-Tenant Suite Access with forged repository parameter is Blocked
    res_cross_suite = await integration_client.get(
        f"/api/v1/repositories/{repo_b}/testpilot/suites/{suite.id}?workspace_id={ws_b}",
        cookies=cookies,
    )
    assert res_cross_suite.status_code in (403, 404)

    # 5. Missing CSRF on state-changing endpoint is Blocked
    app.dependency_overrides[get_current_user] = lambda: integration_env["admin_a"]
    browser_cookies = {"orchestrix_session": "sess-token-123", "orchestrix_csrf": csrf}
    res_no_csrf = await integration_client.post(
        f"/api/v1/repositories/{repo_a}/testpilot/suites/{suite.id}/approve?workspace_id={ws_a}",
        cookies=browser_cookies,  # Cookie present but missing Origin / X-CSRF-Token header
        headers={"Origin": "http://localhost:3000"},  # Missing X-CSRF-Token
    )
    assert res_no_csrf.status_code == 403
    assert "CSRF" in res_no_csrf.json()["detail"]
