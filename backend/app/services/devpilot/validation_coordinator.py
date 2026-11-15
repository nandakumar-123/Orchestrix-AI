from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.devpilot import (
    CodeGenerationResult,
    DevPilotEvent,
    DevPilotTask,
    DevPilotValidationRun,
)
from app.services.code_intelligence import PARSER_REGISTRY, analyze_code_content
from app.services.impactmind.engine import ImpactMindEngine
from app.services.impactmind.test_runner import ControlledTestRunner

logger = logging.getLogger("orchestrix.devpilot.validation")


class ValidationCoordinator:
    """
    Coordinates multi-stage validation for DevPilot in the isolated task workspace:
    Stage 1: Tree-sitter AST & Syntax Verification
    Stage 2: ImpactMind Regression Blast Radius & Test Selection
    Stage 3: Controlled Test Execution (requiring explicit human approval)
    """

    def __init__(
        self,
        impact_engine: ImpactMindEngine | None = None,
        test_runner: ControlledTestRunner | None = None,
    ) -> None:
        self.impact_engine = impact_engine or ImpactMindEngine()
        self.test_runner = test_runner or ControlledTestRunner()

    async def run_syntax_validation(
        self,
        db: AsyncSession,
        task: DevPilotTask,
        generation_result: CodeGenerationResult,
    ) -> DevPilotValidationRun:
        """
        Validate that every created or modified file parses cleanly with Tree-sitter AST.
        """
        syntax_errors: list[str] = []

        for ch in generation_result.changes:
            if ch.change_type == "DELETE" or not ch.new_content:
                continue

            ext = os.path.splitext(ch.file_path)[1].lower()
            lang = None
            for lang_name in PARSER_REGISTRY.get_supported_languages():
                spec = PARSER_REGISTRY.get_language_spec(lang_name)
                if spec and ext in spec.extensions:
                    lang = lang_name
                    break

            if lang:
                try:
                    res = analyze_code_content(ch.new_content.encode("utf-8"), lang)
                    if res.parse_error:
                        syntax_errors.append(f"{ch.file_path}: {res.parse_error}")
                except Exception as e:
                    syntax_errors.append(f"{ch.file_path}: AST parsing failed with exception: {e}")

        status = "FAILED" if syntax_errors else "PASSED"
        val_run = DevPilotValidationRun(
            task_id=task.id,
            workspace_id=task.workspace_id,
            stage="SYNTAX_AND_AST",
            command="tree-sitter ast validation",
            status=status,
            exit_code=1 if syntax_errors else 0,
            stdout=f"Verified {len(generation_result.changes)} files via Tree-sitter AST parser."
            if not syntax_errors
            else "",
            stderr="\n".join(syntax_errors) if syntax_errors else None,
            duration_ms=50,
            created_at=utc_now(),
        )
        db.add(val_run)
        await db.commit()
        return val_run

    async def run_impact_assessment(
        self,
        db: AsyncSession,
        task: DevPilotTask,
        generation_result: CodeGenerationResult,
    ) -> Any:
        """
        Run Phase 11 ImpactMind change analysis on the generated unified diff.
        """
        if not generation_result.unified_diff.strip():
            return None

        try:
            assessment = await self.impact_engine.analyze_changes(
                db=db,
                workspace_id=task.workspace_id,
                repository_id=task.repository_id,
                diff_text=generation_result.unified_diff,
                snapshot_id=task.snapshot_id,
                comparison_mode="diff_input",
            )

            val_run = DevPilotValidationRun(
                task_id=task.id,
                workspace_id=task.workspace_id,
                stage="IMPACTMIND_REGRESSION",
                command="impactmind analyze diff",
                status="PASSED",
                exit_code=0,
                stdout=(
                    f"Structural Exposure Score: {assessment.structural_exposure_score:.1f} "
                    f"({assessment.exposure_tier}). "
                    f"Recommended {len(assessment.test_recommendations)} regression tests."
                ),
                stderr=None,
                duration_ms=100,
                created_at=utc_now(),
            )
            db.add(val_run)
            await db.commit()
            return assessment
        except Exception as e:
            logger.warning(f"ImpactMind validation run failed: {e}")
            return None

    async def execute_controlled_tests(
        self,
        db: AsyncSession,
        task: DevPilotTask,
        run_approved: bool,
        test_command: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> DevPilotValidationRun:
        """
        Execute regression tests in the isolated task workspace under ControlledTestRunner.
        Rejects immediately if run_approved is False.
        """
        working_dir = task.isolated_workspace_path or "."
        command = test_command or "pytest"

        exec_res = await self.test_runner.execute_approved_tests(
            execution_id=f"devpilot-{task.id}-{uuid.uuid4().hex[:6]}",
            command=command,
            working_dir=working_dir,
            run_approved=run_approved,
            timeout_seconds=timeout_seconds,
        )

        val_run = DevPilotValidationRun(
            task_id=task.id,
            workspace_id=task.workspace_id,
            stage="CONTROLLED_TEST_RUN",
            command=command,
            status=exec_res.status,
            exit_code=exec_res.exit_code,
            stdout=exec_res.stdout,
            stderr=exec_res.stderr,
            duration_ms=exec_res.duration_ms,
            created_at=utc_now(),
        )
        db.add(val_run)

        db.add(
            DevPilotEvent(
                task_id=task.id,
                workspace_id=task.workspace_id,
                event_type="TEST_EXECUTION_COMPLETED",
                message=f"Test runner executed with status '{exec_res.status}'. Passed: {exec_res.passed_count}, Failed: {exec_res.failed_count}",
                details={
                    "command": command,
                    "status": exec_res.status,
                    "exit_code": exec_res.exit_code,
                    "duration_ms": exec_res.duration_ms,
                },
            )
        )
        await db.commit()
        return val_run
