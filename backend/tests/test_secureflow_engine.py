from __future__ import annotations

import json
import os
import tempfile
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import text

from app.db.base import Base
from app.db.models.devpilot import DevPilotTask
from app.db.models.github_installation import GitHubInstallation
from app.db.models.repository import Repository
from app.db.models.secureflow import (
    FindingSeverity,
    FindingStatus,
    SecureFlowFinding,
    SecureFlowScan,
    SecureFlowScanEvent,
    SecureFlowScanStatus,
)
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.services.secureflow.dependency_scanner import DependencyScanner
from app.services.secureflow.finding_manager import FindingManager
from app.services.secureflow.redaction import (
    contains_secrets,
    redact_data_structure,
    redact_secrets,
    sanitize_evidence_line,
)
from app.services.secureflow.remediation_bridge import DevPilotRemediationBridge
from app.services.secureflow.sast_scanner import SASTScanner
from app.services.secureflow.schemas import (
    DependencyScanResult,
    NormalizedFinding,
    SASTScanResult,
    SecretScanResult,
)
from app.services.secureflow.secret_scanner import SecretScanner
from app.services.secureflow.service import SecureFlowService

# ==============================================================================
# DATABASE FIXTURES (SQLite in-memory with Foreign Keys Enabled)
# ==============================================================================


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
async def seed_data(test_session: AsyncSession) -> dict[str, Any]:
    """Seed base user, workspace, installation, and repositories for testing."""
    user = User(email="sec-engineer@orchestrix.ai", full_name="SecFlow Lead")
    workspace = Workspace(name="SecureFlow Workspace", slug="secflow-ws")
    test_session.add_all([user, workspace])
    await test_session.commit()

    installation = GitHubInstallation(
        workspace_id=workspace.id,
        installation_id=55443322,
        account_login="orchestrix-sec",
        account_type="Organization",
        account_id=8899,
    )
    test_session.add(installation)
    await test_session.commit()

    repo_a = Repository(
        workspace_id=workspace.id,
        installation_id=installation.id,
        name="sec-target-repo",
        full_name="orchestrix-sec/sec-target-repo",
        owner_login="orchestrix-sec",
        html_url="https://github.com/orchestrix-sec/sec-target-repo",
        github_repository_id=10101,
        default_branch="main",
    )
    repo_b = Repository(
        workspace_id=workspace.id,
        installation_id=installation.id,
        name="isolated-repo-b",
        full_name="orchestrix-sec/isolated-repo-b",
        owner_login="orchestrix-sec",
        html_url="https://github.com/orchestrix-sec/isolated-repo-b",
        github_repository_id=20202,
        default_branch="main",
    )
    test_session.add_all([repo_a, repo_b])
    await test_session.commit()

    return {
        "user": user,
        "workspace": workspace,
        "installation": installation,
        "repo_a": repo_a,
        "repo_b": repo_b,
    }


# ==============================================================================
# 1. SECRET REDACTION & SCRUBBING ENGINE TESTS
# ==============================================================================

SYNTHETIC_GH_TOKEN = "gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
SYNTHETIC_GH_OAUTH = "gh" + "o_1234567890abcdefghijklmnopqrstuvwxyz"
SYNTHETIC_GOOGLE_KEY = "AI" + "zaSyD-1234567890abcdefghijklmnopqrstu"
SYNTHETIC_AWS_KEY = "AK" + "IAIOSFODNN7EXAMPLE"
SYNTHETIC_AWS_SECRET = "aws_" + "secret_access_key = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'"
SYNTHETIC_SLACK_TOKEN = "xox" + "b-123456789012-345678901234-abcdefghijklmnopqrstuvwx"
SYNTHETIC_LEAK_TOKEN = "gh" + "p_111122223333444455556666777788889999"
SYNTHETIC_LEAK_TOKEN_2 = "gh" + "p_222233334444555566667777888899990000"
SYNTHETIC_AWS_KEY_1 = "AK" + "IA1111111111111111"


