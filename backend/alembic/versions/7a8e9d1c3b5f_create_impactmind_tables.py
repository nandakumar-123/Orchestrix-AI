"""create_impactmind_tables

Revision ID: 7a8e9d1c3b5f
Revises: 4973ddae25ec
Create Date: 2026-11-15 08:25:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a8e9d1c3b5f"
down_revision: str | Sequence[str] | None = "4973ddae25ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema to include ImpactMind change impact & regression testing tables."""
    # JSON column helper for postgresql and sqlite
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

    # 1. impact_assessments table
    op.create_table(
        "impact_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("initiated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("base_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("target_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("comparison_mode", sa.String(length=32), nullable=False, server_default="diff_input"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("structural_exposure_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("exposure_tier", sa.String(length=16), nullable=False, server_default="LOW"),
        sa.Column("change_summary", json_type, nullable=False),
        sa.Column("reasons", json_type, nullable=False),
        sa.Column("recommended_actions", json_type, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_impact_assessments_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_impact_assessments_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["repository_snapshots.id"],
            name=op.f("fk_impact_assessments_snapshot_id_repository_snapshots"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["initiated_by_user_id"],
            ["users.id"],
            name=op.f("fk_impact_assessments_initiated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impact_assessments")),
    )
    op.create_index(op.f("ix_impact_assessments_workspace_id"), "impact_assessments", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_impact_assessments_repo_id"), "impact_assessments", ["repository_id"], unique=False)
    op.create_index(op.f("ix_impact_assessments_snapshot_id"), "impact_assessments", ["snapshot_id"], unique=False)
    op.create_index(op.f("ix_impact_assessments_status"), "impact_assessments", ["status"], unique=False)
    op.create_index(op.f("ix_impact_assessments_created_at"), "impact_assessments", ["created_at"], unique=False)

    # 2. impact_change_classifications table
    op.create_table(
        "impact_change_classifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("symbol_name", sa.String(length=255), nullable=True),
        sa.Column("symbol_id", sa.String(length=512), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("is_breaking", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("breaking_reason", sa.String(length=512), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="resolved"),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["impact_assessments.id"],
            name=op.f("fk_impact_change_classifications_assessment_id_impact_assessments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impact_change_classifications")),
    )
    op.create_index(op.f("ix_impact_changes_assessment_id"), "impact_change_classifications", ["assessment_id"], unique=False)
    op.create_index(op.f("ix_impact_changes_category"), "impact_change_classifications", ["category"], unique=False)

    # 3. impact_impacted_entities table
    op.create_table(
        "impact_impacted_entities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.String(length=512), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=True),
        sa.Column("impact_type", sa.String(length=32), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("relationship_type", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["impact_assessments.id"],
            name=op.f("fk_impact_impacted_entities_assessment_id_impact_assessments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impact_impacted_entities")),
    )
    op.create_index(op.f("ix_impacted_entities_assessment_id"), "impact_impacted_entities", ["assessment_id"], unique=False)
    op.create_index(op.f("ix_impacted_entities_type"), "impact_impacted_entities", ["impact_type"], unique=False)

    # 4. impact_test_recommendations table
    op.create_table(
        "impact_test_recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("test_file", sa.String(length=1024), nullable=False),
        sa.Column("test_name", sa.String(length=255), nullable=True),
        sa.Column("test_framework", sa.String(length=64), nullable=False, server_default="pytest"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="MEDIUM"),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("related_symbol", sa.String(length=255), nullable=True),
        sa.Column("evidence_source", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["impact_assessments.id"],
            name=op.f("fk_impact_test_recommendations_assessment_id_impact_assessments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impact_test_recommendations")),
    )
    op.create_index(op.f("ix_test_recommendations_assessment_id"), "impact_test_recommendations", ["assessment_id"], unique=False)
    op.create_index(op.f("ix_test_recommendations_priority"), "impact_test_recommendations", ["priority"], unique=False)

    # 5. impact_test_executions table
    op.create_table(
        "impact_test_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("command", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("stderr", sa.Text(), nullable=True),
        sa.Column("passed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["impact_assessments.id"],
            name=op.f("fk_impact_test_executions_assessment_id_impact_assessments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impact_test_executions")),
    )
    op.create_index(op.f("ix_test_executions_assessment_id"), "impact_test_executions", ["assessment_id"], unique=False)
    op.create_index(op.f("ix_test_executions_status"), "impact_test_executions", ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("impact_test_executions")
    op.drop_table("impact_test_recommendations")
    op.drop_table("impact_impacted_entities")
    op.drop_table("impact_change_classifications")
    op.drop_table("impact_assessments")
