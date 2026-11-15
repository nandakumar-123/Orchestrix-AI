"""
Phase 14 Step 1.1: DevMemory & FlowForge Tenant Integrity & Audit Retention Hardening Tests.

Validates:
1. Cross-workspace memory relationships are strictly rejected at the database constraint level.
2. Mismatched memory access-log workspace IDs are strictly rejected.
3. Cross-workspace memory evidence attachments are strictly rejected.
4. Repository isolation: memories cannot reference a repository from another workspace.
5. FlowForge step executions, approvals, and events enforce composite tenant and execution foreign keys.
6. Workflow version uniqueness is enforced.
7. Memory audit retention: memories with access logs cannot be deleted (ondelete=RESTRICT), requiring archiving.
8. Shared 384-dimensional embedding provider reuse and vector representation.
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    EngineeringMemory,
    EvidenceType,
    GitHubInstallation,
    MemoryAccessLog,
    MemoryAccessType,
    MemoryConsumerAgent,
    MemoryEvidence,
    MemoryRelationship,
    MemoryRelationshipType,
    MemorySourceType,
    MemoryType,
    MemoryVerificationStatus,
    Repository,
    User,
    WorkflowApproval,
    WorkflowApprovalStatus,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionStatus,
    WorkflowStatus,
    WorkflowStepExecution,
    WorkflowStepStatus,
    WorkflowVersion,
    Workspace,
)
from app.services.embedding_service import get_embedding_provider

pytestmark = pytest.mark.asyncio


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


@pytest.fixture
async def dual_workspaces(test_session: AsyncSession) -> dict[str, object]:
    """Seed two completely separate workspaces, users, installations, and repositories."""
    u1 = User(email="tenant-a-lead@orchestrix.ai", full_name="Tenant A Lead")
    u2 = User(email="tenant-b-lead@orchestrix.ai", full_name="Tenant B Lead")
    ws1 = Workspace(name="Workspace Alpha", slug="workspace-alpha")
    ws2 = Workspace(name="Workspace Beta", slug="workspace-beta")
    test_session.add_all([u1, u2, ws1, ws2])
    await test_session.commit()
    await test_session.refresh(u1)
    await test_session.refresh(u2)
    await test_session.refresh(ws1)
    await test_session.refresh(ws2)

    inst1 = GitHubInstallation(
        workspace_id=ws1.id,
        installation_id=111100,
        account_login="alpha-corp",
        account_type="Organization",
        account_id=101,
    )
    inst2 = GitHubInstallation(
        workspace_id=ws2.id,
        installation_id=222200,
        account_login="beta-corp",
        account_type="Organization",
        account_id=202,
    )
    test_session.add_all([inst1, inst2])
    await test_session.commit()
    await test_session.refresh(inst1)
    await test_session.refresh(inst2)

    repo1 = Repository(
        workspace_id=ws1.id,
        installation_id=inst1.id,
        name="alpha-service",
        full_name="alpha-corp/alpha-service",
        owner_login="alpha-corp",
        html_url="https://github.com/alpha-corp/alpha-service",
        github_repository_id=111999,
        default_branch="main",
    )
    repo2 = Repository(
        workspace_id=ws2.id,
        installation_id=inst2.id,
        name="beta-service",
        full_name="beta-corp/beta-service",
        owner_login="beta-corp",
        html_url="https://github.com/beta-corp/beta-service",
        github_repository_id=222999,
        default_branch="main",
    )
    test_session.add_all([repo1, repo2])
    await test_session.commit()
    await test_session.refresh(repo1)
    await test_session.refresh(repo2)

    return {
        "ws1": ws1,
        "ws2": ws2,
        "u1": u1,
        "u2": u2,
        "repo1": repo1,
        "repo2": repo2,
    }


# =============================================================================
# DevMemory Tenant Isolation Hardening Tests
# =============================================================================


async def test_cross_workspace_memory_relationship_rejected(
    test_session: AsyncSession, dual_workspaces: dict[str, object]
) -> None:
    """Verify that a relationship connecting memories across distinct workspaces is rejected."""
    ws1 = dual_workspaces["ws1"]
    ws2 = dual_workspaces["ws2"]
    assert isinstance(ws1, Workspace)
    assert isinstance(ws2, Workspace)
    ws1_id = ws1.id
    ws2_id = ws2.id

    # Memory in Workspace 1
    mem_ws1 = EngineeringMemory(
        workspace_id=ws1_id,
        memory_type=MemoryType.ARCHITECTURE_DECISION,
        source_type=MemorySourceType.USER_INPUT,
        title="Workspace 1 Architecture",
        content="Internal decision for WS1",
        content_hash="hash_ws1_unique_rel",
        confidence_score=0.9,
    )
    # Memory in Workspace 2
    mem_ws2 = EngineeringMemory(
        workspace_id=ws2_id,
        memory_type=MemoryType.ARCHITECTURE_DECISION,
        source_type=MemorySourceType.USER_INPUT,
        title="Workspace 2 Architecture",
        content="Internal decision for WS2",
        content_hash="hash_ws2_unique_rel",
        confidence_score=0.9,
    )
    test_session.add_all([mem_ws1, mem_ws2])
    await test_session.commit()
    await test_session.refresh(mem_ws1)
    await test_session.refresh(mem_ws2)
    mem_ws1_id = mem_ws1.id
    mem_ws2_id = mem_ws2.id

    # Attempt to link mem_ws1 and mem_ws2 with workspace_id = ws1_id
    cross_rel_1 = MemoryRelationship(
        workspace_id=ws1_id,
        source_memory_id=mem_ws1_id,
        target_memory_id=mem_ws2_id,  # belongs to ws2!
        relationship_type=MemoryRelationshipType.RELATES_TO,
        confidence_score=0.8,
    )
    test_session.add(cross_rel_1)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()

    # Attempt to link mem_ws1 and mem_ws2 with workspace_id = ws2_id
    cross_rel_2 = MemoryRelationship(
        workspace_id=ws2_id,
        source_memory_id=mem_ws1_id,  # belongs to ws1!
        target_memory_id=mem_ws2_id,
        relationship_type=MemoryRelationshipType.RELATES_TO,
        confidence_score=0.8,
    )
    test_session.add(cross_rel_2)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


async def test_mismatched_access_log_workspace_rejected(
    test_session: AsyncSession, dual_workspaces: dict[str, object]
) -> None:
    """Verify that an access log referencing a memory in another workspace is rejected."""
    ws1 = dual_workspaces["ws1"]
    ws2 = dual_workspaces["ws2"]
    assert isinstance(ws1, Workspace)
    assert isinstance(ws2, Workspace)

    mem_ws1 = EngineeringMemory(
        workspace_id=ws1.id,
        memory_type=MemoryType.ENGINEERING_CONVENTION,
        source_type=MemorySourceType.AGENT_EXECUTION,
        title="Workspace 1 Secret Memory",
        content="Classified content",
        content_hash="hash_ws1_access_log",
        confidence_score=1.0,
    )
    test_session.add(mem_ws1)
    await test_session.commit()
    await test_session.refresh(mem_ws1)

    # Attempt to log access from workspace 2 referencing workspace 1 memory
    mismatched_log = MemoryAccessLog(
        memory_id=mem_ws1.id,
        workspace_id=ws2.id,  # Mismatched!
        agent_type=MemoryConsumerAgent.DEVPILOT,
        access_type=MemoryAccessType.RETRIEVE,
    )
    test_session.add(mismatched_log)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


async def test_repository_isolation_mismatched_workspace_rejected(
    test_session: AsyncSession, dual_workspaces: dict[str, object]
) -> None:
    """Verify that a memory cannot reference a repository belonging to another workspace."""
    ws1 = dual_workspaces["ws1"]
    repo2 = dual_workspaces["repo2"]
    assert isinstance(ws1, Workspace)
    assert isinstance(repo2, Repository)

    # Attempt to create memory in ws1 referencing repo2 (which belongs to ws2)
    leaked_memory = EngineeringMemory(
        workspace_id=ws1.id,
        repository_id=repo2.id,  # Belongs to ws2!
        memory_type=MemoryType.REPO_KNOWLEDGE,
        source_type=MemorySourceType.AGENT_EXECUTION,
        title="Cross Repository Leak Attempt",
        content="Attempting to attach ws2 repo to ws1 memory",
        content_hash="hash_cross_repo_leak",
        confidence_score=0.9,
    )
    test_session.add(leaked_memory)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


async def test_mismatched_memory_evidence_workspace_rejected(
    test_session: AsyncSession, dual_workspaces: dict[str, object]
) -> None:
    """Verify that memory evidence must match the memory's workspace."""
    ws1 = dual_workspaces["ws1"]
    ws2 = dual_workspaces["ws2"]
    assert isinstance(ws1, Workspace)
    assert isinstance(ws2, Workspace)

    mem_ws1 = EngineeringMemory(
        workspace_id=ws1.id,
        memory_type=MemoryType.VERIFIED_BUGFIX,
        source_type=MemorySourceType.AGENT_EXECUTION,
        title="Bugfix in WS1",
        content="Fix for WS1 issue",
        content_hash="hash_ws1_evidence_test",
        confidence_score=0.95,
    )
    test_session.add(mem_ws1)
    await test_session.commit()
    await test_session.refresh(mem_ws1)

    mismatched_evidence = MemoryEvidence(
        memory_id=mem_ws1.id,
        workspace_id=ws2.id,  # Mismatched!
        evidence_type=EvidenceType.CODE_SNIPPET,
        evidence_content="corroborating snippet",
    )
    test_session.add(mismatched_evidence)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