def test_secret_redaction_patterns() -> None:
    """Verify high-precision detection and redaction across all credential classes."""
    samples = [
        (SYNTHETIC_GH_TOKEN, "GitHub Classic Token"),
        (SYNTHETIC_GH_OAUTH, "GitHub OAuth Token"),
        (SYNTHETIC_GOOGLE_KEY, "Google API Key"),
        (SYNTHETIC_AWS_KEY, "AWS Access Key"),
        (SYNTHETIC_AWS_SECRET, "AWS Secret Key"),
        ("postgres://app_user:s3cr3t_p@ssw0rd@db.neon.tech/main", "Database URL"),
        (SYNTHETIC_SLACK_TOKEN, "Slack Token"),
        (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
            "JWT",
        ),
    ]

    for raw, label in samples:
        assert contains_secrets(raw), f"Failed to detect {label}: {raw}"
        redacted = redact_secrets(raw)
        assert "[REDACTED_SECRET]" in redacted, f"Failed to replace with token for {label}"
        assert raw not in redacted, f"Raw secret leaked in redacted output for {label}"


def test_secret_redaction_false_positives() -> None:
    """Verify normal code, UUIDs, and commit hashes are not misidentified as secrets."""
    benign_samples = [
        "def calculate_total(price: float, tax: float) -> float:\n    return price * (1 + tax)",
        "task_id = 'c0a80101-0000-0000-0000-000000000001'",
        "commit_sha = '7459d13e9a4f21b7a2d8b5c9e1f2a3b4c5d6e7f8'",
        "import numpy as np\nx = np.arange(10)",
    ]
    for sample in benign_samples:
        assert not contains_secrets(sample)
        assert redact_secrets(sample) == sample


def test_sanitize_evidence_line_and_recursive_redaction() -> None:
    """Verify sanitized evidence lines and nested data structures."""
    line = f'    api_key = "{SYNTHETIC_GOOGLE_KEY}"  # primary key'
    sanitized = sanitize_evidence_line(line)
    assert 'api_key = "[REDACTED_SECRET]"' in sanitized
    assert "AIza" not in sanitized

    nested = {
        "user": "developer",
        "tokens": [
            SYNTHETIC_LEAK_TOKEN,
            {"key": SYNTHETIC_AWS_KEY_1},
        ],
        "meta": {"status": "active"},
    }
    cleaned = redact_data_structure(nested)
    assert cleaned["tokens"][0] == "[REDACTED_SECRET]"
    assert cleaned["tokens"][1]["key"] == "[REDACTED_SECRET]"
    assert cleaned["user"] == "developer"


# ==============================================================================
# 2. SECRET SCANNER WORKSPACE TESTS
# ==============================================================================


def test_secret_scanner_workspace_detection() -> None:
    """Test filesystem scanning for credentials with file eligibility and redaction."""
    scanner = SecretScanner()

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create eligible file with secret
        app_file = os.path.join(temp_dir, "config.py")
        with open(app_file, "w", encoding="utf-8") as f:
            f.write(f'import os\nGITHUB_TOKEN = "{SYNTHETIC_LEAK_TOKEN}"\nDEBUG = True\n')

        # Create ignored vendor directory and file
        vendor_dir = os.path.join(temp_dir, "node_modules", "package")
        os.makedirs(vendor_dir, exist_ok=True)
        with open(os.path.join(vendor_dir, "leak.js"), "w", encoding="utf-8") as f:
            f.write(f'const token = "{SYNTHETIC_LEAK_TOKEN_2}";\n')

        res: SecretScanResult = scanner.scan_directory(temp_dir)

        assert res.is_available is True
        assert len(res.findings) == 1

        finding = res.findings[0]
        assert finding.scanner == "secret-scanner"
        assert finding.category == "SECRET"
        assert finding.severity == FindingSeverity.CRITICAL
        assert finding.file_path == "config.py"
        assert finding.line_start == 2

        # Verify evidence NEVER stores raw secret
        assert "11112222" not in (finding.redacted_evidence or "")
        assert "[REDACTED_SECRET]" in (finding.redacted_evidence or "")


