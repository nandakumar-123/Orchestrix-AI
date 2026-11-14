from __future__ import annotations

import collections
import logging
from typing import Any, cast

from app.services.graph_service import (
    BaseGraphProvider,
    GraphRelationship,
    MockGraphProvider,
)

logger = logging.getLogger("orchestrix.graph_query")


class GraphQueryEngine:
    """
    High-level query engine over the repository knowledge graph.
    Supports provider-agnostic queries (works with both Neo4j and MockGraphProvider).
    """

    def __init__(self, provider: BaseGraphProvider) -> None:
        self.provider = provider

    async def find_callers(
        self,
        snapshot_id: str,
        target_symbol_id: str,
        max_depth: int = 3,
    ) -> list[dict[str, Any]]:
        """Find callers of a symbol up to max_depth."""
        if isinstance(self.provider, MockGraphProvider):
            return self._mock_find_callers(target_symbol_id, max_depth)

        cypher = (
            """
        MATCH path = (caller:CodeEntity)-[:RELATED*1.."""
            + str(max_depth)
            + """]->(target:CodeEntity {id: $target_id})
        WHERE all(r in relationships(path) WHERE r.type = 'CALLS')
        RETURN caller, relationships(path) as rels, length(path) as depth
        ORDER BY depth ASC
        LIMIT 50
        """
        )
        records = await self.provider.execute_query(cypher, {"target_id": target_symbol_id})
        results = []
        for rec in records:
            results.append(
                {
                    "caller": rec.get("caller"),
                    "depth": rec.get("depth", 1),
                }
            )
        return results

    def _mock_find_callers(self, target_symbol_id: str, max_depth: int) -> list[dict[str, Any]]:
        mock = self.provider
        assert isinstance(mock, MockGraphProvider)

        visited: set[str] = set()
        queue: collections.deque[tuple[str, int]] = collections.deque([(target_symbol_id, 0)])
        results: list[dict[str, Any]] = []

        while queue:
            curr_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            for in_rel in mock.in_edges.get(curr_id, []):
                if in_rel.type == "CALLS" and in_rel.source_id not in visited:
                    visited.add(in_rel.source_id)
                    caller_node = mock.nodes.get(in_rel.source_id)
                    if caller_node:
                        results.append(
                            {
                                "caller": caller_node.to_dict(),
                                "relationship": in_rel.to_dict(),
                                "depth": depth + 1,
                            }
                        )
                        queue.append((in_rel.source_id, depth + 1))

        return results

    async def find_implementations(
        self,
        snapshot_id: str,
        interface_symbol_id: str,
    ) -> list[dict[str, Any]]:
        """Find implementations of an interface."""
        if isinstance(self.provider, MockGraphProvider):
            mock = self.provider
            impls = []
            for in_rel in mock.in_edges.get(interface_symbol_id, []):
                if in_rel.type in ("IMPLEMENTS", "EXTENDS"):
                    node = mock.nodes.get(in_rel.source_id)
                    if node:
                        impls.append(
                            {
                                "implementation": node.to_dict(),
                                "relationship": in_rel.to_dict(),
                            }
                        )
            return impls

        cypher = """
        MATCH (impl:CodeEntity)-[r:RELATED]->(iface:CodeEntity {id: $interface_id})
        WHERE r.type IN ['IMPLEMENTS', 'EXTENDS']
        RETURN impl, r
        """
        records = await self.provider.execute_query(cypher, {"interface_id": interface_symbol_id})
        return [
            {"implementation": rec.get("impl"), "relationship": rec.get("r")} for rec in records
        ]

    async def find_importing_files(
        self,
        snapshot_id: str,
        file_path: str,
    ) -> list[dict[str, Any]]:
        """Find files that import the target file."""
        target_file_id = f"file:{snapshot_id}:{file_path}"
        if isinstance(self.provider, MockGraphProvider):
            mock = self.provider
            importers = []
            for in_rel in mock.in_edges.get(target_file_id, []):
                if in_rel.type == "IMPORTS":
                    node = mock.nodes.get(in_rel.source_id)
                    if node:
                        importers.append(
                            {
                                "file": node.to_dict(),
                                "relationship": in_rel.to_dict(),
                            }
                        )
            return importers

        cypher = """
        MATCH (f:CodeEntity)-[r:RELATED]->(target:CodeEntity {id: $target_file_id})
        WHERE r.type = 'IMPORTS'
        RETURN f, r
        """
        records = await self.provider.execute_query(cypher, {"target_file_id": target_file_id})
        return [{"file": rec.get("f"), "relationship": rec.get("r")} for rec in records]

    async def find_dependencies(
        self,
        snapshot_id: str,
        node_id: str,
        direction: str = "outgoing",  # "outgoing", "incoming", or "both"
        max_depth: int = 2,
    ) -> list[dict[str, Any]]:
        """Find dependencies or dependents of any node."""
        if isinstance(self.provider, MockGraphProvider):
            mock = self.provider
            results: list[dict[str, Any]] = []
            visited: set[str] = set()
            queue: collections.deque[tuple[str, int]] = collections.deque([(node_id, 0)])

            while queue:
                curr_id, depth = queue.popleft()
                if depth >= max_depth:
                    continue

                edges_to_check: list[GraphRelationship] = []
                if direction in ("outgoing", "both"):
                    edges_to_check.extend(mock.out_edges.get(curr_id, []))
                if direction in ("incoming", "both"):
                    edges_to_check.extend(mock.in_edges.get(curr_id, []))

                for edge in edges_to_check:
                    next_id = edge.target_id if edge.source_id == curr_id else edge.source_id
                    if next_id not in visited and next_id != node_id:
                        visited.add(next_id)
                        target_node = mock.nodes.get(next_id)
                        if target_node:
                            results.append(
                                {
                                    "node": target_node.to_dict(),
                                    "relationship": edge.to_dict(),
                                    "depth": depth + 1,
                                }
                            )
                            queue.append((next_id, depth + 1))
            return results

        # Neo4j Cypher path query
        dir_syntax = (
            "-(r:RELATED)-"
            if direction == "both"
            else ("-[r:RELATED]->" if direction == "outgoing" else "<-[r:RELATED]-")
        )
        cypher = f"""
        MATCH path = (start:CodeEntity {{id: $node_id}}){dir_syntax}(target:CodeEntity)
        RETURN target, r, length(path) as depth
        LIMIT 50
        """
        records = await self.provider.execute_query(cypher, {"node_id": node_id})
        return [
            {
                "node": rec.get("target"),
                "relationship": rec.get("r"),
                "depth": rec.get("depth", 1),
            }
            for rec in records
        ]

    async def find_circular_dependencies(self, snapshot_id: str) -> list[list[str]]:
        """
        Detect cycles in imports across files in the snapshot.
        Returns lists of file paths forming circular import loops.
        """
        if isinstance(self.provider, MockGraphProvider):
            mock = self.provider
            # Build file adjacency graph
            file_prefix = f"file:{snapshot_id}:"
            adj: dict[str, list[str]] = {}
            for rel in mock.relationships:
                if (
                    rel.type == "IMPORTS"
                    and rel.source_id.startswith(file_prefix)
                    and rel.target_id.startswith(file_prefix)
                ):
                    src_path = rel.source_id[len(file_prefix) :]
                    tgt_path = rel.target_id[len(file_prefix) :]
                    adj.setdefault(src_path, []).append(tgt_path)

            cycles: list[list[str]] = []
            visited: set[str] = set()
            stack: list[str] = []
            stack_set: set[str] = set()

            def dfs(node: str) -> None:
                visited.add(node)
                stack.append(node)
                stack_set.add(node)

                for neighbor in adj.get(node, []):
                    if neighbor not in visited:
                        dfs(neighbor)
                    elif neighbor in stack_set:
                        # Cycle detected!
                        idx = stack.index(neighbor)
                        cycle = stack[idx:] + [neighbor]
                        if len(cycle) > 2 and cycle not in cycles:
                            cycles.append(cycle)

                stack.pop()
                stack_set.remove(node)

            for fnode in list(adj.keys()):
                if fnode not in visited:
                    dfs(fnode)

            return cycles

        # Neo4j cycle detection
        cypher = """
        MATCH (f1:CodeEntity {label: 'File', snapshot_id: $snapshot_id})
        MATCH path = (f1)-[:RELATED*2..5]->(f1)
        WHERE all(r in relationships(path) WHERE r.type = 'IMPORTS')
        RETURN [n in nodes(path) | n.file_path] as cycle
        LIMIT 10
        """
        records = await self.provider.execute_query(cypher, {"snapshot_id": snapshot_id})
        return [rec["cycle"] for rec in records if "cycle" in rec]

    async def trace_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 5,
    ) -> list[dict[str, Any]] | None:
        """Find the shortest relationship path between two nodes."""
        if isinstance(self.provider, MockGraphProvider):
            mock = self.provider
            queue: collections.deque[tuple[str, list[dict[str, Any]]]] = collections.deque(
                [(source_id, [])]
            )
            visited: set[str] = {source_id}

            while queue:
                curr_id, path = queue.popleft()
                if curr_id == target_id:
                    return path

                if len(path) >= max_depth:
                    continue

                for rel in mock.out_edges.get(curr_id, []):
                    if rel.target_id not in visited:
                        visited.add(rel.target_id)
                        queue.append(
                            (
                                rel.target_id,
                                path
                                + [
                                    {
                                        "source_id": rel.source_id,
                                        "target_id": rel.target_id,
                                        "type": rel.type,
                                    }
                                ],
                            )
                        )
            return None

        cypher = (
            """
        MATCH path = shortestPath((a:CodeEntity {id: $source_id})-[:RELATED*1.."""
            + str(max_depth)
            + """]->(b:CodeEntity {id: $target_id}))
        RETURN [r in relationships(path) | {source_id: startNode(r).id, target_id: endNode(r).id, type: r.type}] as path_steps
        """
        )
        records = await self.provider.execute_query(
            cypher, {"source_id": source_id, "target_id": target_id}
        )
        if records and records[0].get("path_steps"):
            return cast(list[dict[str, Any]], records[0]["path_steps"])
        return None
