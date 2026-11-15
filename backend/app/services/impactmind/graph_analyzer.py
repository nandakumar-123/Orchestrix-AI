from __future__ import annotations

import collections
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.services.graph_service import (
    BaseGraphProvider,
    GraphNode,
    GraphRelationship,
    get_graph_provider,
)
from app.services.impactmind.ast_classifier import ClassifiedChange

logger = logging.getLogger("orchestrix.impactmind.graph_analyzer")


@dataclass
class GraphImpactNode:
    id: str
    name: str
    label: str
    file_path: str
    impact_type: str  # "direct_dependent" | "indirect_dependent" | "exposed_endpoint" | "database_model" | "affected_test"
    depth: int
    relationship_type: str
    confidence: float
    evidence: str | None = None
    is_uncertain: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "label": self.label,
            "file_path": self.file_path,
            "impact_type": self.impact_type,
            "depth": self.depth,
            "relationship_type": self.relationship_type,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "is_uncertain": self.is_uncertain,
        }


@dataclass
class GraphImpactAnalysisResult:
    target_changes: list[ClassifiedChange]
    direct_dependents: list[GraphImpactNode] = field(default_factory=list)
    indirect_dependents: list[GraphImpactNode] = field(default_factory=list)
    exposed_endpoints: list[GraphImpactNode] = field(default_factory=list)
    database_models: list[GraphImpactNode] = field(default_factory=list)
    affected_tests: list[GraphImpactNode] = field(default_factory=list)
    uncertain_dependents: list[GraphImpactNode] = field(default_factory=list)
    subgraph: dict[str, Any] = field(default_factory=dict)
    is_degraded: bool = False
    provider_name: str = "mock"