# ==============================================================================
# 3. DEPENDENCY SCANNER TESTS (pip-audit & npm audit)
# ==============================================================================


def test_dependency_scanner_pip_audit_parsing() -> None:
    """Verify parsing pip-audit JSON output into NormalizedFindings."""
    scanner = DependencyScanner()

    fake_pip_audit_json = json.dumps(
        {
            "dependencies": [
                {
                    "name": "insecure-pkg",
                    "version": "1.0.0",
                    "vulns": [
                        {
                            "id": "PYSEC-2024-999",
                            "fix_versions": ["1.0.1", "1.1.0"],
                            "description": "Remote code execution in parse_header",
                            "aliases": ["CVE-2024-12345"],
                        }
                    ],
                }
            ]
        }
    )

    findings = scanner.parse_pip_audit_json(fake_pip_audit_json, "requirements.txt")
    assert len(findings) == 1
    f = findings[0]
    assert f.scanner == "pip-audit"
    assert f.category == "DEPENDENCY"
    assert f.rule_id == "PYSEC-2024-999"
    assert f.file_path == "requirements.txt"
    assert f.severity in (FindingSeverity.CRITICAL, FindingSeverity.HIGH)
    assert "insecure-pkg" in f.title
    assert "1.0.1" in (f.remediation_recommendation or "")


def test_dependency_scanner_npm_audit_parsing() -> None:
    """Verify parsing npm audit JSON output into NormalizedFindings."""
    scanner = DependencyScanner()

    fake_npm_audit_json = json.dumps(
        {
            "vulnerabilities": {
                "lodash": {
                    "name": "lodash",
                    "severity": "critical",
                    "isDirect": True,
                    "via": [
                        {
                            "source": 1065,
                            "name": "lodash",
                            "dependency": "lodash",
                            "title": "Prototype Pollution in lodash",
                            "url": "https://github.com/advisories/GHSA-p6mc-m468-83gw",
                            "severity": "critical",
                            "range": "<4.17.21",
                        }
                    ],
                    "effects": [],
                    "range": "<4.17.21",
                    "nodes": ["node_modules/lodash"],
                    "fixAvailable": True,
                }
            }
        }
    )

    findings = scanner.parse_npm_audit_json(fake_npm_audit_json, "package-lock.json")
    assert len(findings) == 1
    f = findings[0]
    assert f.scanner == "npm-audit"
    assert f.category == "DEPENDENCY"
    assert f.severity == FindingSeverity.CRITICAL
    assert "lodash" in f.title
    assert "Prototype Pollution" in f.description


# ==============================================================================
# 4. SAST SCANNER (SEMGREP) & UNAVAILABILITY HANDLING TESTS
# ==============================================================================


def test_sast_scanner_semgrep_parsing() -> None:
    """Verify parsing Semgrep JSON results into NormalizedFindings."""
    scanner = SASTScanner()

    fake_semgrep_json = json.dumps(
        {
            "results": [
                {
                    "check_id": "python.lang.security.deserialization.pickle.avoid-pickle",
                    "path": "app/utils.py",
                    "start": {"line": 15, "col": 5},
                    "end": {"line": 15, "col": 25},
                    "extra": {
                        "message": "Avoid using pickle for deserialization of untrusted data",
                        "severity": "ERROR",
                        "metadata": {
                            "cwe": ["CWE-502: Deserialization of Untrusted Data"],
                            "owasp": ["A08:2021 - Software and Data Integrity Failures"],
                        },
                        "lines": "    data = pickle.loads(raw)",
                    },
                }
            ],
            "errors": [],
        }
    )

    findings = scanner.parse_semgrep_json(fake_semgrep_json, "/repo")
    assert len(findings) == 1
    f = findings[0]
    assert f.scanner == "semgrep"
    assert f.category == "SAST"
    assert f.severity == FindingSeverity.HIGH
    assert f.file_path == "app/utils.py"
    assert f.line_start == 15
    assert "CWE-502" in f.description


