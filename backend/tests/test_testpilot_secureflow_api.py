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
    SecureFlowScanEvent,
    SecureFlowScanStatus,
)
from app.db.models.testpilot import (
    TestPilotCoverageReport,
    TestPilotExecution,
    TestPilotResult,
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
async def test_env(test_db_session: AsyncSession) -> dict[str, Any]:
    # Workspace A
    ws_a_id = uuid.uuid4()
    ws_b_id = uuid.uuid4()
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    repo_a_id = uuid.uuid4()
    repo_b_id = uuid.uuid4()

    user_a = User(id=user_a_id, email="alice@example.com", full_name="Alice", is_active=True)
    user_b = User(id=user_b_id, email="bob@example.com", full_name="Bob", is_active=True)

    ws_a = Workspace(id=ws_a_id, name="Workspace Alpha", slug="workspace-alpha")
    ws_b = Workspace(id=ws_b_id, name="Workspace Beta", slug="workspace-beta")

    mem_a = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_a_id, user_id=user_a_id, role=WorkspaceRole.ADMIN
    )
    mem_b = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_b_id, user_id=user_b_id, role=WorkspaceRole.ADMIN
    )

    inst = GitHubInstallation(
        id=inst_id,
        workspace_id=ws_a_id,
        installation_id=123456,
        account_login="alice-org",
        account_type="Organization",
        account_id=123456,
    )

    repo_a = Repository(
        id=repo_a_id,
        workspace_id=ws_a_id,
        installation_id=inst_id,
        github_repository_id=111,
        name="alpha-repo",
        full_name="alice-org/alpha-repo",
        owner_login="alice-org",
        html_url="https://github.com/alice-org/alpha-repo",
        default_branch="main",
        is_active=True,
    )

    repo_b = Repository(
        id=repo_b_id,
        workspace_id=ws_b_id,
        installation_id=inst_id,
        github_repository_id=222,
        name="beta-repo",
        full_name="alice-org/beta-repo",
        owner_login="alice-org",
        html_url="https://github.com/alice-org/beta-repo",
        default_branch="main",
        is_active=True,
    )

    test_db_session.add_all([user_a, user_b, ws_a, ws_b, mem_a, mem_b, inst, repo_a, repo_b])
    await test_db_session.flush()

    return {
        "user_a": user_a,
        "user_b": user_b,
        "ws_a_id": ws_a_id,
        "ws_b_id": ws_b_id,
        "repo_a": repo_a,
        "repo_b": repo_b,
    }


def _auth_headers(csrf: str | None = None) -> dict[str, str]:
    token = csrf or generate_csrf_token()
    return {
        "X-CSRF-Token": token,
        "Cookie": f"csrf_token={token}",
    }


# =============================================================================
# 1. Authorization & Tenant Isolation Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_unauthenticated_requests_rejected(
    api_client: AsyncClient, test_env: dict[str, Any]
) -> None:
    repo_id = test_env["repo_a"].id
    ws_id = test_env["ws_a_id"]

    # 1. TestPilot detection
    res = await api_client.post(
        f"/api/v1/repositories/{repo_id}/testpilot/detect?workspace_id={ws_id}",
        json={},
    )
    assert res.status_code == 401

    # 2. SecureFlow scans
    res2 = await api_client.get(
        f"/api/v1/repositories/{repo_id}/secureflow/scans?workspace_id={ws_id}"
    )
    assert res2.status_code == 401


@pytest.mark.asyncio
async def test_cross_workspace_idor_rejected(
    api_client: AsyncClient, test_env: dict[str, Any]
) -> None:
    # User B is in Workspace B, attempting to access Repo A in Workspace A
    user_b = test_env["user_b"]
    repo_a_id = test_env["repo_a"].id
    ws_a_id = test_env["ws_a_id"]

    app.dependency_overrides[get_current_user] = lambda: user_b

    # Attempt to list suites in Workspace A
    res = await api_client.get(
        f"/api/v1/repositories/{repo_a_id}/testpilot/suites?workspace_id={ws_a_id}"
    )
    # 403 Forbidden because user_b is not a member of ws_a
    assert res.status_code == 403


# =============================================================================
# 2. TestPilot API Endpoints Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_testpilot_detect_framework(
    api_client: AsyncClient, test_env: dict[str, Any]
) -> None:
    user_a = test_env["user_a"]
    repo_a_id = test_env["repo_a"].id
    ws_a_id = test_env["ws_a_id"]
    app.dependency_overrides[get_current_user] = lambda: user_a

    res = await api_client.post(
        f"/api/v1/repositories/{repo_a_id}/testpilot/detect?workspace_id={ws_a_id}",
        json={},
    )
    assert res.status_code == 200
    data = res.json()
    assert "framework" in data
    assert "runner_command" in data
    assert "is_available" in data


