import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    GitHubInstallation,
    Repository,
    RepositorySnapshot,
    TestExecutionStatus,
    TestFramework,
    TestPilotCase,
    TestPilotCoverageReport,
    TestPilotExecution,
    TestPilotResult,
    TestPilotSuite,
    TestPilotTestType,
    TestResultOutcome,
    TestSuiteStatus,
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
    """Seed base user, workspace, installation, and repository entities."""
    user = User(
        email="qa-lead@orchestrix.ai",
        full_name="QA Lead",
    )
    workspace = Workspace(
        name="Test Engineering Workspace",
        slug="test-eng-ws",
    )
    test_session.add_all([user, workspace])
    await test_session.commit()

    installation = GitHubInstallation(
        workspace_id=workspace.id,
        installation_id=987654321,
        account_login="test-org",
        account_type="Organization",
        account_id=12345,
    )
    test_session.add(installation)
    await test_session.commit()

    repo = Repository(
        workspace_id=workspace.id,
        installation_id=installation.id,
        name="test-repo",
        full_name="test-org/test-repo",
        owner_login="test-org",
        html_url="https://github.com/test-org/test-repo",
        github_repository_id=12345678,
        default_branch="main",
    )
    test_session.add(repo)
    await test_session.commit()

    snapshot = RepositorySnapshot(
        workspace_id=workspace.id,
        repository_id=repo.id,
        commit_sha="a" * 40,
        branch="main",
    )
    test_session.add(snapshot)
    await test_session.commit()

    return {
        "user": user,
        "workspace": workspace,
        "installation": installation,
        "repository": repo,
        "snapshot": snapshot,
    }


