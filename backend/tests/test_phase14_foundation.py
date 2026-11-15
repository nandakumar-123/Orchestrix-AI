"""
Phase 14 Step 1: Foundation Tests for FlowForge and DevMemory.

Validates:
1. FlowForge database models, relationships, triggers, executions, steps, approvals, and events.
2. DevMemory database models, embeddings, evidence, relationships, and access logs.
3. Tenant isolation (workspace scoping) for both systems.
4. Audit retention (RESTRICT delete on execution-bound definitions) and cascade integrity.
5. Schema check constraints (confidence score bounds, relationship self-loop prevention, content hash uniqueness).
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

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
    WorkflowEvent,
    WorkflowEventType,
    WorkflowExecution,
    WorkflowExecutionStatus,
    WorkflowStatus,
    WorkflowStepExecution,
    WorkflowStepStatus,
    WorkflowTrigger,
    WorkflowTriggerType,
    WorkflowVersion,
    Workspace,
)

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
async def seed_data(test_session: AsyncSession) -> dict[str, object]:
    """Seed baseline user, workspace, and repository."""
    user = User(
        email="lead-architect@orchestrix.ai",
        full_name="Lead Architect",
    )
    workspace = Workspace(
        name="Platform Core Team",
        slug="platform-core-team",
    )
    test_session.add_all([user, workspace])
    await test_session.commit()
    await test_session.refresh(user)
    await test_session.refresh(workspace)

    installation = GitHubInstallation(
        workspace_id=workspace.id,
        installation_id=5551234,
        account_login="orchestrix",
        account_type="Organization",
        account_id=67890,
    )
    test_session.add(installation)
    await test_session.commit()
    await test_session.refresh(installation)

    repo = Repository(
        workspace_id=workspace.id,
        installation_id=installation.id,
        name="workflow-engine-core",
        full_name="orchestrix/workflow-engine-core",
        owner_login="orchestrix",
        html_url="https://github.com/orchestrix/workflow-engine-core",
        github_repository_id=88123456,
        default_branch="main",
    )
    test_session.add(repo)
    await test_session.commit()
    await test_session.refresh(repo)

    return {"user": user, "workspace": workspace, "repo": repo}


# =============================================================================
# FlowForge Foundation Tests
# =============================================================================


async def test_flowforge_workflow_definition_and_versions(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Validate FlowForge workflow definition and immutable version relationships."""
    workspace = seed_data["workspace"]
    user = seed_data["user"]
    assert isinstance(workspace, Workspace)
    assert isinstance(user, User)

    # 1. Create Workflow Definition
    workflow = WorkflowDefinition(
        workspace_id=workspace.id,
        name="Autonomous CI Remediation",
        description="Triggered on test failure, dispatches TestPilot and DevPilot",
        status=WorkflowStatus.DRAFT,
        created_by=user.id,
    )
    test_session.add(workflow)
    await test_session.commit()
    await test_session.refresh(workflow)

    assert workflow.id is not None
    assert workflow.name == "Autonomous CI Remediation"
    assert workflow.status == WorkflowStatus.DRAFT

    # 2. Add Versions
    v1 = WorkflowVersion(
        workflow_id=workflow.id,
        workspace_id=workspace.id,
        version_number=1,
        workflow_definition_json={
            "nodes": [
                {"id": "trigger", "type": "event", "name": "CI Failure"},
                {"id": "analyze", "type": "agent", "name": "SecureFlow Analysis"},
            ],
            "edges": [{"from": "trigger", "to": "analyze"}],
        },
        description="Initial v1 graph definition",
        created_by=user.id,
    )
    v2 = WorkflowVersion(
        workflow_id=workflow.id,
        workspace_id=workspace.id,
        version_number=2,
        workflow_definition_json={
            "nodes": [
                {"id": "trigger", "type": "event", "name": "CI Failure"},
                {"id": "analyze", "type": "agent", "name": "SecureFlow Analysis"},
                {"id": "remediate", "type": "agent", "name": "DevPilot Remediation"},
            ],
            "edges": [
                {"from": "trigger", "to": "analyze"},
                {"from": "analyze", "to": "remediate"},
            ],
        },
        description="Added DevPilot remediation stage",
        created_by=user.id,
    )
    test_session.add_all([v1, v2])
    await test_session.commit()
    await test_session.refresh(workflow)

    # Re-fetch versions
    versions = (
        await test_session.scalars(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow.id)
            .order_by(WorkflowVersion.version_number)
        )
    ).all()

    assert len(versions) == 2
    assert versions[0].version_number == 1
    assert versions[1].version_number == 2
    assert versions[1].workflow_definition_json["nodes"][2]["id"] == "remediate"


