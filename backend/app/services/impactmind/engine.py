from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.impactmind import (
    ChangeClassification,
    ImpactAssessment,
    ImpactedEntity,
    TestExecutionRun,
    TestRecommendation,
)
from app.db.models.repository_intelligence import (
    CodeSymbol,
    RepositoryFile,
    RepositorySnapshot,
)
from app.services.graph_service import BaseGraphProvider, get_graph_provider
from app.services.impactmind.ast_classifier import ASTChangeClassifier, ClassifiedChange
from app.services.impactmind.diff_parser import GitDiffParser, ParsedDiffResult
from app.services.impactmind.exposure_scorer import ExposureScoreResult, StructuralExposureScorer
from app.services.impactmind.graph_analyzer import GraphImpactAnalyzer
from app.services.impactmind.semantic_analyzer import SemanticImpactAnalyzer
from app.services.impactmind.test_runner import ControlledTestRunner, TestExecutionResult
from app.services.impactmind.test_selector import RegressionTestSelector, SelectedRegressionTest
from app.services.semantic_retrieval import SemanticRetrievalEngine

logger = logging.getLogger("orchestrix.impactmind.engine")


class ImpactMindEngine:
    """
    Main orchestration engine for ImpactMind.
    Coordinates Git diff parsing, AST classification, graph traversal,
    semantic search, regression test selection, structural exposure scoring,
    and PostgreSQL persistence.
    """

    def __init__(
        self,
        graph_provider: BaseGraphProvider | None = None,
        search_engine: SemanticRetrievalEngine | None = None,
    ) -> None:
        self.graph_provider = graph_provider or get_graph_provider()
        self.diff_parser = GitDiffParser()
        self.graph_analyzer = GraphImpactAnalyzer(self.graph_provider)
        self.semantic_analyzer = SemanticImpactAnalyzer(search_engine)
        self.test_selector = RegressionTestSelector()
        self.scorer = StructuralExposureScorer()
        self.test_runner = ControlledTestRunner()

    async def analyze_changes(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        diff_text: str | None = None,
        github_compare_payload: dict[str, Any] | None = None,
        base_commit_sha: str | None = None,
        target_commit_sha: str | None = None,
        comparison_mode: str = "diff_input",
        user_id: uuid.UUID | None = None,
        snapshot_id: uuid.UUID | None = None,
        file_contents_before: dict[str, str] | None = None,
        file_contents_after: dict[str, str] | None = None,
    ) -> ImpactAssessment:
        """
        Execute full change-impact analysis pipeline and persist assessment.
        """
        # 1. Resolve Snapshot (use latest if not provided)
        if not snapshot_id:
            snap_stmt = (
                select(RepositorySnapshot)
                .where(RepositorySnapshot.repository_id == repository_id)
                .order_by(desc(RepositorySnapshot.created_at))
                .limit(1)
            )
            snap_res = await db.execute(snap_stmt)
            latest_snap = snap_res.scalar_one_or_none()
            if latest_snap:
                snapshot_id = latest_snap.id

        # 2. Parse Git Diff
        if github_compare_payload:
            parsed_diff = self.diff_parser.parse_github_compare_payload(github_compare_payload)
            base_commit_sha = base_commit_sha or parsed_diff.base_commit_sha
            target_commit_sha = target_commit_sha or parsed_diff.target_commit_sha
        elif diff_text:
            parsed_diff = self.diff_parser.parse_unified_diff(
                diff_text,
                base_commit_sha=base_commit_sha,
                target_commit_sha=target_commit_sha,
            )
        else:
            parsed_diff = ParsedDiffResult(
                base_commit_sha=base_commit_sha, target_commit_sha=target_commit_sha
            )

        # 3. Load Existing Symbols & Files from DB
        existing_symbols: list[CodeSymbol] = []
        all_test_files: list[str] = []
        if snapshot_id:
            sym_stmt = select(CodeSymbol).where(CodeSymbol.snapshot_id == snapshot_id)
            sym_res = await db.execute(sym_stmt)
            existing_symbols = list(sym_res.scalars().all())

            f_stmt = select(RepositoryFile).where(RepositoryFile.snapshot_id == snapshot_id)
            f_res = await db.execute(f_stmt)
            for f in f_res.scalars().all():
                if (
                    "/tests/" in f.path
                    or f.path.startswith("tests/")
                    or f.path.endswith((".test.ts", ".spec.ts", "_test.py", "_test.go"))
                ):
                    all_test_files.append(f.path)

        # 4. AST Change Classification
        classifier = ASTChangeClassifier(
            existing_symbols=existing_symbols,
            file_contents_before=file_contents_before or {},
            file_contents_after=file_contents_after or {},
        )
        classifications: list[ClassifiedChange] = classifier.classify_diff(parsed_diff)

        # 5. Graph Impact Analysis
        graph_result = None
        if snapshot_id:
            graph_result = await self.graph_analyzer.analyze_impact(
                snapshot_id=snapshot_id,
                changes=classifications,
                max_depth=3,
            )

        # 6. Semantic Impact Analysis
        semantic_result = None
        graph_files = set()
        if graph_result:
            graph_files = {d.file_path for d in graph_result.direct_dependents + graph_result.indirect_dependents}
        try:
            semantic_result = await self.semantic_analyzer.analyze_semantic_impact(
                db=db,
                workspace_id=workspace_id,
                repository_id=repository_id,
                changes=classifications,
                graph_impacted_file_paths=graph_files,
            )
        except Exception as e:
            logger.warning(f"Semantic impact analysis skipped due to error: {e}")

        # 7. Regression Test Selection
        recommended_tests: list[SelectedRegressionTest] = self.test_selector.select_tests(
            changes=classifications,
            graph_result=graph_result,
            semantic_result=semantic_result,
            all_test_files=all_test_files,
        )

        # 8. Structural Exposure Scoring
        score_res: ExposureScoreResult = self.scorer.compute_score(
            changes=classifications,
            graph_result=graph_result,
            recommended_tests=recommended_tests,
            test_execution=None,
        )

        # 9. Create Assessment Record
        breaking_count = sum(1 for c in classifications if c.is_breaking)
        change_summary = {
            "total_files_changed": parsed_diff.total_files_changed,
            "total_additions": parsed_diff.total_additions,
            "total_deletions": parsed_diff.total_deletions,
            "breaking_changes_count": breaking_count,
            "total_classifications": len(classifications),
            "direct_dependents_count": len(graph_result.direct_dependents) if graph_result else 0,
            "indirect_dependents_count": len(graph_result.indirect_dependents) if graph_result else 0,
            "exposed_endpoints_count": len(graph_result.exposed_endpoints) if graph_result else 0,
            "database_models_count": len(graph_result.database_models) if graph_result else 0,
            "recommended_tests_count": len(recommended_tests),
            "is_graph_degraded": graph_result.is_degraded if graph_result else False,
            "is_semantic_degraded": semantic_result.is_degraded if semantic_result else False,
        }

        assessment = ImpactAssessment(
            workspace_id=workspace_id,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            initiated_by_user_id=user_id,
            base_commit_sha=base_commit_sha,
            target_commit_sha=target_commit_sha,
            comparison_mode=comparison_mode,
            status="completed",
            structural_exposure_score=score_res.score,
            exposure_tier=score_res.tier,
            change_summary=change_summary,
            reasons=score_res.reasons,
            recommended_actions=score_res.recommended_actions,
            completed_at=utc_now(),
        )
        db.add(assessment)
        await db.flush()

        # 10. Persist Child Entities
        for c in classifications:
            db.add(
                ChangeClassification(
                    assessment_id=assessment.id,
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
            )

        if graph_result:
            all_impacted = (
                graph_result.direct_dependents
                + graph_result.indirect_dependents
                + graph_result.exposed_endpoints
                + graph_result.database_models
                + graph_result.affected_tests
            )
            for imp in all_impacted:
                db.add(
                    ImpactedEntity(
                        assessment_id=assessment.id,
                        entity_id=imp.id,
                        name=imp.name,
                        label=imp.label,
                        file_path=imp.file_path,
                        impact_type=imp.impact_type,
                        depth=imp.depth,
                        relationship_type=imp.relationship_type,
                        confidence=imp.confidence,
                        evidence=imp.evidence,
                    )
                )

        # Add semantic matches as impacted entities
        if semantic_result and semantic_result.matches:
            for sm in semantic_result.matches:
                db.add(
                    ImpactedEntity(
                        assessment_id=assessment.id,
                        entity_id=sm.chunk_id,
                        name=sm.symbol_name or sm.file_path,
                        label=sm.symbol_type or "CodeChunk",
                        file_path=sm.file_path,
                        impact_type="semantic_similarity",
                        depth=1,
                        relationship_type="SIMILAR_TO",
                        confidence=sm.similarity_score,
                        evidence=sm.relation_reason,
                    )
                )

        for tr in recommended_tests:
            db.add(
                TestRecommendation(
                    assessment_id=assessment.id,
                    test_file=tr.test_file,
                    test_name=tr.test_name,
                    test_framework=tr.test_framework,
                    priority=tr.priority,
                    reason=tr.reason,
                    related_symbol=tr.related_symbol,
                    evidence_source=tr.evidence_source,
                    confidence=tr.confidence,
                )
            )

        await db.commit()
        await db.refresh(assessment)
        return assessment

    async def get_assessment(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        assessment_id: uuid.UUID,
    ) -> ImpactAssessment | None:
        """Fetch assessment ensuring tenant workspace isolation."""
        stmt = (
            select(ImpactAssessment)
            .where(
                ImpactAssessment.id == assessment_id,
                ImpactAssessment.workspace_id == workspace_id,
            )
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_assessments(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ImpactAssessment], int]:
        """List assessment history for a repository."""
        stmt = (
            select(ImpactAssessment)
            .where(
                ImpactAssessment.workspace_id == workspace_id,
                ImpactAssessment.repository_id == repository_id,
            )
            .order_by(desc(ImpactAssessment.created_at))
            .limit(limit)
            .offset(offset)
        )
        res = await db.execute(stmt)
        assessments = list(res.scalars().all())

        count_stmt = (
            select(ImpactAssessment)
            .where(
                ImpactAssessment.workspace_id == workspace_id,
                ImpactAssessment.repository_id == repository_id,
            )
        )
        c_res = await db.execute(count_stmt)
        total = len(list(c_res.scalars().all()))

        return assessments, total

    async def run_regression_tests(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        assessment_id: uuid.UUID,
        working_dir: str,
        run_approved: bool,
        custom_command: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> TestExecutionRun:
        """Execute approved regression tests and record results."""
        assessment = await self.get_assessment(db, workspace_id, assessment_id)
        if not assessment:
            raise LookupError(f"ImpactAssessment {assessment_id} not found")

        # Determine command
        if custom_command:
            command = custom_command
        else:
            rec_tests = [
                SelectedRegressionTest(
                    test_file=r.test_file,
                    test_name=r.test_name,
                    test_framework=r.test_framework,
                    priority=r.priority,
                    reason=r.reason,
                    related_symbol=r.related_symbol,
                    evidence_source=r.evidence_source,
                    confidence=r.confidence,
                )
                for r in assessment.test_recommendations
            ]
            command = self.test_runner.build_test_command(rec_tests)

        exec_id = str(uuid.uuid4())
        test_run = TestExecutionRun(
            id=uuid.UUID(exec_id),
            assessment_id=assessment.id,
            command=command,
            status="PENDING",
            started_at=utc_now(),
        )
        db.add(test_run)
        await db.commit()

        # Execute
        result: TestExecutionResult = await self.test_runner.execute_approved_tests(
            execution_id=exec_id,
            command=command,
            working_dir=working_dir,
            run_approved=run_approved,
            timeout_seconds=timeout_seconds,
        )

        test_run.status = result.status
        test_run.exit_code = result.exit_code
        test_run.stdout = result.stdout
        test_run.stderr = result.stderr
        test_run.passed_count = result.passed_count
        test_run.failed_count = result.failed_count
        test_run.skipped_count = result.skipped_count
        test_run.duration_ms = result.duration_ms
        test_run.completed_at = utc_now()

        # Recompute score with test execution feedback
        recomputed_score = self.scorer.compute_score(
            changes=[],  # preserve existing reasons
            graph_result=None,
            recommended_tests=[],
            test_execution=result,
        )
        if result.status == "PASSED":
            assessment.structural_exposure_score = max(0.0, assessment.structural_exposure_score - 10.0)
            assessment.reasons = list(assessment.reasons) + [
                f"Approved regression test suite passed ({result.passed_count} tests) (-10.0 credit)"
            ]
        elif result.status == "FAILED":
            assessment.structural_exposure_score = min(100.0, assessment.structural_exposure_score + 15.0)
            assessment.reasons = list(assessment.reasons) + [
                f"Approved regression test suite failed ({result.failed_count} failures) (+15.0 penalty)"
            ]

        # Update exposure tier
        if assessment.structural_exposure_score >= 70.0:
            assessment.exposure_tier = "CRITICAL"
        elif assessment.structural_exposure_score >= 45.0:
            assessment.exposure_tier = "HIGH"
        elif assessment.structural_exposure_score >= 20.0:
            assessment.exposure_tier = "MEDIUM"
        else:
            assessment.exposure_tier = "LOW"

        db.add(assessment)
        db.add(test_run)
        await db.commit()
        await db.refresh(test_run)
        return test_run

    async def cancel_execution(self, db: AsyncSession, execution_id: uuid.UUID) -> bool:
        """Cancel an in-flight test execution run and mark its database record as cancelled."""
        cancelled = self.test_runner.cancel_execution(str(execution_id))
        test_run = await db.get(TestExecutionRun, execution_id)
        if test_run and test_run.status in ("PENDING", "RUNNING"):
            test_run.status = "CANCELLED"
            test_run.stderr = (test_run.stderr or "") + "\nExecution was cancelled by user request."
            test_run.completed_at = utc_now()
            db.add(test_run)
            await db.commit()
            return True
        return cancelled

    async def get_execution(self, db: AsyncSession, execution_id: uuid.UUID) -> TestExecutionRun | None:
        """Fetch test execution run by ID."""
        return await db.get(TestExecutionRun, execution_id)