@pytest.mark.asyncio
async def test_testpilot_suite_creation_and_fields(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Test creating a TestPilotSuite with full audit and snapshot metadata."""
    workspace = seed_data["workspace"]
    repo = seed_data["repository"]
    snapshot = seed_data["snapshot"]
    user = seed_data["user"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo, Repository)
    assert isinstance(snapshot, RepositorySnapshot)
    assert isinstance(user, User)

    suite = TestPilotSuite(
        workspace_id=workspace.id,
        repository_id=repo.id,
        snapshot_id=snapshot.id,
        framework=TestFramework.PYTEST,
        test_type=TestPilotTestType.UNIT,
        status=TestSuiteStatus.AWAITING_APPROVAL,
        target_files=["app/services/calculator.py", "app/utils/math.py"],
        approved_by=user.id,
        approved_at=datetime.now(UTC),
    )
    test_session.add(suite)
    await test_session.commit()
    await test_session.refresh(suite)

    assert isinstance(suite.id, uuid.UUID)
    assert suite.framework == "pytest"
    assert suite.test_type == "unit"
    assert suite.status == "awaiting_approval"
    assert suite.target_files == ["app/services/calculator.py", "app/utils/math.py"]
    assert suite.approved_by == user.id
    assert suite.approved_at is not None
    assert suite.created_at is not None


@pytest.mark.asyncio
async def test_testpilot_case_creation_and_cascade(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Test creating test cases and verifying cascade deletion when suite is removed."""
    workspace = seed_data["workspace"]
    repo = seed_data["repository"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo, Repository)

    suite = TestPilotSuite(
        workspace_id=workspace.id,
        repository_id=repo.id,
        framework=TestFramework.PYTEST,
        test_type=TestPilotTestType.REGRESSION,
        target_files=["app/auth.py"],
    )
    test_session.add(suite)
    await test_session.commit()

    case1 = TestPilotCase(
        suite_id=suite.id,
        name="test_valid_token_authentication",
        description="Verifies valid JWT returns 200 OK",
        test_type=TestPilotTestType.REGRESSION,
        target_symbol="authenticate_request",
        code="def test_valid_token():\n    assert authenticate_request('valid') is True",
        is_edge_case=False,
    )
    case2 = TestPilotCase(
        suite_id=suite.id,
        name="test_expired_token_handling",
        description="Verifies expired JWT throws 401 error",
        test_type=TestPilotTestType.EDGE_CASE,
        target_symbol="authenticate_request",
        code="def test_expired_token():\n    assert authenticate_request('expired') is False",
        is_edge_case=True,
    )
    test_session.add_all([case1, case2])
    await test_session.commit()

    await test_session.refresh(suite)
    assert len(suite.cases) == 2
    assert suite.cases[0].is_edge_case is False
    assert suite.cases[1].is_edge_case is True

    # Code is stored passively and not executed
    assert "assert authenticate_request" in suite.cases[0].code

    # Deleting the suite should cascade delete child cases
    await test_session.delete(suite)
    await test_session.commit()

    cases_count = await test_session.scalar(
        text("SELECT count(*) FROM testpilot_cases WHERE suite_id = :sid"),
        {"sid": str(suite.id)},
    )
    assert cases_count == 0


@pytest.mark.asyncio
async def test_testpilot_execution_and_result_lifecycle(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Test execution run lifecycle with granular results and nonnegative constraints."""
    workspace = seed_data["workspace"]
    repo = seed_data["repository"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo, Repository)

    execution = TestPilotExecution(
        workspace_id=workspace.id,
        repository_id=repo.id,
        command="pytest tests/unit -v --tb=short",
        status=TestExecutionStatus.RUNNING,
        duration_ms=1250,
        passed_count=5,
        failed_count=1,
        skipped_count=0,
        stdout="5 passed, 1 failed in 1.25s",
        stderr="",
        executed_at=datetime.now(UTC),
    )
    test_session.add(execution)
    await test_session.commit()

    res1 = TestPilotResult(
        execution_id=execution.id,
        test_name="tests.test_auth::test_login",
        status=TestResultOutcome.PASSED,
        duration_ms=150,
    )
    res2 = TestPilotResult(
        execution_id=execution.id,
        test_name="tests.test_auth::test_token_refresh",
        status=TestResultOutcome.FAILED,
        duration_ms=210,
        failure_message="AssertionError: 401 != 200",
        traceback="Traceback (most recent call last):\n  File ...",
    )
    test_session.add_all([res1, res2])
    await test_session.commit()

    await test_session.refresh(execution)
    assert len(execution.results) == 2
    results_by_name = {r.test_name: r for r in execution.results}
    assert results_by_name["tests.test_auth::test_login"].status == "PASSED"
    assert results_by_name["tests.test_auth::test_token_refresh"].status == "FAILED"
    assert "AssertionError" in (
        results_by_name["tests.test_auth::test_token_refresh"].failure_message or ""
    )

    # Update execution to finished state
    execution.status = TestExecutionStatus.FAILED
    execution.exit_code = 1
    await test_session.commit()
    await test_session.refresh(execution)
    assert execution.status == "FAILED"
    assert execution.exit_code == 1


@pytest.mark.asyncio
async def test_testpilot_execution_nonnegative_counts_constraint(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Test that negative durations and counts violate CheckConstraints."""
    workspace = seed_data["workspace"]
    repo = seed_data["repository"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo, Repository)

    invalid_exec = TestPilotExecution(
        workspace_id=workspace.id,
        repository_id=repo.id,
        command="pytest",
        duration_ms=-10,  # Negative duration
        passed_count=-1,
    )
    test_session.add(invalid_exec)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_testpilot_coverage_report_bounds_and_nullability(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Test line/branch coverage percentages enforce range [0.0, 100.0] and support null."""
    workspace = seed_data["workspace"]
    repo = seed_data["repository"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo, Repository)

    # Valid report with nullable percentages
    report_null = TestPilotCoverageReport(
        workspace_id=workspace.id,
        repository_id=repo.id,
        line_coverage_pct=None,
        branch_coverage_pct=None,
        uncovered_files=[],
        uncovered_functions=[],
    )
    test_session.add(report_null)
    await test_session.commit()
    await test_session.refresh(report_null)
    assert report_null.line_coverage_pct is None
    assert report_null.branch_coverage_pct is None

    # Valid report with accurate percentages
    report_valid = TestPilotCoverageReport(
        workspace_id=workspace.id,
        repository_id=repo.id,
        line_coverage_pct=84.5,
        branch_coverage_pct=72.0,
        uncovered_files=["app/legacy.py"],
        uncovered_functions=[{"file": "app/legacy.py", "function": "old_handler"}],
    )
    test_session.add(report_valid)
    await test_session.commit()
    await test_session.refresh(report_valid)
    assert report_valid.line_coverage_pct == 84.5
    assert report_valid.branch_coverage_pct == 72.0

    # Invalid report with > 100.0% coverage
    report_invalid = TestPilotCoverageReport(
        workspace_id=workspace.id,
        repository_id=repo.id,
        line_coverage_pct=105.0,  # Out of range!
    )
    test_session.add(report_invalid)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_historical_execution_preservation_on_suite_deletion(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Test that deleting a TestPilotSuite does NOT delete historical executions (ON DELETE SET NULL)."""
    workspace = seed_data["workspace"]
    repo = seed_data["repository"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo, Repository)

    suite = TestPilotSuite(
        workspace_id=workspace.id,
        repository_id=repo.id,
        framework=TestFramework.PYTEST,
        test_type=TestPilotTestType.UNIT,
    )
    test_session.add(suite)
    await test_session.commit()

    execution = TestPilotExecution(
        workspace_id=workspace.id,
        repository_id=repo.id,
        suite_id=suite.id,
        command="pytest tests/suite1",
        status=TestExecutionStatus.PASSED,
        duration_ms=450,
        passed_count=3,
    )
    test_session.add(execution)
    await test_session.commit()

    # Delete suite
    await test_session.delete(suite)
    await test_session.commit()

    # Execution remains intact with suite_id = NULL
    await test_session.refresh(execution)
    assert execution.id is not None
    assert execution.suite_id is None
    assert execution.status == "PASSED"
    assert execution.passed_count == 3
