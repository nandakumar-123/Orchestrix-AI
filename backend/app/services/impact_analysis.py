from __future__ import annotations

import collections
import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.graph_service import (
    BaseGraphProvider,
    GraphNode,
    GraphRelationship,
    MockGraphProvider,
)

logger = logging.getLogger("orchestrix.impact_analysis")


@dataclass
class ImpactAnalysisResult:
    """
    Result of evaluating the blast radius and structural exposure of a code symbol or file.

    Note: The risk_score (0.0 to 100.0) and risk_level (LOW, MEDIUM, HIGH, CRITICAL)
    represent a heuristic structural exposure metric derived from graph topology,
    call depth, dependent counts, exposed public routes, and automated test coverage.
    It is not an empirical statistical prediction of regression or bug probability.
    """

    target_id: str
    target_name: str
    target_type: str
    risk_level: str  # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    risk_score: float  # 0.0 to 100.0
    score_type: str = "heuristic_structural_exposure"
    score_label: str = "Blast Radius & Structural Exposure Score"
    reasons: list[str] = field(default_factory=list)
    direct_dependents: list[dict[str, Any]] = field(default_factory=list)
    indirect_dependents: list[dict[str, Any]] = field(default_factory=list)
    affected_endpoints: list[dict[str, Any]] = field(default_factory=list)
    affected_tests: list[dict[str, Any]] = field(default_factory=list)
    affected_database_models: list[dict[str, Any]] = field(default_factory=list)
    subgraph: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "target_name": self.target_name,
            "target_type": self.target_type,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "score_type": self.score_type,
            "score_label": self.score_label,
            "reasons": self.reasons,
            "direct_dependents": self.direct_dependents,
            "indirect_dependents": self.indirect_dependents,
            "affected_endpoints": self.affected_endpoints,
            "affected_tests": self.affected_tests,
            "affected_database_models": self.affected_database_models,
            "subgraph": self.subgraph,
        }


