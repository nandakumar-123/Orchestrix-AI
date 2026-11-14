from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from app.core.config import settings
from app.services.graph_service import (
    GraphNode,
    GraphRelationship,
    Neo4jGraphProvider,
)


async def _resolve_live_neo4j_provider() -> tuple[Neo4jGraphProvider | None, str]:
    """
    Attempt to connect to live Neo4j Aura / cluster.
    Returns (provider, "") on success, or (None, skip_reason) if unavailable.
    """
    uri = settings.NEO4J_URI.strip()
    user = settings.NEO4J_USERNAME.strip()
    pwd = settings.NEO4J_PASSWORD.strip()

    if not uri or not user or not pwd:
        return None, "Neo4j credentials not configured in settings/environment"

    # Candidates to try: direct URI, and neo4j+ssc:// if corporate proxy/self-signed cert in chain
    candidates = [uri]
    if uri.startswith("neo4j+s://"):
        candidates.append(uri.replace("neo4j+s://", "neo4j+ssc://"))
    elif uri.startswith("bolt+s://"):
        candidates.append(uri.replace("bolt+s://", "bolt+ssc://"))

    last_error = ""
    for candidate_uri in candidates:
        provider = Neo4jGraphProvider(
            uri=candidate_uri,
            username=user,
            password=pwd,
            database=settings.NEO4J_DATABASE
            if (settings.NEO4J_DATABASE and settings.NEO4J_DATABASE.lower() != "neo4j")
            else None,
        )
        try:
            is_healthy = await provider.health_check()
            if is_healthy:
                return provider, ""
            await provider.close()
        except Exception as e:
            last_error = str(e)
            try:
                await provider.close()
            except Exception:
                pass

    return None, f"Could not establish live connection to Neo4j Aura: {last_error}"


@pytest_asyncio.fixture
async def live_neo4j() -> AsyncGenerator[Neo4jGraphProvider, None]:
    """
    Pytest fixture yielding an active Neo4jGraphProvider connected to live Neo4j Aura.
    Skips the test if live Neo4j Aura is unreachable.
    """
    provider, skip_reason = await _resolve_live_neo4j_provider()
    if provider is None:
        pytest.skip(skip_reason)

    try:
        yield provider
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_neo4j_live_connection_and_auth(live_neo4j: Neo4jGraphProvider) -> None:
    """Test 1: Verify TLS connection, authentication, and simple ping query."""
    is_healthy = await live_neo4j.health_check()
    assert is_healthy is True

    result = await live_neo4j.execute_query("RETURN 1 AS alive, 'Neo4j Aura' AS platform")
    assert len(result) == 1
    assert result[0]["alive"] == 1
    assert result[0]["platform"] == "Neo4j Aura"


@pytest.mark.asyncio
async def test_neo4j_live_node_and_relationship_crud(live_neo4j: Neo4jGraphProvider) -> None:
    """Test 2: Parameterized Cypher CRUD for nodes and relationships."""
    test_snapshot = f"test-crud-{uuid.uuid4().hex[:10]}"
    try:
        node_a = GraphNode(
            id=f"fn:a:{test_snapshot}",
            label="Function",
            properties={
                "name": "calculate_tax",
                "file_path": "finance/tax.py",
                "snapshot_id": test_snapshot,
                "complexity": 5,
            },
        )
        node_b = GraphNode(
            id=f"fn:b:{test_snapshot}",
            label="Function",
            properties={
                "name": "get_tax_rate",
                "file_path": "finance/rates.py",
                "snapshot_id": test_snapshot,
                "complexity": 2,
            },
        )

        # 1. Upsert nodes
        count_nodes = await live_neo4j.upsert_nodes([node_a, node_b])
        assert count_nodes == 2

        # 2. Upsert relationship
        rel = GraphRelationship(
            source_id=node_a.id,
            target_id=node_b.id,
            type="CALLS",
            properties={
                "snapshot_id": test_snapshot,
                "status": "resolved",
                "confidence": 0.95,
            },
        )
        count_rels = await live_neo4j.upsert_relationships([rel])
        assert count_rels == 1

        # 3. Read back via parameterized Cypher
        rows = await live_neo4j.execute_query(
            """
            MATCH (a:CodeEntity {id: $source_id})-[r:RELATED {type: $rel_type}]->(b:CodeEntity {id: $target_id})
            RETURN a.name AS caller, b.name AS callee, r.confidence AS confidence, r.status AS status
            """,
            {"source_id": node_a.id, "rel_type": "CALLS", "target_id": node_b.id},
        )
        assert len(rows) == 1
        assert rows[0]["caller"] == "calculate_tax"
        assert rows[0]["callee"] == "get_tax_rate"
        assert rows[0]["status"] == "resolved"
        assert abs(rows[0]["confidence"] - 0.95) < 1e-4

        # 4. Property update via MERGE
        node_a.properties["complexity"] = 8
        await live_neo4j.upsert_nodes([node_a])
        updated_rows = await live_neo4j.execute_query(
            "MATCH (a:CodeEntity {id: $id}) RETURN a.complexity AS complexity",
            {"id": node_a.id},
        )
        assert updated_rows[0]["complexity"] == 8

    finally:
        # Cleanup
        await live_neo4j.delete_snapshot_graph(test_snapshot)