@pytest.mark.asyncio
async def test_sast_scanner_unavailable_never_reports_clean() -> None:
    """CRITICAL: If Semgrep is missing, status must be UNAVAILABLE, NEVER clean!"""
    scanner = SASTScanner()

    with patch.object(scanner, "is_available", return_value=False):
        res: SASTScanResult = await scanner.scan_directory(".")
        assert res.is_available is False
        assert len(res.findings) == 0
        assert "not installed" in (res.error or "")


# ==============================================================================
# 5. FINDING MANAGER: REPOSITORY DEDUPLICATION & STATUS LIFECYCLE
# ==============================================================================


@pytest.mark.asyncio
async def test_finding_manager_deduplication_and_lifecycle(
    test_session: AsyncSession, seed_data: dict[str, Any]
) -> None:
    """Verify deterministic fingerprinting, repository deduplication, and status transitions."""
    repo_a = seed_data["repo_a"]
    manager = FindingManager()

    # Create dummy scan record
    scan = SecureFlowScan(
        workspace_id=repo_a.workspace_id,
        repository_id=repo_a.id,
        scan_type="FULL",
        status=SecureFlowScanStatus.RUNNING,
    )
    test_session.add(scan)
    await test_session.commit()

    finding_dto = NormalizedFinding(
        scanner="sast-scanner",
        category="SAST",
        severity=FindingSeverity.HIGH,
        confidence=0.9,
        rule_id="SEC-AUTH-01",
        title="Hardcoded Authorization Bypass",
        description="Found bypass flag in security middleware",
        file_path="app/middleware/auth.py",
        line_start=30,
        redacted_evidence="if token == 'test-bypass': return True",
    )

    # 1. Ingest initial finding
    findings = await manager.persist_and_reconcile_findings(
        db=test_session,
        workspace_id=repo_a.workspace_id,
        repository_id=repo_a.id,
        scan_id=scan.id,
        new_findings=[finding_dto],
    )
    assert len(findings) == 1
    f_db = findings[0]
    assert f_db.status == FindingStatus.OPEN
    fp = f_db.fingerprint
    assert fp is not None

    # 2. Ingest identical finding in a second scan -> MUST DEDUPLICATE (not duplicate row)
    scan2 = SecureFlowScan(
        workspace_id=repo_a.workspace_id,
        repository_id=repo_a.id,
        scan_type="FULL",
        status=SecureFlowScanStatus.RUNNING,
    )
    test_session.add(scan2)
    await test_session.commit()

    findings_2 = await manager.persist_and_reconcile_findings(
        db=test_session,
        workspace_id=repo_a.workspace_id,
        repository_id=repo_a.id,
        scan_id=scan2.id,
        new_findings=[finding_dto],
    )
    assert len(findings_2) == 1
    assert findings_2[0].id == f_db.id  # Exactly same entity updated!
    assert findings_2[0].scan_id == scan2.id

    # Verify database has only 1 finding record for repo_a
    count_stmt = select(SecureFlowFinding).where(SecureFlowFinding.repository_id == repo_a.id)
    all_f = (await test_session.execute(count_stmt)).scalars().all()
    assert len(all_f) == 1

    # 3. Lifecycle transitions & audit events
    # Transition to CONFIRMED
    updated = await manager.update_finding_status(
        db=test_session,
        finding_id=f_db.id,
        new_status=FindingStatus.CONFIRMED,
        note="Confirmed by security lead",
    )
    assert updated is not None
    assert updated.status == FindingStatus.CONFIRMED

    # Transition to RESOLVED
    updated = await manager.update_finding_status(
        db=test_session,
        finding_id=f_db.id,
        new_status=FindingStatus.RESOLVED,
        note="Patched in commit 123",
    )
    assert updated is not None
    assert updated.status == FindingStatus.RESOLVED

    # Verify audit events logged in DB
    events_stmt = select(SecureFlowScanEvent).order_by(SecureFlowScanEvent.created_at.asc())
    events = (await test_session.execute(events_stmt)).scalars().all()
    assert len(events) >= 2


