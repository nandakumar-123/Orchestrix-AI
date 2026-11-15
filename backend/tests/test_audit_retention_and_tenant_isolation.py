import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy import delete, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    DevPilotTask,
    FindingSeverity,
    GitHubInstallation,
    Repository,
    ScanEventType,
    SecureFlowFinding,
    SecureFlowScan,
    SecureFlowScanEvent,
    SecureFlowScanStatus,
    TestExecutionStatus,
    TestFramework,
    TestPilotExecution,
    TestPilotSuite,
    TestPilotTestType,
    User,
    Workspace,
)


@pytest.fixture
async def test_session() -> AsyncGenerator[AsyncSession, None]:
    """Isolated SQLite in-memory async database session with PRAGMA foreign_keys = ON."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def multi_workspace_setup(test_session: AsyncSession) -> dict[str, object]:
    """
    Seed two completely isolated workspaces (Workspace A and Workspace B),
    each with its own repository, installation, and DevPilot task.
    """
    user_a = User(email="owner-a@orchestrix.ai", full_name="User A")
    ws_a = Workspace(name="Workspace Alpha", slug="workspace-alpha")
    user_b = User(email="owner-b@orchestrix.ai", full_name="User B")
    ws_b = Workspace(name="Workspace Beta", slug="workspace-beta")
    test_session.add_all([user_a, ws_a, user_b, ws_b])
    await test_session.commit()

    inst_a = GitHubInstallation(
        workspace_id=ws_a.id,
        installation_id=1001,
        account_login="org-alpha",
        account_type="Organization",
        account_id=5001,
    )
    inst_b = GitHubInstallation(
        workspace_id=ws_b.id,
        installation_id=1002,
        account_login="org-beta",
        account_type="Organization",
        account_id=5002,
    )
    test_session.add_all([inst_a, inst_b])
    await test_session.commit()

    repo_a = Repository(
        workspace_id=ws_a.id,
        installation_id=inst_a.id,
        name="repo-alpha",
        full_name="org-alpha/repo-alpha",
        owner_login="org-alpha",
        html_url="https://github.com/org-alpha/repo-alpha",
        github_repository_id=8801,
        default_branch="main",
    )
    repo_b = Repository(
        workspace_id=ws_b.id,
        installation_id=inst_b.id,
        name="repo-beta",
        full_name="org-beta/repo-beta",
        owner_login="org-beta",
        html_url="https://github.com/org-beta/repo-beta",
        github_repository_id=8802,
        default_branch="main",
    )
    test_session.add_all([repo_a, repo_b])
    await test_session.commit()

    task_a = DevPilotTask(
        workspace_id=ws_a.id,
        repository_id=repo_a.id,
        title="Task Alpha",
        prompt="Fix vuln in alpha",
        task_type="SECURITY",
        status="CREATED",
    )
    task_b = DevPilotTask(
        workspace_id=ws_b.id,
        repository_id=repo_b.id,
        title="Task Beta",
        prompt="Fix vuln in beta",
        task_type="SECURITY",
        status="CREATED",
    )
    test_session.add_all([task_a, task_b])
    await test_session.commit()

    return {
        "ws_a_id": ws_a.id,
        "ws_b_id": ws_b.id,
        "repo_a_id": repo_a.id,
        "repo_b_id": repo_b.id,
        "task_a_id": task_a.id,
        "task_b_id": task_b.id,
    }


# ==============================================================================
# PART 1: CROSS-WORKSPACE TENANT ISOLATION SCENARIOS (1 - 7)
# ==============================================================================


@pytest.mark.asyncio
async def test_scenario_1_cross_workspace_testpilot_suite_rejected(
    test_session: AsyncSession, multi_workspace_setup: dict[str, object]
) -> None:
    """Scenario 1: Workspace A attempts to create a TestPilot suite using Workspace B's repository => REJECTED."""
    ws_a_id = multi_workspace_setup["ws_a_id"]
    repo_b_id = multi_workspace_setup["repo_b_id"]
    assert isinstance(ws_a_id, uuid.UUID)
    assert isinstance(repo_b_id, uuid.UUID)

    invalid_suite = TestPilotSuite(
        workspace_id=ws_a_id,
        repository_id=repo_b_id,  # Repo B does not belong to Workspace A
        framework=TestFramework.PYTEST,
        test_type=TestPilotTestType.UNIT,
    )
    test_session.add(invalid_suite)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_scenario_2_cross_workspace_testpilot_execution_rejected(
    test_session: AsyncSession, multi_workspace_setup: dict[str, object]
) -> None:
    """Scenario 2: Workspace A attempts to create a TestPilot execution using Workspace B's repository => REJECTED."""
    ws_a_id = multi_workspace_setup["ws_a_id"]
    repo_b_id = multi_workspace_setup["repo_b_id"]
    assert isinstance(ws_a_id, uuid.UUID)
    assert isinstance(repo_b_id, uuid.UUID)

    invalid_execution = TestPilotExecution(
        workspace_id=ws_a_id,
        repository_id=repo_b_id,  # Repo B does not belong to Workspace A
        command="pytest",
        status=TestExecutionStatus.PENDING,
    )
    test_session.add(invalid_execution)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_scenario_3_cross_workspace_secureflow_scan_rejected(
    test_session: AsyncSession, multi_workspace_setup: dict[str, object]
) -> None:
    """Scenario 3: Workspace A attempts to create a SecureFlow scan using Workspace B's repository => REJECTED."""
    ws_a_id = multi_workspace_setup["ws_a_id"]
    repo_b_id = multi_workspace_setup["repo_b_id"]
    assert isinstance(ws_a_id, uuid.UUID)
    assert isinstance(repo_b_id, uuid.UUID)

    invalid_scan = SecureFlowScan(
        workspace_id=ws_a_id,
        repository_id=repo_b_id,  # Repo B does not belong to Workspace A
        scan_type="FULL",
        status=SecureFlowScanStatus.PENDING,
    )
    test_session.add(invalid_scan)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_scenario_4_cross_workspace_secureflow_finding_rejected(
    test_session: AsyncSession, multi_workspace_setup: dict[str, object]
) -> None:
    """Scenario 4: Workspace A attempts to create a SecureFlow finding using Workspace B's repository => REJECTED."""
    ws_a_id = multi_workspace_setup["ws_a_id"]
    ws_b_id = multi_workspace_setup["ws_b_id"]
    repo_b_id = multi_workspace_setup["repo_b_id"]
    assert isinstance(ws_a_id, uuid.UUID)
    assert isinstance(ws_b_id, uuid.UUID)
    assert isinstance(repo_b_id, uuid.UUID)

    # First, create a valid scan in Workspace B
    scan_b = SecureFlowScan(
        workspace_id=ws_b_id,
        repository_id=repo_b_id,
        scan_type="FULL",
    )
    test_session.add(scan_b)
    await test_session.commit()

    # Workspace A attempts to claim repo B's finding
    invalid_finding = SecureFlowFinding(
        workspace_id=ws_a_id,  # Workspace A
        repository_id=repo_b_id,  # Repo B
        scan_id=scan_b.id,
        scanner="semgrep",
        category="SAST",
        severity=FindingSeverity.HIGH,
        rule_id="RULE-X",
        title="Cross workspace finding",
        description="Invalid tenant combination",
        fingerprint="fp_cross_ws_1",
    )
    test_session.add(invalid_finding)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_scenario_5_cross_repository_or_workspace_scan_reference_rejected(
    test_session: AsyncSession, multi_workspace_setup: dict[str, object]
) -> None:
    """Scenario 5: A SecureFlow finding references a scan belonging to a different repository or workspace => REJECTED."""
    ws_a_id = multi_workspace_setup["ws_a_id"]
    ws_b_id = multi_workspace_setup["ws_b_id"]
    repo_a_id = multi_workspace_setup["repo_a_id"]
    repo_b_id = multi_workspace_setup["repo_b_id"]
    assert isinstance(ws_a_id, uuid.UUID)
    assert isinstance(ws_b_id, uuid.UUID)
    assert isinstance(repo_a_id, uuid.UUID)
    assert isinstance(repo_b_id, uuid.UUID)

    # Valid scan created in Workspace B / Repo B
    scan_b = SecureFlowScan(
        workspace_id=ws_b_id,
        repository_id=repo_b_id,
        scan_type="SECRET",
    )
    test_session.add(scan_b)
    await test_session.commit()

    # Finding belongs to Repo A, but tries to reference Scan B (from Repo B)
    invalid_finding = SecureFlowFinding(
        workspace_id=ws_a_id,
        repository_id=repo_a_id,
        scan_id=scan_b.id,  # Scan B belongs to Repo B, not Repo A!
        scanner="secret-scanner",
        category="SECRET",
        severity=FindingSeverity.CRITICAL,
        rule_id="SEC-001",
        title="Leaked token",
        description="Foreign scan linkage",
        fingerprint="fp_foreign_scan",
    )
    test_session.add(invalid_finding)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_scenario_6_cross_repository_or_workspace_suite_reference_rejected(
    test_session: AsyncSession, multi_workspace_setup: dict[str, object]
) -> None:
    """Scenario 6: A TestPilot execution references a suite belonging to another repository or workspace => REJECTED."""
    ws_a_id = multi_workspace_setup["ws_a_id"]
    ws_b_id = multi_workspace_setup["ws_b_id"]
    repo_a_id = multi_workspace_setup["repo_a_id"]
    repo_b_id = multi_workspace_setup["repo_b_id"]
    assert isinstance(ws_a_id, uuid.UUID)
    assert isinstance(ws_b_id, uuid.UUID)
    assert isinstance(repo_a_id, uuid.UUID)
    assert isinstance(repo_b_id, uuid.UUID)

    # Valid suite created in Repo B
    suite_b = TestPilotSuite(
        workspace_id=ws_b_id,
        repository_id=repo_b_id,
        framework=TestFramework.PYTEST,
        test_type=TestPilotTestType.UNIT,
    )
    test_session.add(suite_b)
    await test_session.commit()

    # Execution in Repo A attempts to reference Suite B (which belongs to Repo B)
    invalid_exec = TestPilotExecution(
        workspace_id=ws_a_id,
        repository_id=repo_a_id,
        suite_id=suite_b.id,  # Suite B belongs to Repo B, not Repo A!
        command="pytest tests/unit",
        status=TestExecutionStatus.PENDING,
    )
    test_session.add(invalid_exec)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_scenario_7_cross_workspace_devpilot_task_reference_rejected(
    test_session: AsyncSession, multi_workspace_setup: dict[str, object]
) -> None:
    """Scenario 7: A SecureFlow finding references a DevPilot task belonging to another workspace => REJECTED."""
    ws_a_id = multi_workspace_setup["ws_a_id"]
    repo_a_id = multi_workspace_setup["repo_a_id"]
    task_b_id = multi_workspace_setup["task_b_id"]
    assert isinstance(ws_a_id, uuid.UUID)
    assert isinstance(repo_a_id, uuid.UUID)
    assert isinstance(task_b_id, uuid.UUID)

    # Valid scan in Workspace A
    scan_a = SecureFlowScan(
        workspace_id=ws_a_id,
        repository_id=repo_a_id,
        scan_type="SAST",
    )
    test_session.add(scan_a)
    await test_session.commit()

    # Finding in Workspace A attempts to link to DevPilot task from Workspace B
    invalid_finding = SecureFlowFinding(
        workspace_id=ws_a_id,
        repository_id=repo_a_id,
        scan_id=scan_a.id,
        scanner="semgrep",
        category="SAST",
        severity=FindingSeverity.HIGH,
        rule_id="XSS-001",
        title="Reflected XSS",
        description="Cross workspace task link attempt",
        devpilot_task_id=task_b_id,  # Task B belongs to Workspace B!
        fingerprint="fp_cross_task_ref",
    )
    test_session.add(invalid_finding)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