@pytest.mark.asyncio
async def test_neo4j_live_batched_ingestion_1000(live_neo4j: Neo4jGraphProvider) -> None:
    """Test 3: Batched ingestion of 1,000+ nodes and 1,000+ relationships."""
    test_snapshot = f"test-batch-{uuid.uuid4().hex[:10]}"
    total_count = 1000

    try:
        nodes: list[GraphNode] = []
        relationships: list[GraphRelationship] = []

        # Create a chain of 1,000 nodes: N0 -> N1 -> N2 -> ... -> N999
        for i in range(total_count):
            node_id = f"node:{test_snapshot}:{i}"
            nodes.append(
                GraphNode(
                    id=node_id,
                    label="Symbol",
                    properties={
                        "name": f"symbol_{i}",
                        "index": i,
                        "snapshot_id": test_snapshot,
                    },
                )
            )
            if i > 0:
                prev_id = f"node:{test_snapshot}:{i - 1}"
                relationships.append(
                    GraphRelationship(
                        source_id=prev_id,
                        target_id=node_id,
                        type="DEPENDS_ON",
                        properties={
                            "snapshot_id": test_snapshot,
                            "order": i,
                        },
                    )
                )

        # Batch upsert nodes (handled in 500-item chunks by provider)
        upserted_nodes = await live_neo4j.upsert_nodes(nodes)
        assert upserted_nodes == total_count

        # Batch upsert relationships
        upserted_rels = await live_neo4j.upsert_relationships(relationships)
        assert upserted_rels == total_count - 1

        # Verify counts in graph
        count_res = await live_neo4j.execute_query(
            """
            MATCH (n:CodeEntity {snapshot_id: $snapshot_id})
            RETURN count(n) AS node_count
            """,
            {"snapshot_id": test_snapshot},
        )
        assert count_res[0]["node_count"] == total_count

        rel_count_res = await live_neo4j.execute_query(
            """
            MATCH (:CodeEntity {snapshot_id: $snapshot_id})-[r:RELATED {type: 'DEPENDS_ON'}]->(:CodeEntity {snapshot_id: $snapshot_id})
            RETURN count(r) AS rel_count
            """,
            {"snapshot_id": test_snapshot},
        )
        assert rel_count_res[0]["rel_count"] == total_count - 1

    finally:
        deleted = await live_neo4j.delete_snapshot_graph(test_snapshot)
        assert deleted == total_count