@pytest.mark.asyncio
async def test_testpilot_generate_approve_execute_workflow(
    api_client: AsyncClient, test_env: dict[str, Any], test_db_session: AsyncSession
) -> None:
    user_a = test_env["user_a"]
    repo_a_id = test_env["repo_a"].id
    ws_a_id = test_env["ws_a_id"]
    app.dependency_overrides[get_current_user] = lambda: user_a
    headers = _auth_headers()

    # 1. Generate test suite
    gen_payload = {
        "framework": "pytest",
        "target_files": ["app/math.py"],
        "source_context": "def add(a, b): return a + b\n",
        "test_type": "unit",
    }
    with patch(
        "app.services.testpilot.generator.TestGenerator.generate_suite",
        new_callable=AsyncMock,
    ) as mock_gen:
        from app.services.testpilot.schemas import GeneratedTestCase, GeneratedTestSuite

        mock_gen.return_value = GeneratedTestSuite(
            framework="pytest",
            target_files=["app/math.py"],
            test_type="unit",
            cases=[
                GeneratedTestCase(
                    name="test_add_positive",
                    description="Tests addition of two integers",
                    test_type="unit",
                    target_symbol="add",
                    code="def test_add_positive(): assert add(1, 2) == 3\n",
                )
            ],
        )

        res = await api_client.post(
            f"/api/v1/repositories/{repo_a_id}/testpilot/suites?workspace_id={ws_a_id}",
            json=gen_payload,
            headers=headers,
        )
        assert res.status_code == 201
        suite_data = res.json()
        suite_id = suite_data["id"]
        assert suite_data["status"] in ("GENERATED", "generated")
        assert len(suite_data["test_cases"]) == 1

    # 2. Attempt execute BEFORE approval (Mandatory approval boundary enforcement)
    exec_res = await api_client.post(
        f"/api/v1/repositories/{repo_a_id}/testpilot/suites/{suite_id}/execute?workspace_id={ws_a_id}",
        json={"timeout_seconds": 60},
        headers=headers,
    )
    assert exec_res.status_code == 403
    assert "approval is required" in exec_res.json()["detail"].lower()

    # 3. Approve suite
    appr_res = await api_client.post(
        f"/api/v1/repositories/{repo_a_id}/testpilot/suites/{suite_id}/approve?workspace_id={ws_a_id}",
        headers=headers,
    )
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] in ("APPROVED", "approved")
    assert appr_res.json()["approved_by"] == str(user_a.id)

    # 4. Execute approved suite
    with patch(
        "app.services.testpilot.runner.TestPilotRunner.execute_suite",
        new_callable=AsyncMock,
    ) as mock_exec:
        from app.services.testpilot.schemas import IndividualTestResult, TestExecutionSummary

        exec_id = uuid.uuid4()
        mock_exec.return_value = TestExecutionSummary(
            execution_id=exec_id,
            suite_id=uuid.UUID(suite_id),
            command="pytest -v",
            status="PASSED",
            exit_code=0,
            stdout="tests/test_math.py::test_add_positive PASSED\n1 passed in 0.05s\n",
            stderr="",
            duration_ms=50,
            passed_count=1,
            failed_count=0,
            skipped_count=0,
            results=[
                IndividualTestResult(
                    test_name="tests/test_math.py::test_add_positive",
                    status="PASSED",
                    duration_ms=50,
                )
            ],
        )

        # Seed database execution record for endpoint retrieval
        db_exec = TestPilotExecution(
            id=exec_id,
            workspace_id=ws_a_id,
            repository_id=repo_a_id,
            suite_id=uuid.UUID(suite_id),
            command="pytest -v",
            status="PASSED",
            exit_code=0,
            stdout="tests/test_math.py::test_add_positive PASSED\n1 passed in 0.05s\n",
            stderr="",
            duration_ms=50,
            passed_count=1,
            failed_count=0,
            skipped_count=0,
        )
        test_db_session.add(db_exec)
        await test_db_session.flush()

        run_res = await api_client.post(
            f"/api/v1/repositories/{repo_a_id}/testpilot/suites/{suite_id}/execute?workspace_id={ws_a_id}",
            json={"timeout_seconds": 60},
            headers=headers,
        )
        assert run_res.status_code == 200
        run_data = run_res.json()
        assert run_data["status"] == "PASSED"
        assert run_data["passed_count"] == 1

    # 5. Retrieve execution details
    get_exec_res = await api_client.get(
        f"/api/v1/repositories/{repo_a_id}/testpilot/executions/{exec_id}?workspace_id={ws_a_id}"
    )
    assert get_exec_res.status_code == 200
    assert get_exec_res.json()["command"] == "pytest -v"


