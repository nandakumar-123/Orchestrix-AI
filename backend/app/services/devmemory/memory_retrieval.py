from __future__ import annotations

import logging
import math
import uuid
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import utc_now
from app.db.models.devmemory import (
    EngineeringMemory,
    MemoryAccessLog,
    MemoryAccessType,
    MemoryConsumerAgent,
    MemoryVerificationStatus,
)
from app.services.devmemory.schemas import (
    MemoryResponse,
    MemorySearchRequest,
    MemorySearchResult,
)
from app.services.embedding_service import get_embedding_provider

logger = logging.getLogger("orchestrix.devmemory.retrieval")


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2, strict=True))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def compute_lexical_score(query: str, title: str, content: str) -> float:
    """
    Deterministic BM25-inspired lexical overlap score.
    Measures term frequency and query coverage across title and body.
    """
    q_tokens = set(query.lower().split())
    if not q_tokens:
        return 0.0

    target = f"{title} {content}".lower()
    t_words = target.split()
    if not t_words:
        return 0.0

    hits = sum(1 for tok in q_tokens if tok in target)
    coverage = hits / len(q_tokens)

    # Term frequency boost
    tf_count = sum(t_words.count(tok) for tok in q_tokens)
    tf_norm = min(1.0, tf_count / (len(q_tokens) * 3))

    return round(0.6 * coverage + 0.4 * tf_norm, 4)


class DevMemoryRetrievalService:
    """
    Semantic and hybrid retrieval engine for DevMemory.
    - Tenant-isolated retrieval strictly scoped by workspace_id.
    - Excludes ARCHIVED and OUTDATED memories by default.
    - Applies calibrated boost for VERIFIED memories and concrete evidence.
    - Recency decay weighting for up-to-date knowledge preference.
    """

    def __init__(self) -> None:
        self._embedding_provider = None

    def _get_embedding_provider(self):
        if self._embedding_provider is None:
            self._embedding_provider = get_embedding_provider()
        return self._embedding_provider

    async def search(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        request: MemorySearchRequest,
        consumer: MemoryConsumerAgent = MemoryConsumerAgent.USER,
    ) -> list[MemorySearchResult]:
        """
        Execute tenant-isolated semantic and hybrid memory retrieval.
        """
        # 1. Filter builder
        stmt = (
            select(EngineeringMemory)
            .where(EngineeringMemory.workspace_id == workspace_id)
            .options(selectinload(EngineeringMemory.evidence))
        )

        # Repository scoping
        if request.repository_id:
            # Include repository-specific OR workspace-wide (repository_id is None)
            stmt = stmt.where(
                (EngineeringMemory.repository_id == request.repository_id)
                | (EngineeringMemory.repository_id.is_(None))
            )

        # Memory type filter
        if request.memory_types:
            type_vals = [t.value for t in request.memory_types]
            stmt = stmt.where(EngineeringMemory.memory_type.in_(type_vals))

        # Verification status filtering
        if request.verification_statuses:
            status_vals = [s.value for s in request.verification_statuses]
            stmt = stmt.where(EngineeringMemory.verification_status.in_(status_vals))
        else:
            # Default exclusions: omit ARCHIVED and OUTDATED unless explicitly requested
            excluded = []
            if not request.include_archived:
                excluded.append(MemoryVerificationStatus.ARCHIVED.value)
            if not request.include_outdated:
                excluded.append(MemoryVerificationStatus.OUTDATED.value)
            if excluded:
                stmt = stmt.where(~EngineeringMemory.verification_status.in_(excluded))

        res = await db.execute(stmt)
        candidates = list(res.scalars().all())
        if not candidates:
            return []

        # 2. Query embedding generation
        query_vec: list[float] | None = None
        try:
            query_vec = await self._get_embedding_provider().embed_query(request.query)
        except Exception as e:
            logger.warning(f"Query embedding generation failed: {e}")
            query_vec = None

        # 3. Hybrid scoring
        results: list[MemorySearchResult] = []
        now = utc_now()

        w_sem = request.hybrid_weight_semantic
        w_lex = request.hybrid_weight_lexical

        for mem in candidates:
            # Semantic similarity score
            sem_score = 0.0
            if query_vec is not None and mem.embedding:
                sem_score = cosine_similarity(query_vec, mem.embedding)

            # Lexical score
            lex_score = compute_lexical_score(request.query, mem.title, mem.content)

            # Base hybrid score
            base_score = (w_sem * sem_score) + (w_lex * lex_score)

            # Multiplier boosts:
            # Verified boost (+20%)
            is_verified = mem.verification_status == MemoryVerificationStatus.VERIFIED.value
            ver_boost = 1.2 if is_verified else 1.0

            # Evidence boost (+10% if backed by empirical evidence)
            ev_count = len(mem.evidence)
            ev_boost = 1.1 if ev_count > 0 else 1.0

            # Recency multiplier (slight decay for very old memories: half-life ~ 90 days)
            mem_updated = mem.updated_at
            if mem_updated.tzinfo is None and now.tzinfo is not None:
                mem_updated = mem_updated.replace(tzinfo=UTC)
            elif mem_updated.tzinfo is not None and now.tzinfo is None:
                now_cmp = now.replace(tzinfo=UTC)
            else:
                now_cmp = now
            age_days = max(0.0, (now_cmp - mem_updated).total_seconds() / 86400.0)
            recency_multiplier = 1.0 / (1.0 + (age_days / 365.0))

            final_score = base_score * ver_boost * ev_boost * recency_multiplier
            final_score = round(min(1.0, final_score), 4)

            if final_score >= request.min_score:
                resp = MemoryResponse.model_validate(mem)
                results.append(
                    MemorySearchResult(
                        memory=resp,
                        relevance_score=final_score,
                        semantic_score=round(sem_score, 4),
                        lexical_score=round(lex_score, 4),
                        is_verified=is_verified,
                        evidence_count=ev_count,
                    )
                )

        # Sort descending by relevance score
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        top_results = results[: request.limit]

        # Log access audit for cited top memories
        for item in top_results:
            db.add(
                MemoryAccessLog(
                    memory_id=item.memory.id,
                    workspace_id=workspace_id,
                    agent_type=consumer.value,
                    access_type=MemoryAccessType.RETRIEVE.value,
                    context_metadata={
                        "query": request.query[:200],
                        "relevance_score": item.relevance_score,
                    },
                    accessed_at=now,
                )
            )
        await db.flush()

        return top_results
