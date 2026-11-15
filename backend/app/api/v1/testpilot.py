from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    enforce_csrf_protection,
    get_current_user,
)
from app.api.v1.permissions import (
    require_workspace_admin,
    require_workspace_member,
    require_workspace_viewer,
)
from app.api.v1.schemas_agents import (
    CoverageReportListResponse,
    CoverageReportResponse,
    DetectedFrameworkResponse,
    DiagnosisResponse,
    ImpactTestSelectionResponse,
    IndividualTestResultResponse,
    TestCaseItem,
    TestExecutionResponse,
    TestPilotDetectRequest,
    TestPilotDiagnoseRequest,
    TestPilotExecuteSuiteRequest,
    TestPilotGenerateSuiteRequest,
    TestPilotImpactSelectionRequest,
    TestPilotRejectSuiteRequest,
    TestPilotSuiteListResponse,
    TestPilotSuiteResponse,
)
from app.db.base import WorkspaceRole, utc_now
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.testpilot import (
    TestPilotCoverageReport,
    TestPilotExecution,
    TestPilotResult,
    TestPilotSuite,
    TestSuiteStatus,
)
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.devpilot.workspace_manager import TaskWorkspaceManager
from app.services.testpilot.exceptions import (
    TestApprovalRequiredError,
    TestExecutionSecurityError,
    TestPilotError,
)
from app.services.testpilot.service import TestPilotService

testpilot_router = APIRouter(prefix="/repositories", tags=["testpilot"])
logger = logging.getLogger("orchestrix.api.testpilot")

_testpilot_service: TestPilotService | None = None


def get_testpilot_service() -> TestPilotService:
    global _testpilot_service
    if _testpilot_service is None:
        _testpilot_service = TestPilotService()
    return _testpilot_service


def _format_suite_response(suite: TestPilotSuite) -> TestPilotSuiteResponse:
    test_case_items = [
        TestCaseItem(
            id=c.id,
            name=c.name,
            description=c.description,
            test_type=c.test_type,
            target_symbol=c.target_symbol,
            code=c.code,
            is_edge_case=c.is_edge_case,
            relevance_explanation="",
        )
        for c in (suite.cases or [])
    ]
    return TestPilotSuiteResponse(
        id=suite.id,
        workspace_id=suite.workspace_id,
        repository_id=suite.repository_id,
        snapshot_id=suite.snapshot_id,
        framework=suite.framework,
        target_files=suite.target_files,
        test_type=suite.test_type,
        test_cases=test_case_items,
        status=suite.status,
        created_at=suite.created_at,
        approved_at=suite.approved_at,
        approved_by=suite.approved_by,
    )


def _format_execution_response(execution: TestPilotExecution) -> TestExecutionResponse:
    return TestExecutionResponse(
        id=execution.id,
        suite_id=execution.suite_id,
        workspace_id=execution.workspace_id,
        repository_id=execution.repository_id,
        command=execution.command,
        status=execution.status,
        exit_code=execution.exit_code,
        duration_ms=execution.duration_ms,
        passed_count=execution.passed_count,
        failed_count=execution.failed_count,
        skipped_count=execution.skipped_count,
        error_message=execution.error_message,
        stdout=execution.stdout,
        stderr=execution.stderr,
        executed_at=execution.executed_at,
        created_at=execution.created_at,
    )


def _format_coverage_response(report: TestPilotCoverageReport) -> CoverageReportResponse:
    return CoverageReportResponse(
        id=report.id,
        workspace_id=report.workspace_id,
        repository_id=report.repository_id,
        execution_id=report.execution_id,
        line_coverage_pct=report.line_coverage_pct,
        branch_coverage_pct=report.branch_coverage_pct,
        uncovered_files=report.uncovered_files,
        uncovered_functions=report.uncovered_functions,
        raw_report=report.raw_report,
        created_at=report.created_at,
    )


# -----------------------------------------------------------------------------
# 1. Detect Framework (VIEWER)
# -----------------------------------------------------------------------------


