from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    enforce_csrf_protection,
    get_current_user,
    require_workspace_membership,
)
from app.api.v1.schemas import (
    CancelTestsRequest,
    ChangeClassificationItem,
    ExposedFileSummaryItem,
    ImpactAnalyzeRequest,
    ImpactAssessmentListResponse,
    ImpactAssessmentResponse,
    ImpactedEntityItem,
    RiskAssessmentSummaryItem,
    RunTestsRequest,
    TestExecutionRunItem,
    TestRecommendationItem,
    WorkspaceRiskOverviewResponse,
)
from app.db.base import WorkspaceRole
from app.db.models.impactmind import ImpactAssessment
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.impactmind.engine import ImpactMindEngine

impact_router = APIRouter(prefix="/repositories", tags=["impactmind"])
risk_router = APIRouter(prefix="/risk", tags=["risk"])
logger = logging.getLogger("orchestrix.api.impactmind")

# Singleton engine instance
_impact_engine: ImpactMindEngine | None = None


def get_impact_engine() -> ImpactMindEngine:
    global _impact_engine
    if _impact_engine is None:
        _impact_engine = ImpactMindEngine()
    return _impact_engine


def _to_assessment_response(assessment: Any) -> ImpactAssessmentResponse:
    """Helper to convert ORM model to API response schema."""
    return ImpactAssessmentResponse(
        id=assessment.id,
        workspace_id=assessment.workspace_id,
        repository_id=assessment.repository_id,
        snapshot_id=assessment.snapshot_id,
        base_commit_sha=assessment.base_commit_sha,
        target_commit_sha=assessment.target_commit_sha,
        comparison_mode=assessment.comparison_mode,
        status=assessment.status,
        structural_exposure_score=assessment.structural_exposure_score,
        exposure_tier=assessment.exposure_tier,
        score_type="heuristic_structural_exposure",
        score_label="Blast Radius & Structural Exposure Score",
        change_summary=assessment.change_summary or {},
        reasons=assessment.reasons or [],
        recommended_actions=assessment.recommended_actions or [],
        error_message=assessment.error_message,
        classifications=[
            ChangeClassificationItem(
                id=c.id,
                file_path=c.file_path,
                symbol_name=c.symbol_name,
                symbol_id=c.symbol_id,
                category=c.category,
                is_breaking=c.is_breaking,
                breaking_reason=c.breaking_reason,
                confidence=c.confidence,
                evidence=c.evidence,
                status=c.status,
            )
            for c in (assessment.classifications or [])
        ],
        impacted_entities=[
            ImpactedEntityItem(
                id=e.id,
                entity_id=e.entity_id,
                name=e.name,
                label=e.label,
                file_path=e.file_path,
                impact_type=e.impact_type,
                depth=e.depth,
                relationship_type=e.relationship_type,
                confidence=e.confidence,
                evidence=e.evidence,
            )
            for e in (assessment.impacted_entities or [])
        ],
        test_recommendations=[
            TestRecommendationItem(
                id=t.id,
                test_file=t.test_file,
                test_name=t.test_name,
                test_framework=t.test_framework,
                priority=t.priority,
                reason=t.reason,
                related_symbol=t.related_symbol,
                evidence_source=t.evidence_source,
                confidence=t.confidence,
            )
            for t in (assessment.test_recommendations or [])
        ],
        test_executions=[
            TestExecutionRunItem(
                id=x.id,
                command=x.command,
                status=x.status,
                exit_code=x.exit_code,
                stdout=x.stdout,
                stderr=x.stderr,
                passed_count=x.passed_count,
                failed_count=x.failed_count,
                skipped_count=x.skipped_count,
                duration_ms=x.duration_ms,
                started_at=x.started_at,
                completed_at=x.completed_at,
            )
            for x in (assessment.test_executions or [])
        ],
        created_at=assessment.created_at,
        completed_at=assessment.completed_at,
    )


