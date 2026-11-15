from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.testpilot import (
    TestPilotExecution,
    TestPilotSuite,
    TestPilotTestType,
    TestSuiteStatus,
)
from app.services.testpilot.coverage import CoverageAnalyzer
from app.services.testpilot.detector import FrameworkDetector
from app.services.testpilot.diagnoser import FailureDiagnoser
from app.services.testpilot.exceptions import TestPilotError
from app.services.testpilot.generator import TestGenerator
from app.services.testpilot.impact_selector import ImpactTestSelector
from app.services.testpilot.runner import TestPilotRunner
from app.services.testpilot.schemas import (
    CoverageReportSummary,
    DetectedFrameworkInfo,
    DiagnosisReport,
    ImpactTestSelectionResult,
    TestExecutionSummary,
)

logger = logging.getLogger("orchestrix.testpilot.service")


class TestPilotService:
    """
    TestPilot — Autonomous Software Testing Agent Orchestration Service.
    Coordinates framework detection, AI test generation, human approval gates,
    controlled isolated execution, failure diagnosis, coverage, and regression selection.
    """

    __test__ = False

    def __init__(
        self,
        detector: FrameworkDetector | None = None,
        generator: TestGenerator | None = None,
        runner: TestPilotRunner | None = None,
        diagnoser: FailureDiagnoser | None = None,
        coverage_analyzer: CoverageAnalyzer | None = None,
        impact_selector: ImpactTestSelector | None = None,
    ) -> None:
        self.detector = detector or FrameworkDetector()
        self.generator = generator or TestGenerator()
        self.runner = runner or TestPilotRunner()
        self.diagnoser = diagnoser or FailureDiagnoser()
        self.coverage_analyzer = coverage_analyzer or CoverageAnalyzer()
        self.impact_selector = impact_selector or ImpactTestSelector()

    def detect_framework(self, root_dir: str) -> DetectedFrameworkInfo:
        """Detect software test framework and conventions in a directory."""
        return self.detector.detect_from_directory(root_dir)

    async def generate_test_suite(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        framework: str,
        target_files: list[str],
        source_context: str,
        test_type: str = TestPilotTestType.UNIT,
        snapshot_id: uuid.UUID | None = None,
        symbols_info: list[dict[str, Any]] | None = None,
    ) -> TestPilotSuite:
        """
        Generate and persist a proposed test suite in GENERATED status.
        Mandatory approval boundary: Never writes to repository or executes without approval.
        """
        # Incorporate DevMemory test conventions and known limitations safely
        augmented_context = source_context
        try:
            from app.db.models.devmemory import MemoryConsumerAgent
            from app.services.devmemory.agent_interface import AgentMemoryInterface

            memory_iface = AgentMemoryInterface()
            mem_context = await memory_iface.build_agent_context(
                db=db,
                workspace_id=workspace_id,
                query=f"Test conventions and guidelines for {framework} {test_type}",
                repository_id=repository_id,
                agent=MemoryConsumerAgent.TESTPILOT,
                max_tokens=600,
            )
            if mem_context and "No prior engineering memories found" not in mem_context:
                augmented_context = f"{source_context}\n\n{mem_context}"
        except Exception as mem_err:
            logger.warning(f"TestPilot DevMemory context retrieval skipped safely: {mem_err}")

        suite_dto = await self.generator.generate_suite(
            framework=framework,
            target_files=target_files,
            source_context=augmented_context,
            test_type=test_type,
            symbols_info=symbols_info,
        )
        return await self.generator.persist_suite(
            db=db,
            workspace_id=workspace_id,
            repository_id=repository_id,
            suite_dto=suite_dto,
            snapshot_id=snapshot_id,
        )

    async def approve_test_suite(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        suite_id: uuid.UUID,
        approved_by_user_id: uuid.UUID,
    ) -> TestPilotSuite:
        """
        Explicit human approval gate for a generated test suite.
        """
        stmt = select(TestPilotSuite).where(
            TestPilotSuite.id == suite_id,
            TestPilotSuite.workspace_id == workspace_id,
            TestPilotSuite.repository_id == repository_id,
        )
        res = await db.execute(stmt)
        suite = res.scalar_one_or_none()
        if not suite:
            raise TestPilotError(f"Test suite {suite_id} not found")

        suite.status = TestSuiteStatus.APPROVED
        suite.approved_at = utc_now()
        suite.approved_by = approved_by_user_id
        await db.commit()
        await db.refresh(suite)
        return suite

    async def execute_suite(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        suite_id: uuid.UUID,
        custom_command: str | None = None,
        timeout_seconds: int = 120,
    ) -> TestExecutionSummary:
        """
        Execute an approved test suite inside an isolated task workspace.
        """
        return await self.runner.execute_suite(
            db=db,
            workspace_id=workspace_id,
            repository_id=repository_id,
            suite_id=suite_id,
            custom_command=custom_command,
            timeout_seconds=timeout_seconds,
        )

    async def diagnose_failure(
        self,
        db: AsyncSession,
        execution_id: uuid.UUID,
        source_context: str | None = None,
    ) -> DiagnosisReport:
        """
        Diagnose a failed test execution run using AI and secret-scrubbed traceback analysis.
        """
        stmt = select(TestPilotExecution).where(TestPilotExecution.id == execution_id)
        res = await db.execute(stmt)
        execution = res.scalar_one_or_none()
        if not execution:
            raise TestPilotError(f"Execution {execution_id} not found")

        failing_name = "SuiteExecutionFailure"
        for r in execution.results:
            if r.status == "FAILED":
                failing_name = r.test_name
                break

        return await self.diagnoser.diagnose(
            failing_test_name=failing_name,
            stdout=execution.stdout,
            stderr=execution.stderr,
            source_context=source_context,
        )

    async def collect_coverage(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        raw_coverage_data: dict[str, Any] | str,
        provider: str = "coverage.py",
        execution_id: uuid.UUID | None = None,
    ) -> CoverageReportSummary:
        """
        Parse and persist coverage report metrics.
        """
        summary = self.coverage_analyzer.parse_coverage_json(raw_coverage_data, provider=provider)
        if summary.is_available:
            await self.coverage_analyzer.persist_coverage_report(
                db=db,
                workspace_id=workspace_id,
                repository_id=repository_id,
                summary=summary,
                execution_id=execution_id,
            )
        return summary

    async def select_impacted_tests(
        self,
        diff_text: str,
        all_test_files: list[str] | None = None,
    ) -> ImpactTestSelectionResult:
        """
        Analyze git diff and select prioritized regression tests via ImpactMind.
        """
        return await self.impact_selector.select_regression_tests(
            diff_text=diff_text,
            all_test_files=all_test_files,
        )
