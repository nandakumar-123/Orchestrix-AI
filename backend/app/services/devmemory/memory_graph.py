from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.devmemory import (
    EngineeringMemory,
    MemoryRelationship,
)
from app.services.devmemory.schemas import GraphSyncResponse
from app.services.graph_service import (
    BaseGraphProvider,
    GraphNode,
    GraphRelationship,
    get_graph_provider,
)

logger = logging.getLogger("orchestrix.devmemory.graph")


class DevMemoryGraphService:
    """
    Synchronizes and retrieves DevMemory entities and relationships in the Neo4j Knowledge Graph.
    - Uses existing BaseGraphProvider abstraction directly (Neo4jGraphProvider or MockGraphProvider).
    - Every graph entity contains memory_id and workspace_id for tenant scoping.
    - Graph operations are strictly idempotent with stable node identifiers.
    - PostgreSQL is always the authoritative source of truth; Neo4j failure never destroys data.
    """

    def __init__(self, graph_provider: BaseGraphProvider | None = None) -> None:
        self._provider = graph_provider

    def _get_provider(self) -> BaseGraphProvider:
        if self._provider is None:
            self._provider = get_graph_provider()
        return self._provider

    async def synchronize_workspace_memories(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> GraphSyncResponse:
        """
        Idempotently synchronize all memories and relationships for a workspace into the Knowledge Graph.
        """
        provider = self._get_provider()
        synced_nodes = 0
        synced_rels = 0

        try:
            # 1. Fetch memories for workspace
            stmt_mem = (
                select(EngineeringMemory)
                .where(EngineeringMemory.workspace_id == workspace_id)
                .options(selectinload(EngineeringMemory.evidence))
            )
            memories = list((await db.execute(stmt_mem)).scalars().all())

            # 2. Synchronize memory nodes and evidence
            nodes_to_upsert: list[GraphNode] = []
            rels_to_upsert: list[GraphRelationship] = []

            for mem in memories:
                node = GraphNode(
                    id=f"memory:{mem.id}",
                    label="EngineeringMemory",
                    properties={
                        "memory_id": str(mem.id),
                        "name": mem.title,
                        "workspace_id": str(workspace_id),
                        "repository_id": str(mem.repository_id) if mem.repository_id else "",
                        "memory_type": mem.memory_type,
                        "verification_status": mem.verification_status,
                        "confidence_score": float(mem.confidence_score),
                    },
                )
                nodes_to_upsert.append(node)

                # If repository exists, link Memory -> Repository
                if mem.repository_id:
                    rel_repo = GraphRelationship(
                        source_id=f"memory:{mem.id}",
                        target_id=f"repo:{mem.repository_id}",
                        type="BELONGS_TO_REPO",
                        properties={"workspace_id": str(workspace_id)},
                    )
                    rels_to_upsert.append(rel_repo)

                # Link Memory -> Evidence
                for ev in mem.evidence:
                    ev_node = GraphNode(
                        id=f"evidence:{ev.id}",
                        label="MemoryEvidence",
                        properties={
                            "evidence_id": str(ev.id),
                            "name": f"Evidence - {ev.evidence_type}",
                            "workspace_id": str(workspace_id),
                            "evidence_type": ev.evidence_type,
                            "source_reference": ev.source_reference or "",
                        },
                    )
                    nodes_to_upsert.append(ev_node)

                    ev_rel = GraphRelationship(
                        source_id=f"memory:{mem.id}",
                        target_id=f"evidence:{ev.id}",
                        type="HAS_EVIDENCE",
                        properties={"workspace_id": str(workspace_id)},
                    )
                    rels_to_upsert.append(ev_rel)

            # 3. Synchronize memory relationships
            stmt_rel = select(MemoryRelationship).where(
                MemoryRelationship.workspace_id == workspace_id
            )
            relationships = list((await db.execute(stmt_rel)).scalars().all())

            for r in relationships:
                g_rel = GraphRelationship(
                    source_id=f"memory:{r.source_memory_id}",
                    target_id=f"memory:{r.target_memory_id}",
                    type=r.relationship_type,
                    properties={
                        "relationship_id": str(r.id),
                        "workspace_id": str(workspace_id),
                        "confidence_score": float(r.confidence_score),
                    },
                )
                rels_to_upsert.append(g_rel)

            if nodes_to_upsert:
                synced_nodes = await provider.upsert_nodes(nodes_to_upsert)
            if rels_to_upsert:
                synced_rels = await provider.upsert_relationships(rels_to_upsert)

            return GraphSyncResponse(
                synced_nodes=synced_nodes,
                synced_relationships=synced_rels,
                workspace_id=workspace_id,
                status="SUCCESS",
                message=f"Successfully synchronized {synced_nodes} nodes and {synced_rels} relationships.",
            )

        except Exception as e:
            logger.error(f"Graph synchronization failed for workspace {workspace_id}: {e}")
            return GraphSyncResponse(
                synced_nodes=synced_nodes,
                synced_relationships=synced_rels,
                workspace_id=workspace_id,
                status="DEGRADED",
                message=f"Graph synchronization failed or provider unavailable: {e}",
            )

    async def get_memory_subgraph(
        self,
        workspace_id: uuid.UUID,
        memory_id: uuid.UUID,
        depth: int = 2,
    ) -> dict[str, Any]:
        """
        Retrieve localized memory neighborhood subgraph enforcing workspace filtering.
        """
        provider = self._get_provider()
        node_id = f"memory:{memory_id}"
        try:
            subgraph = await provider.get_subgraph(
                snapshot_id=workspace_id,
                labels=["EngineeringMemory", "MemoryEvidence"],
                limit=100,
            )
            # Filter nodes and relationships strictly by workspace_id
            valid_nodes = [
                n
                for n in subgraph.get("nodes", [])
                if getattr(n, "properties", {}).get("workspace_id") == str(workspace_id)
            ]
            valid_node_ids = {getattr(n, "id", None) for n in valid_nodes}
            valid_rels = [
                r
                for r in subgraph.get("relationships", [])
                if getattr(r, "source_id", None) in valid_node_ids
                and getattr(r, "target_id", None) in valid_node_ids
            ]

            return {
                "nodes": [n.to_dict() if hasattr(n, "to_dict") else n for n in valid_nodes],
                "relationships": [
                    r.to_dict() if hasattr(r, "to_dict") else r for r in valid_rels
                ],
            }
        except Exception as e:
            logger.warning(f"Graph traversal failed for memory {memory_id}: {e}")
            return {"nodes": [], "relationships": [], "error": str(e)}