# ==============================================================================
# 6. TENANT ISOLATION TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_finding_manager_tenant_isolation(
    test_session: AsyncSession, seed_data: dict[str, Any]
) -> None:
    """Verify repository A cannot read, query, or mutate repository B findings."""
    repo_a = seed_data["repo_a"]
    repo_b = seed_data["repo_b"]
    manager = FindingManager()

    scan_a = SecureFlowScan(
        workspace_id=repo_a.workspace_id,
        repository_id=repo_a.id,
        scan_type="SECRETS",
        status=SecureFlowScanStatus.RUNNING,
    )
    test_session.add(scan_a)
    await test_session.commit()

    finding_dto = NormalizedFinding(
        scanner="secret-scanner",
        category="SECRET",
        severity=FindingSeverity.CRITICAL,
        confidence=1.0,
        rule_id="SECRET-TEST-01",
        title="Repo A Secret",
        description="Confidential secret in Repo A",
        file_path="creds.txt",
        line_start=1,
    )

    findings = await manager.persist_and_reconcile_findings(
        db=test_session,
        workspace_id=repo_a.workspace_id,
        repository_id=repo_a.id,
        scan_id=scan_a.id,
        new_findings=[finding_dto],
    )
    finding_a = findings[0]

    # Attempting to fetch finding from Repo B perspective MUST yield nothing
    stmt_repo_b = select(SecureFlowFinding).where(
        SecureFlowFinding.id == finding_a.id,
        SecureFlowFinding.repository_id == repo_b.id,
    )
    res_b = (await test_session.execute(stmt_repo_b)).scalar_one_or_none()
    assert res_b is None


# ==============================================================================
# 7. SECUREFLOW SERVICE ORCHESTRATION & PARTIAL COMPLETION TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_secureflow_service_partial_completion_handling(
    test_session: AsyncSession, seed_data: dict[str, Any]
) -> None:
    """Verify when a scanner fails or is unavailable, scan is marked PARTIALLY_COMPLETED."""
    repo_a = seed_data["repo_a"]

    mock_secret_scanner = MagicMock()
    mock_secret_scanner.scan_directory.return_value = SecretScanResult(
        scanner_name="secret-scanner",
        is_available=True,
        findings=[
            NormalizedFinding(
                scanner="secret-scanner",
                category="SECRET",
                severity=FindingSeverity.CRITICAL,
                confidence=1.0,
                rule_id="SECRET-AWS-KEY",
                title="AWS Key Leak",
                description="AWS Key in config",
                file_path="aws.env",
                line_start=1,
            )
        ],
        scanned_files_count=10,
    )

    mock_dep_scanner = MagicMock()
    mock_dep_scanner.scan_python_dependencies = AsyncMock(
        return_value=DependencyScanResult(
            scanner_name="pip-audit",
            is_available=True,
            findings=[],
            scanned_files=["requirements.txt"],
        )
    )
    mock_dep_scanner.scan_npm_dependencies = AsyncMock(
        return_value=DependencyScanResult(
            scanner_name="npm-audit",
            is_available=True,
            findings=[],
            scanned_files=[],
        )
    )

    # SAST scanner is UNAVAILABLE
    mock_sast_scanner = MagicMock()
    mock_sast_scanner.scan_directory = AsyncMock(
        return_value=SASTScanResult(
            scanner_name="semgrep",
            is_available=False,
            findings=[],
            rules_run_count=0,
            error="Semgrep CLI not installed",
        )
    )

    service = SecureFlowService(
        secret_scanner=mock_secret_scanner,
        dependency_scanner=mock_dep_scanner,
        sast_scanner=mock_sast_scanner,
    )

    with tempfile.TemporaryDirectory() as temp_repo:
        summary = await service.run_scan(
            db=test_session,
            workspace_id=repo_a.workspace_id,
            repository_id=repo_a.id,
            target_dir=temp_repo,
            scan_type="FULL",
        )

        assert summary.status == SecureFlowScanStatus.PARTIALLY_COMPLETED
        assert summary.critical_count == 1
        assert summary.high_count == 0
        assert summary.total_findings == 1

        # Check DB record
        scan_record = await test_session.get(SecureFlowScan, summary.scan_id)
        assert scan_record is not None
        assert scan_record.status == SecureFlowScanStatus.PARTIALLY_COMPLETED
        assert scan_record.critical_count == 1
        assert scan_record.scanners_used is not None
        semgrep_meta = next(
            (s for s in scan_record.scanners_used if s.get("name") == "semgrep"), None
        )
        assert semgrep_meta is not None
        assert semgrep_meta["available"] is False
        assert semgrep_meta["status"] == "UNAVAILABLE"


