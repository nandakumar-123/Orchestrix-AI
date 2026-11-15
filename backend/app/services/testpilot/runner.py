from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.testpilot import (
    TestPilotExecution,
    TestPilotResult,
    TestPilotSuite,
    TestResultOutcome,
    TestSuiteStatus,
)
from app.services.devpilot.workspace_manager import TaskWorkspaceManager
from app.services.impactmind.test_runner import ControlledTestRunner
from app.services.testpilot.exceptions import (
    TestApprovalRequiredError,
    TestExecutionSecurityError,
    TestPilotError,
)
from app.services.testpilot.schemas import IndividualTestResult, TestExecutionSummary

logger = logging.getLogger("orchestrix.testpilot.runner")

# Regex patterns to parse individual test outcomes from pytest / vitest stdout
PYTEST_TEST_LINE_PATTERN = re.compile(
    r"^([\w\./\-\\]+::[\w\d_\-\[\]]+)\s+(PASSED|FAILED|SKIPPED|XFAIL|ERROR)", re.MULTILINE
)
VITEST_TEST_LINE_PATTERN = re.compile(r"^[√✓×✗]\s+(.+?)(?:\s+\(\d+ms\))?$", re.MULTILINE)


class TestPilotRunner:
    """
    Controlled Test Execution Engine.
    Executes approved test suites inside isolated workspaces using ControlledTestRunner.
    Enforces human approval, command allowlists, timeouts, Windows Job Object containment,
    and granular test outcome persistence.
    """

    __test__ = False

    def __init__(
        self,
        test_runner: ControlledTestRunner | None = None,
        workspace_manager: TaskWorkspaceManager | None = None,
    ) -> None:
        self.controlled_runner = test_runner or ControlledTestRunner()
        self.workspace_manager = workspace_manager or TaskWorkspaceManager()

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
        Execute an approved test suite inside an isolated workspace.
        """
        # 1. Load suite and verify tenant isolation
        stmt = select(TestPilotSuite).where(
            TestPilotSuite.id == suite_id,
            TestPilotSuite.workspace_id == workspace_id,
            TestPilotSuite.repository_id == repository_id,
        )
        res = await db.execute(stmt)
        suite = res.scalar_one_or_none()
        if not suite:
            raise TestPilotError(
                f"Test suite {suite_id} not found for workspace {workspace_id} and repo {repository_id}"
            )

        # 2. Mandatory Approval Check
        if suite.status != TestSuiteStatus.APPROVED:
            raise TestApprovalRequiredError(
                f"Test suite {suite_id} cannot be executed in status '{suite.status}'. "
                "Explicit human approval is required before execution."
            )

        # 3. Create isolated workspace and stage approved test cases
        exec_task_id = uuid.uuid4()
        workspace_dir = self.workspace_manager.create_task_workspace(exec_task_id)

        try:
            # Stage test files into workspace
            for case in suite.cases:
                ext = ".py" if suite.framework in ("pytest", "unittest") else ".test.ts"
                safe_name = re.sub(r"[^\w\-_]", "_", case.name)
                case_rel_path = f"tests/test_{safe_name}{ext}"
                self.workspace_manager.write_isolated_file(exec_task_id, case_rel_path, case.code)

            # 4. Resolve and sanitize command
            raw_cmd = custom_command or self._resolve_default_command(suite.framework)
            try:
                self.controlled_runner.sanitize_command(raw_cmd)
            except ValueError as ve:
                raise TestExecutionSecurityError(
                    f"Unauthorized or insecure test command: {ve}"
                ) from ve

            # 5. Execute via ControlledTestRunner inside isolated workspace
            run_res = await self.controlled_runner.execute_approved_tests(
                execution_id=str(exec_task_id),
                command=raw_cmd,
                working_dir=workspace_dir,
                run_approved=True,
                timeout_seconds=float(timeout_seconds),
            )

            # 6. Parse individual test results
            individual_results = self._parse_individual_results(run_res.stdout, run_res.stderr)

            # 7. Persist execution record
            execution = TestPilotExecution(
                workspace_id=workspace_id,
                repository_id=repository_id,
                suite_id=suite.id,
                command=raw_cmd,
                status=run_res.status,
                exit_code=run_res.exit_code,
                stdout=run_res.stdout,
                stderr=run_res.stderr,
                duration_ms=run_res.duration_ms,
                passed_count=run_res.passed_count,
                failed_count=run_res.failed_count,
                skipped_count=run_res.skipped_count,
                error_message=run_res.error_message,
                executed_at=utc_now(),
                created_at=utc_now(),
            )
            db.add(execution)
            await db.commit()
            await db.refresh(execution)

            # Persist individual results
            for ir in individual_results:
                tr = TestPilotResult(
                    execution_id=execution.id,
                    test_name=ir.test_name,
                    status=ir.status,
                    duration_ms=ir.duration_ms,
                    failure_message=ir.failure_message,
                    traceback=ir.traceback,
                )
                db.add(tr)
            await db.commit()

            return TestExecutionSummary(
                execution_id=execution.id,
                suite_id=suite.id,
                command=raw_cmd,
                status=run_res.status,
                exit_code=run_res.exit_code,
                stdout=run_res.stdout,
                stderr=run_res.stderr,
                duration_ms=run_res.duration_ms,
                passed_count=run_res.passed_count,
                failed_count=run_res.failed_count,
                skipped_count=run_res.skipped_count,
                results=individual_results,
                error_message=run_res.error_message,
                executed_at=execution.executed_at,
            )
        finally:
            # Clean up task workspace
            self.workspace_manager.cleanup_workspace(exec_task_id)

    def _resolve_default_command(self, framework: str) -> str:
        if framework in ("pytest", "unittest"):
            return "pytest -v"
        elif framework == "vitest":
            return "npx vitest run"
        elif framework == "jest":
            return "npx jest"
        elif framework == "mocha":
            return "npx mocha"
        return "pytest -v"

    def _parse_individual_results(self, stdout: str, stderr: str) -> list[IndividualTestResult]:
        """Parse structured test outcomes from runner output."""
        results: list[IndividualTestResult] = []

        # Pytest verbose line parsing
        for match in PYTEST_TEST_LINE_PATTERN.finditer(stdout):
            test_path = match.group(1).strip()
            raw_outcome = match.group(2).upper()
            status = TestResultOutcome.PASSED
            if raw_outcome in ("FAILED", "ERROR"):
                status = TestResultOutcome.FAILED
            elif raw_outcome in ("SKIPPED", "XFAIL"):
                status = TestResultOutcome.SKIPPED

            results.append(
                IndividualTestResult(
                    test_name=test_path,
                    status=status,
                    duration_ms=0,
                )
            )

        if not results:
            # Vitest line parsing
            for line in stdout.splitlines():
                line_str = line.strip()
                if line_str.startswith(("✓", "√")):
                    results.append(
                        IndividualTestResult(
                            test_name=line_str.lstrip("✓√ ").strip(),
                            status=TestResultOutcome.PASSED,
                        )
                    )
                elif line_str.startswith(("×", "✗")):
                    results.append(
                        IndividualTestResult(
                            test_name=line_str.lstrip("×✗ ").strip(),
                            status=TestResultOutcome.FAILED,
                            failure_message=line_str,
                        )
                    )

        return results
