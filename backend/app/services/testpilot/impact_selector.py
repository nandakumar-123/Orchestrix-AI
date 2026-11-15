from __future__ import annotations

import logging
from typing import Any

from app.services.impactmind.ast_classifier import ASTChangeClassifier
from app.services.impactmind.engine import ImpactMindEngine
from app.services.impactmind.test_selector import RegressionTestSelector
from app.services.testpilot.schemas import ImpactTestSelectionResult

logger = logging.getLogger("orchestrix.testpilot.impact_selector")


class ImpactTestSelector:
    """
    TestPilot integration with Phase 11 ImpactMind intelligence.
    Identifies changed files, impacted symbols, and prioritized regression tests.
    The structural exposure score is an engineering blast-radius metric,
    not a statistical probability of regression.
    """

    def __init__(
        self,
        impact_engine: ImpactMindEngine | None = None,
        selector: RegressionTestSelector | None = None,
    ) -> None:
        self.impact_engine = impact_engine or ImpactMindEngine()
        self.selector = selector or RegressionTestSelector()

    async def select_regression_tests(
        self,
        diff_text: str,
        all_test_files: list[str] | None = None,
    ) -> ImpactTestSelectionResult:
        """
        Analyze diff changes and select targeted regression tests.
        """
        parsed_diff = self.impact_engine.diff_parser.parse_unified_diff(diff_text)
        classifier = ASTChangeClassifier()
        classifications = classifier.classify_diff(parsed_diff)
        recommended_tests = self.selector.select_tests(
            changes=classifications,
            graph_result=None,
            semantic_result=None,
            all_test_files=all_test_files,
        )
        score_res = self.impact_engine.scorer.compute_score(
            changes=classifications,
            graph_result=None,
            recommended_tests=recommended_tests,
        )

        selected_tests_dto: list[dict[str, Any]] = [t.to_dict() for t in recommended_tests]
        impacted_symbols = [c.symbol_name for c in classifications if c.symbol_name]

        rationale: list[str] = []
        if classifications:
            breaking = [c.symbol_name for c in classifications if c.is_breaking and c.symbol_name]
            if breaking:
                rationale.append(f"Identified breaking changes in: {', '.join(breaking[:5])}")
            rationale.append(f"Analyzed {len(classifications)} modified symbols")

        if recommended_tests:
            rationale.append(f"Selected {len(recommended_tests)} targeted regression test suites")
        else:
            rationale.append(
                "No directly affected regression tests identified; recommended unit suite generation"
            )

        modified_files = [f.new_path or f.old_path or "unknown" for f in parsed_diff.files]
        file_desc = f" ({', '.join(modified_files[:3])})" if modified_files else ""
        return ImpactTestSelectionResult(
            selected_tests=selected_tests_dto,
            impacted_symbols=impacted_symbols,
            risk_exposure_score=score_res.score,
            change_summary=f"Analyzed {len(parsed_diff.files)} modified files{file_desc} across {len(classifications)} symbols",
            rationale=rationale,
        )
