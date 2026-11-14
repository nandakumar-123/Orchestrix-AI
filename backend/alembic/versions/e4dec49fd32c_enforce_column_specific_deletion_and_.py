"""enforce column specific deletion and safe member migration validation

Revision ID: e4dec49fd32c
Revises: 74f29699180e
Create Date: 2026-11-14 16:02:07.570115

"""

from collections.abc import Sequence

from sqlalchemy.sql import text

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4dec49fd32c"
down_revision: str | Sequence[str] | None = "74f29699180e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """
    1. Fix A: Upgrade engineering_tasks composite foreign key to PostgreSQL column-specific
       'ON DELETE SET NULL (repository_id)'.
       This ensures deleting a repository nulls only repository_id while preserving
       the mandatory workspace_id column on engineering tasks.

    2. Fix B: Safe repository_members validation and data integrity guarantee.
       Verifies that any existing repository member belongs to a valid repository and workspace,
       and that the user has an active workspace membership. If any invalid records exist,
       it stops and fails the migration safely rather than deleting or modifying data.
    """
    bind = op.get_bind()

    # --- 1. Fix A: Update engineering_tasks constraint to column-specific ON DELETE SET NULL ---
    op.drop_constraint(
        "fk_engineering_tasks_repository_workspace",
        "engineering_tasks",
        type_="foreignkey",
    )
    # Check if we are running on PostgreSQL
    if bind.dialect.name == "postgresql":
        op.execute(
            text(
                "ALTER TABLE engineering_tasks "
                "ADD CONSTRAINT fk_engineering_tasks_repository_workspace "
                "FOREIGN KEY (repository_id, workspace_id) "
                "REFERENCES repositories(id, workspace_id) "
                "ON DELETE SET NULL (repository_id);"
            )
        )
    else:
        op.create_foreign_key(
            "fk_engineering_tasks_repository_workspace",
            "engineering_tasks",
            "repositories",
            ["repository_id", "workspace_id"],
            ["id", "workspace_id"],
            ondelete="SET NULL",
        )

    # --- 2. Fix B: Data Integrity Verification & Safe Member Backfill Guarantee ---
    # Check for orphaned repository members without valid workspace or repository
    orphan_repo_check = bind.execute(
        text(
            "SELECT count(*) FROM repository_members rm "
            "LEFT JOIN repositories r ON rm.repository_id = r.id AND rm.workspace_id = r.workspace_id "
            "WHERE r.id IS NULL;"
        )
    ).scalar()
    if orphan_repo_check and orphan_repo_check > 0:
        raise RuntimeError(
            f"Migration aborted: Found {orphan_repo_check} repository_members records with no matching repository in the same workspace."
        )

    # Check for repository members whose user is not a member of the workspace
    orphan_user_check = bind.execute(
        text(
            "SELECT count(*) FROM repository_members rm "
            "LEFT JOIN workspace_memberships wm ON rm.user_id = wm.user_id AND rm.workspace_id = wm.workspace_id "
            "WHERE wm.id IS NULL;"
        )
    ).scalar()
    if orphan_user_check and orphan_user_check > 0:
        raise RuntimeError(
            f"Migration aborted: Found {orphan_user_check} repository_members records where the user has no workspace membership."
        )


def downgrade() -> None:
    """Downgrade schema back to standard ON DELETE SET NULL."""
    op.drop_constraint(
        "fk_engineering_tasks_repository_workspace",
        "engineering_tasks",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_engineering_tasks_repository_workspace",
        "engineering_tasks",
        "repositories",
        ["repository_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="SET NULL",
    )
