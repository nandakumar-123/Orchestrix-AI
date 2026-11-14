import logging
import math
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.repository import Repository
from app.db.models.repository_intelligence import RepositorySnapshot
from app.db.models.semantic_intelligence import SemanticCodeChunk
from app.services.embedding_service import BaseEmbeddingProvider, get_embedding_provider

logger = logging.getLogger("orchestrix.retrieval")


@dataclass
class RetrievedChunkResult:
    """Standardized result item from semantic or hybrid code retrieval."""

    chunk_id: uuid.UUID
    repository_id: uuid.UUID
    repository_name: str
    snapshot_id: uuid.UUID
    file_path: str
    language: str
    symbol_name: str | None
    symbol_type: str | None
    parent_symbol_name: str | None
    start_line: int
    end_line: int
    content: str
    source_code_excerpt: str
    similarity_score: float  # Normalized 0.0 to 1.0
    vector_score: float
    lexical_score: float
    symbol_score: float
    metadata: dict[str, Any]


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two float vectors in Python."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    sim = dot / (norm_a * norm_b)
    return max(0.0, min(1.0, (sim + 1.0) / 2.0 if sim < 0 else sim))


def _extract_query_terms(query: str) -> list[str]:
    """Tokenize query into lowercase alphanumeric words."""
    words = re.findall(r"[a-zA-Z0-9_]{2,}", query.lower())
    # Filter common English stopwords
    stopwords = {
        "where",
        "what",
        "which",
        "how",
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "from",
        "are",
        "handled",
        "implemented",
        "used",
        "defined",
        "does",
        "have",
        "been",
        "show",
        "find",
        "code",
        "file",
        "all",
    }
    return [w for w in words if w not in stopwords] or words


def _compute_lexical_score(text: str, terms: list[str]) -> float:
    """Calculate term match score between 0.0 and 1.0."""
    if not terms or not text:
        return 0.0
    text_lower = text.lower()
    matches = sum(1 for term in terms if term in text_lower)
    return matches / len(terms)


