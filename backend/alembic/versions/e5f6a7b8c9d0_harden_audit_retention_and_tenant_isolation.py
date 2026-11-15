"""harden_audit_retention_and_tenant_isolation

Revision ID: e5f6a7b8c9d0
Revises: 9c0a1b2d3e4f
Create Date: 2026-11-15 11:58:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "9c0a1b2d3e4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema with security audit retention and cross-workspace tenant isolation."""
    # 1. DevPilot tasks tenant unique constraints
    op.create_unique_constraint(
        "uq_devpilot_tasks_id_workspace",
        "devpilot_tasks",
        ["id", "workspace_id"],
    )
    op.create_unique_constraint(
        "uq_devpilot_tasks_id_repo",
        "devpilot_tasks",
        ["id", "repository_id"],
    )

    # 2. TestPilot suites tenant unique constraint
    op.create_unique_constraint(
        "uq_testpilot_suites_id_repo_workspace",
        "testpilot_suites",
        ["id", "repository_id", "workspace_id"],
    )

    # 3. TestPilot executions: enforce suite belongs to exact same repository and workspace
    op.create_foreign_key(
        "fk_testpilot_executions_suite_tenant",
        "testpilot_executions",
        "testpilot_suites",
        ["suite_id", "repository_id", "workspace_id"],
        ["id", "repository_id", "workspace_id"],
    )

    # 4. SecureFlow scans: tenant unique constraint and audit retention on repository deletion
    op.create_unique_constraint(
        "uq_secureflow_scans_id_repo_workspace",
        "secureflow_scans",
        ["id", "repository_id", "workspace_id"],
    )
    op.drop_constraint(
        "fk_secureflow_scans_repo_workspace",
        "secureflow_scans",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_secureflow_scans_repo_workspace",
        "secureflow_scans",
        "repositories",
        ["repository_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "fk_secureflow_scans_repository_id_repositories",
        "secureflow_scans",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_secureflow_scans_repository_id_repositories",
        "secureflow_scans",
        "repositories",
        ["repository_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # 5. SecureFlow findings: audit retention and cross-tenant foreign key enforcement
    op.drop_constraint(
        "fk_secureflow_findings_repository_id_repositories",
        "secureflow_findings",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_secureflow_findings_repository_id_repositories",
        "secureflow_findings",
        "repositories",
        ["repository_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "fk_secureflow_findings_scan_id_secureflow_scans",
        "secureflow_findings",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_secureflow_findings_scan_id_secureflow_scans",
        "secureflow_findings",
        "secureflow_scans",
        ["scan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_secureflow_findings_scan_tenant",
        "secureflow_findings",
        "secureflow_scans",
        ["scan_id", "repository_id", "workspace_id"],
        ["id", "repository_id", "workspace_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_secureflow_findings_task_repo",
        "secureflow_findings",
        "devpilot_tasks",
        ["devpilot_task_id", "repository_id"],
        ["id", "repository_id"],
    )
    op.create_foreign_key(
        "fk_secureflow_findings_task_workspace",
        "secureflow_findings",
        "devpilot_tasks",
        ["devpilot_task_id", "workspace_id"],
        ["id", "workspace_id"],
    )

    # 6. SecureFlow scan events: audit retention on scan deletion
    op.drop_constraint(
        "fk_secureflow_scan_events_scan_id_secureflow_scans",
        "secureflow_scan_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_secureflow_scan_events_scan_id_secureflow_scans",
        "secureflow_scan_events",
        "secureflow_scans",
        ["scan_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Downgrade schema to revert hardening constraints."""
    # 6. SecureFlow scan events
    op.drop_constraint(
        "fk_secureflow_scan_events_scan_id_secureflow_scans",
        "secureflow_scan_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_secureflow_scan_events_scan_id_secureflow_scans",
        "secureflow_scan_events",
        "secureflow_scans",
        ["scan_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 5. SecureFlow findings
    op.drop_constraint(
        "fk_secureflow_findings_task_workspace",
        "secureflow_findings",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_secureflow_findings_task_repo",
        "secureflow_findings",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_secureflow_findings_scan_tenant",
        "secureflow_findings",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_secureflow_findings_scan_id_secureflow_scans",
        "secureflow_findings",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_secureflow_findings_scan_id_secureflow_scans",
        "secureflow_findings",
        "secureflow_scans",
        ["scan_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "fk_secureflow_findings_repository_id_repositories",
        "secureflow_findings",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_secureflow_findings_repository_id_repositories",
        "secureflow_findings",
        "repositories",
        ["repository_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 4. SecureFlow scans
    op.drop_constraint(
        "fk_secureflow_scans_repository_id_repositories",
        "secureflow_scans",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_secureflow_scans_repository_id_repositories",
        "secureflow_scans",
        "repositories",
        ["repository_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "fk_secureflow_scans_repo_workspace",
        "secureflow_scans",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_secureflow_scans_repo_workspace",
        "secureflow_scans",
        "repositories",
        ["repository_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "uq_secureflow_scans_id_repo_workspace",
        "secureflow_scans",
        type_="unique",
    )

    # 3. TestPilot executions
    op.drop_constraint(
        "fk_testpilot_executions_suite_tenant",
        "testpilot_executions",
        type_="foreignkey",
    )

    # 2. TestPilot suites
    op.drop_constraint(
        "uq_testpilot_suites_id_repo_workspace",
        "testpilot_suites",
        type_="unique",
    )

    # 1. DevPilot tasks
    op.drop_constraint(
        "uq_devpilot_tasks_id_repo",
        "devpilot_tasks",
        type_="unique",
    )
    op.drop_constraint(
        "uq_devpilot_tasks_id_workspace",
        "devpilot_tasks",
        type_="unique",
    )