async def test_devmemory_audit_retention_on_access_log(
    test_session: AsyncSession, dual_workspaces: dict[str, object]
) -> None:
    """Verify that cited/accessed memories cannot be hard-deleted (RESTRICT), preserving audit history."""
    ws1 = dual_workspaces["ws1"]
    assert isinstance(ws1, Workspace)

    memory = EngineeringMemory(
        workspace_id=ws1.id,
        memory_type=MemoryType.ARCHITECTURE_DECISION,
        source_type=MemorySourceType.USER_INPUT,
        title="Critical Security Decision",
        content="Never expose internal ports",
        content_hash="hash_critical_audit_mem",
        confidence_score=1.0,
    )
    test_session.add(memory)
    await test_session.commit()
    await test_session.refresh(memory)

    access_log = MemoryAccessLog(
        memory_id=memory.id,
        workspace_id=ws1.id,
        agent_type=MemoryConsumerAgent.DEVPILOT,
        access_type=MemoryAccessType.CITE,
    )
    test_session.add(access_log)
    await test_session.commit()

    # Attempting to delete the memory directly must fail with RESTRICT constraint
    await test_session.delete(memory)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()

    # Soft-archiving the memory instead preserves history cleanly
    await test_session.refresh(memory)
    memory.verification_status = MemoryVerificationStatus.ARCHIVED
    await test_session.commit()
    await test_session.refresh(memory)

    assert memory.verification_status == MemoryVerificationStatus.ARCHIVED
    assert len(memory.access_logs) == 1