# ==============================================================================
# PART 2: SECURITY AUDIT RETENTION & SAFE DELETION TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_scan_deletion_with_findings_rejected_via_orm(
    test_session: AsyncSession, multi_workspace_setup: dict[str, object]
) -> None:
    """Deleting a SecureFlowScan with existing findings via ORM is REJECTED by RESTRICT constraint."""
    ws_a_id = multi_workspace_setup["ws_a_id"]
    repo_a_id = multi_workspace_setup["repo_a_id"]
    assert isinstance(ws_a_id, uuid.UUID)
    assert isinstance(repo_a_id, uuid.UUID)

    scan = SecureFlowScan(workspace_id=ws_a_id, repository_id=repo_a_id, scan_type="FULL")
    test_session.add(scan)
    await test_session.commit()
    scan_id = scan.id

    finding = SecureFlowFinding(
        workspace_id=ws_a_id,
        repository_id=repo_a_id,
        scan_id=scan_id,
        scanner="pip-audit",
        category="DEPENDENCY",
        severity=FindingSeverity.CRITICAL,
        rule_id="CVE-2024-9999",
        title="Critical vuln",
        description="Audit finding to retain",
        fingerprint="fp_audit_retention_1",
    )
    test_session.add(finding)
    await test_session.commit()
    finding_id = finding.id

    # ORM-level deletion of scan must be rejected
    await test_session.delete(scan)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()

    # Verify scan and finding still exist via scalar query
    count = await test_session.scalar(
        select(func.count())
        .select_from(SecureFlowFinding)
        .where(SecureFlowFinding.id == finding_id)
    )
    assert count == 1

    scan_count = await test_session.scalar(
        select(func.count()).select_from(SecureFlowScan).where(SecureFlowScan.id == scan_id)
    )
    assert scan_count == 1


