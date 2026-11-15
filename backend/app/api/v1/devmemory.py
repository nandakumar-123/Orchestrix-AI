from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    enforce_csrf_protection,
    get_current_user,
    require_workspace_membership,
)
from app.db.base import WorkspaceRole
from app.db.models.devmemory import (
    EngineeringMemory,
    MemoryVerificationStatus,
)
from app.db.models.membership import WorkspaceMembership
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.devmemory.memory_context import DevMemoryContextBuilder
from app.services.devmemory.memory_graph import DevMemoryGraphService
from app.services.devmemory.memory_retrieval import DevMemoryRetrievalService
from app.services.devmemory.memory_service import (
    DevMemoryService,
    InvalidMemoryTransitionError,
    MemoryNotFoundError,
    TenantBoundaryViolationError,
)
from app.services.devmemory.schemas import (
    GraphSyncResponse,
    MemoryContextRequest,
    MemoryContextResponse,
    MemoryCreateRequest,
    MemoryEvidenceCreateRequest,
    MemoryEvidenceResponse,
    MemoryOutdateRequest,
    MemoryRelationshipCreateRequest,
    MemoryRelationshipResponse,
    MemoryResponse,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryStatsResponse,
    MemoryUpdateRequest,
    MemoryVerifyRequest,
)

logger = logging.getLogger("orchestrix.api.devmemory")

devmemory_router = APIRouter(prefix="/devmemory", tags=["DevMemory"])

_memory_service = DevMemoryService()
_retrieval_service = DevMemoryRetrievalService()
_context_builder = DevMemoryContextBuilder(_retrieval_service)
_graph_service = DevMemoryGraphService()


# =============================================================================
# Memory CRUD & Lifecycle Endpoints
# =============================================================================