@pytest.mark.asyncio
async def test_neo4j_live_traversal_and_paths(live_neo4j: Neo4jGraphProvider) -> None:
    """Test 4: Graph traversal, multi-hop caller inspection, variable-length paths (*1..3), and shortestPath."""
    test_snapshot = f"test-traverse-{uuid.uuid4().hex[:10]}"

    try:
        # Build DAG:
        # api_handler -> service_a -> helper_b -> repo_c
        #                               ^
        #               service_d ------+
        nodes = [
            GraphNode(
                id=f"api:{test_snapshot}",
                label="APIEndpoint",
                properties={"name": "POST /checkout", "snapshot_id": test_snapshot},
            ),
            GraphNode(
                id=f"svc_a:{test_snapshot}",
                label="Service",
                properties={"name": "CheckoutService", "snapshot_id": test_snapshot},
            ),
            GraphNode(
                id=f"svc_d:{test_snapshot}",
                label="Service",
                properties={"name": "BillingService", "snapshot_id": test_snapshot},
            ),
            GraphNode(
                id=f"hlp_b:{test_snapshot}",
                label="Helper",
                properties={"name": "TaxCalculator", "snapshot_id": test_snapshot},
            ),
            GraphNode(
                id=f"repo_c:{test_snapshot}",
                label="Repository",
                properties={"name": "TaxRuleRepository", "snapshot_id": test_snapshot},
            ),
        ]
        rels = [
            GraphRelationship(
                source_id=nodes[0].id,
                target_id=nodes[1].id,
                type="CALLS",
                properties={"snapshot_id": test_snapshot},
            ),
            GraphRelationship(
                source_id=nodes[1].id,
                target_id=nodes[3].id,
                type="CALLS",
                properties={"snapshot_id": test_snapshot},
            ),
            GraphRelationship(
                source_id=nodes[2].id,
                target_id=nodes[3].id,
                type="CALLS",
                properties={"snapshot_id": test_snapshot},
            ),
            GraphRelationship(
                source_id=nodes[3].id,
                target_id=nodes[4].id,
                type="CALLS",
                properties={"snapshot_id": test_snapshot},
            ),
        ]
        await live_neo4j.upsert_nodes(nodes)
        await live_neo4j.upsert_relationships(rels)

        # 1. Variable length caller traversal (*1..3) to find all upstream callers of helper_b
        upstream = await live_neo4j.execute_query(
            """
            MATCH (caller:CodeEntity)-[:RELATED*1..3]->(target:CodeEntity {id: $target_id})
            RETURN DISTINCT caller.name AS caller_name
            ORDER BY caller_name
            """,
            {"target_id": nodes[3].id},
        )
        upstream_names = {r["caller_name"] for r in upstream}
        assert "POST /checkout" in upstream_names
        assert "CheckoutService" in upstream_names
        assert "BillingService" in upstream_names

        # 2. Shortest path from api_handler to repo_c
        path_res = await live_neo4j.execute_query(
            """
            MATCH (start:CodeEntity {id: $start_id}), (end:CodeEntity {id: $end_id})
            MATCH p = shortestPath((start)-[:RELATED*]->(end))
            RETURN length(p) AS hop_count
            """,
            {"start_id": nodes[0].id, "end_id": nodes[4].id},
        )
        assert len(path_res) == 1
        assert path_res[0]["hop_count"] == 3

    finally:
        await live_neo4j.delete_snapshot_graph(test_snapshot)


@pytest.mark.asyncio
async def test_neo4j_live_snapshot_scoped_cleanup(live_neo4j: Neo4jGraphProvider) -> None:
    """Test 5: Verify delete_snapshot_graph removes only specified snapshot nodes without data bleed."""
    snap_a = f"test-isolation-a-{uuid.uuid4().hex[:8]}"
    snap_b = f"test-isolation-b-{uuid.uuid4().hex[:8]}"

    try:
        # Create nodes in snap_a
        nodes_a = [
            GraphNode(
                id=f"a1:{snap_a}",
                label="Function",
                properties={"name": "func_a1", "snapshot_id": snap_a},
            ),
            GraphNode(
                id=f"a2:{snap_a}",
                label="Function",
                properties={"name": "func_a2", "snapshot_id": snap_a},
            ),
        ]
        # Create nodes in snap_b
        nodes_b = [
            GraphNode(
                id=f"b1:{snap_b}",
                label="Function",
                properties={"name": "func_b1", "snapshot_id": snap_b},
            ),
        ]

        await live_neo4j.upsert_nodes(nodes_a)
        await live_neo4j.upsert_nodes(nodes_b)

        # Delete snap_a
        deleted_a = await live_neo4j.delete_snapshot_graph(snap_a)
        assert deleted_a == 2

        # Verify snap_b is completely intact
        subgraph_b = await live_neo4j.get_subgraph(snapshot_id=snap_b)
        assert subgraph_b["total_nodes"] == 1
        assert subgraph_b["nodes"][0]["id"] == f"b1:{snap_b}"

        # Verify snap_a is empty
        subgraph_a = await live_neo4j.get_subgraph(snapshot_id=snap_a)
        assert subgraph_a["total_nodes"] == 0

    finally:
        await live_neo4j.delete_snapshot_graph(snap_a)
        await live_neo4j.delete_snapshot_graph(snap_b)


@pytest.mark.asyncio
async def test_neo4j_live_connection_pool_and_health_check(live_neo4j: Neo4jGraphProvider) -> None:
    """Test 6: Verify connection pool acquisition, concurrent queries, and driver resilience."""

    # Run 10 concurrent queries across connection pool
    async def run_ping(idx: int) -> int:
        res = await live_neo4j.execute_query("RETURN $idx AS idx", {"idx": idx})
        return int(res[0]["idx"])

    tasks = [run_ping(i) for i in range(10)]
    results = await asyncio.gather(*tasks)
    assert results == list(range(10))

    # Health check succeeds
    assert await live_neo4j.health_check() is True