@pytest.mark.asyncio
async def test_scan_deletion_with_findings_rejected_via_sql(
    test_session: AsyncSession, multi_workspace_setup: dict[str, object]
) -> None:
    """Direct SQL deletion of a SecureFlowScan with existing findings is REJECTED."""
    ws_a_id = multi_workspace_setup["ws_a_id"]
    repo_a_id = multi_workspace_setup["repo_a_id"]
    assert isinstance(ws_a_id, uuid.UUID)
    assert isinstance(repo_a_id, uuid.UUID)

    scan = SecureFlowScan(workspace_id=ws_a_id, repository_id=repo_a_id, scan_type="FULL")
    test_session.add(scan)
    await test_session.commit()
    scan_id = scan.id

    finding = SecureFlowFinding(
        workspace_id=ws_a_id,
        repository_id=repo_a_id,
        scan_id=scan_id,
        scanner="pip-audit",
        category="DEPENDENCY",
        severity=FindingSeverity.HIGH,
        rule_id="CVE-2024-8888",
        title="Direct SQL test vuln",
        description="Audit finding to retain",
        fingerprint="fp_audit_retention_2",
    )
    test_session.add(finding)
    await test_session.commit()
    finding_id = finding.id

    # Direct SQL deletion must be rejected
    with pytest.raises(IntegrityError):
        await test_session.execute(delete(SecureFlowScan).where(SecureFlowScan.id == scan_id))
        await test_session.commit()
    await test_session.rollback()

    # Verify finding still exists
    count = await test_session.scalar(
        select(func.count())
        .select_from(SecureFlowFinding)
        .where(SecureFlowFinding.id == finding_id)
    )
    assert count == 1


