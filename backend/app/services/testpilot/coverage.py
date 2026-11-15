from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.testpilot import TestPilotCoverageReport
from app.services.testpilot.schemas import CoverageReportSummary

logger = logging.getLogger("orchestrix.testpilot.coverage")


class CoverageAnalyzer:
    """
    Test Coverage Intelligence Engine.
    Collects and parses real line and branch coverage from coverage.py and Vitest/Jest.
    Preserves null for missing branch metrics and avoids fabricating values.
    """

    def parse_coverage_json(
        self, raw_data: dict[str, Any] | str, provider: str = "coverage.py"
    ) -> CoverageReportSummary:
        """
        Parse structured coverage data into standardized CoverageReportSummary.
        """
        if isinstance(raw_data, str):
            try:
                data = json.loads(raw_data)
            except Exception as e:
                logger.error(f"Malformed coverage JSON: {e}")
                return CoverageReportSummary(
                    line_coverage_pct=None,
                    branch_coverage_pct=None,
                    is_available=False,
                    provider=provider,
                )
        else:
            data = raw_data

        if provider == "coverage.py":
            totals = data.get("totals", {})
            percent_covered = totals.get("percent_covered")
            line_pct = round(float(percent_covered), 2) if percent_covered is not None else None

            # Branch coverage check: check if num_branches > 0
            has_branches = totals.get("num_branches", 0) > 0
            branch_pct: float | None = None
            if has_branches and "covered_branches" in totals and "num_branches" in totals:
                num_b = totals["num_branches"]
                cov_b = totals["covered_branches"]
                branch_pct = round((cov_b / num_b) * 100.0, 2) if num_b > 0 else None

            uncovered_files: list[str] = []
            files_dict = data.get("files", {})
            for fpath, fmetrics in files_dict.items():
                f_summary = fmetrics.get("summary", {})
                missing = f_summary.get("missing_lines", 0)
                if missing > 0:
                    uncovered_files.append(fpath.replace("\\", "/"))

            return CoverageReportSummary(
                line_coverage_pct=line_pct,
                branch_coverage_pct=branch_pct,
                uncovered_files=uncovered_files,
                uncovered_functions=[],
                is_available=True,
                provider="coverage.py",
                raw_report=data,
            )

        elif provider in ("vitest", "jest"):
            # Vitest / Jest coverage-summary.json format: {"total": {"lines": {"pct": 85.5}, "branches": {"pct": 70.0}}}
            total = data.get("total", {})
            lines_data = total.get("lines", {})
            branch_data = total.get("branches", {})

            line_pct = (
                float(lines_data["pct"])
                if "pct" in lines_data and lines_data["pct"] is not None
                else None
            )
            # If total branches is 0, branch coverage is None
            total_branches = branch_data.get("total", 0)
            branch_pct = (
                float(branch_data["pct"])
                if total_branches > 0 and "pct" in branch_data and branch_data["pct"] is not None
                else None
            )

            uncovered_files = [
                fpath.replace("\\", "/")
                for fpath, fstats in data.items()
                if fpath != "total"
                and isinstance(fstats, dict)
                and fstats.get("lines", {}).get("pct", 100) < 100
            ]

            return CoverageReportSummary(
                line_coverage_pct=line_pct,
                branch_coverage_pct=branch_pct,
                uncovered_files=uncovered_files,
                uncovered_functions=[],
                is_available=True,
                provider=provider,
                raw_report=data,
            )

        return CoverageReportSummary(
            line_coverage_pct=None,
            branch_coverage_pct=None,
            is_available=False,
            provider=provider,
        )

    async def persist_coverage_report(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        summary: CoverageReportSummary,
        execution_id: uuid.UUID | None = None,
    ) -> TestPilotCoverageReport:
        """
        Persist coverage metrics to TestPilotCoverageReport table.
        """
        report = TestPilotCoverageReport(
            workspace_id=workspace_id,
            repository_id=repository_id,
            execution_id=execution_id,
            line_coverage_pct=summary.line_coverage_pct,
            branch_coverage_pct=summary.branch_coverage_pct,
            uncovered_files=summary.uncovered_files,
            uncovered_functions=summary.uncovered_functions,
            raw_report=summary.raw_report,
            created_at=utc_now(),
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)
        return report
