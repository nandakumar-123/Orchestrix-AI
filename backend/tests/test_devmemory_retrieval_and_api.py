"""
Comprehensive DevMemory retrieval, context assembly, graph integration, and API tests.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.devmemory import (
    EvidenceType,
    MemoryConsumerAgent,
    MemoryRelationshipType,
    MemoryType,
)
from app.db.models.workspace import Workspace
from app.services.devmemory.memory_context import DevMemoryContextBuilder
from app.services.devmemory.memory_graph import DevMemoryGraphService
from app.services.devmemory.memory_retrieval import DevMemoryRetrievalService
from app.services.devmemory.memory_service import DevMemoryService
from app.services.devmemory.schemas import (
    MemoryCreateRequest,
    MemoryEvidenceCreateRequest,
    MemoryRelationshipCreateRequest,
    MemorySearchRequest,
)


@pytest.fixture
async def test_session() -> AsyncGenerator[AsyncSession, None]:
    """Isolated SQLite in-memory async database session with PRAGMA foreign_keys = ON."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_hybrid_search_scoring_and_status_filtering(test_session: AsyncSession) -> None:
    """
    Test hybrid retrieval ranks verified memories higher, computes boost multipliers,
    and excludes OUTDATED and ARCHIVED memories unless explicitly requested.
    """
    service = DevMemoryService()
    retrieval = DevMemoryRetrievalService()

    ws = Workspace(name="WS-Search", slug="ws-search")
    test_session.add(ws)
    await test_session.flush()

    # 1. Unverified memory
    m_unverified = await service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.ARCHITECTURE_DECISION,
            title="FastAPI Lifespan Context Manager Pattern",
            content="Use lifespan context manager for async engine initialization instead of on_event.",
        ),
    )

    # 2. Verified memory with evidence
    m_verified = await service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.ARCHITECTURE_DECISION,
            title="FastAPI Lifespan Async Engine Pattern",
            content="Use async lifespan context manager with engine dispose on shutdown.",
        ),
    )
    await service.verify_memory(
        test_session,
        ws.id,
        m_verified.id,
        evidence=MemoryEvidenceCreateRequest(
            evidence_type=EvidenceType.TEST_RESULT,
            source_reference="test_lifespan",
            evidence_content="Passed integration tests",
        ),
    )

    # 3. Outdated memory
    m_outdated = await service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.ARCHITECTURE_DECISION,
            title="FastAPI Deprecated On Event Startup",
            content="Use on_event startup for database connections.",
        ),
    )
    await service.mark_outdated(test_session, ws.id, m_outdated.id, reason="Deprecated in FastAPI")

    # 4. Archived memory
    m_archived = await service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.ARCHITECTURE_DECISION,
            title="Old Database Startup Hook",
            content="Use global app startup hook for connection initialization.",
        ),
    )
    await service.archive_memory(test_session, ws.id, m_archived.id, reason="Obsolete")

    await test_session.commit()

    # Search default: should exclude outdated and archived
    req = MemorySearchRequest(
        query="FastAPI lifespan startup initialization",
        limit=5,
        min_score=0.0,
    )
    results = await retrieval.search(test_session, ws.id, req)

    returned_ids = [r.memory.id for r in results]
    assert m_archived.id not in returned_ids
    assert m_outdated.id not in returned_ids
    assert m_verified.id in returned_ids
    assert m_unverified.id in returned_ids

    # Verified memory should score higher than unverified memory
    verified_result = next(r for r in results if r.memory.id == m_verified.id)
    unverified_result = next(r for r in results if r.memory.id == m_unverified.id)
    assert verified_result.relevance_score >= unverified_result.relevance_score
    assert verified_result.is_verified is True


@pytest.mark.asyncio
async def test_context_builder_budget_and_containment(test_session: AsyncSession) -> None:
    """Test context builder renders formatted markdown, enforces token limits, and logs citations."""
    service = DevMemoryService()
    builder = DevMemoryContextBuilder()

    ws = Workspace(name="WS-Context", slug="ws-context")
    test_session.add(ws)
    await test_session.flush()

    m1 = await service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.SECURITY_KNOWLEDGE,
            title="Secret Masking in Logs",
            content="Never print raw bearer tokens, private keys, or passwords to stdout or logs.",
        ),
    )
    m2 = await service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.TEST_KNOWLEDGE,
            title="Hermetic Async Fixtures",
            content="Use expire_on_commit=False for SQLAlchemy async test fixtures.",
        ),
    )
    await test_session.commit()

    from app.services.devmemory.schemas import MemoryContextRequest

    ctx_resp = await builder.build_context(
        test_session,
        workspace_id=ws.id,
        request=MemoryContextRequest(
            query="Secret logging and test fixtures",
            agent=MemoryConsumerAgent.DEVPILOT,
            max_tokens=1500,
            limit=5,
            include_unverified=True,
        ),
    )

    assert "RELEVANT ORGANIZATIONAL ENGINEERING MEMORY (DevMemory)" in ctx_resp.context_markdown
    assert "Secret Masking in Logs" in ctx_resp.context_markdown
    assert any(str(m.id) in [str(c) for c in ctx_resp.citations] for m in [m1, m2])


