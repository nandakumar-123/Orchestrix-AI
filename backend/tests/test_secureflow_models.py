import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    DevPilotTask,
    FindingSeverity,
    FindingStatus,
    GitHubInstallation,
    Repository,
    RepositorySnapshot,
    ScanEventType,
    SecureFlowFinding,
    SecureFlowScan,
    SecureFlowScanEvent,
    SecureFlowScanStatus,
    User,
    Workspace,
)


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


@pytest.fixture
async def seed_data(test_session: AsyncSession) -> dict[str, object]:
    """Seed base user, workspace, installation, repository, and devpilot task."""
    user = User(
        email="security-officer@orchestrix.ai",
        full_name="Security Officer",
    )
    workspace = Workspace(
        name="Security Intelligence Team",
        slug="sec-intel-team",
    )
    test_session.add_all([user, workspace])
    await test_session.commit()

    installation = GitHubInstallation(
        workspace_id=workspace.id,
        installation_id=5551234,
        account_login="sec-org",
        account_type="Organization",
        account_id=67890,
    )
    test_session.add(installation)
    await test_session.commit()

    repo = Repository(
        workspace_id=workspace.id,
        installation_id=installation.id,
        name="crypto-service",
        full_name="sec-org/crypto-service",
        owner_login="sec-org",
        html_url="https://github.com/sec-org/crypto-service",
        github_repository_id=99887766,
        default_branch="main",
    )
    test_session.add(repo)
    await test_session.commit()

    snapshot = RepositorySnapshot(
        workspace_id=workspace.id,
        repository_id=repo.id,
        commit_sha="c" * 40,
        branch="main",
    )
    test_session.add(snapshot)
    await test_session.commit()

    devpilot_task = DevPilotTask(
        workspace_id=workspace.id,
        repository_id=repo.id,
        title="Remediate Vulnerable Dependency",
        prompt="Upgrade cryptopackage to safe release >= 2.0",
        task_type="SECURITY",
        status="CREATED",
    )
    test_session.add(devpilot_task)
    await test_session.commit()

    return {
        "user": user,
        "workspace": workspace,
        "installation": installation,
        "repository": repo,
        "snapshot": snapshot,
        "devpilot_task": devpilot_task,
    }