@testpilot_router.post(
    "/{repository_id}/testpilot/detect",
    response_model=DetectedFrameworkResponse,
    status_code=status.HTTP_200_OK,
    summary="Detect test framework for repository",
)
async def detect_test_framework(
    repository_id: uuid.UUID,
    payload: TestPilotDetectRequest | None = None,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    service: TestPilotService = Depends(get_testpilot_service),
) -> DetectedFrameworkResponse:
    repo, workspace_id, _membership = auth_ctx
    wm = TaskWorkspaceManager()
    target_dir = wm.get_task_workspace_dir(repo.id)
    if payload and payload.subpath:
        clean_sub = payload.subpath.replace("\\", "/").strip().lstrip("/")
        if ".." in clean_sub.split("/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Path traversal detected in subpath",
            )
        target_dir = os.path.join(target_dir, clean_sub)

    detected = service.detect_framework(target_dir)
    return DetectedFrameworkResponse(
        language=detected.language,
        framework=detected.framework,
        config_file=detected.config_file,
        test_directory=detected.test_directory,
        naming_convention=detected.naming_convention,
        runner_command=detected.runner_command,
        is_available=detected.is_available,
        confidence=detected.confidence,
        missing_requirements=detected.missing_requirements,
    )


# -----------------------------------------------------------------------------
# 2. Generate Proposed Test Suite (MEMBER)
# -----------------------------------------------------------------------------


@testpilot_router.post(
    "/{repository_id}/testpilot/suites",
    response_model=TestPilotSuiteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a proposed test suite (requires approval before execution)",
)
async def generate_test_suite(
    repository_id: uuid.UUID,
    payload: TestPilotGenerateSuiteRequest,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_member),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
    service: TestPilotService = Depends(get_testpilot_service),
) -> TestPilotSuiteResponse:
    repo, workspace_id, _membership = auth_ctx
    try:
        suite = await service.generate_test_suite(
            db=db,
            workspace_id=workspace_id,
            repository_id=repo.id,
            framework=payload.framework.value,
            target_files=payload.target_files,
            source_context=payload.source_context,
            test_type=payload.test_type.value,
            snapshot_id=payload.snapshot_id,
            symbols_info=payload.symbols_info,
        )
        return _format_suite_response(suite)
    except TestPilotError as e:
        logger.warning(f"TestPilot generation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.exception(f"Unexpected error generating suite: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate test suite",
        ) from e


# -----------------------------------------------------------------------------
# 3. List Test Suites (VIEWER)
# -----------------------------------------------------------------------------


@testpilot_router.get(
    "/{repository_id}/testpilot/suites",
    response_model=TestPilotSuiteListResponse,
    status_code=status.HTTP_200_OK,
    summary="List test suites for repository",
)
async def list_test_suites(
    repository_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    db: AsyncSession = Depends(get_db_session),
) -> TestPilotSuiteListResponse:
    repo, workspace_id, _membership = auth_ctx
    stmt = select(TestPilotSuite).where(
        TestPilotSuite.workspace_id == workspace_id,
        TestPilotSuite.repository_id == repo.id,
    )
    if status_filter:
        stmt = stmt.where(TestPilotSuite.status == status_filter)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(desc(TestPilotSuite.created_at)).offset(offset).limit(limit)
    res = await db.execute(stmt)
    suites = res.scalars().all()

    return TestPilotSuiteListResponse(
        items=[_format_suite_response(s) for s in suites],
        total=total,
        limit=limit,
        offset=offset,
    )


# -----------------------------------------------------------------------------
# 4. Retrieve Test Suite Details (VIEWER)
# -----------------------------------------------------------------------------


