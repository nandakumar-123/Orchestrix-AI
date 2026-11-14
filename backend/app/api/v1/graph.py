from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    enforce_csrf_protection,
    get_current_user,
    require_workspace_membership,
)
from app.api.v1.schemas import (
    GraphEdgeResponse,
    GraphIndexStatusResponse,
    GraphIndexTriggerRequest,
    GraphNodeResponse,
    GraphQueryRequest,
    GraphQueryResponse,
    ImpactPreviewRequest,
    ImpactPreviewResponse,
    IntelligenceSearchRequest,
    SemanticSearchResponse,
    SemanticSearchResultItem,
    SubgraphResponse,
)
from app.db.base import WorkspaceRole
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.repository_intelligence import RepositorySnapshot
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.graph_indexing_service import GraphIndexingService
from app.services.graph_query_engine import GraphQueryEngine
from app.services.graph_service import get_graph_provider
from app.services.impact_analysis import ImpactAnalysisEngine
from app.services.semantic_retrieval import SemanticRetrievalEngine

graph_router = APIRouter(prefix="/repositories", tags=["knowledge-graph"])
logger = logging.getLogger("orchestrix.api.graph")


async def _resolve_snapshot_id(
    db: AsyncSession,
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID,
    explicit_snapshot_id: uuid.UUID | None,
) -> uuid.UUID:
    """Helper to resolve active snapshot ID if not explicitly provided."""
    if explicit_snapshot_id:
        snap = await db.get(RepositorySnapshot, explicit_snapshot_id)
        if not snap or snap.repository_id != repository_id or snap.workspace_id != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Snapshot {explicit_snapshot_id} not found in repository {repository_id}",
            )
        return snap.id

    stmt = (
        select(RepositorySnapshot.id)
        .where(
            RepositorySnapshot.repository_id == repository_id,
            RepositorySnapshot.workspace_id == workspace_id,
        )
        .order_by(desc(RepositorySnapshot.created_at))
        .limit(1)
    )
    res = await db.execute(stmt)
    active_id = res.scalar_one_or_none()
    if not active_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No indexed snapshot found for repository {repository_id}",
        )
    return active_id


@graph_router.post(
    "/{repository_id}/graph-index",
    response_model=GraphIndexStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger knowledge graph extraction and ingestion",
)
async def trigger_graph_indexing(
    repository_id: uuid.UUID,
    payload: GraphIndexTriggerRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.ADMIN)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Trigger multi-language code relationship graph indexing."""
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace {workspace_id}",
        )

    service = GraphIndexingService()
    try:
        result = await service.index_snapshot(
            db=db,
            snapshot_id=payload.snapshot_id,
            force_reindex=payload.force_reindex,
        )
        return GraphIndexStatusResponse(
            status=result["status"],
            snapshot_id=payload.snapshot_id,
            provider=result["provider"],
            total_nodes=result["total_nodes"],
            total_relationships=result["total_relationships"],
        )
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Graph indexing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Graph indexing error: {str(e)}",
        ) from e


@graph_router.get(
    "/{repository_id}/graph-index/status",
    response_model=GraphIndexStatusResponse,
    summary="Get knowledge graph index status",
)
async def get_graph_index_status(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    snapshot_id: uuid.UUID | None = Query(None, description="Snapshot ID"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Fetch status and counts of the repository knowledge graph."""
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace {workspace_id}",
        )

    target_snapshot_id = await _resolve_snapshot_id(db, repository_id, workspace_id, snapshot_id)
    service = GraphIndexingService()
    try:
        status_info = await service.get_index_status(db, target_snapshot_id)
        return GraphIndexStatusResponse(
            status=status_info["status"],
            snapshot_id=target_snapshot_id,
            provider=status_info["provider"],
            total_nodes=status_info["total_nodes"],
            total_relationships=status_info["total_relationships"],
            indexed_at=status_info.get("indexed_at"),
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


@graph_router.get(
    "/{repository_id}/graph",
    response_model=SubgraphResponse,
    summary="Fetch knowledge graph visual subgraph",
)
async def get_repository_graph(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    snapshot_id: uuid.UUID | None = Query(None, description="Snapshot ID"),
    file_path: str | None = Query(None, description="Filter by file path"),
    labels: list[str] | None = Query(None, description="Filter by node labels"),
    limit: int = Query(default=150, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Fetch visual subgraph for knowledge graph explorer."""
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace {workspace_id}",
        )

    target_snapshot_id = await _resolve_snapshot_id(db, repository_id, workspace_id, snapshot_id)
    provider = get_graph_provider()
    subgraph = await provider.get_subgraph(
        snapshot_id=target_snapshot_id,
        labels=labels,
        file_path=file_path,
        limit=limit,
    )

    return SubgraphResponse(
        nodes=[
            GraphNodeResponse(id=n["id"], label=n["label"], properties=n.get("properties", {}))
            for n in subgraph["nodes"]
        ],
        edges=[
            GraphEdgeResponse(
                source_id=e["source_id"],
                target_id=e["target_id"],
                type=e["type"],
                properties=e.get("properties", {}),
            )
            for e in subgraph["edges"]
        ],
        total_nodes=subgraph["total_nodes"],
        total_edges=subgraph["total_edges"],
    )


@graph_router.post(
    "/{repository_id}/graph/query",
    response_model=GraphQueryResponse,
    summary="Execute targeted knowledge graph query",
)
async def query_repository_graph(
    repository_id: uuid.UUID,
    payload: GraphQueryRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Execute targeted query (callers, implementations, importing_files, dependencies, circular_dependencies, path)."""
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace {workspace_id}",
        )

    target_snapshot_id = await _resolve_snapshot_id(
        db, repository_id, workspace_id, payload.snapshot_id
    )
    provider = get_graph_provider()
    engine = GraphQueryEngine(provider)
    sid = str(target_snapshot_id)

    qtype = payload.query_type.lower()
    results: Any = []
    if qtype == "callers":
        if not payload.target_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target_id is required for callers query",
            )
        results = await engine.find_callers(sid, payload.target_id, max_depth=payload.max_depth)
    elif qtype == "implementations":
        if not payload.target_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target_id is required for implementations query",
            )
        results = await engine.find_implementations(sid, payload.target_id)
    elif qtype == "importing_files":
        if not payload.file_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="file_path is required for importing_files query",
            )
        results = await engine.find_importing_files(sid, payload.file_path)
    elif qtype == "dependencies":
        if not payload.target_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target_id is required for dependencies query",
            )
        results = await engine.find_dependencies(
            sid,
            payload.target_id,
            direction=payload.direction,
            max_depth=payload.max_depth,
        )
    elif qtype == "circular_dependencies":
        results = await engine.find_circular_dependencies(sid)
    elif qtype == "path":
        if not payload.source_id or not payload.target_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="source_id and target_id are required for path query",
            )
        results = await engine.trace_path(
            payload.source_id, payload.target_id, max_depth=payload.max_depth
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown query_type: {payload.query_type}",
        )

    return GraphQueryResponse(
        query_type=payload.query_type,
        count=len(results) if isinstance(results, list) else (1 if results else 0),
        results=results,
    )


