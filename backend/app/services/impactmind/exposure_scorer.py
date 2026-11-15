from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.impactmind.ast_classifier import ClassifiedChange
from app.services.impactmind.graph_analyzer import GraphImpactAnalysisResult
from app.services.impactmind.test_runner import TestExecutionResult
from app.services.impactmind.test_selector import SelectedRegressionTest

logger = logging.getLogger("orchestrix.impactmind.exposure_scorer")


@dataclass
class ExposureScoreResult:
    """Calculated Blast Radius & Structural Exposure Score with transparent component weights."""

    score: float  # 0.0 to 100.0
    tier: str  # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    score_type: str = "heuristic_structural_exposure"
    score_label: str = "Blast Radius & Structural Exposure Score"
    reasons: list[str] = field(default_factory=list)
    component_breakdown: dict[str, float] = field(default_factory=dict)
    recommended_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "tier": self.tier,
            "score_type": self.score_type,
            "score_label": self.score_label,
            "reasons": self.reasons,
            "component_breakdown": {k: round(v, 1) for k, v in self.component_breakdown.items()},
            "recommended_actions": self.recommended_actions,
        }


class StructuralExposureScorer:
    """
    Computes the Blast Radius & Structural Exposure Score (0–100)
    combining AST change severity, breaking changes, graph callers,
    exposed API endpoints, database models, and test verification.
    """

    def compute_score(
        self,
        changes: list[ClassifiedChange],
        graph_result: GraphImpactAnalysisResult | None = None,
        recommended_tests: list[SelectedRegressionTest] | None = None,
        test_execution: TestExecutionResult | None = None,
    ) -> ExposureScoreResult:
        reasons: list[str] = []
        actions: list[str] = []
        breakdown: dict[str, float] = {}

        total_score = 0.0

        # 1. Direct Dependents (Max: 25.0)
        direct_count = len(graph_result.direct_dependents) if graph_result else 0
        direct_score = min(25.0, direct_count * 5.0)
        breakdown["direct_dependents"] = direct_score
        total_score += direct_score
        if direct_count > 0:
            reasons.append(
                f"{direct_count} direct dependent component(s) impacted (+{direct_score:.1f})"
            )

        # 2. Indirect Downstream Dependents (Max: 15.0)
        indirect_count = len(graph_result.indirect_dependents) if graph_result else 0
        indirect_score = min(15.0, indirect_count * 2.5)
        breakdown["indirect_dependents"] = indirect_score
        total_score += indirect_score
        if indirect_count > 0:
            reasons.append(
                f"{indirect_count} indirect downstream dependent(s) impacted (+{indirect_score:.1f})"
            )

        # 3. Breaking Changes & Contract Alterations (Max: 20.0)
        breaking_changes = [c for c in changes if c.is_breaking]
        breaking_score = min(20.0, len(breaking_changes) * 10.0)
        breakdown["breaking_changes"] = breaking_score
        total_score += breaking_score
        if breaking_changes:
            reasons.append(
                f"{len(breaking_changes)} potentially breaking contract change(s) detected (+{breaking_score:.1f})"
            )
            actions.append(
                "Ensure breaking changes are versioned or backward-compatible before merging."
            )

        # 4. Public API & Database Model Exposure (Max: 20.0)
        api_count = len(graph_result.exposed_endpoints) if graph_result else 0
        db_count = len(graph_result.database_models) if graph_result else 0
        exposure_score = min(20.0, (api_count * 10.0) + (db_count * 10.0))
        breakdown["api_database_exposure"] = exposure_score
        total_score += exposure_score
        if api_count > 0:
            reasons.append(f"Directly exposes/modifies {api_count} public API endpoint(s)")
            actions.append("Verify API route contracts and client integrations.")
        if db_count > 0:
            reasons.append(f"Directly impacts {db_count} database model(s) / table(s)")
            actions.append("Confirm database migrations and schema consistency.")

        # 5. Automated Test Coverage & Verification (Max: 20.0 penalty or discount)
        tests_available = len(recommended_tests) if recommended_tests else 0
        test_score = 0.0

        if tests_available == 0 and (direct_count > 0 or api_count > 0):
            test_score = 20.0
            reasons.append(
                "No automated test cases found covering the modified code path (+20.0 penalty)"
            )
            actions.append("Author regression unit tests for modified components.")
        elif test_execution and test_execution.status == "PASSED":
            test_score = -10.0  # Discount for proven passing regression tests
            reasons.append(
                f"Approved regression test suite passed ({test_execution.passed_count} tests) (-10.0 credit)"
            )
        elif test_execution and test_execution.status == "FAILED":
            test_score = 15.0
            reasons.append(
                f"Approved regression test suite failed ({test_execution.failed_count} failures) (+15.0 penalty)"
            )
            actions.append("Inspect test failures and address regressions before proceeding.")
        elif tests_available > 0:
            reasons.append(f"{tests_available} automated test case(s) identified for verification")

        breakdown["test_verification"] = test_score
        total_score += test_score

        # Clamp score to [0.0, 100.0]
        final_score = max(0.0, min(100.0, total_score))

        # Assign Risk / Exposure Tier
        if final_score >= 70.0:
            tier = "CRITICAL"
        elif final_score >= 45.0:
            tier = "HIGH"
        elif final_score >= 20.0:
            tier = "MEDIUM"
        else:
            tier = "LOW"

        if not reasons:
            reasons.append("Isolated modification with no detected downstream dependents.")

        if not actions:
            actions.append("Safe for standard code review and deployment.")

        return ExposureScoreResult(
            score=final_score,
            tier=tier,
            reasons=reasons,
            component_breakdown=breakdown,
            recommended_actions=actions,
        )