class GraphImpactAnalyzer:
    """
    Traverses the repository knowledge graph to trace multi-hop blast radius,
    callers, downstream dependents, exposed API routes, database tables,
    and automated test suites.
    """

    def __init__(self, provider: BaseGraphProvider | None = None) -> None:
        self.provider = provider or get_graph_provider()

    async def analyze_impact(
        self,
        snapshot_id: uuid.UUID | str,
        changes: list[ClassifiedChange],
        max_depth: int = 3,
        min_confidence: float = 0.5,
    ) -> GraphImpactAnalysisResult:
        """
        Analyze code change blast radius across knowledge graph nodes.
        Uses in-memory traversal for Mock provider, and graph queries for Neo4j.
        """
        is_healthy = False
        try:
            is_healthy = await self.provider.health_check()
        except Exception as e:
            logger.warning(f"Graph provider health check failed: {e}")

        if not is_healthy:
            logger.warning("Graph provider is offline or degraded; returning degraded analysis")
            return GraphImpactAnalysisResult(
                target_changes=changes,
                is_degraded=True,
                provider_name=self.provider.provider_name,
            )

        sid = str(snapshot_id)

        # 1. Fetch relevant subgraph
        subgraph = await self.provider.get_subgraph(snapshot_id=sid, limit=500)
        nodes_dict: dict[str, GraphNode] = {
            n["id"]: GraphNode(id=n["id"], label=n["label"], properties=n.get("properties", {}))
            for n in subgraph.get("nodes", [])
        }
        edges_list: list[GraphRelationship] = [
            GraphRelationship(
                source_id=e["source_id"],
                target_id=e["target_id"],
                type=e["type"],
                properties=e.get("properties", {}),
            )
            for e in subgraph.get("edges", [])
        ]

        # Index incoming and outgoing edges for BFS
        in_edges: dict[str, list[GraphRelationship]] = {}
        out_edges: dict[str, list[GraphRelationship]] = {}
        for r in edges_list:
            out_edges.setdefault(r.source_id, []).append(r)
            in_edges.setdefault(r.target_id, []).append(r)

        # 2. Locate starting root nodes for the changed symbols and files
        root_ids: set[str] = set()
        for c in changes:
            # Check symbol node
            if c.symbol_name:
                for nid, node in nodes_dict.items():
                    n_file = node.properties.get("file_path", "")
                    n_name = node.properties.get("name", "")
                    if n_file == c.file_path and n_name == c.symbol_name:
                        root_ids.add(nid)
            # Check file node
            file_node_id = f"file:{sid}:{c.file_path}"
            if file_node_id in nodes_dict:
                root_ids.add(file_node_id)

        # 3. BFS Traversal
        visited_nodes: dict[str, int] = dict.fromkeys(root_ids, 0)
        queue: collections.deque[tuple[str, int]] = collections.deque((rid, 0) for rid in root_ids)

        direct_deps: list[GraphImpactNode] = []
        indirect_deps: list[GraphImpactNode] = []
        exposed_endpoints: list[GraphImpactNode] = []
        database_models: list[GraphImpactNode] = []
        affected_tests: list[GraphImpactNode] = []
        uncertain_deps: list[GraphImpactNode] = []

        visited_edges: list[GraphRelationship] = []

        while queue:
            curr_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            # Check incoming edges (who calls, imports, extends, or tests this node)
            for in_rel in in_edges.get(curr_id, []):
                if in_rel.type in ("CONTAINS",):
                    continue  # Do not traverse backwards into directory or container containers

                dep_id = in_rel.source_id
                dep_node = nodes_dict.get(dep_id)
                if not dep_node:
                    continue

                visited_edges.append(in_rel)
                rel_conf = float(in_rel.properties.get("confidence", 1.0))
                is_uncertain = (
                    rel_conf < min_confidence or in_rel.properties.get("status") == "unresolved"
                )

                if dep_id not in visited_nodes:
                    visited_nodes[dep_id] = depth + 1
                    queue.append((dep_id, depth + 1))

                    dep_obj = GraphImpactNode(
                        id=dep_node.id,
                        name=dep_node.properties.get("name") or dep_node.id,
                        label=dep_node.label,
                        file_path=dep_node.properties.get("file_path", ""),
                        impact_type="direct_dependent" if depth == 0 else "indirect_dependent",
                        depth=depth + 1,
                        relationship_type=in_rel.type,
                        confidence=rel_conf,
                        evidence=in_rel.properties.get("evidence")
                        or in_rel.properties.get("raw_statement"),
                        is_uncertain=is_uncertain,
                    )

                    if is_uncertain:
                        uncertain_deps.append(dep_obj)
                    elif depth == 0:
                        direct_deps.append(dep_obj)
                    else:
                        indirect_deps.append(dep_obj)

                    if dep_node.label == "TestCase" or in_rel.type == "TESTS":
                        test_obj = GraphImpactNode(
                            id=dep_node.id,
                            name=dep_node.properties.get("name") or dep_node.id,
                            label="TestCase",
                            file_path=dep_node.properties.get("file_path", ""),
                            impact_type="affected_test",
                            depth=depth + 1,
                            relationship_type=in_rel.type,
                            confidence=rel_conf,
                            evidence=in_rel.properties.get("evidence"),
                            is_uncertain=is_uncertain,
                        )
                        affected_tests.append(test_obj)

            # Check outgoing edges (exposed public endpoints or database models defined/modified)
            for out_rel in out_edges.get(curr_id, []):
                if out_rel.type in ("EXPOSES", "DEFINES", "READS_FROM", "WRITES_TO"):
                    tgt_id = out_rel.target_id
                    tgt_node = nodes_dict.get(tgt_id)
                    if not tgt_node:
                        continue

                    visited_edges.append(out_rel)
                    rel_conf = float(out_rel.properties.get("confidence", 1.0))

                    if tgt_id not in visited_nodes:
                        visited_nodes[tgt_id] = depth + 1
                        queue.append((tgt_id, depth + 1))

                        out_obj = GraphImpactNode(
                            id=tgt_node.id,
                            name=tgt_node.properties.get("name")
                            or tgt_node.properties.get("table_name")
                            or tgt_node.properties.get("path")
                            or tgt_node.id,
                            label=tgt_node.label,
                            file_path=tgt_node.properties.get("file_path", ""),
                            impact_type="exposed_endpoint"
                            if tgt_node.label in ("APIEndpoint", "Endpoint")
                            else "database_model",
                            depth=depth + 1,
                            relationship_type=out_rel.type,
                            confidence=rel_conf,
                            evidence=out_rel.properties.get("evidence"),
                            is_uncertain=False,
                        )

                        if tgt_node.label in ("APIEndpoint", "Endpoint"):
                            exposed_endpoints.append(out_obj)
                        elif tgt_node.label in ("DatabaseTable", "DatabaseModel"):
                            database_models.append(out_obj)

        impacted_nodes = [nodes_dict[nid].to_dict() for nid in visited_nodes if nid in nodes_dict]
        impacted_subgraph = {
            "nodes": impacted_nodes,
            "edges": [e.to_dict() for e in visited_edges],
            "total_nodes": len(impacted_nodes),
            "total_edges": len(visited_edges),
        }

        return GraphImpactAnalysisResult(
            target_changes=changes,
            direct_dependents=direct_deps,
            indirect_dependents=indirect_deps,
            exposed_endpoints=exposed_endpoints,
            database_models=database_models,
            affected_tests=affected_tests,
            uncertain_dependents=uncertain_deps,
            subgraph=impacted_subgraph,
            is_degraded=False,
            provider_name=self.provider.provider_name,
        )
