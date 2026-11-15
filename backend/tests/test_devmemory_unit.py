from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.devmemory import (
    EvidenceType,
    MemoryRelationshipType,
    MemorySourceType,
    MemoryType,
    MemoryVerificationStatus,
)
from app.db.models.github_installation import GitHubInstallation
from app.db.models.repository import Repository
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.services.devmemory.memory_service import (
    DevMemoryService,
    InvalidMemoryTransitionError,
    MemoryNotFoundError,
)
from app.services.devmemory.schemas import (
    MemoryCreateRequest,
    MemoryEvidenceCreateRequest,
    MemoryRelationshipCreateRequest,
    MemoryUpdateRequest,
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
        await session.execute(text("PRAGMA foreign_keys = ON;"))
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_memory_creation_lifecycle_and_redaction(test_session: AsyncSession) -> None:
    """Test memory creation defaults to UNVERIFIED, redacts secrets, and computes content hash."""
    service = DevMemoryService()
    ws = Workspace(name="WS-Mem-1", slug="ws-mem-1")
    user = User(email="author@example.com", full_name="Author")
    test_session.add_all([ws, user])
    await test_session.flush()

    raw_content = "Architecture decision using token ghp_1234567890abcdef1234567890abcdef1234 and AWS key AKIAIOSFODNN7EXAMPLE"
    req = MemoryCreateRequest(
        memory_type=MemoryType.ARCHITECTURE_DECISION,
        title="Database Migration Choice (AKIAIOSFODNN7EXAMPLE)",
        content=raw_content,
        summary="Summary with ghp_1234567890abcdef1234567890abcdef1234",
        source_type=MemorySourceType.USER_INPUT,
        confidence_score=0.95,
    )

    mem = await service.create_memory(test_session, ws.id, req, created_by=user.id)
    await test_session.commit()

    assert mem.verification_status == MemoryVerificationStatus.UNVERIFIED.value
    assert "[REDACTED_SECRET]" in mem.content
    assert "AKIAIOSFODNN7EXAMPLE" not in mem.content
    assert "ghp_1234567890abcdef1234567890abcdef1234" not in mem.content
    assert "[REDACTED_SECRET]" in mem.title
    assert mem.content_hash is not None


@pytest.mark.asyncio
async def test_memory_deduplication_returns_existing(test_session: AsyncSession) -> None:
    """Test exact duplicate creation returns existing memory instead of duplicate record."""
    service = DevMemoryService()
    ws = Workspace(name="WS-Dedup", slug="ws-dedup")
    test_session.add(ws)
    await test_session.flush()

    req = MemoryCreateRequest(
        memory_type=MemoryType.REPOSITORY_CONVENTION,
        title="Code Formatting Standard",
        content="Always run ruff check backend before commit.",
        source_type=MemorySourceType.USER_INPUT,
    )

    mem1 = await service.create_memory(test_session, ws.id, req)
    await test_session.commit()

    mem2 = await service.create_memory(test_session, ws.id, req)
    await test_session.commit()

    assert mem1.id == mem2.id


@pytest.mark.asyncio
async def test_verification_workflow_requires_evidence(test_session: AsyncSession) -> None:
    """Test memory cannot be VERIFIED without concrete evidence."""
    service = DevMemoryService()
    ws = Workspace(name="WS-Verify", slug="ws-verify")
    test_session.add(ws)
    await test_session.flush()

    req = MemoryCreateRequest(
        memory_type=MemoryType.VERIFIED_SOLUTION,
        title="Async SQLite Connection Fix",
        content="Configure expire_on_commit=False on AsyncSession.",
        source_type=MemorySourceType.AGENT_EXECUTION,
    )
    mem = await service.create_memory(test_session, ws.id, req)
    await test_session.commit()

    # Attempt verification without evidence -> Expect failure
    with pytest.raises(InvalidMemoryTransitionError):
        await service.verify_memory(test_session, ws.id, mem.id, evidence=None)

    # Verification with evidence -> Success
    ev = MemoryEvidenceCreateRequest(
        evidence_type=EvidenceType.TEST_RESULT,
        source_reference="test_suite_execution_123",
        evidence_content="Passed 311 pytest unit and integration tests cleanly.",
    )
    verified_mem = await service.verify_memory(
        test_session, ws.id, mem.id, evidence=ev, reason="Empirical test confirmation"
    )
    await test_session.commit()

    assert verified_mem.verification_status == MemoryVerificationStatus.VERIFIED.value
    assert len(verified_mem.evidence) == 1
    assert verified_mem.evidence[0].evidence_type == EvidenceType.TEST_RESULT.value


@pytest.mark.asyncio
async def test_outdated_and_archived_lifecycle(test_session: AsyncSession) -> None:
    """Test OUTDATED and ARCHIVED transitions and immutability of archived records."""
    service = DevMemoryService()
    ws = Workspace(name="WS-Life", slug="ws-life")
    test_session.add(ws)
    await test_session.flush()

    req = MemoryCreateRequest(
        memory_type=MemoryType.DEPENDENCY_KNOWLEDGE,
        title="Legacy Python 3.9 Deprecation",
        content="All packages must support Python 3.9 runtime.",
    )
    mem = await service.create_memory(test_session, ws.id, req)
    await test_session.commit()

    # Mark outdated
    outdated = await service.mark_outdated(
        test_session, ws.id, mem.id, reason="Upgraded to Python 3.11"
    )
    await test_session.commit()
    assert outdated.verification_status == MemoryVerificationStatus.OUTDATED.value

    # Archive memory
    archived = await service.archive_memory(test_session, ws.id, mem.id, reason="Retired standard")
    await test_session.commit()
    assert archived.verification_status == MemoryVerificationStatus.ARCHIVED.value

    # Attempting to update archived memory raises InvalidMemoryTransitionError
    with pytest.raises(InvalidMemoryTransitionError):
        await service.update_memory(
            test_session, ws.id, mem.id, MemoryUpdateRequest(title="New Title")
        )


@pytest.mark.asyncio
async def test_cross_workspace_memory_and_relationship_isolation(
    test_session: AsyncSession,
) -> None:
    """Verify memories and relationships cannot cross workspace boundaries."""
    service = DevMemoryService()
    ws_a = Workspace(name="WS-A", slug="ws-a")
    ws_b = Workspace(name="WS-B", slug="ws-b")
    test_session.add_all([ws_a, ws_b])
    await test_session.flush()

    mem_a = await service.create_memory(
        test_session,
        ws_a.id,
        MemoryCreateRequest(
            memory_type=MemoryType.ARCHITECTURE_DECISION,
            title="Tenant A Private Arch",
            content="Private proprietary architecture in Workspace A.",
        ),
    )
    mem_b = await service.create_memory(
        test_session,
        ws_b.id,
        MemoryCreateRequest(
            memory_type=MemoryType.ARCHITECTURE_DECISION,
            title="Tenant B Private Arch",
            content="Private proprietary architecture in Workspace B.",
        ),
    )
    await test_session.commit()

    # Workspace B cannot read Workspace A memory
    with pytest.raises(MemoryNotFoundError):
        await service.get_memory(test_session, ws_b.id, mem_a.id)

    # Cross-workspace relationship creation fails
    with pytest.raises(MemoryNotFoundError):
        await service.create_relationship(
            test_session,
            ws_a.id,
            MemoryRelationshipCreateRequest(
                source_memory_id=mem_a.id,
                target_memory_id=mem_b.id,
                relationship_type=MemoryRelationshipType.RELATES_TO,
            ),
        )


@pytest.mark.asyncio
async def test_relationship_supersession_marks_target_outdated(test_session: AsyncSession) -> None:
    """Test SUPERSEDES relationship automatically marks target memory OUTDATED."""
    service = DevMemoryService()
    ws = Workspace(name="WS-Rel", slug="ws-rel")
    test_session.add(ws)
    await test_session.flush()

    old_mem = await service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.TECHNICAL_DECISION,
            title="Use REST for internal IPC",
            content="All internal services communicate over HTTP REST.",
        ),
    )
    new_mem = await service.create_memory(
        test_session,
        ws.id,
        MemoryCreateRequest(
            memory_type=MemoryType.TECHNICAL_DECISION,
            title="Adopt gRPC for internal IPC",
            content="Internal services communicate over high-performance gRPC.",
        ),
    )
    await test_session.commit()

    rel = await service.create_relationship(
        test_session,
        ws.id,
        MemoryRelationshipCreateRequest(
            source_memory_id=new_mem.id,
            target_memory_id=old_mem.id,
            relationship_type=MemoryRelationshipType.SUPERSEDES,
        ),
    )
    await test_session.commit()

    assert rel.relationship_type == MemoryRelationshipType.SUPERSEDES.value
    # Target memory must now be OUTDATED
    refreshed_old = await service.get_memory(test_session, ws.id, old_mem.id)
    assert refreshed_old.verification_status == MemoryVerificationStatus.OUTDATED.value


