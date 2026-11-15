"""create_testpilot_secureflow_tables

Revision ID: 9c0a1b2d3e4f
Revises: 8b9f0a2d4c6e
Create Date: 2026-11-15 11:25:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c0a1b2d3e4f"
down_revision: str | Sequence[str] | None = "8b9f0a2d4c6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema to include TestPilot and SecureFlow database tables."""
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

    # 1. testpilot_suites table
    op.create_table(
        "testpilot_suites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("framework", sa.String(length=64), nullable=False),
        sa.Column("test_type", sa.String(length=32), nullable=False, server_default="unit"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="generated"),
        sa.Column("target_files", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_testpilot_suites_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_testpilot_suites_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["repository_snapshots.id"],
            name=op.f("fk_testpilot_suites_snapshot_id_repository_snapshots"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_testpilot_suites_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_testpilot_suites_repo_workspace",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "test_type IN ('unit', 'integration', 'regression', 'edge_case', 'negative')",
            name="ck_testpilot_suites_test_type",
        ),
        sa.CheckConstraint(
            "status IN ('generated', 'awaiting_approval', 'approved', 'rejected', 'archived')",
            name="ck_testpilot_suites_status",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_testpilot_suites")),
    )
    op.create_index(
        op.f("ix_testpilot_suites_workspace_id"),
        "testpilot_suites",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_suites_repository_id"),
        "testpilot_suites",
        ["repository_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_suites_snapshot_id"),
        "testpilot_suites",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_suites_status"),
        "testpilot_suites",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_suites_created_at"),
        "testpilot_suites",
        ["created_at"],
        unique=False,
    )

    # 2. testpilot_cases table
    op.create_table(
        "testpilot_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("suite_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("test_type", sa.String(length=32), nullable=False, server_default="unit"),
        sa.Column("target_symbol", sa.String(length=255), nullable=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="generated"),
        sa.Column("is_edge_case", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["testpilot_suites.id"],
            name=op.f("fk_testpilot_cases_suite_id_testpilot_suites"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "test_type IN ('unit', 'integration', 'regression', 'edge_case', 'negative')",
            name="ck_testpilot_cases_test_type",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_testpilot_cases")),
    )
    op.create_index(
        op.f("ix_testpilot_cases_suite_id"),
        "testpilot_cases",
        ["suite_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_cases_status"),
        "testpilot_cases",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_cases_created_at"),
        "testpilot_cases",
        ["created_at"],
        unique=False,
    )

    # 3. testpilot_executions table
    op.create_table(
        "testpilot_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("suite_id", sa.Uuid(), nullable=True),
        sa.Column("command", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=False),
        sa.Column("stderr", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_testpilot_executions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_testpilot_executions_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["testpilot_suites.id"],
            name=op.f("fk_testpilot_executions_suite_id_testpilot_suites"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_testpilot_executions_repo_workspace",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'PASSED', 'FAILED', 'ERROR', 'TIMED_OUT', 'CANCELLED', 'BLOCKED')",
            name="ck_testpilot_executions_status",
        ),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name="ck_testpilot_executions_duration_ms_nonnegative",
        ),
        sa.CheckConstraint(
            "passed_count >= 0",
            name="ck_testpilot_executions_passed_count_nonnegative",
        ),
        sa.CheckConstraint(
            "failed_count >= 0",
            name="ck_testpilot_executions_failed_count_nonnegative",
        ),
        sa.CheckConstraint(
            "skipped_count >= 0",
            name="ck_testpilot_executions_skipped_count_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_testpilot_executions")),
    )
    op.create_index(
        op.f("ix_testpilot_executions_workspace_id"),
        "testpilot_executions",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_executions_repository_id"),
        "testpilot_executions",
        ["repository_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_executions_suite_id"),
        "testpilot_executions",
        ["suite_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_executions_status"),
        "testpilot_executions",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_executions_created_at"),
        "testpilot_executions",
        ["created_at"],
        unique=False,
    )

    # 4. testpilot_results table
    op.create_table(
        "testpilot_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("test_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["testpilot_executions.id"],
            name=op.f("fk_testpilot_results_execution_id_testpilot_executions"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('PASSED', 'FAILED', 'ERROR', 'SKIPPED', 'BLOCKED')",
            name="ck_testpilot_results_status",
        ),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name="ck_testpilot_results_duration_ms_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_testpilot_results")),
    )
    op.create_index(
        op.f("ix_testpilot_results_execution_id"),
        "testpilot_results",
        ["execution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_results_status"),
        "testpilot_results",
        ["status"],
        unique=False,
    )

    # 5. testpilot_coverage_reports table
    op.create_table(
        "testpilot_coverage_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.Column("line_coverage_pct", sa.Float(), nullable=True),
        sa.Column("branch_coverage_pct", sa.Float(), nullable=True),
        sa.Column("uncovered_files", json_type, nullable=False),
        sa.Column("uncovered_functions", json_type, nullable=False),
        sa.Column("raw_report", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_testpilot_coverage_reports_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_testpilot_coverage_reports_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["testpilot_executions.id"],
            name=op.f("fk_testpilot_coverage_reports_execution_id_testpilot_executions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_testpilot_coverage_reports_repo_workspace",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "line_coverage_pct IS NULL OR (line_coverage_pct >= 0.0 AND line_coverage_pct <= 100.0)",
            name="ck_testpilot_coverage_reports_line_coverage_pct",
        ),
        sa.CheckConstraint(
            "branch_coverage_pct IS NULL OR (branch_coverage_pct >= 0.0 AND branch_coverage_pct <= 100.0)",
            name="ck_testpilot_coverage_reports_branch_coverage_pct",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_testpilot_coverage_reports")),
    )
    op.create_index(
        op.f("ix_testpilot_coverage_reports_workspace_id"),
        "testpilot_coverage_reports",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_coverage_reports_repository_id"),
        "testpilot_coverage_reports",
        ["repository_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_coverage_reports_execution_id"),
        "testpilot_coverage_reports",
        ["execution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_testpilot_coverage_reports_created_at"),
        "testpilot_coverage_reports",
        ["created_at"],
        unique=False,
    )

    # 6. secureflow_scans table
    op.create_table(
        "secureflow_scans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("scan_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("scanners_used", json_type, nullable=False),
        sa.Column("total_findings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("critical_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("high_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("medium_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("low_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_secureflow_scans_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_secureflow_scans_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["repository_snapshots.id"],
            name=op.f("fk_secureflow_scans_snapshot_id_repository_snapshots"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_secureflow_scans_repo_workspace",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'PARTIALLY_COMPLETED')",
            name="ck_secureflow_scans_status",
        ),
        sa.CheckConstraint(
            "total_findings >= 0",
            name="ck_secureflow_scans_total_findings_nonnegative",
        ),
        sa.CheckConstraint(
            "critical_count >= 0",
            name="ck_secureflow_scans_critical_count_nonnegative",
        ),
        sa.CheckConstraint(
            "high_count >= 0",
            name="ck_secureflow_scans_high_count_nonnegative",
        ),
        sa.CheckConstraint(
            "medium_count >= 0",
            name="ck_secureflow_scans_medium_count_nonnegative",
        ),
        sa.CheckConstraint(
            "low_count >= 0",
            name="ck_secureflow_scans_low_count_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_secureflow_scans")),
    )
    op.create_index(
        op.f("ix_secureflow_scans_workspace_id"),
        "secureflow_scans",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secureflow_scans_repository_id"),
        "secureflow_scans",
        ["repository_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secureflow_scans_snapshot_id"),
        "secureflow_scans",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secureflow_scans_status"),
        "secureflow_scans",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secureflow_scans_scan_type"),
        "secureflow_scans",
        ["scan_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secureflow_scans_created_at"),
        "secureflow_scans",
        ["created_at"],
        unique=False,
    )

    # 7. secureflow_findings table
    op.create_table(
        "secureflow_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("scanner", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="MEDIUM"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("file_path", sa.String(length=1024), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("rule_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("redacted_evidence", sa.Text(), nullable=True),
        sa.Column("remediation_recommendation", sa.Text(), nullable=True),
        sa.Column("remediation_code_snippet", sa.Text(), nullable=True),
        sa.Column("external_advisory_url", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="OPEN"),
        sa.Column("devpilot_task_id", sa.Uuid(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_secureflow_findings_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_secureflow_findings_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"],
            ["secureflow_scans.id"],
            name=op.f("fk_secureflow_findings_scan_id_secureflow_scans"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["devpilot_task_id"],
            ["devpilot_tasks.id"],
            name=op.f("fk_secureflow_findings_devpilot_task_id_devpilot_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_secureflow_findings_repo_workspace",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "repository_id",
            "fingerprint",
            name="uq_secureflow_findings_repo_fingerprint",
        ),
        sa.CheckConstraint(
            "severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN')",
            name="ck_secureflow_findings_severity",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CONFIRMED', 'FALSE_POSITIVE', 'ACCEPTED_RISK', 'RESOLVED')",
            name="ck_secureflow_findings_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_secureflow_findings_confidence_range",
        ),
        sa.CheckConstraint(
            "line_start IS NULL OR line_start > 0",
            name="ck_secureflow_findings_line_start_positive",
        ),
        sa.CheckConstraint(
            "line_end IS NULL OR line_end > 0",
            name="ck_secureflow_findings_line_end_positive",
        ),
        sa.CheckConstraint(
            "line_start IS NULL OR line_end IS NULL OR line_end >= line_start",
            name="ck_secureflow_findings_line_range_valid",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_secureflow_findings")),
    )
    op.create_index(
        op.f("ix_secureflow_findings_workspace_id"),
        "secureflow_findings",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secureflow_findings_repository_id"),
        "secureflow_findings",
        ["repository_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secureflow_findings_scan_id"),
        "secureflow_findings",
        ["scan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secureflow_findings_severity"),
        "secureflow_findings",
        ["severity"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secureflow_findings_status"),
        "secureflow_findings",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secureflow_findings_category"),
        "secureflow_findings",
        ["category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secureflow_findings_fingerprint"),
        "secureflow_findings",
        ["fingerprint"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secureflow_findings_created_at"),
        "secureflow_findings",
        ["created_at"],
        unique=False,
    )

    # 8. secureflow_scan_events table
    op.create_table(
        "secureflow_scan_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["scan_id"],
            ["secureflow_scans.id"],
            name=op.f("fk_secureflow_scan_events_scan_id_secureflow_scans"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_secureflow_scan_events")),
    )
    op.create_index(
        op.f("ix_secureflow_scan_events_scan_id"),
        "secureflow_scan_events",
        ["scan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secureflow_scan_events_created_at"),
        "secureflow_scan_events",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema to remove TestPilot and SecureFlow database tables."""
    # Drop tables in reverse creation order
    op.drop_table("secureflow_scan_events")
    op.drop_table("secureflow_findings")
    op.drop_table("secureflow_scans")
    op.drop_table("testpilot_coverage_reports")
    op.drop_table("testpilot_results")
    op.drop_table("testpilot_executions")
    op.drop_table("testpilot_cases")
    op.drop_table("testpilot_suites")