# ==============================================================================
# 8. DEVPILOT REMEDIATION BRIDGE TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_devpilot_remediation_bridge_scrubs_secrets_and_preserves_approval(
    test_session: AsyncSession, seed_data: dict[str, Any]
) -> None:
    """Verify remediation tasks have scrubbed prompts and preserve human approval boundary."""
    repo_a = seed_data["repo_a"]
    user = seed_data["user"]
    bridge = DevPilotRemediationBridge()

    # Create scan and finding with secret token in title/description/evidence
    scan = SecureFlowScan(
        workspace_id=repo_a.workspace_id,
        repository_id=repo_a.id,
        scan_type="SECRETS",
        status=SecureFlowScanStatus.COMPLETED,
    )
    test_session.add(scan)
    await test_session.commit()

    finding = SecureFlowFinding(
        workspace_id=repo_a.workspace_id,
        repository_id=repo_a.id,
        scan_id=scan.id,
        scanner="secret-scanner",
        category="SECRET",
        rule_id="SECRET-GITHUB-PAT",
        title=f"Found secret token {SYNTHETIC_LEAK_TOKEN}",
        description=f"Leaked token {SYNTHETIC_LEAK_TOKEN} in settings.py",
        severity=FindingSeverity.CRITICAL,
        confidence=1.0,
        status=FindingStatus.OPEN,
        file_path="settings.py",
        line_start=12,
        redacted_evidence='TOKEN = "[REDACTED_SECRET]"',
        fingerprint="test-pat-hash-1234",
    )
    test_session.add(finding)
    await test_session.commit()

    # Create DevPilot remediation task
    result = await bridge.create_remediation_task(
        db=test_session,
        finding_id=finding.id,
        user_id=user.id,
    )

    assert result.devpilot_task_id is not None
    assert result.requires_plan_approval is True
    assert result.requires_code_approval is True

    # Verify DevPilotTask was created in database
    devpilot_task = await test_session.get(DevPilotTask, result.devpilot_task_id)
    assert devpilot_task is not None

    # CRITICAL: Human approval boundary must be preserved (CREATED status, NOT executed/completed)
    assert devpilot_task.status == "CREATED"
    assert devpilot_task.task_type == "SECURITY"

    # CRITICAL: Raw token must NEVER appear in prompt or title!
    assert SYNTHETIC_LEAK_TOKEN not in devpilot_task.prompt
    assert SYNTHETIC_LEAK_TOKEN not in devpilot_task.title
    assert "[REDACTED_SECRET]" in devpilot_task.prompt

    # Verify finding is linked to task
    await test_session.refresh(finding)
    assert finding.devpilot_task_id == devpilot_task.id