async def test_flowforge_triggers(test_session: AsyncSession, seed_data: dict[str, object]) -> None:
    """Validate FlowForge trigger definitions and configuration storage."""
    workspace = seed_data["workspace"]
    user = seed_data["user"]
    assert isinstance(workspace, Workspace)
    assert isinstance(user, User)

    workflow = WorkflowDefinition(
        workspace_id=workspace.id,
        name="Scheduled Security Scan",
        status=WorkflowStatus.ACTIVE,
        created_by=user.id,
    )
    test_session.add(workflow)
    await test_session.commit()
    await test_session.refresh(workflow)

    # Add schedule trigger
    schedule_trigger = WorkflowTrigger(
        workflow_id=workflow.id,
        workspace_id=workspace.id,
        trigger_type=WorkflowTriggerType.SCHEDULE,
        configuration_json={"cron": "0 2 * * *", "timezone": "UTC"},
        enabled=True,
    )

    # Add webhook trigger
    webhook_trigger = WorkflowTrigger(
        workflow_id=workflow.id,
        workspace_id=workspace.id,
        trigger_type=WorkflowTriggerType.WEBHOOK,
        configuration_json={"endpoint_path": "/hooks/workflows/github"},
        enabled=False,
    )
    test_session.add_all([schedule_trigger, webhook_trigger])
    await test_session.commit()

    triggers = (
        await test_session.scalars(
            select(WorkflowTrigger)
            .where(WorkflowTrigger.workflow_id == workflow.id)
            .order_by(WorkflowTrigger.trigger_type)
        )
    ).all()

    assert len(triggers) == 2
    assert triggers[0].trigger_type == WorkflowTriggerType.SCHEDULE
    assert triggers[0].enabled is True
    assert triggers[0].configuration_json["cron"] == "0 2 * * *"
    assert triggers[1].trigger_type == WorkflowTriggerType.WEBHOOK
    assert triggers[1].enabled is False