class SemanticRetrievalEngine:
    """
    Production-grade hybrid code retrieval engine combining:
    1. Dense semantic vector similarity (HNSW / cosine distance)
    2. Exact lexical token matching
    3. Structural symbol-name alignment
    4. File-path relevancy scoring
    Enforces strict workspace tenant isolation.
    """

    def __init__(self, provider: BaseEmbeddingProvider | None = None) -> None:
        self.provider = provider or get_embedding_provider()

    async def search(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        query: str,
        snapshot_id: uuid.UUID | None = None,
        language: str | None = None,
        symbol_type: str | None = None,
        file_path_prefix: str | None = None,
        limit: int = 15,
        vector_weight: float = 0.50,
        lexical_weight: float = 0.25,
        symbol_weight: float = 0.15,
        path_weight: float = 0.10,
    ) -> list[RetrievedChunkResult]:
        """
        Execute hybrid semantic retrieval for repository code.
        """
        clean_query = query.strip()
        if not clean_query:
            return []

        # 1. Authorize repository ownership and workspace isolation
        repo_stmt = select(Repository).where(
            Repository.id == repository_id,
            Repository.workspace_id == workspace_id,
        )
        repo_res = await db.execute(repo_stmt)
        repo = repo_res.scalars().first()
        if not repo:
            raise LookupError(f"Repository {repository_id} not found in workspace {workspace_id}")

        # 2. Resolve active snapshot if not specified
        target_snapshot_id = snapshot_id
        if not target_snapshot_id:
            snap_stmt = (
                select(RepositorySnapshot.id)
                .where(
                    RepositorySnapshot.repository_id == repository_id,
                    RepositorySnapshot.workspace_id == workspace_id,
                )
                .order_by(desc(RepositorySnapshot.created_at))
                .limit(1)
            )
            snap_res = await db.execute(snap_stmt)
            target_snapshot_id = snap_res.scalar_one_or_none()

        if not target_snapshot_id:
            logger.info("No indexed snapshot found for repository %s", repository_id)
            return []

        # 3. Generate query embedding vector
        query_vector = await self.provider.embed_query(clean_query)
        query_terms = _extract_query_terms(clean_query)

        # 4. Fetch candidate chunks matching filters
        base_filters = [
            SemanticCodeChunk.workspace_id == workspace_id,
            SemanticCodeChunk.repository_id == repository_id,
            SemanticCodeChunk.snapshot_id == target_snapshot_id,
        ]
        if language:
            base_filters.append(func.lower(SemanticCodeChunk.language) == language.lower())
        if symbol_type:
            base_filters.append(func.lower(SemanticCodeChunk.symbol_type) == symbol_type.lower())
        if file_path_prefix:
            base_filters.append(SemanticCodeChunk.file_path.startswith(file_path_prefix))

        # Check if database is PostgreSQL (using pgvector) or SQLite fallback
        bind = db.bind
        is_postgres = bind is not None and "postgresql" in bind.dialect.name

        candidates: list[tuple[SemanticCodeChunk, float]] = []

        if is_postgres and hasattr(SemanticCodeChunk.embedding, "cosine_distance"):
            # PostgreSQL pgvector native similarity
            # In pgvector: cosine_distance is 0 for identical, 2 for opposite.
            # Similarity = 1.0 - (cosine_distance / 2.0) or 1.0 - cosine_distance
            cosine_dist = SemanticCodeChunk.embedding.cosine_distance(query_vector)
            stmt = (
                select(SemanticCodeChunk, cosine_dist.label("dist"))
                .where(*base_filters)
                .order_by(cosine_dist)
                .limit(max(limit * 3, 50))
            )
            res = await db.execute(stmt)
            for chunk, dist in res.all():
                # Normalize cosine distance (0.0=identical, 2.0=opposite) to 1.0 (identical) down to 0.0
                sim = max(0.0, 1.0 - (float(dist) if dist is not None else 1.0))
                candidates.append((chunk, sim))
        else:
            # SQLite / in-memory unit testing path
            stmt = select(SemanticCodeChunk).where(*base_filters)
            res = await db.execute(stmt)
            all_chunks = res.scalars().all()
            for chunk in all_chunks:
                sim = 0.0
                if chunk.embedding is not None:
                    # In SQLite, embedding is stored as list or string
                    emb_list = chunk.embedding
                    if isinstance(emb_list, list):
                        sim = _cosine_similarity(query_vector, emb_list)
                candidates.append((chunk, sim))

        # 5. Hybrid Scoring and Ranking
        scored_results: list[RetrievedChunkResult] = []

        for chunk, v_sim in candidates:
            # Lexical score against content
            lex_score = _compute_lexical_score(chunk.content, query_terms)

            # Symbol name match score
            sym_text = f"{chunk.symbol_name or ''} {chunk.parent_symbol_name or ''}"
            sym_score = _compute_lexical_score(sym_text, query_terms)

            # Path match score
            path_score = _compute_lexical_score(chunk.file_path, query_terms)

            # Weighted combination
            final_score = (
                (vector_weight * v_sim)
                + (lexical_weight * lex_score)
                + (symbol_weight * sym_score)
                + (path_weight * path_score)
            )

            # Produce clean excerpt (first 6 lines or matching line range)
            content_lines = chunk.content.splitlines()
            excerpt_lines = content_lines[:8]
            excerpt = "\n".join(excerpt_lines)
            if len(content_lines) > 8:
                excerpt += f"\n... [{len(content_lines) - 8} more lines]"

            scored_results.append(
                RetrievedChunkResult(
                    chunk_id=chunk.id,
                    repository_id=chunk.repository_id,
                    repository_name=repo.name,
                    snapshot_id=chunk.snapshot_id,
                    file_path=chunk.file_path,
                    language=chunk.language,
                    symbol_name=chunk.symbol_name,
                    symbol_type=chunk.symbol_type,
                    parent_symbol_name=chunk.parent_symbol_name,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content=chunk.content,
                    source_code_excerpt=excerpt,
                    similarity_score=round(min(1.0, max(0.0, final_score)), 4),
                    vector_score=round(v_sim, 4),
                    lexical_score=round(lex_score, 4),
                    symbol_score=round(sym_score, 4),
                    metadata=chunk.metadata_ or {},
                )
            )

        # 6. Sort by combined similarity score descending and return top K
        scored_results.sort(key=lambda r: r.similarity_score, reverse=True)
        return scored_results[:limit]