@devmemory_router.post(
    "/memories",
    response_model=MemoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new engineering memory",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def create_memory(
    payload: MemoryCreateRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryResponse:
    try:
        mem = await _memory_service.create_memory(
            db=db,
            workspace_id=workspace_id,
            request=payload,
            created_by=current_user.id,
        )
        await db.commit()
        return MemoryResponse.model_validate(mem)
    except TenantBoundaryViolationError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except Exception as e:
        await db.rollback()
        logger.exception(f"Failed to create memory: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@devmemory_router.get(
    "/memories",
    response_model=list[MemoryResponse],
    summary="List engineering memories in workspace",
)
async def list_memories(
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    repository_id: uuid.UUID | None = Query(None, description="Optional repository filter"),
    verification_status: str | None = Query(None, description="Filter by verification status"),
    memory_type: str | None = Query(None, description="Filter by memory type"),
    include_archived: bool = Query(False, description="Include archived memories"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> list[MemoryResponse]:
    stmt = (
        select(EngineeringMemory)
        .where(EngineeringMemory.workspace_id == workspace_id)
        .options(selectinload(EngineeringMemory.evidence))
        .order_by(EngineeringMemory.created_at.desc())
    )
    if repository_id:
        stmt = stmt.where(EngineeringMemory.repository_id == repository_id)
    if verification_status:
        stmt = stmt.where(EngineeringMemory.verification_status == verification_status)
    elif not include_archived:
        stmt = stmt.where(
            EngineeringMemory.verification_status != MemoryVerificationStatus.ARCHIVED.value
        )
    if memory_type:
        stmt = stmt.where(EngineeringMemory.memory_type == memory_type)

    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    memories = list(res.scalars().all())
    return [MemoryResponse.model_validate(m) for m in memories]


@devmemory_router.get(
    "/stats",
    response_model=MemoryStatsResponse,
    summary="Get aggregated memory statistics in workspace",
)
async def get_memory_stats(
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    repository_id: uuid.UUID | None = Query(None, description="Optional repository filter"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryStatsResponse:
    base_stmt = select(EngineeringMemory).where(EngineeringMemory.workspace_id == workspace_id)
    if repository_id:
        base_stmt = base_stmt.where(EngineeringMemory.repository_id == repository_id)

    res = await db.execute(base_stmt)
    memories = list(res.scalars().all())

    total = len(memories)
    verified = sum(1 for m in memories if m.verification_status == MemoryVerificationStatus.VERIFIED.value)
    unverified = sum(1 for m in memories if m.verification_status == MemoryVerificationStatus.UNVERIFIED.value)
    outdated = sum(1 for m in memories if m.verification_status == MemoryVerificationStatus.OUTDATED.value)
    archived = sum(1 for m in memories if m.verification_status == MemoryVerificationStatus.ARCHIVED.value)

    type_counts: dict[str, int] = {}
    for m in memories:
        t = str(m.memory_type)
        type_counts[t] = type_counts.get(t, 0) + 1

    return MemoryStatsResponse(
        total_count=total,
        verified_count=verified,
        unverified_count=unverified,
        outdated_count=outdated,
        archived_count=archived,
        type_counts=type_counts,
    )


@devmemory_router.get(
    "/memories/{memory_id}",
    response_model=MemoryResponse,
    summary="Get memory details",
)
async def get_memory(
    memory_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryResponse:
    try:
        mem = await _memory_service.get_memory(db, workspace_id, memory_id)
        await db.commit()
        return MemoryResponse.model_validate(mem)
    except MemoryNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@devmemory_router.patch(
    "/memories/{memory_id}",
    response_model=MemoryResponse,
    summary="Update permitted memory fields",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def update_memory(
    memory_id: uuid.UUID,
    payload: MemoryUpdateRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryResponse:
    try:
        mem = await _memory_service.update_memory(
            db=db,
            workspace_id=workspace_id,
            memory_id=memory_id,
            request=payload,
        )
        await db.commit()
        return MemoryResponse.model_validate(mem)
    except MemoryNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except InvalidMemoryTransitionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@devmemory_router.post(
    "/memories/{memory_id}/verify",
    response_model=MemoryResponse,
    summary="Verify memory with evidence",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def verify_memory(
    memory_id: uuid.UUID,
    payload: MemoryVerifyRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryResponse:
    try:
        mem = await _memory_service.verify_memory(
            db=db,
            workspace_id=workspace_id,
            memory_id=memory_id,
            evidence=payload.evidence,
            reason=payload.reason,
            verified_by=current_user.id,
        )
        await db.commit()
        return MemoryResponse.model_validate(mem)
    except MemoryNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except InvalidMemoryTransitionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@devmemory_router.post(
    "/memories/{memory_id}/outdate",
    response_model=MemoryResponse,
    summary="Mark memory as outdated",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def outdate_memory(
    memory_id: uuid.UUID,
    payload: MemoryOutdateRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryResponse:
    try:
        mem = await _memory_service.mark_outdated(
            db=db,
            workspace_id=workspace_id,
            memory_id=memory_id,
            reason=payload.reason,
        )
        await db.commit()
        return MemoryResponse.model_validate(mem)
    except MemoryNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except InvalidMemoryTransitionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@devmemory_router.post(
    "/memories/{memory_id}/archive",
    response_model=MemoryResponse,
    summary="Archive memory from active retrieval",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def archive_memory(
    memory_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    reason: str | None = Query(None, description="Reason for archival"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.ADMIN)),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryResponse:
    try:
        mem = await _memory_service.archive_memory(
            db=db,
            workspace_id=workspace_id,
            memory_id=memory_id,
            reason=reason,
        )
        await db.commit()
        return MemoryResponse.model_validate(mem)
    except MemoryNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


# =============================================================================
# Evidence Endpoints
# =============================================================================


@devmemory_router.post(
    "/memories/{memory_id}/evidence",
    response_model=MemoryEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach supporting evidence to memory",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def attach_evidence(
    memory_id: uuid.UUID,
    payload: MemoryEvidenceCreateRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryEvidenceResponse:
    try:
        ev = await _memory_service.attach_evidence(
            db=db,
            workspace_id=workspace_id,
            memory_id=memory_id,
            evidence=payload,
        )
        await db.commit()
        return MemoryEvidenceResponse.model_validate(ev)
    except MemoryNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except InvalidMemoryTransitionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@devmemory_router.get(
    "/memories/{memory_id}/evidence",
    response_model=list[MemoryEvidenceResponse],
    summary="List supporting evidence for memory",
)
async def list_evidence(
    memory_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> list[MemoryEvidenceResponse]:
    try:
        ev_list = await _memory_service.list_evidence(db, workspace_id, memory_id)
        return [MemoryEvidenceResponse.model_validate(e) for e in ev_list]
    except MemoryNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


# =============================================================================
# Retrieval & Context Endpoints
# =============================================================================


@devmemory_router.post(
    "/search",
    response_model=list[MemorySearchResult],
    summary="Semantic and hybrid memory retrieval",
)
async def search_memories(
    payload: MemorySearchRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> list[MemorySearchResult]:
    results = await _retrieval_service.search(
        db=db,
        workspace_id=workspace_id,
        request=payload,
    )
    await db.commit()
    return results


@devmemory_router.post(
    "/context",
    response_model=MemoryContextResponse,
    summary="Assemble structured markdown agent memory context",
)
async def build_context(
    payload: MemoryContextRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryContextResponse:
    ctx = await _context_builder.build_context(
        db=db,
        workspace_id=workspace_id,
        request=payload,
    )
    await db.commit()
    return ctx


# =============================================================================
# Relationships Endpoints
# =============================================================================


@devmemory_router.post(
    "/relationships",
    response_model=MemoryRelationshipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create semantic relationship between memories",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def create_relationship(
    payload: MemoryRelationshipCreateRequest,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryRelationshipResponse:
    try:
        rel = await _memory_service.create_relationship(
            db=db,
            workspace_id=workspace_id,
            request=payload,
        )
        await db.commit()
        return MemoryRelationshipResponse.model_validate(rel)
    except MemoryNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except InvalidMemoryTransitionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@devmemory_router.get(
    "/memories/{memory_id}/relationships",
    response_model=list[MemoryRelationshipResponse],
    summary="List relationships for a memory",
)
async def list_relationships(
    memory_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> list[MemoryRelationshipResponse]:
    try:
        rels = await _memory_service.list_relationships(db, workspace_id, memory_id)
        return [MemoryRelationshipResponse.model_validate(r) for r in rels]
    except MemoryNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


# =============================================================================
# Graph Endpoints
# =============================================================================


@devmemory_router.post(
    "/graph/synchronize",
    response_model=GraphSyncResponse,
    summary="Synchronize workspace memories to Knowledge Graph",
    dependencies=[Depends(enforce_csrf_protection)],
)
async def synchronize_graph(
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.ADMIN)),
    db: AsyncSession = Depends(get_db_session),
) -> GraphSyncResponse:
    return await _graph_service.synchronize_workspace_memories(db, workspace_id)


@devmemory_router.get(
    "/memories/{memory_id}/graph",
    summary="Get localized memory neighborhood graph",
)
async def get_memory_graph(
    memory_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    depth: int = Query(2, ge=1, le=5),
    _current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
) -> dict[str, Any]:
    return await _graph_service.get_memory_subgraph(workspace_id, memory_id, depth=depth)