@pytest.mark.asyncio
async def test_scan_deletion_with_events_rejected_via_orm_and_sql(
    test_session: AsyncSession, multi_workspace_setup: dict[str, object]
) -> None:
    """Deleting a SecureFlowScan with audit scan events is REJECTED by RESTRICT constraint."""
    ws_a_id = multi_workspace_setup["ws_a_id"]
    repo_a_id = multi_workspace_setup["repo_a_id"]
    assert isinstance(ws_a_id, uuid.UUID)
    assert isinstance(repo_a_id, uuid.UUID)

    scan = SecureFlowScan(workspace_id=ws_a_id, repository_id=repo_a_id, scan_type="FULL")
    test_session.add(scan)
    await test_session.commit()
    scan_id = scan.id

    event = SecureFlowScanEvent(
        scan_id=scan_id,
        event_type=ScanEventType.SCAN_STARTED,
        message="Scan started for audit compliance",
    )
    test_session.add(event)
    await test_session.commit()
    event_id = event.id

    # ORM deletion rejected
    await test_session.delete(scan)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()

    # Direct SQL deletion rejected
    with pytest.raises(IntegrityError):
        await test_session.execute(delete(SecureFlowScan).where(SecureFlowScan.id == scan_id))
        await test_session.commit()
    await test_session.rollback()

    # Verify event and scan still exist
    ev_count = await test_session.scalar(
        select(func.count())
        .select_from(SecureFlowScanEvent)
        .where(SecureFlowScanEvent.id == event_id)
    )
    assert ev_count == 1


@pytest.mark.asyncio
async def test_repository_deletion_with_security_scans_rejected(
    test_session: AsyncSession, multi_workspace_setup: dict[str, object]
) -> None:
    """Deleting a repository that has historical security scans is REJECTED by RESTRICT constraint."""
    ws_a_id = multi_workspace_setup["ws_a_id"]
    repo_a_id = multi_workspace_setup["repo_a_id"]
    assert isinstance(ws_a_id, uuid.UUID)
    assert isinstance(repo_a_id, uuid.UUID)

    scan = SecureFlowScan(workspace_id=ws_a_id, repository_id=repo_a_id, scan_type="FULL")
    test_session.add(scan)
    await test_session.commit()
    scan_id = scan.id

    # Direct SQL deletion of repository must be rejected by fk_secureflow_scans_repo_workspace RESTRICT
    with pytest.raises(IntegrityError):
        await test_session.execute(delete(Repository).where(Repository.id == repo_a_id))
        await test_session.commit()
    await test_session.rollback()

    # Scan remains intact
    count = await test_session.scalar(
        select(func.count()).select_from(SecureFlowScan).where(SecureFlowScan.id == scan_id)
    )
    assert count == 1


@pytest.mark.asyncio
async def test_safe_empty_scan_deletion_permitted(
    test_session: AsyncSession, multi_workspace_setup: dict[str, object]
) -> None:
    """An empty scan (no findings, no events) can be deleted cleanly without violating RESTRICT."""
    ws_a_id = multi_workspace_setup["ws_a_id"]
    repo_a_id = multi_workspace_setup["repo_a_id"]
    assert isinstance(ws_a_id, uuid.UUID)
    assert isinstance(repo_a_id, uuid.UUID)

    scan = SecureFlowScan(workspace_id=ws_a_id, repository_id=repo_a_id, scan_type="FULL")
    test_session.add(scan)
    await test_session.commit()

    # Empty scan deletion succeeds
    await test_session.delete(scan)
    await test_session.commit()

    reloaded = await test_session.get(SecureFlowScan, scan.id)
    assert reloaded is None