@impact_router.post(
    "/{repository_id}/impact/analyze",
    response_model=ImpactAssessmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze code changes and compute blast radius & regression test recommendations",
)
async def analyze_change_impact(
    repository_id: uuid.UUID,
    payload: ImpactAnalyzeRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
    engine: ImpactMindEngine = Depends(get_impact_engine),
) -> ImpactAssessmentResponse:
    """
    Run ImpactMind change analysis pipeline on a diff or commit range.
    Identifies affected symbols, classifies changes, determines downstream impact,
    computes structural exposure, and selects ranked regression tests.
    """
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace",
        )

    try:
        assessment = await engine.analyze_changes(
            db=db,
            workspace_id=workspace_id,
            repository_id=repository_id,
            diff_text=payload.diff_text,
            base_commit_sha=payload.base_commit_sha,
            target_commit_sha=payload.target_commit_sha,
            comparison_mode=payload.comparison_mode,
            user_id=current_user.id,
            snapshot_id=payload.snapshot_id,
            file_contents_before=payload.file_contents_before,
            file_contents_after=payload.file_contents_after,
        )
        return _to_assessment_response(assessment)
    except Exception as e:
        logger.exception(f"Error during ImpactMind change analysis: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ImpactMind analysis failed: {e}",
        ) from e


@impact_router.get(
    "/{repository_id}/impact/history",
    response_model=ImpactAssessmentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List historical impact assessments for a repository",
)
async def list_impact_history(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
    engine: ImpactMindEngine = Depends(get_impact_engine),
) -> ImpactAssessmentListResponse:
    """Fetch paginated history of impact assessments for the repository."""
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace",
        )

    assessments, total = await engine.list_assessments(
        db, workspace_id, repository_id, limit=limit, offset=offset
    )

    return ImpactAssessmentListResponse(
        assessments=[_to_assessment_response(a) for a in assessments],
        total=total,
        limit=limit,
        offset=offset,
    )


@impact_router.get(
    "/{repository_id}/impact/{assessment_id}",
    response_model=ImpactAssessmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get details of a change impact assessment report",
)
async def get_impact_assessment(
    repository_id: uuid.UUID,
    assessment_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
    engine: ImpactMindEngine = Depends(get_impact_engine),
) -> ImpactAssessmentResponse:
    """Retrieve detailed report of a previous ImpactMind assessment."""
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace",
        )

    assessment = await engine.get_assessment(db, workspace_id, assessment_id)
    if not assessment or assessment.repository_id != repository_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Impact assessment {assessment_id} not found",
        )

    return _to_assessment_response(assessment)


@impact_router.get(
    "/{repository_id}/impact/{assessment_id}/tests",
    response_model=list[TestRecommendationItem],
    status_code=status.HTTP_200_OK,
    summary="Get recommended regression tests for an assessment",
)
async def get_test_recommendations(
    repository_id: uuid.UUID,
    assessment_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
    engine: ImpactMindEngine = Depends(get_impact_engine),
) -> list[TestRecommendationItem]:
    """Retrieve ranked regression test cases recommended by ImpactMind."""
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace",
        )

    assessment = await engine.get_assessment(db, workspace_id, assessment_id)
    if not assessment or assessment.repository_id != repository_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Impact assessment {assessment_id} not found",
        )

    return [
        TestRecommendationItem(
            id=t.id,
            test_file=t.test_file,
            test_name=t.test_name,
            test_framework=t.test_framework,
            priority=t.priority,
            reason=t.reason,
            related_symbol=t.related_symbol,
            evidence_source=t.evidence_source,
            confidence=t.confidence,
        )
        for t in (assessment.test_recommendations or [])
    ]