@testpilot_router.get(
    "/{repository_id}/testpilot/suites/{suite_id}",
    response_model=TestPilotSuiteResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve details of a specific test suite",
)
async def get_test_suite(
    repository_id: uuid.UUID,
    suite_id: uuid.UUID,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    db: AsyncSession = Depends(get_db_session),
) -> TestPilotSuiteResponse:
    repo, workspace_id, _membership = auth_ctx
    stmt = select(TestPilotSuite).where(
        TestPilotSuite.id == suite_id,
        TestPilotSuite.workspace_id == workspace_id,
        TestPilotSuite.repository_id == repo.id,
    )
    suite = (await db.execute(stmt)).scalar_one_or_none()
    if not suite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test suite {suite_id} not found",
        )
    return _format_suite_response(suite)


# -----------------------------------------------------------------------------
# 5. Approve Test Suite (ADMIN or OWNER)
# -----------------------------------------------------------------------------


@testpilot_router.post(
    "/{repository_id}/testpilot/suites/{suite_id}/approve",
    response_model=TestPilotSuiteResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve a generated test suite for execution (Admin/Owner only)",
)
async def approve_test_suite(
    repository_id: uuid.UUID,
    suite_id: uuid.UUID,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_admin),
    _csrf: None = Depends(enforce_csrf_protection),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    service: TestPilotService = Depends(get_testpilot_service),
) -> TestPilotSuiteResponse:
    repo, workspace_id, _membership = auth_ctx
    try:
        suite = await service.approve_test_suite(
            db=db,
            workspace_id=workspace_id,
            repository_id=repo.id,
            suite_id=suite_id,
            approved_by_user_id=current_user.id,
        )
        return _format_suite_response(suite)
    except TestPilotError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


# -----------------------------------------------------------------------------
# 6. Reject Test Suite (ADMIN or OWNER)
# -----------------------------------------------------------------------------


@testpilot_router.post(
    "/{repository_id}/testpilot/suites/{suite_id}/reject",
    response_model=TestPilotSuiteResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject a proposed test suite (Admin/Owner only)",
)
async def reject_test_suite(
    repository_id: uuid.UUID,
    suite_id: uuid.UUID,
    payload: TestPilotRejectSuiteRequest | None = None,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_admin),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
) -> TestPilotSuiteResponse:
    repo, workspace_id, _membership = auth_ctx
    stmt = select(TestPilotSuite).where(
        TestPilotSuite.id == suite_id,
        TestPilotSuite.workspace_id == workspace_id,
        TestPilotSuite.repository_id == repo.id,
    )
    suite = (await db.execute(stmt)).scalar_one_or_none()
    if not suite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test suite {suite_id} not found",
        )

    suite.status = TestSuiteStatus.REJECTED
    await db.commit()
    await db.refresh(suite)
    return _format_suite_response(suite)


# -----------------------------------------------------------------------------
# 7. Execute Approved Test Suite (MEMBER)
# -----------------------------------------------------------------------------


@testpilot_router.post(
    "/{repository_id}/testpilot/suites/{suite_id}/execute",
    response_model=TestExecutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute an approved test suite in an isolated workspace",
)
async def execute_test_suite(
    repository_id: uuid.UUID,
    suite_id: uuid.UUID,
    payload: TestPilotExecuteSuiteRequest,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_member),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
    service: TestPilotService = Depends(get_testpilot_service),
) -> TestExecutionResponse:
    repo, workspace_id, _membership = auth_ctx
    try:
        summary = await service.execute_suite(
            db=db,
            workspace_id=workspace_id,
            repository_id=repo.id,
            suite_id=suite_id,
            custom_command=payload.custom_command,
            timeout_seconds=payload.timeout_seconds,
        )
        stmt = select(TestPilotExecution).where(TestPilotExecution.id == summary.execution_id)
        execution = (await db.execute(stmt)).scalar_one()
        return _format_execution_response(execution)
    except TestApprovalRequiredError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except TestExecutionSecurityError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except TestPilotError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.exception(f"Unexpected error executing test suite: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Test execution encountered an internal error",
        ) from e


# -----------------------------------------------------------------------------
# 8. Retrieve Execution Details (VIEWER)
# -----------------------------------------------------------------------------