@pytest.mark.asyncio
async def test_secureflow_scan_creation_and_counts(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Test creating a SecureFlowScan with accurate scanner execution outcomes and metrics."""
    workspace = seed_data["workspace"]
    repo = seed_data["repository"]
    snapshot = seed_data["snapshot"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo, Repository)
    assert isinstance(snapshot, RepositorySnapshot)

    scan = SecureFlowScan(
        workspace_id=workspace.id,
        repository_id=repo.id,
        snapshot_id=snapshot.id,
        scan_type="FULL",
        status=SecureFlowScanStatus.COMPLETED,
        scanners_used=[
            {"name": "pip-audit", "status": "COMPLETED", "duration_ms": 420},
            {"name": "secret-scanner", "status": "COMPLETED", "duration_ms": 110},
        ],
        total_findings=2,
        critical_count=1,
        high_count=1,
        medium_count=0,
        low_count=0,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    test_session.add(scan)
    await test_session.commit()
    await test_session.refresh(scan)

    assert isinstance(scan.id, uuid.UUID)
    assert scan.scan_type == "FULL"
    assert scan.status == "COMPLETED"
    assert scan.total_findings == 2
    assert scan.critical_count == 1
    assert scan.high_count == 1
    assert len(scan.scanners_used) == 2


@pytest.mark.asyncio
async def test_secureflow_scan_nonnegative_counts_constraint(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Test that negative finding counts violate database CheckConstraints."""
    workspace = seed_data["workspace"]
    repo = seed_data["repository"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo, Repository)

    invalid_scan = SecureFlowScan(
        workspace_id=workspace.id,
        repository_id=repo.id,
        scan_type="SAST",
        total_findings=-1,  # Negative count!
    )
    test_session.add(invalid_scan)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_secureflow_finding_creation_and_remediation_link(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Test creating a security finding with stable fingerprint and DevPilot remediation link."""
    workspace = seed_data["workspace"]
    repo = seed_data["repository"]
    devpilot_task = seed_data["devpilot_task"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo, Repository)
    assert isinstance(devpilot_task, DevPilotTask)

    scan = SecureFlowScan(
        workspace_id=workspace.id,
        repository_id=repo.id,
        scan_type="DEPENDENCY",
        status=SecureFlowScanStatus.COMPLETED,
    )
    test_session.add(scan)
    await test_session.commit()

    fingerprint = SecureFlowFinding.compute_fingerprint(
        rule_id="PYSEC-2024-001",
        file_path="pyproject.toml",
        line_start=12,
        line_end=12,
        title="Vulnerable dependency cryptography < 42.0",
    )

    finding = SecureFlowFinding(
        workspace_id=workspace.id,
        repository_id=repo.id,
        scan_id=scan.id,
        scanner="pip-audit",
        category="DEPENDENCY",
        severity=FindingSeverity.CRITICAL,
        confidence=1.0,
        file_path="pyproject.toml",
        line_start=12,
        line_end=12,
        rule_id="PYSEC-2024-001",
        title="Vulnerable dependency cryptography < 42.0",
        description="Remote code execution flaw in TLS certificate verification.",
        redacted_evidence="cryptography==41.0.1",
        remediation_recommendation="Update cryptography to >= 42.0.0",
        remediation_code_snippet='cryptography = ">=42.0.0"',
        external_advisory_url="https://osv.dev/vulnerability/PYSEC-2024-001",
        status=FindingStatus.OPEN,
        devpilot_task_id=devpilot_task.id,
        fingerprint=fingerprint,
    )
    test_session.add(finding)
    await test_session.commit()
    await test_session.refresh(finding)

    assert finding.id is not None
    assert finding.severity == "CRITICAL"
    assert finding.confidence == 1.0
    assert finding.fingerprint == fingerprint
    assert finding.devpilot_task_id == devpilot_task.id
    assert finding.devpilot_task is not None
    assert finding.devpilot_task.title == "Remediate Vulnerable Dependency"


@pytest.mark.asyncio
async def test_secureflow_finding_repository_scoped_fingerprint_uniqueness(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """
    Test finding fingerprint deduplication is strictly scoped per repository:
    - Same repository + same fingerprint => IntegrityError (prevents duplicates).
    - Different repository + same fingerprint => SUT allows both legitimately.
    """
    workspace = seed_data["workspace"]
    repo1 = seed_data["repository"]
    installation = seed_data["installation"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo1, Repository)
    assert isinstance(installation, GitHubInstallation)

    ws_id = workspace.id
    repo1_id = repo1.id
    inst_id = installation.id

    scan1 = SecureFlowScan(
        workspace_id=ws_id,
        repository_id=repo1_id,
        scan_type="SECRET",
    )
    test_session.add(scan1)
    await test_session.commit()
    scan1_id = scan1.id

    fp = SecureFlowFinding.compute_fingerprint(
        rule_id="AWS-SECRET-KEY",
        file_path="config.py",
        line_start=10,
        line_end=10,
        title="Hardcoded AWS Access Key",
    )

    f1 = SecureFlowFinding(
        workspace_id=ws_id,
        repository_id=repo1_id,
        scan_id=scan1_id,
        scanner="secret-scanner",
        category="SECRET",
        severity=FindingSeverity.HIGH,
        rule_id="AWS-SECRET-KEY",
        title="Hardcoded AWS Access Key",
        description="Detected AWS credentials in config",
        fingerprint=fp,
    )
    test_session.add(f1)
    await test_session.commit()

    # 1. Duplicate finding in the SAME repository must be rejected
    f1_dup = SecureFlowFinding(
        workspace_id=ws_id,
        repository_id=repo1_id,
        scan_id=scan1_id,
        scanner="secret-scanner",
        category="SECRET",
        severity=FindingSeverity.HIGH,
        rule_id="AWS-SECRET-KEY",
        title="Hardcoded AWS Access Key",
        description="Duplicate detected in next run",
        fingerprint=fp,
    )
    test_session.add(f1_dup)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()

    # 2. Same fingerprint in a DIFFERENT repository MUST be accepted
    repo2 = Repository(
        workspace_id=ws_id,
        installation_id=inst_id,
        name="payment-service",
        full_name="sec-org/payment-service",
        owner_login="sec-org",
        html_url="https://github.com/sec-org/payment-service",
        github_repository_id=33445566,
        default_branch="main",
    )
    test_session.add(repo2)
    await test_session.commit()
    repo2_id = repo2.id

    scan2 = SecureFlowScan(
        workspace_id=ws_id,
        repository_id=repo2_id,
        scan_type="SECRET",
    )
    test_session.add(scan2)
    await test_session.commit()
    scan2_id = scan2.id

    f2_other_repo = SecureFlowFinding(
        workspace_id=ws_id,
        repository_id=repo2_id,
        scan_id=scan2_id,
        scanner="secret-scanner",
        category="SECRET",
        severity=FindingSeverity.HIGH,
        rule_id="AWS-SECRET-KEY",
        title="Hardcoded AWS Access Key",
        description="Same finding in payment-service repository",
        fingerprint=fp,  # Same fingerprint, different repo
    )
    test_session.add(f2_other_repo)
    await test_session.commit()
    await test_session.refresh(f2_other_repo)
    assert f2_other_repo.repository_id == repo2_id
    assert f2_other_repo.fingerprint == fp


@pytest.mark.asyncio
async def test_secureflow_finding_line_ranges_and_confidence_constraints(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Test check constraints on confidence range [0.0, 1.0] and line ranges."""
    workspace = seed_data["workspace"]
    repo = seed_data["repository"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo, Repository)

    ws_id = workspace.id
    repo_id = repo.id

    scan = SecureFlowScan(
        workspace_id=ws_id,
        repository_id=repo_id,
        scan_type="SAST",
    )
    test_session.add(scan)
    await test_session.commit()
    scan_id = scan.id

    # Invalid confidence (> 1.0)
    f_bad_conf = SecureFlowFinding(
        workspace_id=ws_id,
        repository_id=repo_id,
        scan_id=scan_id,
        scanner="semgrep",
        category="SAST",
        severity=FindingSeverity.MEDIUM,
        confidence=1.5,  # Out of range!
        rule_id="TEST-RULE",
        title="Test",
        description="Test",
        fingerprint="bad_conf",
    )
    test_session.add(f_bad_conf)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()

    # Invalid line range (line_end < line_start)
    f_bad_lines = SecureFlowFinding(
        workspace_id=ws_id,
        repository_id=repo_id,
        scan_id=scan_id,
        scanner="semgrep",
        category="SAST",
        severity=FindingSeverity.MEDIUM,
        line_start=50,
        line_end=20,  # line_end < line_start!
        rule_id="TEST-RULE",
        title="Test",
        description="Test",
        fingerprint="bad_lines",
    )
    test_session.add(f_bad_lines)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_secureflow_scan_events_audit_log(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Test scan lifecycle event logging for complete immutable audit trails."""
    workspace = seed_data["workspace"]
    repo = seed_data["repository"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo, Repository)

    scan = SecureFlowScan(
        workspace_id=workspace.id,
        repository_id=repo.id,
        scan_type="FULL",
        status=SecureFlowScanStatus.RUNNING,
    )
    test_session.add(scan)
    await test_session.commit()

    e1 = SecureFlowScanEvent(
        scan_id=scan.id,
        event_type=ScanEventType.SCAN_STARTED,
        message="Full security scan initialized for commit sha cccc...",
        details={"branch": "main", "scanners": ["pip-audit", "secret-scanner"]},
    )
    e2 = SecureFlowScanEvent(
        scan_id=scan.id,
        event_type=ScanEventType.FINDINGS_RECORDED,
        message="Recorded 2 critical findings from pip-audit",
        details={"scanner": "pip-audit", "new_findings": 2},
    )
    test_session.add_all([e1, e2])
    await test_session.commit()

    await test_session.refresh(scan)
    assert len(scan.events) == 2
    assert scan.events[0].event_type == "SCAN_STARTED"
    assert scan.events[1].event_type == "FINDINGS_RECORDED"
    assert scan.events[1].details == {"scanner": "pip-audit", "new_findings": 2}


@pytest.mark.asyncio
async def test_devpilot_task_deletion_preserves_finding(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Test that deleting a DevPilotTask sets devpilot_task_id to NULL without deleting the finding."""
    workspace = seed_data["workspace"]
    repo = seed_data["repository"]
    devpilot_task = seed_data["devpilot_task"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo, Repository)
    assert isinstance(devpilot_task, DevPilotTask)

    scan = SecureFlowScan(
        workspace_id=workspace.id,
        repository_id=repo.id,
        scan_type="SAST",
    )
    test_session.add(scan)
    await test_session.commit()

    finding = SecureFlowFinding(
        workspace_id=workspace.id,
        repository_id=repo.id,
        scan_id=scan.id,
        scanner="semgrep",
        category="SAST",
        severity=FindingSeverity.HIGH,
        rule_id="SQLI-001",
        title="Potential SQL Injection",
        description="Unparameterized string format in query builder",
        devpilot_task_id=devpilot_task.id,
        fingerprint="sqli_fp_123",
    )
    test_session.add(finding)
    await test_session.commit()

    # Delete DevPilotTask
    await test_session.delete(devpilot_task)
    await test_session.commit()

    # Finding must remain intact with devpilot_task_id = NULL
    await test_session.refresh(finding)
    assert finding.id is not None
    assert finding.devpilot_task_id is None
    assert finding.title == "Potential SQL Injection"
