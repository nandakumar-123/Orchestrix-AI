from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.repository_intelligence import (
    CodeSymbol,
    FileDependency,
    RepositoryFile,
    RepositorySnapshot,
)
from app.services.graph_service import (
    BaseGraphProvider,
    get_graph_provider,
)
from app.services.relationship_extraction import MultiLanguageRelationshipExtractor

logger = logging.getLogger("orchestrix.graph_indexing")


class GraphIndexingService:
    """
    Orchestrates knowledge graph extraction and ingestion into Neo4j or Mock provider.
    Extracts multi-language code relationships, symbol definitions, calls, imports,
    inheritance, endpoints, models, and test cases.
    """

    def __init__(self, provider: BaseGraphProvider | None = None) -> None:
        self.provider = provider or get_graph_provider()

    async def index_snapshot(
        self,
        db: AsyncSession,
        snapshot_id: uuid.UUID,
        file_contents: dict[str, str] | None = None,
        force_reindex: bool = False,
    ) -> dict[str, Any]:
        """
        Extract code relationship graph and ingest into graph database.
        """
        # 1. Fetch snapshot
        stmt = select(RepositorySnapshot).where(RepositorySnapshot.id == snapshot_id)
        res = await db.execute(stmt)
        snapshot = res.scalar_one_or_none()
        if not snapshot:
            raise LookupError(f"RepositorySnapshot {snapshot_id} not found")

        # 2. Fetch files, symbols, and dependencies
        f_stmt = select(RepositoryFile).where(RepositoryFile.snapshot_id == snapshot_id)
        f_res = await db.execute(f_stmt)
        files = list(f_res.scalars().all())

        s_stmt = select(CodeSymbol).where(CodeSymbol.snapshot_id == snapshot_id)
        s_res = await db.execute(s_stmt)
        symbols = list(s_res.scalars().all())

        d_stmt = select(FileDependency).where(FileDependency.snapshot_id == snapshot_id)
        d_res = await db.execute(d_stmt)
        dependencies = list(d_res.scalars().all())

        # 3. Extract relationships and nodes
        extractor = MultiLanguageRelationshipExtractor(
            snapshot=snapshot,
            files=files,
            symbols=symbols,
            dependencies=dependencies,
            file_contents=file_contents or {},
        )
        nodes, relationships = extractor.extract_all()

        # 4. Ingest into graph provider
        if force_reindex:
            await self.provider.delete_snapshot_graph(snapshot_id)

        upserted_nodes = await self.provider.upsert_nodes(nodes)
        upserted_rels = await self.provider.upsert_relationships(relationships)

        # 5. Record graph metadata on snapshot structure summary
        summary = dict(snapshot.structure_summary or {})
        summary["graph_index"] = {
            "status": "completed",
            "provider": self.provider.provider_name,
            "total_nodes": len(nodes),
            "total_relationships": len(relationships),
            "indexed_at": utc_now().isoformat(),
        }
        snapshot.structure_summary = summary
        db.add(snapshot)
        await db.commit()

        return {
            "status": "completed",
            "snapshot_id": str(snapshot_id),
            "provider": self.provider.provider_name,
            "total_nodes": len(nodes),
            "total_relationships": len(relationships),
            "upserted_nodes": upserted_nodes,
            "upserted_relationships": upserted_rels,
        }

    async def get_index_status(
        self,
        db: AsyncSession,
        snapshot_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Fetch graph indexing status and entity counts."""
        stmt = select(RepositorySnapshot).where(RepositorySnapshot.id == snapshot_id)
        res = await db.execute(stmt)
        snapshot = res.scalar_one_or_none()
        if not snapshot:
            raise LookupError(f"RepositorySnapshot {snapshot_id} not found")

        summary = snapshot.structure_summary or {}
        graph_info = summary.get("graph_index")

        if not graph_info:
            return {
                "status": "not_indexed",
                "snapshot_id": str(snapshot_id),
                "total_nodes": 0,
                "total_relationships": 0,
                "provider": self.provider.provider_name,
            }

        return {
            "status": graph_info.get("status", "completed"),
            "snapshot_id": str(snapshot_id),
            "total_nodes": graph_info.get("total_nodes", 0),
            "total_relationships": graph_info.get("total_relationships", 0),
            "indexed_at": graph_info.get("indexed_at"),
            "provider": graph_info.get("provider", self.provider.provider_name),
        }
