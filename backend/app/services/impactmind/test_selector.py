from __future__ import annotations

import logging
import posixpath
from dataclasses import dataclass
from typing import Any

from app.services.impactmind.ast_classifier import ClassifiedChange
from app.services.impactmind.graph_analyzer import GraphImpactAnalysisResult
from app.services.impactmind.semantic_analyzer import SemanticImpactResult

logger = logging.getLogger("orchestrix.impactmind.test_selector")


@dataclass
class SelectedRegressionTest:
    test_file: str
    test_name: str | None
    test_framework: str  # "pytest" | "vitest" | "go_test" | "generic"
    priority: str  # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    reason: str
    related_symbol: str | None
    evidence_source: str  # "graph_tests_edge" | "direct_call" | "api_exposure" | "semantic_match" | "naming_convention"
    confidence: float
    rank_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_file": self.test_file,
            "test_name": self.test_name,
            "test_framework": self.test_framework,
            "priority": self.priority,
            "reason": self.reason,
            "related_symbol": self.related_symbol,
            "evidence_source": self.evidence_source,
            "confidence": round(self.confidence, 2),
            "rank_score": round(self.rank_score, 2),
        }


class RegressionTestSelector:
    """
    Intelligent Regression Test Selector.
    Ranks and selects tests from knowledge graph relationships, API exposure,
    direct/indirect dependents, and semantic relevance.
    """

    @classmethod
    def detect_test_framework(cls, file_path: str) -> str:
        """Detect the appropriate test runner from the file extension and naming convention."""
        ext = posixpath.splitext(file_path)[1].lower()
        if ext == ".py":
            return "pytest"
        if ext in (".ts", ".tsx", ".js", ".jsx"):
            return "vitest"
        if ext == ".go":
            return "go_test"
        return "generic"

    def select_tests(
        self,
        changes: list[ClassifiedChange],
        graph_result: GraphImpactAnalysisResult | None,
        semantic_result: SemanticImpactResult | None = None,
        all_test_files: list[str] | None = None,
    ) -> list[SelectedRegressionTest]:
        """
        Rank and prioritize recommended tests based on multi-source evidence.
        """
        candidates: dict[str, SelectedRegressionTest] = {}
        breaking_symbols = {c.symbol_name for c in changes if c.is_breaking and c.symbol_name}

        # 1. Tests from Knowledge Graph TESTS relationships (Priority: CRITICAL / HIGH)
        if graph_result and graph_result.affected_tests:
            for t_node in graph_result.affected_tests:
                key = f"{t_node.file_path}:{t_node.name}"
                is_breaking = t_node.name in breaking_symbols or any(
                    c.symbol_name == t_node.name for c in changes if c.is_breaking
                )
                priority = "CRITICAL" if is_breaking else "HIGH"
                rank = 100.0 if priority == "CRITICAL" else 85.0

                candidates[key] = SelectedRegressionTest(
                    test_file=t_node.file_path,
                    test_name=t_node.name,
                    test_framework=self.detect_test_framework(t_node.file_path),
                    priority=priority,
                    reason=f"Directly verifies modified symbol '{t_node.name}' via Knowledge Graph",
                    related_symbol=t_node.name,
                    evidence_source="graph_tests_edge",
                    confidence=t_node.confidence,
                    rank_score=rank,
                )

        # 2. Tests covering API Endpoints or Database Models
        if graph_result and (graph_result.exposed_endpoints or graph_result.database_models):
            for ep in graph_result.exposed_endpoints:
                # Find tests in test files that mention the endpoint or route
                ep_name = ep.name
                if all_test_files:
                    for t_file in all_test_files:
                        if "api" in t_file.lower() or "endpoint" in t_file.lower():
                            key = f"{t_file}:endpoint_test"
                            if key not in candidates:
                                candidates[key] = SelectedRegressionTest(
                                    test_file=t_file,
                                    test_name=None,
                                    test_framework=self.detect_test_framework(t_file),
                                    priority="HIGH",
                                    reason=f"Covers public API route exposed by modified handler: {ep_name}",
                                    related_symbol=ep_name,
                                    evidence_source="api_exposure",
                                    confidence=0.85,
                                    rank_score=75.0,
                                )

        # 3. Direct / Indirect Callers that are Test Cases
        if graph_result:
            for dep in graph_result.direct_dependents + graph_result.indirect_dependents:
                if (
                    dep.label == "TestCase"
                    or "/tests/" in dep.file_path
                    or dep.file_path.startswith("tests/")
                ):
                    key = f"{dep.file_path}:{dep.name}"
                    if key not in candidates:
                        priority = "HIGH" if dep.depth == 1 else "MEDIUM"
                        rank = 70.0 if dep.depth == 1 else 50.0
                        candidates[key] = SelectedRegressionTest(
                            test_file=dep.file_path,
                            test_name=dep.name,
                            test_framework=self.detect_test_framework(dep.file_path),
                            priority=priority,
                            reason=f"Downstream dependent test case (depth {dep.depth}) calling affected code path",
                            related_symbol=dep.name,
                            evidence_source="direct_call",
                            confidence=dep.confidence,
                            rank_score=rank,
                        )

        # 4. Convention-Based Test Matching (e.g., auth.py -> test_auth.py)
        if all_test_files:
            for c in changes:
                base_name = posixpath.splitext(posixpath.basename(c.file_path))[0]
                expected_names = [
                    f"test_{base_name}",
                    f"{base_name}_test",
                    f"{base_name}.test",
                    f"{base_name}.spec",
                ]
                for t_file in all_test_files:
                    t_base = posixpath.splitext(posixpath.basename(t_file))[0]
                    if any(cand in t_base for cand in expected_names):
                        key = f"{t_file}:convention"
                        if key not in candidates:
                            candidates[key] = SelectedRegressionTest(
                                test_file=t_file,
                                test_name=None,
                                test_framework=self.detect_test_framework(t_file),
                                priority="HIGH" if c.is_breaking else "MEDIUM",
                                reason=f"Unit test suite matching changed module '{base_name}'",
                                related_symbol=c.symbol_name or base_name,
                                evidence_source="naming_convention",
                                confidence=0.90,
                                rank_score=65.0,
                            )

        # 5. Semantic Impact Matches that are Test Files
        if semantic_result and semantic_result.matches:
            for s_match in semantic_result.matches:
                if (
                    "/tests/" in s_match.file_path
                    or s_match.file_path.startswith("tests/")
                    or s_match.file_path.endswith((".test.ts", ".spec.ts", "_test.py", "_test.go"))
                ):
                    key = f"{s_match.file_path}:{s_match.symbol_name or 'chunk'}"
                    if key not in candidates:
                        candidates[key] = SelectedRegressionTest(
                            test_file=s_match.file_path,
                            test_name=s_match.symbol_name,
                            test_framework=self.detect_test_framework(s_match.file_path),
                            priority="LOW",
                            reason=f"Semantically relevant test logic matching {s_match.matched_query}",
                            related_symbol=s_match.symbol_name,
                            evidence_source="semantic_match",
                            confidence=s_match.similarity_score,
                            rank_score=40.0 * s_match.similarity_score,
                        )

        # Sort by rank_score descending
        sorted_tests = sorted(candidates.values(), key=lambda t: t.rank_score, reverse=True)
        return sorted_tests