# =============================================================================
# FlowForge Tenant Isolation & Audit Retention Hardening Tests
# =============================================================================


async def test_mismatched_flowforge_step_execution_workspace_rejected(
    test_session: AsyncSession, dual_workspaces: dict[str, object]
) -> None:
    """Verify that workflow step executions cannot reference an execution from another workspace."""
    ws1 = dual_workspaces["ws1"]
    ws2 = dual_workspaces["ws2"]
    assert isinstance(ws1, Workspace)
    assert isinstance(ws2, Workspace)

    workflow = WorkflowDefinition(
        workspace_id=ws1.id,
        name="Flow WS1",
        status=WorkflowStatus.ACTIVE,
    )
    test_session.add(workflow)
    await test_session.commit()
    await test_session.refresh(workflow)

    version = WorkflowVersion(
        workflow_id=workflow.id,
        workspace_id=ws1.id,
        version_number=1,
        workflow_definition_json={},
    )
    test_session.add(version)
    await test_session.commit()
    await test_session.refresh(version)

    execution = WorkflowExecution(
        workflow_id=workflow.id,
        workflow_version_id=version.id,
        workspace_id=ws1.id,
        status=WorkflowExecutionStatus.RUNNING,
    )
    test_session.add(execution)
    await test_session.commit()
    await test_session.refresh(execution)

    # Step execution with mismatched workspace_id = ws2
    mismatched_step = WorkflowStepExecution(
        execution_id=execution.id,
        workspace_id=ws2.id,  # Mismatched!
        node_id="step-mismatch",
        status=WorkflowStepStatus.RUNNING,
    )
    test_session.add(mismatched_step)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


