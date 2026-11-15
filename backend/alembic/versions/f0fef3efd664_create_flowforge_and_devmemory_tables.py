"""create_flowforge_and_devmemory_tables

Revision ID: f0fef3efd664
Revises: e5f6a7b8c9d0
Create Date: 2026-11-15 17:10:18.664913

"""

from collections.abc import Sequence

import pgvector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f0fef3efd664"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Upgrade schema to include FlowForge and DevMemory database foundations."""
    # Ensure pgvector extension is available in PostgreSQL
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # =========================================================================
    # 1. FlowForge: flowforge_workflows
    # =========================================================================
    op.create_table(
        "flowforge_workflows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_flowforge_workflows_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_flowforge_workflows_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flowforge_workflows")),
        sa.UniqueConstraint("workspace_id", "name", name="uq_flowforge_workflows_workspace_name"),
        sa.UniqueConstraint("id", "workspace_id", name="uq_flowforge_workflows_id_workspace"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'PAUSED', 'ARCHIVED')",
            name="ck_flowforge_workflows_status",
        ),
    )
    op.create_index(
        "ix_flowforge_workflows_workspace_id",
        "flowforge_workflows",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_flowforge_workflows_status",
        "flowforge_workflows",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_flowforge_workflows_created_at",
        "flowforge_workflows",
        ["created_at"],
        unique=False,
    )

    # =========================================================================
    # 2. FlowForge: flowforge_workflow_versions
    # =========================================================================
    op.create_table(
        "flowforge_workflow_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("workflow_definition_json", json_type, nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["flowforge_workflows.id"],
            name=op.f("fk_flowforge_workflow_versions_workflow_id_flowforge_workflows"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_flowforge_workflow_versions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_flowforge_workflow_versions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "workspace_id"],
            ["flowforge_workflows.id", "flowforge_workflows.workspace_id"],
            name="fk_flowforge_versions_workflow_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flowforge_workflow_versions")),
        sa.UniqueConstraint(
            "workflow_id",
            "version_number",
            name="uq_flowforge_versions_workflow_version",
        ),
        sa.UniqueConstraint("id", "workflow_id", name="uq_flowforge_versions_id_workflow"),
    )
    op.create_index(
        "ix_flowforge_versions_workflow_id",
        "flowforge_workflow_versions",
        ["workflow_id"],
        unique=False,
    )
    op.create_index(
        "ix_flowforge_versions_workspace_id",
        "flowforge_workflow_versions",
        ["workspace_id"],
        unique=False,
    )

    # =========================================================================
    # 3. FlowForge: flowforge_workflow_triggers
    # =========================================================================
    op.create_table(
        "flowforge_workflow_triggers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("trigger_type", sa.String(length=64), nullable=False),
        sa.Column("configuration_json", json_type, nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["flowforge_workflows.id"],
            name=op.f("fk_flowforge_workflow_triggers_workflow_id_flowforge_workflows"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_flowforge_workflow_triggers_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "workspace_id"],
            ["flowforge_workflows.id", "flowforge_workflows.workspace_id"],
            name="fk_flowforge_triggers_workflow_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flowforge_workflow_triggers")),
        sa.CheckConstraint(
            "trigger_type IN ('WEBHOOK', 'SCHEDULE', 'EVENT', 'MANUAL')",
            name="ck_flowforge_triggers_type",
        ),
    )
    op.create_index(
        "ix_flowforge_triggers_workflow_type",
        "flowforge_workflow_triggers",
        ["workflow_id", "trigger_type", "enabled"],
        unique=False,
    )
    op.create_index(
        "ix_flowforge_triggers_workspace_id",
        "flowforge_workflow_triggers",
        ["workspace_id"],
        unique=False,
    )

    # =========================================================================
    # 4. FlowForge: flowforge_workflow_executions
    # =========================================================================
    op.create_table(
        "flowforge_workflow_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("trigger_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("context_data", json_type, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["flowforge_workflows.id"],
            name=op.f("fk_flowforge_workflow_executions_workflow_id_flowforge_workflows"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["flowforge_workflow_versions.id"],
            name=op.f("fk_flowforge_workflow_executions_version_id_flowforge_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_flowforge_workflow_executions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_id"],
            ["flowforge_workflow_triggers.id"],
            name=op.f("fk_flowforge_workflow_executions_trigger_id_flowforge_triggers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id", "workflow_id"],
            [
                "flowforge_workflow_versions.id",
                "flowforge_workflow_versions.workflow_id",
            ],
            name="fk_flowforge_executions_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flowforge_workflow_executions")),
        sa.UniqueConstraint("id", "workspace_id", name="uq_flowforge_executions_id_workspace"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'WAITING_FOR_APPROVAL', 'COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT')",
            name="ck_flowforge_executions_status",
        ),
    )
    op.create_index(
        "ix_flowforge_executions_workspace_workflow",
        "flowforge_workflow_executions",
        ["workspace_id", "workflow_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_flowforge_executions_status",
        "flowforge_workflow_executions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_flowforge_executions_created_at",
        "flowforge_workflow_executions",
        ["created_at"],
        unique=False,
    )

    # =========================================================================
    # 5. FlowForge: flowforge_step_executions
    # =========================================================================
    op.create_table(
        "flowforge_step_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("node_name", sa.String(length=255), nullable=True),
        sa.Column("agent_type", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("input_reference", json_type, nullable=True),
        sa.Column("output_reference", json_type, nullable=True),
        sa.Column(
            "attempt_number",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["flowforge_workflow_executions.id"],
            name=op.f("fk_flowforge_step_executions_execution_id_flowforge_executions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_flowforge_step_executions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flowforge_step_executions")),
        sa.UniqueConstraint("id", "execution_id", name="uq_flowforge_steps_id_execution"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'WAITING_FOR_APPROVAL', 'COMPLETED', 'FAILED', 'SKIPPED', 'CANCELLED')",
            name="ck_flowforge_steps_status",
        ),
    )
    op.create_index(
        "ix_flowforge_steps_exec_node_attempt",
        "flowforge_step_executions",
        ["execution_id", "node_id", "attempt_number"],
        unique=False,
    )
    op.create_index(
        "ix_flowforge_steps_status",
        "flowforge_step_executions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_flowforge_steps_workspace_id",
        "flowforge_step_executions",
        ["workspace_id"],
        unique=False,
    )

    # =========================================================================
    # 6. FlowForge: flowforge_approvals
    # =========================================================================
    op.create_table(
        "flowforge_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("step_execution_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["flowforge_workflow_executions.id"],
            name=op.f("fk_flowforge_approvals_execution_id_flowforge_executions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_execution_id"],
            ["flowforge_step_executions.id"],
            name=op.f("fk_flowforge_approvals_step_id_flowforge_steps"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_flowforge_approvals_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_flowforge_approvals_requested_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_flowforge_approvals_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flowforge_approvals")),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'CANCELLED')",
            name="ck_flowforge_approvals_status",
        ),
    )
    op.create_index(
        "ix_flowforge_approvals_execution_id",
        "flowforge_approvals",
        ["execution_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_flowforge_approvals_step_id",
        "flowforge_approvals",
        ["step_execution_id"],
        unique=False,
    )
    op.create_index(
        "ix_flowforge_approvals_workspace_id",
        "flowforge_approvals",
        ["workspace_id"],
        unique=False,
    )

    # =========================================================================
    # 7. FlowForge: flowforge_events
    # =========================================================================
    op.create_table(
        "flowforge_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["flowforge_workflow_executions.id"],
            name=op.f("fk_flowforge_events_execution_id_flowforge_executions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_flowforge_events_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flowforge_events")),
    )
    op.create_index(
        "ix_flowforge_events_execution_created",
        "flowforge_events",
        ["execution_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_flowforge_events_workspace_id",
        "flowforge_events",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_flowforge_events_event_type",
        "flowforge_events",
        ["event_type"],
        unique=False,
    )

    # =========================================================================
    # 8. DevMemory: engineering_memories
    # =========================================================================
    op.create_table(
        "engineering_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=True),
        sa.Column("memory_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_reference", sa.String(length=1024), nullable=True),
        sa.Column(
            "confidence_score",
            sa.Float(),
            server_default="1.0",
            nullable=False,
        ),
        sa.Column(
            "verification_status",
            sa.String(length=32),
            server_default="UNVERIFIED",
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata", json_type, nullable=True),
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.vector.VECTOR(dim=384),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_engineering_memories_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_engineering_memories_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_engineering_memories_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engineering_memories")),
        sa.UniqueConstraint(
            "workspace_id",
            "content_hash",
            name="uq_devmemory_workspace_content_hash",
        ),
        sa.UniqueConstraint("id", "workspace_id", name="uq_devmemory_id_workspace"),
        sa.CheckConstraint(
            "confidence_score >= 0.0 AND confidence_score <= 1.0",
            name="ck_devmemory_confidence_range",
        ),
        sa.CheckConstraint(
            "verification_status IN ('UNVERIFIED', 'VERIFIED', 'OUTDATED', 'ARCHIVED')",
            name="ck_devmemory_verification_status",
        ),
        sa.CheckConstraint(
            "memory_type IN ('ARCHITECTURE_DECISION', 'TECHNICAL_DECISION', 'VERIFIED_BUGFIX', 'REPO_KNOWLEDGE', 'CODE_EXPLANATION', 'ENGINEERING_CONVENTION', 'TASK_OUTCOME', 'IMPLEMENTATION_DISCOVERY', 'KNOWN_LIMITATION', 'VERIFIED_SOLUTION')",
            name="ck_devmemory_memory_type",
        ),
        sa.CheckConstraint(
            "source_type IN ('AGENT_EXECUTION', 'CODE_REVIEW', 'COMMIT', 'PULL_REQUEST', 'USER_INPUT', 'TEST_FAILURE', 'SECURITY_AUDIT')",
            name="ck_devmemory_source_type",
        ),
    )
    op.create_index(
        "ix_devmemory_workspace_id",
        "engineering_memories",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_devmemory_workspace_repo",
        "engineering_memories",
        ["workspace_id", "repository_id"],
        unique=False,
    )
    op.create_index(
        "ix_devmemory_memory_type",
        "engineering_memories",
        ["workspace_id", "memory_type"],
        unique=False,
    )
    op.create_index(
        "ix_devmemory_verification",
        "engineering_memories",
        ["workspace_id", "verification_status"],
        unique=False,
    )
    op.create_index(
        "ix_devmemory_content_hash",
        "engineering_memories",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        "ix_devmemory_created_at",
        "engineering_memories",
        ["created_at"],
        unique=False,
    )

    # =========================================================================
    # 9. DevMemory: memory_evidence
    # =========================================================================
    op.create_table(
        "memory_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("source_reference", sa.String(length=1024), nullable=True),
        sa.Column("evidence_content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["engineering_memories.id"],
            name=op.f("fk_memory_evidence_memory_id_engineering_memories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_memory_evidence_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_evidence")),
        sa.CheckConstraint(
            "evidence_type IN ('CODE_SNIPPET', 'LOG_TRACE', 'DIFF_PATCH', 'TEST_OUTPUT', 'SECURITY_FINDING', 'BENCHMARK_RESULT')",
            name="ck_devmemory_evidence_type",
        ),
    )
    op.create_index(
        "ix_memory_evidence_memory_id",
        "memory_evidence",
        ["memory_id", "evidence_type"],
        unique=False,
    )
    op.create_index(
        "ix_memory_evidence_workspace_id",
        "memory_evidence",
        ["workspace_id"],
        unique=False,
    )

    # =========================================================================
    # 10. DevMemory: memory_relationships
    # =========================================================================
    op.create_table(
        "memory_relationships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_memory_id", sa.Uuid(), nullable=False),
        sa.Column("target_memory_id", sa.Uuid(), nullable=False),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column(
            "confidence_score",
            sa.Float(),
            server_default="1.0",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_memory_id"],
            ["engineering_memories.id"],
            name=op.f("fk_memory_relationships_source_id_engineering_memories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_memory_id"],
            ["engineering_memories.id"],
            name=op.f("fk_memory_relationships_target_id_engineering_memories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_memory_relationships_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_relationships")),
        sa.UniqueConstraint(
            "source_memory_id",
            "target_memory_id",
            "relationship_type",
            name="uq_devmemory_rel_source_target_type",
        ),
        sa.CheckConstraint(
            "confidence_score >= 0.0 AND confidence_score <= 1.0",
            name="ck_devmemory_rel_confidence_range",
        ),
        sa.CheckConstraint(
            "relationship_type IN ('EXTENDS', 'SUPERSEDES', 'CONTRADICTS', 'RELATES_TO', 'CAUSED_BY', 'RESOLVED_BY')",
            name="ck_devmemory_rel_type",
        ),
        sa.CheckConstraint(
            "source_memory_id != target_memory_id",
            name="ck_devmemory_rel_no_self_loop",
        ),
    )
    op.create_index(
        "ix_memory_relationships_source_target",
        "memory_relationships",
        ["source_memory_id", "target_memory_id"],
        unique=False,
    )
    op.create_index(
        "ix_memory_relationships_workspace_id",
        "memory_relationships",
        ["workspace_id"],
        unique=False,
    )

    # =========================================================================
    # 11. DevMemory: memory_access_logs
    # =========================================================================
    op.create_table(
        "memory_access_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_type", sa.String(length=64), nullable=False),
        sa.Column("access_type", sa.String(length=32), nullable=False),
        sa.Column("context_metadata", json_type, nullable=True),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["engineering_memories.id"],
            name=op.f("fk_memory_access_logs_memory_id_engineering_memories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_memory_access_logs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_access_logs")),
        sa.CheckConstraint(
            "agent_type IN ('DEVPILOT', 'IMPACTMIND', 'TESTPILOT', 'SECUREFLOW', 'FLOWFORGE', 'USER')",
            name="ck_devmemory_access_agent_type",
        ),
        sa.CheckConstraint(
            "access_type IN ('RETRIEVE', 'CITE', 'APPLY', 'VERIFY', 'INVALIDATE')",
            name="ck_devmemory_access_type",
        ),
    )
    op.create_index(
        "ix_memory_access_logs_memory_workspace",
        "memory_access_logs",
        ["memory_id", "workspace_id", "accessed_at"],
        unique=False,
    )
    op.create_index(
        "ix_memory_access_logs_workspace_agent",
        "memory_access_logs",
        ["workspace_id", "agent_type"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema to remove FlowForge and DevMemory tables."""
    op.drop_table("memory_access_logs")
    op.drop_table("memory_relationships")
    op.drop_table("memory_evidence")
    op.drop_table("engineering_memories")
    op.drop_table("flowforge_events")
    op.drop_table("flowforge_approvals")
    op.drop_table("flowforge_step_executions")
    op.drop_table("flowforge_workflow_executions")
    op.drop_table("flowforge_workflow_triggers")
    op.drop_table("flowforge_workflow_versions")
    op.drop_table("flowforge_workflows")