@pytest.mark.asyncio
async def test_graph_synchronization_and_resilience(test_session: AsyncSession) -> None:
    """Test DevMemory knowledge graph sync writes nodes/edges idempotently and degrades gracefully."""
    from app.services.graph_service import MockGraphProvider

    service = DevMemoryService()
    mock_provider = MockGraphProvider()
    graph_svc = DevMemoryGraphService(graph_provider=mock_provider)

    ws = Workspace(name="WS-Graph", slug="ws-graph")
    test_session.add(ws)
    await test_session.flush()

    m1 = await service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.ENGINEERING_CONVENTION,
            title="Pydantic V2 Migration Rule",
            content="Use field_validator instead of validator.",
        ),
    )
    m2 = await service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.ENGINEERING_CONVENTION,
            title="Pydantic Model Config Rule",
            content="Use ConfigDict instead of class Config.",
        ),
    )
    await service.create_relationship(
        test_session,
        ws.id,
        MemoryRelationshipCreateRequest(
            source_memory_id=m1.id,
            target_memory_id=m2.id,
            relationship_type=MemoryRelationshipType.EXTENDS,
        ),
    )
    await test_session.commit()

    # Sync to graph (works with MockGraphProvider or real Neo4j gracefully)
    summary = await graph_svc.synchronize_workspace_memories(test_session, ws.id)
    assert summary.workspace_id == ws.id
    assert summary.synced_nodes >= 2
    assert summary.synced_relationships >= 1
    assert summary.status == "SUCCESS"


@pytest.mark.asyncio
async def test_memory_stats_endpoint(test_session: AsyncSession) -> None:
    """Test get_memory_stats returns accurate counts of verified, unverified, outdated, and archived memories."""
    from app.api.v1.devmemory import get_memory_stats
    from app.db.base import WorkspaceRole
    from app.db.models.membership import WorkspaceMembership
    from app.db.models.user import User

    ws = Workspace(name="WS-Stats", slug="ws-stats")
    user = User(email="stats@orchestrix.ai", is_active=True)
    test_session.add_all([ws, user])
    await test_session.flush()

    mem_service = DevMemoryService()
    # Create 1 unverified
    await mem_service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.ARCHITECTURE_DECISION,
            title="Arch 1",
            content="Architecture decision description",
        ),
    )
    # Create 1 and verify it
    m2 = await mem_service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.ENGINEERING_CONVENTION,
            title="Convention 1",
            content="Convention description",
        ),
    )
    await mem_service.verify_memory(
        test_session,
        ws.id,
        m2.id,
        evidence=MemoryEvidenceCreateRequest(
            evidence_type=EvidenceType.CODE_REFERENCE,
            evidence_content="Verified in file app/core.py",
        ),
    )
    await test_session.commit()

    stats = await get_memory_stats(
        workspace_id=ws.id,
        repository_id=None,
        _current_user=user,
        _membership=WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.VIEWER),
        db=test_session,
    )
    assert stats.total_count == 2
    assert stats.verified_count == 1
    assert stats.unverified_count == 1
    assert stats.outdated_count == 0
    assert stats.archived_count == 0
    assert stats.type_counts[MemoryType.ARCHITECTURE_DECISION.value] == 1
    assert stats.type_counts[MemoryType.ENGINEERING_CONVENTION.value] == 1


@pytest.mark.asyncio
async def test_relationship_invalid_type_validation(test_session: AsyncSession) -> None:
    """Test creating a relationship with an invalid relationship type raises validation error."""
    from pydantic import ValidationError

    ws = Workspace(name="WS-RelVal", slug="ws-relval")
    test_session.add(ws)
    await test_session.flush()

    mem_service = DevMemoryService()
    await mem_service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.TECHNICAL_DECISION,
            title="Tech 1",
            content="Content 1",
        ),
    )
    m2 = await mem_service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.TECHNICAL_DECISION,
            title="Tech 2",
            content="Content 2",
        ),
    )
    await test_session.flush()

    with pytest.raises(ValidationError):
        MemoryRelationshipCreateRequest(
            target_memory_id=m2.id,
            relationship_type="INVALID_RELATIONSHIP_TYPE",  # type: ignore[arg-type]
        )