@graph_router.get(
    "/{repository_id}/graph/symbols/{symbol_id}/relationships",
    response_model=dict[str, Any],
    summary="Get direct graph relationships for a symbol",
)
async def get_symbol_relationships(
    repository_id: uuid.UUID,
    symbol_id: str,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    snapshot_id: uuid.UUID | None = Query(None, description="Snapshot ID"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Retrieve incoming and outgoing edges for an individual symbol."""
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace {workspace_id}",
        )

    target_snapshot_id = await _resolve_snapshot_id(db, repository_id, workspace_id, snapshot_id)
    provider = get_graph_provider()
    engine = GraphQueryEngine(provider)
    sid = str(target_snapshot_id)

    # Fetch incoming and outgoing dependencies
    incoming = await engine.find_dependencies(sid, symbol_id, direction="incoming", max_depth=1)
    outgoing = await engine.find_dependencies(sid, symbol_id, direction="outgoing", max_depth=1)

    return {
        "symbol_id": symbol_id,
        "snapshot_id": str(target_snapshot_id),
        "incoming_count": len(incoming),
        "outgoing_count": len(outgoing),
        "incoming": incoming,
        "outgoing": outgoing,
    }


@graph_router.post(
    "/{repository_id}/impact-preview",
    response_model=ImpactPreviewResponse,
    summary="Calculate blast radius and impact preview",
)
async def preview_change_impact(
    repository_id: uuid.UUID,
    payload: ImpactPreviewRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Compute code change blast radius, affected endpoints, models, and tests."""
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace {workspace_id}",
        )

    target_snapshot_id = await _resolve_snapshot_id(
        db, repository_id, workspace_id, payload.snapshot_id
    )
    provider = get_graph_provider()
    engine = ImpactAnalysisEngine(provider)

    res = await engine.analyze_impact(
        snapshot_id=str(target_snapshot_id),
        file_path=payload.file_path,
        symbol_name=payload.symbol_name,
        symbol_id=payload.symbol_id,
        max_depth=payload.max_depth,
    )

    subgraph = SubgraphResponse(
        nodes=[
            GraphNodeResponse(id=n["id"], label=n["label"], properties=n.get("properties", {}))
            for n in res.subgraph.get("nodes", [])
        ],
        edges=[
            GraphEdgeResponse(
                source_id=e["source_id"],
                target_id=e["target_id"],
                type=e["type"],
                properties=e.get("properties", {}),
            )
            for e in res.subgraph.get("edges", [])
        ],
        total_nodes=res.subgraph.get("total_nodes", 0),
        total_edges=res.subgraph.get("total_edges", 0),
    )

    return ImpactPreviewResponse(
        target_id=res.target_id,
        target_name=res.target_name,
        target_type=res.target_type,
        risk_level=res.risk_level,
        risk_score=res.risk_score,
        reasons=res.reasons,
        direct_dependents=res.direct_dependents,
        indirect_dependents=res.indirect_dependents,
        affected_endpoints=res.affected_endpoints,
        affected_tests=res.affected_tests,
        affected_database_models=res.affected_database_models,
        subgraph=subgraph,
    )


@graph_router.post(
    "/{repository_id}/intelligence/search",
    response_model=SemanticSearchResponse,
    summary="Unified hybrid semantic and graph code search",
)
async def intelligence_search(
    repository_id: uuid.UUID,
    payload: IntelligenceSearchRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Unified code intelligence search combining dense vectors, BM25, and graph relationships."""
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace {workspace_id}",
        )

    retrieval_engine = SemanticRetrievalEngine()
    if payload.include_graph_enrichment:
        provider = get_graph_provider()
        results = await retrieval_engine.search_with_graph(
            db=db,
            workspace_id=workspace_id,
            repository_id=repository_id,
            query=payload.query,
            graph_provider=provider,
            snapshot_id=payload.snapshot_id,
            language=payload.language,
            symbol_type=payload.symbol_type,
            file_path_prefix=payload.file_path_prefix,
            limit=payload.limit,
        )
    else:
        results = await retrieval_engine.search(
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
            metadata=r.metadata or {},
        )
        for r in results
    ]

    return SemanticSearchResponse(
        repository_id=repository_id,
        query=payload.query,
        total_results=len(items),
        results=items,
    )