@impact_router.post(
    "/{repository_id}/impact/{assessment_id}/tests/run",
    response_model=TestExecutionRunItem,
    status_code=status.HTTP_200_OK,
    summary="Execute approved regression tests in controlled environment",
)
async def run_regression_tests(
    repository_id: uuid.UUID,
    assessment_id: uuid.UUID,
    payload: RunTestsRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.ADMIN)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
    engine: ImpactMindEngine = Depends(get_impact_engine),
) -> TestExecutionRunItem:
    """
    Execute recommended or custom regression tests in a strictly controlled subprocess environment.
    Requires explicit user approval (run_approved=true) and ADMIN privileges.
    """
    if not payload.run_approved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Execution rejected: Explicit user approval (run_approved=True) is required.",
        )

    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace",
        )

    assessment = await engine.get_assessment(db, workspace_id, assessment_id)
    if not assessment or assessment.repository_id != repository_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Impact assessment {assessment_id} not found",
        )

    # Resolve working directory (fallback to default repo location or current workspace)
    working_dir = payload.working_dir or "."

    try:
        test_run = await engine.run_regression_tests(
            db=db,
            workspace_id=workspace_id,
            assessment_id=assessment_id,
            working_dir=working_dir,
            run_approved=payload.run_approved,
            custom_command=payload.custom_command,
            timeout_seconds=payload.timeout_seconds,
        )
        return TestExecutionRunItem(
            id=test_run.id,
            command=test_run.command,
            status=test_run.status,
            exit_code=test_run.exit_code,
            stdout=test_run.stdout,
            stderr=test_run.stderr,
            passed_count=test_run.passed_count,
            failed_count=test_run.failed_count,
            skipped_count=test_run.skipped_count,
            duration_ms=test_run.duration_ms,
            started_at=test_run.started_at,
            completed_at=test_run.completed_at,
        )
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe)) from pe
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve)) from ve
    except Exception as e:
        logger.exception(f"Error during controlled test execution: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Test execution failed: {e}",
        ) from e


@impact_router.get(
    "/{repository_id}/impact/{assessment_id}/tests/status",
    response_model=TestExecutionRunItem,
    status_code=status.HTTP_200_OK,
    summary="Check status of regression test execution",
)
async def get_test_execution_status(
    repository_id: uuid.UUID,
    assessment_id: uuid.UUID,
    execution_id: uuid.UUID | None = Query(default=None),
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
    engine: ImpactMindEngine = Depends(get_impact_engine),
) -> TestExecutionRunItem:
    """Retrieve status and metrics of a test execution run."""
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace",
        )

    assessment = await engine.get_assessment(db, workspace_id, assessment_id)
    if not assessment or assessment.repository_id != repository_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Impact assessment {assessment_id} not found",
        )

    if execution_id:
        test_run = await engine.get_execution(db, execution_id)
        if not test_run or test_run.assessment_id != assessment_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Execution run {execution_id} not found",
            )
    else:
        # Default to latest execution run
        if not assessment.test_executions:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No test execution runs found for this assessment",
            )
        test_run = assessment.test_executions[-1]

    return TestExecutionRunItem(
        id=test_run.id,
        command=test_run.command,
        status=test_run.status,
        exit_code=test_run.exit_code,
        stdout=test_run.stdout,
        stderr=test_run.stderr,
        passed_count=test_run.passed_count,
        failed_count=test_run.failed_count,
        skipped_count=test_run.skipped_count,
        duration_ms=test_run.duration_ms,
        started_at=test_run.started_at,
        completed_at=test_run.completed_at,
    )


@impact_router.post(
    "/{repository_id}/impact/{assessment_id}/tests/cancel",
    status_code=status.HTTP_200_OK,
    summary="Cancel in-progress regression test execution",
)
async def cancel_regression_test_execution(
    repository_id: uuid.UUID,
    assessment_id: uuid.UUID,
    payload: CancelTestsRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.ADMIN)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
    engine: ImpactMindEngine = Depends(get_impact_engine),
) -> dict[str, Any]:
    """Request cancellation of an active test execution."""
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace",
        )

    cancelled = await engine.cancel_execution(db, payload.execution_id)
    return {
        "status": "cancelled" if cancelled else "not_running",
        "execution_id": str(payload.execution_id),
    }


