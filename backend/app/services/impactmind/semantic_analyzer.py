from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.impactmind.ast_classifier import ClassifiedChange
from app.services.semantic_retrieval import SemanticRetrievalEngine

logger = logging.getLogger("orchestrix.impactmind.semantic_analyzer")


@dataclass
class SemanticImpactMatch:
    chunk_id: str
    file_path: str
    symbol_name: str | None
    symbol_type: str | None
    start_line: int
    end_line: int
    content: str
    similarity_score: float
    matched_query: str
    relation_reason: str
    impact_type: str = "semantic_similarity"

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "file_path": self.file_path,
            "symbol_name": self.symbol_name,
            "symbol_type": self.symbol_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "similarity_score": round(self.similarity_score, 4),
            "matched_query": self.matched_query,
            "relation_reason": self.relation_reason,
            "impact_type": self.impact_type,
        }


@dataclass
class SemanticImpactResult:
    matches: list[SemanticImpactMatch] = field(default_factory=list)
    total_searches: int = 0
    is_degraded: bool = False


class SemanticImpactAnalyzer:
    """
    Leverages Phase 9 hybrid semantic and lexical retrieval to identify code modules,
    validation logic, error handlers, and tests that share conceptual or semantic
    overlap with the proposed modifications.
    """

    def __init__(self, search_engine: SemanticRetrievalEngine | None = None) -> None:
        self.search_engine = search_engine or SemanticRetrievalEngine()

    async def analyze_semantic_impact(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        changes: list[ClassifiedChange],
        graph_impacted_file_paths: set[str] | None = None,
        top_k: int = 5,
        min_score: float = 0.55,
    ) -> SemanticImpactResult:
        """
        Search for semantically related code chunks not directly identified
        as direct or indirect graph dependencies.
        """
        graph_files = graph_impacted_file_paths or set()
        changed_files = {c.file_path for c in changes}
        excluded_files = graph_files.union(changed_files)

        queries_to_run: list[tuple[str, str]] = []
        for c in changes:
            if c.symbol_name:
                queries_to_run.append(
                    (
                        f"{c.symbol_name} implementation logic and error handling",
                        f"Conceptual match for {c.symbol_name} ({c.category})",
                    )
                )
            elif c.category in ("DATABASE_SCHEMA_CHANGE", "API_ROUTE_CHANGE"):
                queries_to_run.append(
                    (
                        f"{c.file_path} service calls and validation",
                        f"Related functionality for {c.file_path}",
                    )
                )

        if not queries_to_run:
            # Fallback to query with changed filenames
            summary = " ".join(c.file_path for c in changes[:3])
            queries_to_run.append((summary, "General repository context"))

        matches: list[SemanticImpactMatch] = []
        seen_chunks: set[str] = set()

        for query_text, reason in queries_to_run[:5]:  # Limit to 5 distinct queries to conserve CPU
            try:
                retrieved = await self.search_engine.search(
                    db=db,
                    workspace_id=workspace_id,
                    repository_id=repository_id,
                    query=query_text,
                    limit=top_k,
                )

                for chunk in retrieved:
                    # Ignore code from the changed files themselves or directly connected graph nodes
                    if chunk.file_path in excluded_files:
                        continue
                    chunk_key = str(chunk.chunk_id)
                    if chunk_key in seen_chunks:
                        continue
                    if chunk.similarity_score < min_score:
                        continue

                    seen_chunks.add(chunk_key)
                    matches.append(
                        SemanticImpactMatch(
                            chunk_id=chunk_key,
                            file_path=chunk.file_path,
                            symbol_name=chunk.symbol_name,
                            symbol_type=chunk.symbol_type,
                            start_line=chunk.start_line,
                            end_line=chunk.end_line,
                            content=chunk.content[:200]
                            + ("..." if len(chunk.content) > 200 else ""),
                            similarity_score=chunk.similarity_score,
                            matched_query=query_text,
                            relation_reason=reason,
                            impact_type="semantic_similarity",
                        )
                    )
            except Exception as e:
                logger.warning(f"Semantic search query '{query_text}' failed: {e}")
                return SemanticImpactResult(
                    matches=matches, total_searches=len(queries_to_run), is_degraded=True
                )

        return SemanticImpactResult(
            matches=sorted(matches, key=lambda m: m.similarity_score, reverse=True),
            total_searches=len(queries_to_run),
            is_degraded=False,
        )