@pytest.mark.asyncio
async def test_repository_aware_deduplication_isolation(test_session: AsyncSession) -> None:
    """
    Test repository-aware deduplication:
    1. Identical content in Repository A and Repository B creates two distinct repository-scoped memories.
    2. Re-submitting identical content in Repository A returns existing Repository A memory.
    3. Workspace-wide memories (repository_id=None) deduplicate across the workspace.
    4. Identical content in different workspaces creates distinct memories.
    """
    service = DevMemoryService()
    ws1 = Workspace(name="WS-Repo-Dedup-1", slug="ws-repo-dedup-1")
    ws2 = Workspace(name="WS-Repo-Dedup-2", slug="ws-repo-dedup-2")
    test_session.add_all([ws1, ws2])
    await test_session.flush()

    inst1 = GitHubInstallation(
        workspace_id=ws1.id,
        installation_id=101,
        account_login="org",
        account_type="Organization",
        account_id=9001,
    )
    inst2 = GitHubInstallation(
        workspace_id=ws2.id,
        installation_id=102,
        account_login="org",
        account_type="Organization",
        account_id=9001,
    )
    test_session.add_all([inst1, inst2])
    await test_session.flush()

    repo_a = Repository(
        workspace_id=ws1.id,
        installation_id=inst1.id,
        github_repository_id=1001,
        name="service-alpha",
        full_name="org/service-alpha",
        owner_login="org",
        default_branch="main",
        html_url="https://github.com/org/service-alpha",
    )
    repo_b = Repository(
        workspace_id=ws1.id,
        installation_id=inst1.id,
        github_repository_id=1002,
        name="service-beta",
        full_name="org/service-beta",
        owner_login="org",
        default_branch="main",
        html_url="https://github.com/org/service-beta",
    )
    repo_c = Repository(
        workspace_id=ws2.id,
        installation_id=inst2.id,
        github_repository_id=2001,
        name="service-alpha",
        full_name="org/service-alpha",
        owner_login="org",
        default_branch="main",
        html_url="https://github.com/org/service-alpha",
    )
    test_session.add_all([repo_a, repo_b, repo_c])
    await test_session.flush()

    common_content = "Always validate JWT signatures with asymmetric public key rotation."

    # 1. Create memory in Repo A
    req_a = MemoryCreateRequest(
        memory_type=MemoryType.SECURITY_KNOWLEDGE,
        title="JWT Validation Rule",
        content=common_content,
        repository_id=repo_a.id,
    )
    mem_a1 = await service.create_memory(test_session, ws1.id, req_a)
    await test_session.commit()

    # 2. Re-submitting in Repo A returns existing Repo A memory
    mem_a2 = await service.create_memory(test_session, ws1.id, req_a)
    await test_session.commit()
    assert mem_a1.id == mem_a2.id
    assert mem_a1.repository_id == repo_a.id

    # 3. Create identical content in Repo B -> Must be distinct memory with distinct content hash
    req_b = MemoryCreateRequest(
        memory_type=MemoryType.SECURITY_KNOWLEDGE,
        title="JWT Validation Rule",
        content=common_content,
        repository_id=repo_b.id,
    )
    mem_b = await service.create_memory(test_session, ws1.id, req_b)
    await test_session.commit()
    assert mem_b.id != mem_a1.id
    assert mem_b.repository_id == repo_b.id
    assert mem_b.content_hash != mem_a1.content_hash

    # 4. Workspace-wide memory with same content in WS1
    req_ws = MemoryCreateRequest(
        memory_type=MemoryType.SECURITY_KNOWLEDGE,
        title="JWT Validation Rule",
        content=common_content,
        repository_id=None,
    )
    mem_ws1 = await service.create_memory(test_session, ws1.id, req_ws)
    await test_session.commit()
    assert mem_ws1.id != mem_a1.id
    assert mem_ws1.id != mem_b.id
    assert mem_ws1.repository_id is None
    assert mem_ws1.content_hash != mem_a1.content_hash

    # Submitting identical workspace-wide memory in WS1 returns mem_ws1
    mem_ws1_dup = await service.create_memory(test_session, ws1.id, req_ws)
    await test_session.commit()
    assert mem_ws1_dup.id == mem_ws1.id

    # 5. Create identical content in Repo C in WS2 -> Isolated to WS2
    req_c = MemoryCreateRequest(
        memory_type=MemoryType.SECURITY_KNOWLEDGE,
        title="JWT Validation Rule",
        content=common_content,
        repository_id=repo_c.id,
    )
    mem_c = await service.create_memory(test_session, ws2.id, req_c)
    await test_session.commit()
    assert mem_c.id != mem_a1.id
    assert mem_c.workspace_id == ws2.id
    assert mem_c.content_hash != mem_a1.content_hash