@testpilot_router.get(
    "/{repository_id}/testpilot/executions/{execution_id}",
    response_model=TestExecutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve status and summary of a test execution",
)
async def get_test_execution(
    repository_id: uuid.UUID,
    execution_id: uuid.UUID,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    db: AsyncSession = Depends(get_db_session),
) -> TestExecutionResponse:
    repo, workspace_id, _membership = auth_ctx
    stmt = select(TestPilotExecution).where(
        TestPilotExecution.id == execution_id,
        TestPilotExecution.workspace_id == workspace_id,
        TestPilotExecution.repository_id == repo.id,
    )
    execution = (await db.execute(stmt)).scalar_one_or_none()
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test execution {execution_id} not found",
        )
    return _format_execution_response(execution)


# -----------------------------------------------------------------------------
# 9. Retrieve Individual Test Results (VIEWER)
# -----------------------------------------------------------------------------


@testpilot_router.get(
    "/{repository_id}/testpilot/executions/{execution_id}/results",
    response_model=list[IndividualTestResultResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve individual test case results for an execution",
)
async def get_individual_test_results(
    repository_id: uuid.UUID,
    execution_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    db: AsyncSession = Depends(get_db_session),
) -> list[IndividualTestResultResponse]:
    repo, workspace_id, _membership = auth_ctx
    exec_stmt = select(TestPilotExecution).where(
        TestPilotExecution.id == execution_id,
        TestPilotExecution.workspace_id == workspace_id,
        TestPilotExecution.repository_id == repo.id,
    )
    execution = (await db.execute(exec_stmt)).scalar_one_or_none()
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test execution {execution_id} not found",
        )

    stmt = select(TestPilotResult).where(TestPilotResult.execution_id == execution_id)
    if status_filter:
        stmt = stmt.where(TestPilotResult.status == status_filter)
    stmt = stmt.order_by(TestPilotResult.id)
    res = await db.execute(stmt)
    results = res.scalars().all()

    return [
        IndividualTestResultResponse(
            id=r.id,
            execution_id=r.execution_id,
            test_name=r.test_name,
            status=r.status,
            duration_ms=r.duration_ms,
            failure_message=r.failure_message,
            traceback=r.traceback,
        )
        for r in results
    ]


# -----------------------------------------------------------------------------
# 10. Coverage Reports (VIEWER)
# -----------------------------------------------------------------------------


@testpilot_router.get(
    "/{repository_id}/testpilot/coverage",
    response_model=CoverageReportListResponse,
    status_code=status.HTTP_200_OK,
    summary="List coverage reports for repository",
)
async def list_coverage_reports(
    repository_id: uuid.UUID,
    execution_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    db: AsyncSession = Depends(get_db_session),
) -> CoverageReportListResponse:
    repo, workspace_id, _membership = auth_ctx
    stmt = select(TestPilotCoverageReport).where(
        TestPilotCoverageReport.workspace_id == workspace_id,
        TestPilotCoverageReport.repository_id == repo.id,
    )
    if execution_id:
        stmt = stmt.where(TestPilotCoverageReport.execution_id == execution_id)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(desc(TestPilotCoverageReport.created_at)).offset(offset).limit(limit)
    reports = (await db.execute(stmt)).scalars().all()

    return CoverageReportListResponse(
        items=[_format_coverage_response(r) for r in reports],
        total=total,
        limit=limit,
        offset=offset,
    )


# -----------------------------------------------------------------------------
# 11. Diagnose Test Failures (MEMBER)
# -----------------------------------------------------------------------------