async def test_mismatched_flowforge_approval_execution_and_step_rejected(
    test_session: AsyncSession, dual_workspaces: dict[str, object]
) -> None:
    """Verify that approval records cannot mix steps and executions from different runs."""
    ws1 = dual_workspaces["ws1"]
    assert isinstance(ws1, Workspace)

    workflow = WorkflowDefinition(
        workspace_id=ws1.id,
        name="Gate Flow",
        status=WorkflowStatus.ACTIVE,
    )
    test_session.add(workflow)
    await test_session.commit()
    await test_session.refresh(workflow)

    version = WorkflowVersion(
        workflow_id=workflow.id,
        workspace_id=ws1.id,
        version_number=1,
        workflow_definition_json={},
    )
    test_session.add(version)
    await test_session.commit()
    await test_session.refresh(version)

    exec1 = WorkflowExecution(
        workflow_id=workflow.id,
        workflow_version_id=version.id,
        workspace_id=ws1.id,
        status=WorkflowExecutionStatus.RUNNING,
    )
    exec2 = WorkflowExecution(
        workflow_id=workflow.id,
        workflow_version_id=version.id,
        workspace_id=ws1.id,
        status=WorkflowExecutionStatus.RUNNING,
    )
    test_session.add_all([exec1, exec2])
    await test_session.commit()
    await test_session.refresh(exec1)
    await test_session.refresh(exec2)

    step2 = WorkflowStepExecution(
        execution_id=exec2.id,
        workspace_id=ws1.id,
        node_id="step-2",
        status=WorkflowStepStatus.WAITING_FOR_APPROVAL,
    )
    test_session.add(step2)
    await test_session.commit()
    await test_session.refresh(step2)

    # Attempt to associate approval with exec1, but referencing step2 (from exec2)
    cross_approval = WorkflowApproval(
        execution_id=exec1.id,  # Mismatch!
        step_execution_id=step2.id,  # From exec2!
        workspace_id=ws1.id,
        status=WorkflowApprovalStatus.PENDING,
    )
    test_session.add(cross_approval)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


async def test_duplicate_workflow_version_rejected(
    test_session: AsyncSession, dual_workspaces: dict[str, object]
) -> None:
    """Verify that duplicate version numbers for a given workflow are rejected."""
    ws1 = dual_workspaces["ws1"]
    assert isinstance(ws1, Workspace)

    workflow = WorkflowDefinition(
        workspace_id=ws1.id,
        name="Versioned Flow",
        status=WorkflowStatus.ACTIVE,
    )
    test_session.add(workflow)
    await test_session.commit()
    await test_session.refresh(workflow)

    v1_a = WorkflowVersion(
        workflow_id=workflow.id,
        workspace_id=ws1.id,
        version_number=1,
        workflow_definition_json={"nodes": []},
    )
    test_session.add(v1_a)
    await test_session.commit()

    # Second version with identical version_number = 1
    v1_b = WorkflowVersion(
        workflow_id=workflow.id,
        workspace_id=ws1.id,
        version_number=1,
        workflow_definition_json={"nodes": [{"id": "diff"}]},
    )
    test_session.add(v1_b)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


# =============================================================================
# Embedding Provider Reuse Tests
# =============================================================================


async def test_embedding_provider_reuse(
    test_session: AsyncSession, dual_workspaces: dict[str, object]
) -> None:
    """Verify that DevMemory directly reuses the existing 384-dimensional embedding provider."""
    ws1 = dual_workspaces["ws1"]
    assert isinstance(ws1, Workspace)

    provider = get_embedding_provider()
    assert provider.dimension == 384

    sample_text = "FastEmbed and pgvector unified semantic indexing pipeline"
    vector = await provider.embed_query(sample_text)
    assert len(vector) == 384

    # Save to EngineeringMemory and verify retrieval
    memory = EngineeringMemory(
        workspace_id=ws1.id,
        memory_type=MemoryType.REPO_KNOWLEDGE,
        source_type=MemorySourceType.AGENT_EXECUTION,
        title="Unified Embedding Architecture",
        content=sample_text,
        content_hash="hash_unified_embedding_test",
        embedding=vector,
        confidence_score=0.98,
    )
    test_session.add(memory)
    await test_session.commit()
    await test_session.refresh(memory)

    assert memory.id is not None
    assert memory.embedding is not None
    assert len(memory.embedding) == 384

    # Query back
    stored = await test_session.scalar(
        select(EngineeringMemory).where(EngineeringMemory.id == memory.id)
    )
    assert stored is not None
    assert stored.embedding is not None
    assert len(stored.embedding) == 384