@risk_router.get(
    "/overview",
    response_model=WorkspaceRiskOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Get aggregated workspace risk and impact assessment overview",
)
async def get_workspace_risk_overview(
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    repository_id: uuid.UUID | None = Query(default=None, description="Optional repository filter"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspaceRiskOverviewResponse:
    """
    Retrieve real ImpactMind risk assessment metrics across active repositories in the workspace.
    Clearly distinguishes unavailable assessment data from zero risk.
    """
    # 1. Fetch active repositories map
    repo_stmt = select(Repository.id, Repository.name).where(
        Repository.workspace_id == workspace_id,
        Repository.is_active.is_(True),
    )
    if repository_id:
        repo_stmt = repo_stmt.where(Repository.id == repository_id)
    repo_res = await db.execute(repo_stmt)
    repo_map = {row[0]: row[1] for row in repo_res.all()}

    if not repo_map:
        return WorkspaceRiskOverviewResponse(
            workspace_id=workspace_id,
            repository_id=repository_id,
            total_assessments=0,
            has_assessment_data=False,
            latest_risk_score=None,
            latest_risk_tier=None,
            latest_assessment_at=None,
            tier_distribution={"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0},
            breaking_changes_total=0,
            recent_assessments=[],
            top_exposed_files=[],
        )

    # 2. Query assessments for active repositories in workspace
    stmt = (
        select(ImpactAssessment)
        .where(
            ImpactAssessment.workspace_id == workspace_id,
            ImpactAssessment.repository_id.in_(list(repo_map.keys())),
        )
        .options(
            selectinload(ImpactAssessment.classifications),
            selectinload(ImpactAssessment.impacted_entities),
            selectinload(ImpactAssessment.test_recommendations),
        )
        .order_by(desc(ImpactAssessment.created_at))
    )
    if repository_id:
        stmt = stmt.where(ImpactAssessment.repository_id == repository_id)

    assessments = list((await db.execute(stmt)).scalars().all())

    total = len(assessments)
    tier_distribution = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    breaking_total = 0
    file_impact_counter: dict[str, int] = {}
    file_tier_map: dict[str, str] = {}

    recent_items: list[RiskAssessmentSummaryItem] = []

    for a in assessments:
        tier = (a.exposure_tier or "LOW").upper()
        if tier in tier_distribution:
            tier_distribution[tier] += 1
        else:
            tier_distribution[tier] = 1

        breaking_in_a = sum(1 for c in (a.classifications or []) if c.is_breaking)
        breaking_total += breaking_in_a

        for c in (a.classifications or []):
            if c.file_path:
                file_impact_counter[c.file_path] = file_impact_counter.get(c.file_path, 0) + 1
                if tier == "CRITICAL" or file_tier_map.get(c.file_path) != "CRITICAL":
                    file_tier_map[c.file_path] = tier

        if len(recent_items) < 10:
            recent_items.append(
                RiskAssessmentSummaryItem(
                    id=a.id,
                    repository_id=a.repository_id,
                    repository_name=repo_map.get(a.repository_id),
                    comparison_mode=a.comparison_mode,
                    status=a.status,
                    structural_exposure_score=a.structural_exposure_score,
                    exposure_tier=a.exposure_tier,
                    breaking_changes_count=breaking_in_a,
                    impacted_entities_count=len(a.impacted_entities or []),
                    test_recommendations_count=len(a.test_recommendations or []),
                    created_at=a.created_at,
                    completed_at=a.completed_at,
                )
            )

    top_files = [
        ExposedFileSummaryItem(
            file_path=f_path,
            impact_count=count,
            highest_severity=file_tier_map.get(f_path, "LOW"),
        )
        for f_path, count in sorted(file_impact_counter.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    latest = assessments[0] if assessments else None

    return WorkspaceRiskOverviewResponse(
        workspace_id=workspace_id,
        repository_id=repository_id,
        total_assessments=total,
        has_assessment_data=(latest is not None),
        latest_risk_score=latest.structural_exposure_score if latest else None,
        latest_risk_tier=latest.exposure_tier if latest else None,
        latest_assessment_at=latest.completed_at or latest.created_at if latest else None,
        tier_distribution=tier_distribution,
        breaking_changes_total=breaking_total,
        recent_assessments=recent_items,
        top_exposed_files=top_files,
    )