@testpilot_router.post(
    "/{repository_id}/testpilot/executions/{execution_id}/diagnose",
    response_model=DiagnosisResponse,
    status_code=status.HTTP_200_OK,
    summary="Diagnose failure root causes using AI and stack trace analysis",
)
async def diagnose_test_failure(
    repository_id: uuid.UUID,
    execution_id: uuid.UUID,
    payload: TestPilotDiagnoseRequest | None = None,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_member),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
    service: TestPilotService = Depends(get_testpilot_service),
) -> DiagnosisResponse:
    repo, workspace_id, _membership = auth_ctx
    stmt = select(TestPilotExecution).where(
        TestPilotExecution.id == execution_id,
        TestPilotExecution.workspace_id == workspace_id,
        TestPilotExecution.repository_id == repo.id,
    )
    execution = (await db.execute(stmt)).scalar_one_or_none()
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test execution {execution_id} not found",
        )

    try:
        report = await service.diagnose_failure(
            db=db,
            execution_id=execution_id,
            source_context=payload.source_context if payload else None,
        )
        return DiagnosisResponse(
            failing_test=report.failing_test,
            error_message=report.error_message,
            traceback_parsed=report.traceback_parsed,
            root_cause_analysis=report.root_cause_analysis,
            fix_suggestions=report.fix_suggestions,
            affected_files=report.affected_files,
            confidence=report.confidence,
            target_symbol=report.target_symbol,
        )
    except TestPilotError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


# -----------------------------------------------------------------------------
# 12. Regression Test Selection via ImpactMind (VIEWER)
# -----------------------------------------------------------------------------


@testpilot_router.post(
    "/{repository_id}/testpilot/impact/select",
    response_model=ImpactTestSelectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Select targeted regression tests for git diff via ImpactMind",
)
async def select_regression_tests(
    repository_id: uuid.UUID,
    payload: TestPilotImpactSelectionRequest,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    service: TestPilotService = Depends(get_testpilot_service),
) -> ImpactTestSelectionResponse:
    repo, workspace_id, _membership = auth_ctx
    try:
        res = await service.select_impacted_tests(
            diff_text=payload.diff_text,
            all_test_files=payload.all_test_files,
        )
        return ImpactTestSelectionResponse(
            selected_tests=res.selected_tests,
            impacted_symbols=res.impacted_symbols,
            risk_exposure_score=res.risk_exposure_score,
            change_summary=res.change_summary,
            rationale=res.rationale,
        )
    except Exception as e:
        logger.exception(f"Error selecting regression tests: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to analyze diff impact: {e}",
        ) from e


# -----------------------------------------------------------------------------
# 13. Cancel Execution (MEMBER; Owner/Admin or Initiator)
# -----------------------------------------------------------------------------


@testpilot_router.post(
    "/{repository_id}/testpilot/executions/{execution_id}/cancel",
    response_model=TestExecutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a running or pending test execution",
)
async def cancel_test_execution(
    repository_id: uuid.UUID,
    execution_id: uuid.UUID,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_member),
    _csrf: None = Depends(enforce_csrf_protection),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TestExecutionResponse:
    repo, workspace_id, membership = auth_ctx
    stmt = select(TestPilotExecution).where(
        TestPilotExecution.id == execution_id,
        TestPilotExecution.workspace_id == workspace_id,
        TestPilotExecution.repository_id == repo.id,
    )
    execution = (await db.execute(stmt)).scalar_one_or_none()
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test execution {execution_id} not found",
        )

    # Resource ownership check: If not Admin or Owner, member must be suite creator / approver if available
    is_admin = membership.role in (WorkspaceRole.ADMIN, WorkspaceRole.OWNER)
    if not is_admin and execution.suite and execution.suite.approved_by:
        # A standard member can only cancel executions on suites they approved/manage
        if execution.suite.approved_by != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Only workspace admins or the suite approver can cancel this execution",
            )

    if execution.status in {"PASSED", "FAILED", "ERROR", "TIMED_OUT", "CANCELLED", "BLOCKED"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Execution {execution_id} is already in terminal state '{execution.status}'",
        )

    execution.status = "CANCELLED"
    execution.executed_at = utc_now()
    execution.stderr = (execution.stderr or "") + "\nExecution cancelled by user."
    await db.commit()
    await db.refresh(execution)
    return _format_execution_response(execution)