async def test_flowforge_executions_steps_and_approvals(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Validate WorkflowExecution, StepExecution, Approvals, and Events tracking."""
    workspace = seed_data["workspace"]
    user = seed_data["user"]
    assert isinstance(workspace, Workspace)
    assert isinstance(user, User)

    # 1. Create Workflow and Version
    workflow = WorkflowDefinition(
        workspace_id=workspace.id,
        name="Production Deployment Gate",
        status=WorkflowStatus.ACTIVE,
    )
    test_session.add(workflow)
    await test_session.commit()
    await test_session.refresh(workflow)

    version = WorkflowVersion(
        workflow_id=workflow.id,
        workspace_id=workspace.id,
        version_number=1,
        workflow_definition_json={"nodes": [], "edges": []},
    )
    test_session.add(version)
    await test_session.commit()
    await test_session.refresh(version)

    # 2. Start Execution
    execution = WorkflowExecution(
        workflow_id=workflow.id,
        workflow_version_id=version.id,
        workspace_id=workspace.id,
        status=WorkflowExecutionStatus.RUNNING,
        context_data={"target_env": "production", "image_tag": "v1.4.0"},
        started_at=datetime.now(UTC),
    )
    test_session.add(execution)
    await test_session.commit()
    await test_session.refresh(execution)

    # 3. Add Step Execution
    step1 = WorkflowStepExecution(
        execution_id=execution.id,
        workspace_id=workspace.id,
        node_id="gate-approval",
        node_name="Security Sign-off",
        agent_type="HUMAN",
        status=WorkflowStepStatus.WAITING_FOR_APPROVAL,
        input_reference={"required_approvers": 1},
        started_at=datetime.now(UTC),
    )
    test_session.add(step1)
    await test_session.commit()
    await test_session.refresh(step1)

    # 4. Add Workflow Approval
    approval = WorkflowApproval(
        execution_id=execution.id,
        step_execution_id=step1.id,
        workspace_id=workspace.id,
        requested_by=user.id,
        status=WorkflowApprovalStatus.PENDING,
    )
    test_session.add(approval)
    await test_session.commit()
    await test_session.refresh(approval)

    # 5. Add Workflow Event
    event = WorkflowEvent(
        execution_id=execution.id,
        workspace_id=workspace.id,
        event_type=WorkflowEventType.APPROVAL_REQUESTED,
        payload_json={"reason": "Awaiting Admin Sign-off", "approval_id": str(approval.id)},
    )
    test_session.add(event)
    await test_session.commit()

    # 6. Approve
    approval.status = WorkflowApprovalStatus.APPROVED
    approval.approved_by = user.id
    approval.decision_reason = "Security audit verified clean. Approved."
    approval.decided_at = datetime.now(UTC)

    step1.status = WorkflowStepStatus.COMPLETED
    step1.completed_at = datetime.now(UTC)
    step1.output_reference = {"approved_by": str(user.id)}

    execution.status = WorkflowExecutionStatus.COMPLETED
    execution.completed_at = datetime.now(UTC)

    await test_session.commit()
    await test_session.refresh(execution)
    await test_session.refresh(approval)

    assert execution.status == WorkflowExecutionStatus.COMPLETED
    assert approval.status == WorkflowApprovalStatus.APPROVED
    assert approval.decision_reason == "Security audit verified clean. Approved."
    assert len(execution.steps) == 1
    assert len(execution.events) == 1


async def test_flowforge_audit_retention_and_cascade(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """
    Verify audit retention:
    - Attempting to delete a workflow definition with executions fails (RESTRICT).
    - Deleting an execution cascades to step executions and approvals.
    """
    workspace = seed_data["workspace"]
    assert isinstance(workspace, Workspace)

    workflow = WorkflowDefinition(
        workspace_id=workspace.id,
        name="Audit Retained Flow",
        status=WorkflowStatus.ACTIVE,
    )
    test_session.add(workflow)
    await test_session.commit()
    await test_session.refresh(workflow)

    version = WorkflowVersion(
        workflow_id=workflow.id,
        workspace_id=workspace.id,
        version_number=1,
        workflow_definition_json={},
    )
    test_session.add(version)
    await test_session.commit()
    await test_session.refresh(version)

    execution = WorkflowExecution(
        workflow_id=workflow.id,
        workflow_version_id=version.id,
        workspace_id=workspace.id,
        status=WorkflowExecutionStatus.COMPLETED,
    )
    test_session.add(execution)
    await test_session.commit()
    await test_session.refresh(execution)

    step = WorkflowStepExecution(
        execution_id=execution.id,
        workspace_id=workspace.id,
        node_id="step-1",
        node_name="Step 1",
        status=WorkflowStepStatus.COMPLETED,
    )
    test_session.add(step)
    await test_session.commit()

    # Attempting to delete workflow should fail due to RESTRICT on flowforge_workflow_executions
    await test_session.delete(workflow)
    with pytest.raises(IntegrityError):
        await test_session.commit()

    await test_session.rollback()

    # Deleting execution should cascade and delete step execution
    await test_session.delete(execution)
    await test_session.commit()

    steps_left = (
        await test_session.scalars(
            select(WorkflowStepExecution).where(WorkflowStepExecution.execution_id == execution.id)
        )
    ).all()
    assert len(steps_left) == 0


# =============================================================================
# DevMemory Foundation Tests
# =============================================================================


async def test_devmemory_creation_and_vector_embedding(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Validate DevMemory creation, vector embedding storage, and confidence scoring."""
    workspace = seed_data["workspace"]
    user = seed_data["user"]
    repo = seed_data["repo"]
    assert isinstance(workspace, Workspace)
    assert isinstance(user, User)
    assert isinstance(repo, Repository)

    # 384-dimensional mock vector
    dummy_vector = [0.05 * (i % 10) for i in range(384)]

    memory = EngineeringMemory(
        workspace_id=workspace.id,
        repository_id=repo.id,
        memory_type=MemoryType.ARCHITECTURE_DECISION,
        source_type=MemorySourceType.USER_INPUT,
        title="PostgreSQL Neon Partitioning and Connection Pooling",
        summary="Use PgBouncer transaction mode for Neon serverless database pooling.",
        content=(
            "Detailed rationale: Neon requires transaction pooling when scaled to zero. "
            "All async SQLAlchemy connections must disable statement preparation."
        ),
        content_hash="a1b2c3d4e5f67890abcdef1234567890abcdef1234567890abcdef1234567890",
        embedding=dummy_vector,
        confidence_score=0.95,
        verification_status=MemoryVerificationStatus.VERIFIED,
        created_by=user.id,
        metadata_={"decision_maker": "lead-architect", "adr_id": "ADR-042"},
    )
    test_session.add(memory)
    await test_session.commit()
    await test_session.refresh(memory)

    assert memory.id is not None
    assert memory.memory_type == MemoryType.ARCHITECTURE_DECISION
    assert memory.confidence_score == 0.95
    assert memory.verification_status == MemoryVerificationStatus.VERIFIED
    assert len(memory.embedding) == 384
    assert memory.embedding[0] == 0.0


async def test_devmemory_evidence_and_relationships(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Validate MemoryEvidence attachments and bidirectional MemoryRelationships."""
    workspace = seed_data["workspace"]
    repo = seed_data["repo"]
    assert isinstance(workspace, Workspace)
    assert isinstance(repo, Repository)

    mem1 = EngineeringMemory(
        workspace_id=workspace.id,
        repository_id=repo.id,
        memory_type=MemoryType.ENGINEERING_CONVENTION,
        source_type=MemorySourceType.AGENT_EXECUTION,
        title="Async Job Object Sandboxing",
        summary="Isolate subprocesses in Windows Job Objects with timeout enforcement.",
        content="Subprocesses must be assigned to Windows Job Objects to prevent orphan processes.",
        content_hash="hash-1111111111111111111111111111111111111111111111111111111111111111",
        confidence_score=0.85,
    )
    mem2 = EngineeringMemory(
        workspace_id=workspace.id,
        repository_id=repo.id,
        memory_type=MemoryType.ENGINEERING_CONVENTION,
        source_type=MemorySourceType.AGENT_EXECUTION,
        title="Cross-platform Process Group Sandboxing",
        summary="Unified Windows Job Objects and POSIX process groups.",
        content="Supersedes pure Windows approach by wrapping setpgid and Job Objects together.",
        content_hash="hash-2222222222222222222222222222222222222222222222222222222222222222",
        confidence_score=0.92,
    )
    test_session.add_all([mem1, mem2])
    await test_session.commit()
    await test_session.refresh(mem1)
    await test_session.refresh(mem2)

    # 1. Add Evidence to mem2
    evidence = MemoryEvidence(
        memory_id=mem2.id,
        workspace_id=workspace.id,
        evidence_type=EvidenceType.CODE_SNIPPET,
        source_reference="backend/app/services/job_runner.py#L45-80",
        evidence_content="class ProcessGroupIsolationContext: ...",
    )
    test_session.add(evidence)
    await test_session.commit()
    await test_session.refresh(evidence)

    assert evidence.memory_id == mem2.id
    assert evidence.evidence_type == EvidenceType.CODE_SNIPPET

    # 2. Add Relationship: mem2 SUPERSEDES mem1
    rel = MemoryRelationship(
        workspace_id=workspace.id,
        source_memory_id=mem2.id,
        target_memory_id=mem1.id,
        relationship_type=MemoryRelationshipType.SUPERSEDES,
        confidence_score=0.90,
    )
    test_session.add(rel)
    await test_session.commit()
    await test_session.refresh(rel)

    assert rel.relationship_type == MemoryRelationshipType.SUPERSEDES
    assert rel.source_memory_id == mem2.id
    assert rel.target_memory_id == mem1.id

    # Check relationships collection
    await test_session.refresh(mem2)
    assert len(mem2.outgoing_relationships) == 1
    assert mem2.outgoing_relationships[0].target_memory_id == mem1.id


async def test_devmemory_access_logging(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Validate tracking of agent memory retrieval and citation via MemoryAccessLog."""
    workspace = seed_data["workspace"]
    user = seed_data["user"]
    assert isinstance(workspace, Workspace)
    assert isinstance(user, User)

    memory = EngineeringMemory(
        workspace_id=workspace.id,
        memory_type=MemoryType.ENGINEERING_CONVENTION,
        source_type=MemorySourceType.USER_INPUT,
        title="Strict Tenant Isolation on All Queries",
        summary="All database queries must enforce workspace_id filtering.",
        content="Every SELECT/UPDATE/DELETE query must filter by workspace_id explicitly.",
        content_hash="hash-3333333333333333333333333333333333333333333333333333333333333333",
        confidence_score=1.0,
    )
    test_session.add(memory)
    await test_session.commit()
    await test_session.refresh(memory)

    access_log = MemoryAccessLog(
        memory_id=memory.id,
        workspace_id=workspace.id,
        agent_type=MemoryConsumerAgent.DEVPILOT,
        access_type=MemoryAccessType.RETRIEVE,
        context_metadata={
            "query_text": "how do we ensure tenant isolation?",
            "relevance_score": 0.96,
        },
    )
    test_session.add(access_log)
    await test_session.commit()
    await test_session.refresh(access_log)
    await test_session.refresh(memory)

    assert access_log.agent_type == MemoryConsumerAgent.DEVPILOT
    assert access_log.access_type == MemoryAccessType.RETRIEVE
    assert access_log.context_metadata["relevance_score"] == 0.96
    assert len(memory.access_logs) == 1


async def test_devmemory_content_hash_uniqueness(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Validate content hash deduplication per workspace."""
    workspace = seed_data["workspace"]
    assert isinstance(workspace, Workspace)

    m1 = EngineeringMemory(
        workspace_id=workspace.id,
        memory_type=MemoryType.REPO_KNOWLEDGE,
        source_type=MemorySourceType.AGENT_EXECUTION,
        title="Deduplication Test 1",
        summary="First instance",
        content="Identical content body",
        content_hash="duplicate_hash_value_12345",
        confidence_score=0.8,
    )
    test_session.add(m1)
    await test_session.commit()

    # Second memory with same workspace_id and content_hash must violate unique constraint
    m2 = EngineeringMemory(
        workspace_id=workspace.id,
        memory_type=MemoryType.REPO_KNOWLEDGE,
        source_type=MemorySourceType.AGENT_EXECUTION,
        title="Deduplication Test 2",
        summary="Second instance",
        content="Identical content body",
        content_hash="duplicate_hash_value_12345",
        confidence_score=0.8,
    )
    test_session.add(m2)
    with pytest.raises(IntegrityError):
        await test_session.commit()

    await test_session.rollback()


async def test_tenant_isolation_boundary(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Validate that FlowForge and DevMemory records are completely partitioned by workspace_id."""
    ws1 = seed_data["workspace"]
    assert isinstance(ws1, Workspace)

    # Create second workspace
    ws2 = Workspace(
        name="Secondary Isolated Team",
        slug="secondary-isolated-team",
    )
    test_session.add(ws2)
    await test_session.commit()
    await test_session.refresh(ws2)

    # 1. FlowForge separation
    wf1 = WorkflowDefinition(
        workspace_id=ws1.id,
        name="Workflow WS1",
    )
    wf2 = WorkflowDefinition(
        workspace_id=ws2.id,
        name="Workflow WS2",
    )
    test_session.add_all([wf1, wf2])

    # 2. DevMemory separation
    dm1 = EngineeringMemory(
        workspace_id=ws1.id,
        memory_type=MemoryType.ENGINEERING_CONVENTION,
        source_type=MemorySourceType.USER_INPUT,
        title="Memory WS1",
        summary="Summary WS1",
        content="Content WS1",
        content_hash="hash_ws1_content",
        confidence_score=0.9,
    )
    dm2 = EngineeringMemory(
        workspace_id=ws2.id,
        memory_type=MemoryType.ENGINEERING_CONVENTION,
        source_type=MemorySourceType.USER_INPUT,
        title="Memory WS2",
        summary="Summary WS2",
        content="Content WS2",
        content_hash="hash_ws2_content",
        confidence_score=0.9,
    )
    test_session.add_all([dm1, dm2])
    await test_session.commit()

    # Query WS1 records only
    ws1_workflows = (
        await test_session.scalars(
            select(WorkflowDefinition).where(WorkflowDefinition.workspace_id == ws1.id)
        )
    ).all()
    ws1_memories = (
        await test_session.scalars(
            select(EngineeringMemory).where(EngineeringMemory.workspace_id == ws1.id)
        )
    ).all()

    assert len(ws1_workflows) == 1
    assert ws1_workflows[0].name == "Workflow WS1"
    assert len(ws1_memories) == 1
    assert ws1_memories[0].title == "Memory WS1"

    # Query WS2 records only
    ws2_workflows = (
        await test_session.scalars(
            select(WorkflowDefinition).where(WorkflowDefinition.workspace_id == ws2.id)
        )
    ).all()
    ws2_memories = (
        await test_session.scalars(
            select(EngineeringMemory).where(EngineeringMemory.workspace_id == ws2.id)
        )
    ).all()

    assert len(ws2_workflows) == 1
    assert ws2_workflows[0].name == "Workflow WS2"
    assert len(ws2_memories) == 1
    assert ws2_memories[0].title == "Memory WS2"


async def test_devmemory_constraints(
    test_session: AsyncSession, seed_data: dict[str, object]
) -> None:
    """Validate check constraints on confidence score bounds and relationship self-loops."""
    workspace = seed_data["workspace"]
    assert isinstance(workspace, Workspace)
    ws_id = workspace.id

    # 1. Invalid confidence score > 1.0 on memory
    invalid_mem = EngineeringMemory(
        workspace_id=ws_id,
        memory_type=MemoryType.ENGINEERING_CONVENTION,
        source_type=MemorySourceType.USER_INPUT,
        title="Invalid Confidence Score",
        content="Out of bounds",
        content_hash="hash_invalid_score",
        confidence_score=1.5,
    )
    test_session.add(invalid_mem)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()

    # 2. Self-loop relationship (source == target)
    valid_mem = EngineeringMemory(
        workspace_id=ws_id,
        memory_type=MemoryType.ENGINEERING_CONVENTION,
        source_type=MemorySourceType.USER_INPUT,
        title="Valid Node",
        content="Testing self-loop",
        content_hash="hash_valid_node",
        confidence_score=0.9,
    )
    test_session.add(valid_mem)
    await test_session.commit()
    await test_session.refresh(valid_mem)

    self_loop = MemoryRelationship(
        workspace_id=ws_id,
        source_memory_id=valid_mem.id,
        target_memory_id=valid_mem.id,
        relationship_type=MemoryRelationshipType.RELATES_TO,
        confidence_score=0.9,
    )
    test_session.add(self_loop)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()
