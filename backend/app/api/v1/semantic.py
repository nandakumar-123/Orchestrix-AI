import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    enforce_csrf_protection,
    get_current_user,
    require_workspace_membership,
)
from app.api.v1.schemas import (
    AssembledCodeBlockResponse,
    AssembledContextRequest,
    AssembledContextResponse,
    SemanticChunkDetailResponse,
    SemanticIndexRequest,
    SemanticIndexStatusResponse,
    SemanticSearchRequest,
    SemanticSearchResponse,
    SemanticSearchResultItem,
)
from app.db.base import WorkspaceRole
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.repository_intelligence import RepositorySnapshot
from app.db.models.semantic_intelligence import (
    EmbeddingModelMetadata,
    SemanticCodeChunk,
)
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.context_assembly import ContextAssemblyEngine
from app.services.embedding_service import get_embedding_provider
from app.services.semantic_indexing_service import SemanticIndexingService
from app.services.semantic_retrieval import SemanticRetrievalEngine

semantic_router = APIRouter(prefix="/repositories", tags=["semantic-intelligence"])
logger = logging.getLogger("orchestrix.api.semantic")


@semantic_router.post(
    "/{repository_id}/semantic-index",
    response_model=SemanticIndexStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger semantic chunking and embedding generation",
)
async def trigger_semantic_indexing(
    repository_id: uuid.UUID,
    payload: SemanticIndexRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.ADMIN)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """
    Trigger semantic AST chunking and vector embedding for a repository snapshot.
    Enforces ADMIN workspace role and CSRF validation.
    """
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace {workspace_id}",
        )

    # Determine target snapshot
    target_snapshot_id = payload.snapshot_id
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Repository has not been structurally indexed yet. Please run repository indexing first.",
        )

    service = SemanticIndexingService()
    try:
        metadata = await service.index_snapshot(
            db=db,
            workspace_id=workspace_id,
            repository_id=repository_id,
            snapshot_id=target_snapshot_id,
            force_reembed=payload.force_reembed,
        )
        return metadata
    except Exception as exc:
        logger.exception("Failed to execute semantic indexing: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Semantic indexing failed: {exc}",
        ) from exc