class ImpactAnalysisEngine:
    """
    Computes code change blast radius and structural exposure score using the Knowledge Graph.
    Identifies direct callers, downstream dependents, exposed API routes,
    database models, and recommended test cases to verify.

    Clarification: This engine evaluates structural exposure (a heuristic metric based
    on graph topology and exposure vectors). It does NOT predict statistical regression risk.
    """

    def __init__(self, provider: BaseGraphProvider) -> None:
        self.provider = provider

    async def analyze_impact(
        self,
        snapshot_id: str,
        file_path: str | None = None,
        symbol_name: str | None = None,
        symbol_id: str | None = None,
        max_depth: int = 3,
    ) -> ImpactAnalysisResult:
        """
        Analyze code change blast radius across graph relationships.
        """
        if isinstance(self.provider, MockGraphProvider):
            return self._mock_analyze_impact(
                snapshot_id=snapshot_id,
                file_path=file_path,
                symbol_name=symbol_name,
                symbol_id=symbol_id,
                max_depth=max_depth,
            )

        # For Neo4j provider, we can query subgraphs or leverage Cypher traversal
        return await self._neo4j_analyze_impact(
            snapshot_id=snapshot_id,
            file_path=file_path,
            symbol_name=symbol_name,
            symbol_id=symbol_id,
            max_depth=max_depth,
        )

    def _mock_analyze_impact(
        self,
        snapshot_id: str,
        file_path: str | None,
        symbol_name: str | None,
        symbol_id: str | None,
        max_depth: int,
    ) -> ImpactAnalysisResult:
        mock = self.provider
        assert isinstance(mock, MockGraphProvider)

        # 1. Locate starting root node(s)
        start_nodes: list[GraphNode] = []
        if symbol_id and symbol_id in mock.nodes:
            start_nodes.append(mock.nodes[symbol_id])
        elif file_path and symbol_name:
            for n in mock.nodes.values():
                if (
                    n.properties.get("file_path") == file_path
                    and n.properties.get("name") == symbol_name
                ):
                    start_nodes.append(n)
                    break
        elif file_path:
            file_node_id = f"file:{snapshot_id}:{file_path}"
            if file_node_id in mock.nodes:
                start_nodes.append(mock.nodes[file_node_id])
            # Also include symbols in file
            for n in mock.nodes.values():
                if n.properties.get("file_path") == file_path:
                    start_nodes.append(n)
        elif symbol_name:
            for n in mock.nodes.values():
                if n.properties.get("name") == symbol_name:
                    start_nodes.append(n)

        if not start_nodes:
            return ImpactAnalysisResult(
                target_id=symbol_id or file_path or symbol_name or "unknown",
                target_name=symbol_name or file_path or "unknown",
                target_type="Unknown",
                risk_level="LOW",
                risk_score=0.0,
                reasons=["No matching code entities found in knowledge graph"],
            )

        root = start_nodes[0]
        root_id = root.id
        root_name = root.properties.get("name") or root.properties.get("file_path") or root.id
        root_type = root.label

        # 2. Traverse upstream dependents (nodes that depend on root or its contained symbols)
        start_ids = {n.id for n in start_nodes}
        visited_nodes: dict[str, int] = dict.fromkeys(start_ids, 0)
        queue: collections.deque[tuple[str, int]] = collections.deque(
            [(nid, 0) for nid in start_ids]
        )

        impacted_nodes: list[GraphNode] = list(start_nodes)
        impacted_edges: list[GraphRelationship] = []

        direct_dependents: list[dict[str, Any]] = []
        indirect_dependents: list[dict[str, Any]] = []
        affected_endpoints: list[dict[str, Any]] = []
        affected_tests: list[dict[str, Any]] = []
        affected_database_models: list[dict[str, Any]] = []

        while queue:
            curr_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            # Check incoming edges (who calls, imports, extends, tests this)
            for in_rel in mock.in_edges.get(curr_id, []):
                if in_rel.type in ("CONTAINS",):
                    continue  # Don't walk backwards up the file hierarchy container

                dep_id = in_rel.source_id
                dep_node = mock.nodes.get(dep_id)
                if not dep_node:
                    continue

                impacted_edges.append(in_rel)

                if dep_id not in visited_nodes:
                    visited_nodes[dep_id] = depth + 1
                    impacted_nodes.append(dep_node)
                    queue.append((dep_id, depth + 1))

                    dep_dict = {
                        "id": dep_node.id,
                        "name": dep_node.properties.get("name", dep_node.id),
                        "label": dep_node.label,
                        "file_path": dep_node.properties.get("file_path", ""),
                        "relationship": in_rel.type,
                        "depth": depth + 1,
                    }

                    if depth == 0:
                        direct_dependents.append(dep_dict)
                    else:
                        indirect_dependents.append(dep_dict)

                    if dep_node.label == "TestCase" or in_rel.type == "TESTS":
                        affected_tests.append(dep_dict)

            # Check outgoing edges for exposed endpoints or database tables
            for out_rel in mock.out_edges.get(curr_id, []):
                if out_rel.type in ("EXPOSES", "DEFINES", "READS_FROM", "WRITES_TO"):
                    tgt_id = out_rel.target_id
                    tgt_node = mock.nodes.get(tgt_id)
                    if tgt_node:
                        impacted_edges.append(out_rel)
                        if tgt_id not in visited_nodes:
                            visited_nodes[tgt_id] = depth + 1
                            impacted_nodes.append(tgt_node)

                        tgt_dict = {
                            "id": tgt_node.id,
                            "name": tgt_node.properties.get("name")
                            or tgt_node.properties.get("table_name")
                            or tgt_node.properties.get("path")
                            or tgt_node.id,
                            "label": tgt_node.label,
                            "file_path": tgt_node.properties.get("file_path", ""),
                            "relationship": out_rel.type,
                            "depth": depth + 1,
                        }

                        if tgt_node.label == "APIEndpoint":
                            affected_endpoints.append(tgt_dict)
                        elif tgt_node.label in ("DatabaseTable", "DatabaseModel"):
                            affected_database_models.append(tgt_dict)

        # 3. Compute Risk Assessment
        reasons: list[str] = []
        score = 0.0

        if direct_dependents:
            count = len(direct_dependents)
            score += min(30.0, count * 6.0)
            reasons.append(f"{count} direct dependent(s) (callers/importers/subclasses) affected")

        if indirect_dependents:
            count = len(indirect_dependents)
            score += min(20.0, count * 3.0)
            reasons.append(f"{count} indirect downstream dependent(s) affected")

        if affected_endpoints:
            count = len(affected_endpoints)
            score += min(25.0, count * 10.0)
            reasons.append(f"Exposes or modifies {count} public API endpoint(s)")

        if affected_database_models:
            count = len(affected_database_models)
            score += min(20.0, count * 10.0)
            reasons.append(f"Directly impacts {count} database model(s) / table(s)")

        if not affected_tests and (direct_dependents or affected_endpoints):
            score += 15.0
            reasons.append("No automated test cases found covering this symbol")
        elif affected_tests:
            reasons.append(f"{len(affected_tests)} test case(s) verify this code path")

        score = min(100.0, score)

        if score >= 70.0:
            risk_level = "CRITICAL"
        elif score >= 45.0:
            risk_level = "HIGH"
        elif score >= 20.0:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        if not reasons:
            reasons.append("Isolated change with no detected downstream dependents")

        subgraph = {
            "nodes": [n.to_dict() for n in impacted_nodes],
            "edges": [e.to_dict() for e in impacted_edges],
            "total_nodes": len(impacted_nodes),
            "total_edges": len(impacted_edges),
        }

        return ImpactAnalysisResult(
            target_id=root_id,
            target_name=root_name,
            target_type=root_type,
            risk_level=risk_level,
            risk_score=round(score, 1),
            reasons=reasons,
            direct_dependents=direct_dependents,
            indirect_dependents=indirect_dependents,
            affected_endpoints=affected_endpoints,
            affected_tests=affected_tests,
            affected_database_models=affected_database_models,
            subgraph=subgraph,
        )

    async def _neo4j_analyze_impact(
        self,
        snapshot_id: str,
        file_path: str | None,
        symbol_name: str | None,
        symbol_id: str | None,
        max_depth: int,
    ) -> ImpactAnalysisResult:
        # Fallback to subgraph fetch and mock-like evaluation
        subgraph = await self.provider.get_subgraph(
            snapshot_id=snapshot_id,
            file_path=file_path,
            limit=200,
        )
        mock = MockGraphProvider()
        nodes = [
            GraphNode(id=n["id"], label=n["label"], properties=n.get("properties", {}))
            for n in subgraph.get("nodes", [])
        ]
        rels = [
            GraphRelationship(
                source_id=e["source_id"],
                target_id=e["target_id"],
                type=e["type"],
                properties=e.get("properties", {}),
            )
            for e in subgraph.get("edges", [])
        ]
        await mock.upsert_nodes(nodes)
        await mock.upsert_relationships(rels)

        engine = ImpactAnalysisEngine(mock)
        return await engine.analyze_impact(
            snapshot_id=snapshot_id,
            file_path=file_path,
            symbol_name=symbol_name,
            symbol_id=symbol_id,
            max_depth=max_depth,
        )