@pytest.mark.asyncio
async def test_testpilot_reject_suite(
    api_client: AsyncClient, test_env: dict[str, Any], test_db_session: AsyncSession
) -> None:
    user_a = test_env["user_a"]
    repo_a_id = test_env["repo_a"].id
    ws_a_id = test_env["ws_a_id"]
    app.dependency_overrides[get_current_user] = lambda: user_a
    headers = _auth_headers()

    suite = TestPilotSuite(
        id=uuid.uuid4(),
        workspace_id=ws_a_id,
        repository_id=repo_a_id,
        framework="pytest",
        target_files=["src/auth.py"],
        test_type="unit",
        status=TestSuiteStatus.GENERATED,
    )
    test_db_session.add(suite)
    await test_db_session.flush()

    res = await api_client.post(
        f"/api/v1/repositories/{repo_a_id}/testpilot/suites/{suite.id}/reject?workspace_id={ws_a_id}",
        json={"reason": "Redundant tests"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["status"] in ("REJECTED", "rejected")


@pytest.mark.asyncio
async def test_testpilot_coverage_and_diagnose(
    api_client: AsyncClient, test_env: dict[str, Any], test_db_session: AsyncSession
) -> None:
    user_a = test_env["user_a"]
    repo_a_id = test_env["repo_a"].id
    ws_a_id = test_env["ws_a_id"]
    app.dependency_overrides[get_current_user] = lambda: user_a
    headers = _auth_headers()

    # Seed execution & coverage
    exec_id = uuid.uuid4()
    execution = TestPilotExecution(
        id=exec_id,
        workspace_id=ws_a_id,
        repository_id=repo_a_id,
        command="pytest -v",
        status="FAILED",
        exit_code=1,
        stdout="FAIL tests/test_payment.py",
        stderr="Traceback (most recent call last):\n  File 'app/pay.py', line 12, in charge\n    raise ValueError('invalid')\nValueError: invalid",
        failed_count=1,
    )
    res_item = TestPilotResult(
        id=uuid.uuid4(),
        execution_id=exec_id,
        test_name="tests/test_payment.py::test_charge",
        status="FAILED",
        duration_ms=12,
        failure_message="ValueError: invalid",
    )
    cov = TestPilotCoverageReport(
        id=uuid.uuid4(),
        workspace_id=ws_a_id,
        repository_id=repo_a_id,
        execution_id=exec_id,
        line_coverage_pct=88.5,
        branch_coverage_pct=75.0,
        uncovered_files=["app/untested.py"],
    )
    test_db_session.add_all([execution, res_item, cov])
    await test_db_session.flush()

    # 1. Retrieve individual results
    res_res = await api_client.get(
        f"/api/v1/repositories/{repo_a_id}/testpilot/executions/{exec_id}/results?workspace_id={ws_a_id}"
    )
    assert res_res.status_code == 200
    assert len(res_res.json()) == 1
    assert res_res.json()[0]["test_name"] == "tests/test_payment.py::test_charge"

    # 2. Retrieve coverage list
    cov_res = await api_client.get(
        f"/api/v1/repositories/{repo_a_id}/testpilot/coverage?workspace_id={ws_a_id}"
    )
    assert cov_res.status_code == 200
    assert cov_res.json()["total"] >= 1
    assert cov_res.json()["items"][0]["line_coverage_pct"] == 88.5

    # 3. Failure diagnosis
    with patch(
        "app.services.testpilot.diagnoser.FailureDiagnoser.diagnose",
        new_callable=AsyncMock,
    ) as mock_diag:
        from app.services.testpilot.schemas import DiagnosisReport

        mock_diag.return_value = DiagnosisReport(
            failing_test="tests/test_payment.py::test_charge",
            error_message="ValueError: invalid",
            traceback_parsed={"frames": []},
            root_cause_analysis="Input parameter not checked before charging",
            fix_suggestions=["Add validation in app/pay.py:12"],
            affected_files=["app/pay.py"],
            confidence=0.92,
        )

        diag_res = await api_client.post(
            f"/api/v1/repositories/{repo_a_id}/testpilot/executions/{exec_id}/diagnose?workspace_id={ws_a_id}",
            json={},
            headers=headers,
        )
        assert diag_res.status_code == 200
        assert diag_res.json()["confidence"] == 0.92
        assert "Input parameter not checked" in diag_res.json()["root_cause_analysis"]


@pytest.mark.asyncio
async def test_testpilot_impact_selection(
    api_client: AsyncClient, test_env: dict[str, Any]
) -> None:
    user_a = test_env["user_a"]
    repo_a_id = test_env["repo_a"].id
    ws_a_id = test_env["ws_a_id"]
    app.dependency_overrides[get_current_user] = lambda: user_a

    diff_text = """
diff --git a/app/calc.py b/app/calc.py
--- a/app/calc.py
+++ b/app/calc.py
@@ -1,2 +1,3 @@
 def add(a, b):
+    # note
     return a + b
"""
    res = await api_client.post(
        f"/api/v1/repositories/{repo_a_id}/testpilot/impact/select?workspace_id={ws_a_id}",
        json={"diff_text": diff_text},
    )
    assert res.status_code == 200
    assert "risk_exposure_score" in res.json()


# =============================================================================
# 3. SecureFlow API Endpoints Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_secureflow_scanner_availability(
    api_client: AsyncClient, test_env: dict[str, Any]
) -> None:
    user_a = test_env["user_a"]
    repo_a_id = test_env["repo_a"].id
    ws_a_id = test_env["ws_a_id"]
    app.dependency_overrides[get_current_user] = lambda: user_a

    res = await api_client.get(
        f"/api/v1/repositories/{repo_a_id}/secureflow/scanners?workspace_id={ws_a_id}"
    )
    assert res.status_code == 200
    data = res.json()
    assert "scanners" in data
    assert len(data["scanners"]) >= 3
    # Native secret scanner is always available
    scanners = {s["scanner"]: s for s in data["scanners"]}
    assert scanners["secret-scanner"]["is_available"] is True


@pytest.mark.asyncio
async def test_secureflow_start_scan_and_secret_redaction(
    api_client: AsyncClient, test_env: dict[str, Any], test_db_session: AsyncSession
) -> None:
    user_a = test_env["user_a"]
    repo_a_id = test_env["repo_a"].id
    ws_a_id = test_env["ws_a_id"]
    app.dependency_overrides[get_current_user] = lambda: user_a
    headers = _auth_headers()

    with patch(
        "app.services.secureflow.service.SecureFlowService.run_scan",
        new_callable=AsyncMock,
    ) as mock_scan:
        from app.services.secureflow.schemas import ScanExecutionSummary

        scan_id = uuid.uuid4()
        mock_scan.return_value = ScanExecutionSummary(
            scan_id=scan_id,
            workspace_id=ws_a_id,
            repository_id=repo_a_id,
            status=SecureFlowScanStatus.COMPLETED,
            scanners_used=[{"scanner": "secret-scanner", "status": "COMPLETED"}],
            total_findings=1,
            critical_count=1,
            high_count=0,
            medium_count=0,
            low_count=0,
            started_at=None,
            completed_at=None,
        )

        # Seed scan record in DB
        scan = SecureFlowScan(
            id=scan_id,
            workspace_id=ws_a_id,
            repository_id=repo_a_id,
            scan_type="FULL",
            status=SecureFlowScanStatus.COMPLETED,
            scanners_used=[{"scanner": "secret-scanner", "status": "COMPLETED"}],
            total_findings=1,
            critical_count=1,
            high_count=0,
            medium_count=0,
            low_count=0,
        )
        test_db_session.add(scan)
        await test_db_session.flush()

        res = await api_client.post(
            f"/api/v1/repositories/{repo_a_id}/secureflow/scans?workspace_id={ws_a_id}",
            json={"scan_type": "FULL"},
            headers=headers,
        )
        assert res.status_code == 201
        assert res.json()["id"] == str(scan_id)
        assert res.json()["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_secureflow_findings_filtering_and_status_update(
    api_client: AsyncClient, test_env: dict[str, Any], test_db_session: AsyncSession
) -> None:
    user_a = test_env["user_a"]
    repo_a_id = test_env["repo_a"].id
    ws_a_id = test_env["ws_a_id"]
    app.dependency_overrides[get_current_user] = lambda: user_a
    headers = _auth_headers()

    scan_id = uuid.uuid4()
    scan = SecureFlowScan(
        id=scan_id,
        workspace_id=ws_a_id,
        repository_id=repo_a_id,
        scan_type="FULL",
        status=SecureFlowScanStatus.COMPLETED,
        scanners_used=[],
        total_findings=1,
        critical_count=1,
        high_count=0,
        medium_count=0,
        low_count=0,
    )
    finding_id = uuid.uuid4()
    finding = SecureFlowFinding(
        id=finding_id,
        workspace_id=ws_a_id,
        repository_id=repo_a_id,
        scan_id=scan_id,
        scanner="secret-scanner",
        category="SECRET",
        severity=FindingSeverity.CRITICAL,
        confidence=1.0,
        rule_id="SEC001",
        title="Hardcoded API Token",
        description="Leaked token found in config.py",
        redacted_evidence="API_KEY = '[REDACTED_SECRET]'",
        fingerprint="sha256_dummy_fingerprint",
        status=FindingStatus.OPEN,
    )
    test_db_session.add_all([scan, finding])
    await test_db_session.flush()

    # 1. Filter findings by severity
    list_res = await api_client.get(
        f"/api/v1/repositories/{repo_a_id}/secureflow/findings?workspace_id={ws_a_id}&severity=CRITICAL"
    )
    assert list_res.status_code == 200
    data = list_res.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == str(finding_id)

    # 2. Get individual finding
    item_res = await api_client.get(
        f"/api/v1/repositories/{repo_a_id}/secureflow/findings/{finding_id}?workspace_id={ws_a_id}"
    )
    assert item_res.status_code == 200
    assert item_res.json()["title"] == "Hardcoded API Token"

    # 3. Patch finding status
    patch_res = await api_client.patch(
        f"/api/v1/repositories/{repo_a_id}/secureflow/findings/{finding_id}/status?workspace_id={ws_a_id}",
        json={"status": "FALSE_POSITIVE", "note": "Dummy test token"},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "FALSE_POSITIVE"


@pytest.mark.asyncio
async def test_secureflow_scan_events_and_remediation_workflow(
    api_client: AsyncClient, test_env: dict[str, Any], test_db_session: AsyncSession
) -> None:
    user_a = test_env["user_a"]
    repo_a_id = test_env["repo_a"].id
    ws_a_id = test_env["ws_a_id"]
    app.dependency_overrides[get_current_user] = lambda: user_a
    headers = _auth_headers()

    scan_id = uuid.uuid4()
    scan = SecureFlowScan(
        id=scan_id,
        workspace_id=ws_a_id,
        repository_id=repo_a_id,
        scan_type="FULL",
        status=SecureFlowScanStatus.COMPLETED,
        scanners_used=[],
        total_findings=1,
        critical_count=1,
        high_count=0,
        medium_count=0,
        low_count=0,
    )
    event = SecureFlowScanEvent(
        id=uuid.uuid4(),
        scan_id=scan_id,
        event_type="SCAN_STARTED",
        message="Scan initiated for alpha-repo",
        details={"type": "FULL"},
    )
    finding_id = uuid.uuid4()
    finding = SecureFlowFinding(
        id=finding_id,
        workspace_id=ws_a_id,
        repository_id=repo_a_id,
        scan_id=scan_id,
        scanner="secret-scanner",
        category="SECRET",
        severity=FindingSeverity.CRITICAL,
        confidence=1.0,
        rule_id="SEC001",
        title="Hardcoded Secret",
        description="Leaked token found in config.py",
        fingerprint="sha256_dummy_fingerprint2",
        status=FindingStatus.OPEN,
    )
    test_db_session.add_all([scan, event, finding])
    await test_db_session.flush()

    # 1. Retrieve scan events
    ev_res = await api_client.get(
        f"/api/v1/repositories/{repo_a_id}/secureflow/scans/{scan_id}/events?workspace_id={ws_a_id}"
    )
    assert ev_res.status_code == 200
    assert ev_res.json()["total"] == 1
    assert ev_res.json()["items"][0]["event_type"] == "SCAN_STARTED"

    # 2. Trigger DevPilot remediation for finding
    with patch(
        "app.services.secureflow.remediation_bridge.DevPilotRemediationBridge.create_remediation_task",
        new_callable=AsyncMock,
    ) as mock_rem:
        from app.services.secureflow.schemas import RemediationTaskResult

        devpilot_task_id = uuid.uuid4()
        mock_rem.return_value = RemediationTaskResult(
            finding_id=finding_id,
            devpilot_task_id=devpilot_task_id,
            task_title="[Security Remediation] Hardcoded Secret",
            task_status="CREATED",
            requires_plan_approval=True,
            requires_code_approval=True,
        )

        rem_res = await api_client.post(
            f"/api/v1/repositories/{repo_a_id}/secureflow/findings/{finding_id}/remediate?workspace_id={ws_a_id}",
            headers=headers,
        )
        assert rem_res.status_code == 200
        rem_data = rem_res.json()
        assert rem_data["devpilot_task_id"] == str(devpilot_task_id)
        assert rem_data["requires_plan_approval"] is True
