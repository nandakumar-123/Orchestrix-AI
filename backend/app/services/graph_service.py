from __future__ import annotations

import asyncio
import logging
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, cast

from app.core.config import settings

logger = logging.getLogger("orchestrix.graph")


# -----------------------------------------------------------------------------
# Data Models for Knowledge Graph
# -----------------------------------------------------------------------------


@dataclass
class GraphNode:
    id: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "properties": self.properties,
        }


@dataclass
class GraphRelationship:
    source_id: str
    target_id: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "type": self.type,
            "properties": self.properties,
        }


# -----------------------------------------------------------------------------
# Base Graph Provider
# -----------------------------------------------------------------------------


class BaseGraphProvider(ABC):
    """Abstract Base Class for graph database providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the graph provider (e.g., 'neo4j', 'mock')."""
        pass

    @abstractmethod
    async def execute_query(
        self, cypher: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a raw or parameterized Cypher query."""
        pass

    @abstractmethod
    async def upsert_nodes(self, nodes: list[GraphNode]) -> int:
        """Batch upsert graph nodes."""
        pass

    @abstractmethod
    async def upsert_relationships(self, relationships: list[GraphRelationship]) -> int:
        """Batch upsert graph relationships."""
        pass

    @abstractmethod
    async def delete_snapshot_graph(self, snapshot_id: uuid.UUID | str) -> int:
        """Delete all nodes and relationships associated with a snapshot."""
        pass

    @abstractmethod
    async def get_subgraph(
        self,
        snapshot_id: uuid.UUID | str,
        labels: list[str] | None = None,
        file_path: str | None = None,
        limit: int = 150,
    ) -> dict[str, Any]:
        """Fetch nodes and edges for visual explorer and context filtering."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify connectivity to the graph database."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close driver or release connections."""
        pass


# -----------------------------------------------------------------------------
# Mock Graph Provider (Deterministic In-Memory Graph for Offline Tests)
# -----------------------------------------------------------------------------


class MockGraphProvider(BaseGraphProvider):
    """
    In-memory graph engine providing deterministic offline graph capabilities,
    symbol traversal, impact tracing, cycle detection, and Cypher emulation.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.relationships: list[GraphRelationship] = []
        self.out_edges: dict[str, list[GraphRelationship]] = {}
        self.in_edges: dict[str, list[GraphRelationship]] = {}
        self._lock = asyncio.Lock()

    @property
    def provider_name(self) -> str:
        return "mock"

    async def health_check(self) -> bool:
        return True

    async def close(self) -> None:
        async with self._lock:
            self.nodes.clear()
            self.relationships.clear()
            self.out_edges.clear()
            self.in_edges.clear()

    async def upsert_nodes(self, nodes: list[GraphNode]) -> int:
        async with self._lock:
            count = 0
            for node in nodes:
                if node.id in self.nodes:
                    existing = self.nodes[node.id]
                    existing.label = node.label
                    existing.properties.update(node.properties)
                else:
                    self.nodes[node.id] = GraphNode(
                        id=node.id,
                        label=node.label,
                        properties=dict(node.properties),
                    )
                count += 1
            return count

    async def upsert_relationships(self, relationships: list[GraphRelationship]) -> int:
        async with self._lock:
            count = 0
            for rel in relationships:
                # Key for deduplication
                found = False
                for existing in self.relationships:
                    if (
                        existing.source_id == rel.source_id
                        and existing.target_id == rel.target_id
                        and existing.type == rel.type
                    ):
                        existing.properties.update(rel.properties)
                        found = True
                        break
                if not found:
                    new_rel = GraphRelationship(
                        source_id=rel.source_id,
                        target_id=rel.target_id,
                        type=rel.type,
                        properties=dict(rel.properties),
                    )
                    self.relationships.append(new_rel)
                    self.out_edges.setdefault(rel.source_id, []).append(new_rel)
                    self.in_edges.setdefault(rel.target_id, []).append(new_rel)
                count += 1
            return count

    async def delete_snapshot_graph(self, snapshot_id: uuid.UUID | str) -> int:
        sid = str(snapshot_id)
        async with self._lock:
            nodes_to_delete = {
                nid
                for nid, n in self.nodes.items()
                if str(n.properties.get("snapshot_id", "")) == sid
                or nid.startswith(f"snap:{sid}")
                or nid.startswith(f"file:{sid}")
                or nid.startswith(f"sym:{sid}")
                or nid.startswith(f"api:{sid}")
                or nid.startswith(f"model:{sid}")
                or nid.startswith(f"tbl:{sid}")
            }

            for nid in nodes_to_delete:
                del self.nodes[nid]

            kept_rels = []
            for r in self.relationships:
                if r.source_id in nodes_to_delete or r.target_id in nodes_to_delete:
                    continue
                if str(r.properties.get("snapshot_id", "")) == sid:
                    continue
                kept_rels.append(r)

            self.relationships = kept_rels
            self.out_edges.clear()
            self.in_edges.clear()
            for r in self.relationships:
                self.out_edges.setdefault(r.source_id, []).append(r)
                self.in_edges.setdefault(r.target_id, []).append(r)

            return len(nodes_to_delete)

    async def get_subgraph(
        self,
        snapshot_id: uuid.UUID | str,
        labels: list[str] | None = None,
        file_path: str | None = None,
        limit: int = 150,
    ) -> dict[str, Any]:
        sid = str(snapshot_id)
        async with self._lock:
            matched_nodes: list[dict[str, Any]] = []
            matched_node_ids: set[str] = set()

            for n in self.nodes.values():
                node_sid = str(n.properties.get("snapshot_id", ""))
                is_snap_match = (
                    node_sid == sid
                    or n.id.startswith(f"snap:{sid}")
                    or n.id.startswith(f"file:{sid}")
                    or n.id.startswith(f"sym:{sid}")
                    or n.id.startswith(f"api:{sid}")
                    or n.id.startswith(f"model:{sid}")
                    or n.id.startswith(f"tbl:{sid}")
                )
                if not is_snap_match:
                    continue

                if labels and n.label not in labels:
                    continue

                if file_path and n.properties.get("file_path") != file_path:
                    continue

                matched_nodes.append(n.to_dict())
                matched_node_ids.add(n.id)
                if len(matched_nodes) >= limit:
                    break

            matched_edges: list[dict[str, Any]] = []
            for r in self.relationships:
                if r.source_id in matched_node_ids and r.target_id in matched_node_ids:
                    matched_edges.append(r.to_dict())

            return {
                "nodes": matched_nodes,
                "edges": matched_edges,
                "total_nodes": len(matched_nodes),
                "total_edges": len(matched_edges),
            }

    async def execute_query(
        self, cypher: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        params = parameters or {}
        cleaned = cypher.strip()

        # Simple health / ping query
        if "RETURN 1" in cleaned:
            return [{"alive": 1}]

        # Node count query
        if "count(n)" in cleaned.lower() and "count(r)" in cleaned.lower():
            sid = str(params.get("snapshot_id", ""))
            subgraph = await self.get_subgraph(snapshot_id=sid, limit=100000)
            return [
                {
                    "node_count": subgraph["total_nodes"],
                    "relationship_count": subgraph["total_edges"],
                }
            ]

        # Callers query
        if "[:CALLS]" in cleaned and "target_id" in params:
            target_id = params["target_id"]
            callers = []
            for rel in self.in_edges.get(target_id, []):
                if rel.type == "CALLS":
                    caller_node = self.nodes.get(rel.source_id)
                    if caller_node:
                        callers.append(
                            {
                                "caller": caller_node.to_dict(),
                                "relationship": rel.to_dict(),
                            }
                        )
            return callers

        # Interface implementations query
        if "[:IMPLEMENTS]" in cleaned and "interface_id" in params:
            iface_id = params["interface_id"]
            impls = []
            for rel in self.in_edges.get(iface_id, []):
                if rel.type == "IMPLEMENTS":
                    impl_node = self.nodes.get(rel.source_id)
                    if impl_node:
                        impls.append(
                            {
                                "implementation": impl_node.to_dict(),
                                "relationship": rel.to_dict(),
                            }
                        )
            return impls

        # Fallback empty query result
        return []


# -----------------------------------------------------------------------------
# Neo4j Graph Provider (Official neo4j Async Driver)
# -----------------------------------------------------------------------------


class Neo4jGraphProvider(BaseGraphProvider):
    """
    Production-grade Neo4j graph provider connecting to Neo4j Aura or self-hosted
    cluster using the official async Python driver with connection pooling.
    """

    def __init__(
        self,
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j",
    ) -> None:
        self.uri = uri
        self.username = username
        self.password = password
        self.database = database
        self._driver: Any = None

    @property
    def provider_name(self) -> str:
        return "neo4j"

    def _get_driver(self) -> Any:
        if self._driver is None:
            try:
                from neo4j import AsyncGraphDatabase

                self._driver = AsyncGraphDatabase.driver(
                    self.uri,
                    auth=(self.username, self.password),
                    max_connection_lifetime=3600,
                    max_connection_pool_size=50,
                    connection_acquisition_timeout=30.0,
                )
            except Exception as e:
                logger.error(f"Failed to initialize Neo4j AsyncGraphDatabase driver: {e}")
                raise
        return self._driver

    async def health_check(self) -> bool:
        try:
            driver = self._get_driver()
            async with driver.session(database=self.database) as session:
                result = await session.run("RETURN 1 AS alive")
                record = await result.single()
                return record is not None and record["alive"] == 1
        except Exception as e:
            logger.warning(f"Neo4j health check failed: {e}")
            return False

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    async def execute_query(
        self, cypher: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        driver = self._get_driver()
        async with driver.session(database=self.database) as session:
            result = await session.run(cypher, parameters or {})
            records = await result.data()
            return cast(list[dict[str, Any]], records)

    async def upsert_nodes(self, nodes: list[GraphNode]) -> int:
        if not nodes:
            return 0

        driver = self._get_driver()
        batch_size = 500
        total_upserted = 0

        # Parameterized query with UNWIND
        cypher = """
        UNWIND $batch AS item
        MERGE (n:CodeEntity {id: item.id})
        ON CREATE SET n += item.properties, n.label = item.label, n.created_at = timestamp()
        ON MATCH SET n += item.properties, n.label = item.label, n.updated_at = timestamp()
        """

        raw_batch = [n.to_dict() for n in nodes]
        for i in range(0, len(raw_batch), batch_size):
            chunk = raw_batch[i : i + batch_size]
            async with driver.session(database=self.database) as session:
                await session.run(cypher, {"batch": chunk})
                total_upserted += len(chunk)

        return total_upserted

    async def upsert_relationships(self, relationships: list[GraphRelationship]) -> int:
        if not relationships:
            return 0

        driver = self._get_driver()
        batch_size = 500
        total_upserted = 0

        # Parameterized relationship upsert
        cypher = """
        UNWIND $batch AS rel
        MATCH (a:CodeEntity {id: rel.source_id})
        MATCH (b:CodeEntity {id: rel.target_id})
        MERGE (a)-[r:RELATED {type: rel.type}]->(b)
        ON CREATE SET r += rel.properties, r.created_at = timestamp()
        ON MATCH SET r += rel.properties, r.updated_at = timestamp()
        """

        raw_batch = [r.to_dict() for r in relationships]
        for i in range(0, len(raw_batch), batch_size):
            chunk = raw_batch[i : i + batch_size]
            async with driver.session(database=self.database) as session:
                await session.run(cypher, {"batch": chunk})
                total_upserted += len(chunk)

        return total_upserted

    async def delete_snapshot_graph(self, snapshot_id: uuid.UUID | str) -> int:
        driver = self._get_driver()
        sid = str(snapshot_id)
        cypher = """
        MATCH (n:CodeEntity)
        WHERE n.snapshot_id = $snapshot_id
        DETACH DELETE n
        """
        async with driver.session(database=self.database) as session:
            result = await session.run(cypher, {"snapshot_id": sid})
            summary = await result.consume()
            return int(summary.counters.nodes_deleted)

    async def get_subgraph(
        self,
        snapshot_id: uuid.UUID | str,
        labels: list[str] | None = None,
        file_path: str | None = None,
        limit: int = 150,
    ) -> dict[str, Any]:
        driver = self._get_driver()
        sid = str(snapshot_id)

        cypher = """
        MATCH (n:CodeEntity {snapshot_id: $snapshot_id})
        WHERE ($labels IS NULL OR n.label IN $labels)
          AND ($file_path IS NULL OR n.file_path = $file_path)
        WITH n LIMIT $limit
        OPTIONAL MATCH (n)-[r:RELATED]->(m:CodeEntity {snapshot_id: $snapshot_id})
        RETURN collect(DISTINCT n) AS nodes, collect(DISTINCT {source_id: n.id, target_id: m.id, type: r.type, properties: properties(r)}) AS edges
        """

        async with driver.session(database=self.database) as session:
            result = await session.run(
                cypher,
                {
                    "snapshot_id": sid,
                    "labels": labels if labels else None,
                    "file_path": file_path if file_path else None,
                    "limit": limit,
                },
            )
            data = await result.single()
            if not data:
                return {"nodes": [], "edges": [], "total_nodes": 0, "total_edges": 0}

            raw_nodes = data.get("nodes", [])
            raw_edges = [e for e in data.get("edges", []) if e.get("target_id") is not None]

            nodes = [
                {
                    "id": n["id"],
                    "label": n.get("label", "CodeEntity"),
                    "properties": dict(n),
                }
                for n in raw_nodes
            ]

            return {
                "nodes": nodes,
                "edges": raw_edges,
                "total_nodes": len(nodes),
                "total_edges": len(raw_edges),
            }


# -----------------------------------------------------------------------------
# Graph Provider Factory & Singleton Cache
# -----------------------------------------------------------------------------

_CACHED_GRAPH_PROVIDER: BaseGraphProvider | None = None


def set_cached_graph_provider(provider: BaseGraphProvider | None) -> None:
    """Set or override the cached graph provider (used in tests)."""
    global _CACHED_GRAPH_PROVIDER
    _CACHED_GRAPH_PROVIDER = provider


def get_graph_provider() -> BaseGraphProvider:
    """
    Factory function returning the active graph provider.
    Defaults to MockGraphProvider if Neo4j is not configured or in offline/test environment.
    """
    global _CACHED_GRAPH_PROVIDER
    if _CACHED_GRAPH_PROVIDER is not None:
        return _CACHED_GRAPH_PROVIDER

    configured_provider = os.environ.get("ORCHESTRIX_GRAPH_PROVIDER", "").strip().lower()

    if configured_provider == "mock":
        _CACHED_GRAPH_PROVIDER = MockGraphProvider()
        return _CACHED_GRAPH_PROVIDER

    uri = settings.NEO4J_URI.strip()
    if (
        uri
        and (
            uri.startswith("bolt://")
            or uri.startswith("neo4j://")
            or uri.startswith("neo4j+s://")
            or uri.startswith("bolt+s://")
        )
        and settings.NEO4J_USERNAME
        and settings.NEO4J_PASSWORD
    ):
        try:
            _CACHED_GRAPH_PROVIDER = Neo4jGraphProvider(
                uri=uri,
                username=settings.NEO4J_USERNAME,
                password=settings.NEO4J_PASSWORD,
                database=settings.NEO4J_DATABASE or "neo4j",
            )
            return _CACHED_GRAPH_PROVIDER
        except Exception as e:
            logger.warning(f"Could not connect to Neo4j, falling back to MockGraphProvider: {e}")
            _CACHED_GRAPH_PROVIDER = MockGraphProvider()
            return _CACHED_GRAPH_PROVIDER

    # Default to deterministic MockGraphProvider
    _CACHED_GRAPH_PROVIDER = MockGraphProvider()
    return _CACHED_GRAPH_PROVIDER