@semantic_router.get(
    "/{repository_id}/semantic-index/status",
    response_model=SemanticIndexStatusResponse,
    summary="Get semantic indexing status for repository snapshot",
)
async def get_semantic_indexing_status(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    snapshot_id: uuid.UUID | None = Query(default=None, description="Optional target snapshot ID"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """
    Retrieve semantic embedding and indexing metadata for a repository snapshot.
    """
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace {workspace_id}",
        )

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

    provider = get_embedding_provider()

    if not target_snapshot_id:
        return SemanticIndexStatusResponse(
            repository_id=repository_id,
            snapshot_id=None,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimension=provider.dimension,
            total_chunks=0,
            status="unindexed",
            error_message="No snapshots found",
            completed_at=None,
        )

    meta_stmt = select(EmbeddingModelMetadata).where(
        EmbeddingModelMetadata.snapshot_id == target_snapshot_id,
        EmbeddingModelMetadata.model_name == provider.model_name,
    )
    meta_res = await db.execute(meta_stmt)
    meta = meta_res.scalars().first()

    if not meta:
        # Check if chunks exist anyway
        chunks_count_stmt = select(func.count(SemanticCodeChunk.id)).where(
            SemanticCodeChunk.snapshot_id == target_snapshot_id
        )
        cnt_res = await db.execute(chunks_count_stmt)
        total_chunks = cnt_res.scalar() or 0
        return SemanticIndexStatusResponse(
            repository_id=repository_id,
            snapshot_id=target_snapshot_id,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimension=provider.dimension,
            total_chunks=total_chunks,
            status="completed" if total_chunks > 0 else "unindexed",
            error_message=None,
            completed_at=None,
        )

    return meta


@semantic_router.post(
    "/{repository_id}/semantic-search",
    response_model=SemanticSearchResponse,
    summary="Search repository code using natural language query (POST)",
)
async def semantic_search_post(
    repository_id: uuid.UUID,
    payload: SemanticSearchRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """
    Search repository code with natural-language query and hybrid relevance ranking.
    """
    engine = SemanticRetrievalEngine()
    try:
        results = await engine.search(
            db=db,
            workspace_id=workspace_id,
            repository_id=repository_id,
            query=payload.query,
            snapshot_id=payload.snapshot_id,
            language=payload.language,
            symbol_type=payload.symbol_type,
            file_path_prefix=payload.file_path_prefix,
            limit=payload.limit,
        )
        items = [
            SemanticSearchResultItem(
                chunk_id=r.chunk_id,
                repository_id=r.repository_id,
                repository_name=r.repository_name,
                snapshot_id=r.snapshot_id,
                file_path=r.file_path,
                language=r.language,
                symbol_name=r.symbol_name,
                symbol_type=r.symbol_type,
                parent_symbol_name=r.parent_symbol_name,
                start_line=r.start_line,
                end_line=r.end_line,
                source_code_excerpt=r.source_code_excerpt,
                similarity_score=r.similarity_score,
                vector_score=r.vector_score,
                lexical_score=r.lexical_score,
                symbol_score=r.symbol_score,
                metadata=r.metadata,
            )
            for r in results
        ]
        return SemanticSearchResponse(
            repository_id=repository_id,
            query=payload.query,
            total_results=len(items),
            results=items,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Semantic search failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Semantic retrieval failed: {exc}",
        ) from exc


@semantic_router.get(
    "/{repository_id}/semantic-search",
    response_model=SemanticSearchResponse,
    summary="Search repository code using natural language query (GET)",
)
async def semantic_search_get(
    repository_id: uuid.UUID,
    q: str = Query(..., min_length=2, max_length=1000, description="Natural language search query"),
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    snapshot_id: uuid.UUID | None = Query(default=None, description="Optional snapshot filter"),
    language: str | None = Query(default=None, description="Optional language filter"),
    symbol_type: str | None = Query(default=None, description="Optional symbol type filter"),
    file_path_prefix: str | None = Query(default=None, description="Optional path prefix filter"),
    limit: int = Query(default=10, ge=1, le=50, description="Maximum number of results"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """
    Search repository code with natural-language query and hybrid relevance ranking (GET).
    """
    payload = SemanticSearchRequest(
        query=q,
        snapshot_id=snapshot_id,
        language=language,
        symbol_type=symbol_type,
        file_path_prefix=file_path_prefix,
        limit=limit,
    )
    return await semantic_search_post(
        repository_id=repository_id,
        payload=payload,
        workspace_id=workspace_id,
        current_user=current_user,
        _membership=_membership,
        db=db,
    )


@semantic_router.get(
    "/{repository_id}/semantic-chunks/{chunk_id}",
    response_model=SemanticChunkDetailResponse,
    summary="Retrieve full source and metadata of a specific code chunk",
)
async def get_semantic_chunk_detail(
    repository_id: uuid.UUID,
    chunk_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """
    Fetch exact source code excerpt and metadata for a semantic code chunk.
    Enforces workspace isolation.
    """
    stmt = select(SemanticCodeChunk).where(
        SemanticCodeChunk.id == chunk_id,
        SemanticCodeChunk.repository_id == repository_id,
        SemanticCodeChunk.workspace_id == workspace_id,
    )
    res = await db.execute(stmt)
    chunk = res.scalars().first()
    if not chunk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Semantic chunk {chunk_id} not found in workspace {workspace_id}",
        )
    return SemanticChunkDetailResponse(
        id=chunk.id,
        workspace_id=chunk.workspace_id,
        repository_id=chunk.repository_id,
        snapshot_id=chunk.snapshot_id,
        file_id=chunk.file_id,
        file_path=chunk.file_path,
        language=chunk.language,
        symbol_name=chunk.symbol_name,
        symbol_type=chunk.symbol_type,
        parent_symbol_name=chunk.parent_symbol_name,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        content_hash=chunk.content_hash,
        metadata=chunk.metadata_,
        created_at=chunk.created_at,
    )


@semantic_router.post(
    "/{repository_id}/assemble-context",
    response_model=AssembledContextResponse,
    summary="Assemble structured prompt context for agent consumption",
)
async def assemble_agent_context(
    repository_id: uuid.UUID,
    payload: AssembledContextRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """
    Retrieve and assemble relevant code context into bounded structured Markdown
    ready for injection into future AI agent prompts (DevPilot, ImpactMind).
    """
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace {workspace_id}",
        )

    retrieval_engine = SemanticRetrievalEngine()
    results = await retrieval_engine.search(
        db=db,
        workspace_id=workspace_id,
        repository_id=repository_id,
        query=payload.query,
        snapshot_id=payload.snapshot_id,
        language=payload.language,
        limit=payload.limit,
    )

    assembly_engine = ContextAssemblyEngine(max_context_chars=payload.max_characters)
    assembled = assembly_engine.assemble(
        repository_id=repository_id,
        repository_name=repo.name,
        query=payload.query,
        retrieved_chunks=results,
        max_chars=payload.max_characters,
    )

    return AssembledContextResponse(
        repository_id=assembled.repository_id,
        repository_name=assembled.repository_name,
        query=assembled.query,
        total_chunks_retrieved=assembled.total_chunks_retrieved,
        total_blocks_included=assembled.total_blocks_included,
        total_characters=assembled.total_characters,
        estimated_tokens=assembled.estimated_tokens,
        formatted_context_markdown=assembled.formatted_context_markdown,
        blocks=[
            AssembledCodeBlockResponse(
                file_path=b.file_path,
                language=b.language,
                start_line=b.start_line,
                end_line=b.end_line,
                symbol_name=b.symbol_name,
                symbol_type=b.symbol_type,
                parent_symbol_name=b.parent_symbol_name,
                code=b.code,
                similarity_score=b.similarity_score,
            )
            for b in assembled.blocks
        ],
    )
