"""harden_devmemory_and_flowforge_tenant_integrity

Revision ID: c7d8e9f0a1b2
Revises: f0fef3efd664
Create Date: 2026-11-15 17:48:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: str | Sequence[str] | None = "f0fef3efd664"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply composite foreign keys and tenant isolation hardening to DevMemory and FlowForge."""
    # -------------------------------------------------------------------------
    # 1. DevMemory Hardening
    # -------------------------------------------------------------------------

    # 1.1 EngineeringMemory: Enforce repository belongs to same workspace
    op.create_foreign_key(
        "fk_devmemory_repository_workspace",
        "engineering_memories",
        "repositories",
        ["repository_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )

    # 1.2 MemoryEvidence: Enforce evidence belongs to exact same memory and workspace
    op.create_foreign_key(
        "fk_memory_evidence_memory_workspace",
        "memory_evidence",
        "engineering_memories",
        ["memory_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )

    # 1.3 MemoryRelationship: Enforce source and target memories belong to exact same workspace
    op.create_foreign_key(
        "fk_memory_rel_source_workspace",
        "memory_relationships",
        "engineering_memories",
        ["source_memory_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_memory_rel_target_workspace",
        "memory_relationships",
        "engineering_memories",
        ["target_memory_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )

    # 1.4 MemoryAccessLog: Replace CASCADE with RESTRICT to prevent audit loss on cited memories
    op.drop_constraint(
        "fk_memory_access_logs_memory_id_engineering_memories",
        "memory_access_logs",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_memory_access_logs_memory_id_engineering_memories",
        "memory_access_logs",
        "engineering_memories",
        ["memory_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_memory_access_logs_memory_workspace",
        "memory_access_logs",
        "engineering_memories",
        ["memory_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="RESTRICT",
    )

    # -------------------------------------------------------------------------
    # 2. FlowForge Hardening
    # -------------------------------------------------------------------------

    # 2.1 WorkflowExecution: Enforce workflow belongs to exact same workspace
    op.create_foreign_key(
        "fk_flowforge_executions_workflow_workspace",
        "flowforge_workflow_executions",
        "flowforge_workflows",
        ["workflow_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="RESTRICT",
    )

    # 2.2 WorkflowStepExecution: Unique (id, workspace_id) and composite tenant FK to execution
    op.create_unique_constraint(
        "uq_flowforge_steps_id_workspace",
        "flowforge_step_executions",
        ["id", "workspace_id"],
    )
    op.create_foreign_key(
        "fk_flowforge_steps_execution_workspace",
        "flowforge_step_executions",
        "flowforge_workflow_executions",
        ["execution_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )

    # 2.3 WorkflowApproval: Enforce approval belongs to execution's workspace and step belongs to execution
    op.create_foreign_key(
        "fk_flowforge_approvals_execution_workspace",
        "flowforge_approvals",
        "flowforge_workflow_executions",
        ["execution_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_flowforge_approvals_step_execution",
        "flowforge_approvals",
        "flowforge_step_executions",
        ["step_execution_id", "execution_id"],
        ["id", "execution_id"],
        ondelete="CASCADE",
    )

    # 2.4 WorkflowEvent: Enforce events belong to execution's workspace
    op.create_foreign_key(
        "fk_flowforge_events_execution_workspace",
        "flowforge_events",
        "flowforge_workflow_executions",
        ["execution_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Revert composite foreign keys and tenant isolation hardening."""
    # Revert FlowForge
    op.drop_constraint(
        "fk_flowforge_events_execution_workspace",
        "flowforge_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_flowforge_approvals_step_execution",
        "flowforge_approvals",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_flowforge_approvals_execution_workspace",
        "flowforge_approvals",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_flowforge_steps_execution_workspace",
        "flowforge_step_executions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_flowforge_steps_id_workspace",
        "flowforge_step_executions",
        type_="unique",
    )
    op.drop_constraint(
        "fk_flowforge_executions_workflow_workspace",
        "flowforge_workflow_executions",
        type_="foreignkey",
    )

    # Revert DevMemory
    op.drop_constraint(
        "fk_memory_access_logs_memory_workspace",
        "memory_access_logs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_memory_access_logs_memory_id_engineering_memories",
        "memory_access_logs",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_memory_access_logs_memory_id_engineering_memories",
        "memory_access_logs",
        "engineering_memories",
        ["memory_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "fk_memory_rel_target_workspace",
        "memory_relationships",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_memory_rel_source_workspace",
        "memory_relationships",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_memory_evidence_memory_workspace",
        "memory_evidence",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_devmemory_repository_workspace",
        "engineering_memories",
        type_="foreignkey",
    )
