"""create_devpilot_tables

Revision ID: 8b9f0a2d4c6e
Revises: 7a8e9d1c3b5f
Create Date: 2026-11-15 09:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b9f0a2d4c6e"
down_revision: str | Sequence[str] | None = "7a8e9d1c3b5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema to include DevPilot autonomous AI software engineering tables."""
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

    # 1. devpilot_tasks table
    op.create_table(
        "devpilot_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False, server_default="FEATURE"),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="CREATED"),
        sa.Column("base_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("target_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("isolated_workspace_path", sa.String(length=512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("clarification_prompt", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_devpilot_tasks_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_devpilot_tasks_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_devpilot_tasks_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devpilot_tasks")),
    )
    op.create_index(
        op.f("ix_devpilot_tasks_workspace_id"), "devpilot_tasks", ["workspace_id"], unique=False
    )
    op.create_index(
        op.f("ix_devpilot_tasks_repository_id"), "devpilot_tasks", ["repository_id"], unique=False
    )
    op.create_index(op.f("ix_devpilot_tasks_status"), "devpilot_tasks", ["status"], unique=False)
    op.create_index(
        op.f("ix_devpilot_tasks_created_at"), "devpilot_tasks", ["created_at"], unique=False
    )

    # 2. devpilot_engineering_plans table
    op.create_table(
        "devpilot_engineering_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("task_understanding", sa.Text(), nullable=False),
        sa.Column("existing_implementation_analysis", sa.Text(), nullable=False),
        sa.Column("security_implications", sa.Text(), nullable=False),
        sa.Column("impact_assessment_id", sa.Uuid(), nullable=True),
        sa.Column("exposure_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("exposure_tier", sa.String(length=32), nullable=False, server_default="LOW"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("approval_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["devpilot_tasks.id"],
            name=op.f("fk_devpilot_engineering_plans_task_id_devpilot_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_devpilot_engineering_plans_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devpilot_engineering_plans")),
    )
    op.create_index(
        op.f("ix_devpilot_plans_task_id"), "devpilot_engineering_plans", ["task_id"], unique=False
    )
    op.create_index(
        op.f("ix_devpilot_plans_workspace_id"),
        "devpilot_engineering_plans",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_devpilot_plans_status"), "devpilot_engineering_plans", ["status"], unique=False
    )

    # 3. devpilot_plan_steps table
    op.create_table(
        "devpilot_plan_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("target_files", json_type, nullable=False),
        sa.Column("affected_symbols", json_type, nullable=False),
        sa.Column(
            "action_type", sa.String(length=32), nullable=False, server_default="MODIFY_FILE"
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False, server_default="LOW"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PLANNED"),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["devpilot_engineering_plans.id"],
            name=op.f("fk_devpilot_plan_steps_plan_id_devpilot_engineering_plans"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devpilot_plan_steps")),
    )
    op.create_index(
        op.f("ix_devpilot_plan_steps_plan_id"), "devpilot_plan_steps", ["plan_id"], unique=False
    )
    op.create_index(
        op.f("ix_devpilot_plan_steps_step_number"),
        "devpilot_plan_steps",
        ["step_number"],
        unique=False,
    )

    # 4. devpilot_generation_results table
    op.create_table(
        "devpilot_generation_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider_used", sa.String(length=64), nullable=False),
        sa.Column("model_used", sa.String(length=64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_files_changed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unified_diff", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="GENERATED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["devpilot_tasks.id"],
            name=op.f("fk_devpilot_generation_results_task_id_devpilot_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_devpilot_generation_results_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devpilot_generation_results")),
    )
    op.create_index(
        op.f("ix_devpilot_gen_results_task_id"),
        "devpilot_generation_results",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_devpilot_gen_results_workspace_id"),
        "devpilot_generation_results",
        ["workspace_id"],
        unique=False,
    )

    # 5. devpilot_code_changes table
    op.create_table(
        "devpilot_code_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_result_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("change_type", sa.String(length=32), nullable=False, server_default="MODIFY"),
        sa.Column("old_content", sa.Text(), nullable=True),
        sa.Column("new_content", sa.Text(), nullable=True),
        sa.Column("diff_hunk", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["generation_result_id"],
            ["devpilot_generation_results.id"],
            name=op.f("fk_devpilot_code_changes_gen_id_devpilot_generation_results"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devpilot_code_changes")),
    )
    op.create_index(
        op.f("ix_devpilot_code_changes_gen_id"),
        "devpilot_code_changes",
        ["generation_result_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_devpilot_code_changes_file_path"),
        "devpilot_code_changes",
        ["file_path"],
        unique=False,
    )

    # 6. devpilot_review_findings table
    op.create_table(
        "devpilot_review_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("severity", sa.String(length=32), nullable=False, server_default="INFO"),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="CORRECTNESS"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("suggested_correction", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["devpilot_tasks.id"],
            name=op.f("fk_devpilot_review_findings_task_id_devpilot_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_devpilot_review_findings_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devpilot_review_findings")),
    )
    op.create_index(
        op.f("ix_devpilot_review_task_id"), "devpilot_review_findings", ["task_id"], unique=False
    )
    op.create_index(
        op.f("ix_devpilot_review_severity"), "devpilot_review_findings", ["severity"], unique=False
    )

    # 7. devpilot_validation_runs table
    op.create_table(
        "devpilot_validation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("command", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PASSED"),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("stderr", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["devpilot_tasks.id"],
            name=op.f("fk_devpilot_validation_runs_task_id_devpilot_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_devpilot_validation_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devpilot_validation_runs")),
    )
    op.create_index(
        op.f("ix_devpilot_val_runs_task_id"), "devpilot_validation_runs", ["task_id"], unique=False
    )
    op.create_index(
        op.f("ix_devpilot_val_runs_status"), "devpilot_validation_runs", ["status"], unique=False
    )

    # 8. devpilot_approvals table
    op.create_table(
        "devpilot_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("approval_type", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["devpilot_tasks.id"],
            name=op.f("fk_devpilot_approvals_task_id_devpilot_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_devpilot_approvals_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_devpilot_approvals_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devpilot_approvals")),
    )
    op.create_index(
        op.f("ix_devpilot_approvals_task_id"), "devpilot_approvals", ["task_id"], unique=False
    )
    op.create_index(
        op.f("ix_devpilot_approvals_user_id"), "devpilot_approvals", ["user_id"], unique=False
    )

    # 9. devpilot_events table
    op.create_table(
        "devpilot_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["devpilot_tasks.id"],
            name=op.f("fk_devpilot_events_task_id_devpilot_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_devpilot_events_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devpilot_events")),
    )
    op.create_index(
        op.f("ix_devpilot_events_task_id"), "devpilot_events", ["task_id"], unique=False
    )
    op.create_index(
        op.f("ix_devpilot_events_created_at"), "devpilot_events", ["created_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema to drop DevPilot tables."""
    op.drop_table("devpilot_events")
    op.drop_table("devpilot_approvals")
    op.drop_table("devpilot_validation_runs")
    op.drop_table("devpilot_review_findings")
    op.drop_table("devpilot_code_changes")
    op.drop_table("devpilot_generation_results")
    op.drop_table("devpilot_plan_steps")
    op.drop_table("devpilot_engineering_plans")
    op.drop_table("devpilot_tasks")
