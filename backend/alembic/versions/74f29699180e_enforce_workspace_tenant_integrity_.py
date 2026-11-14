"""enforce workspace tenant integrity constraints

Revision ID: 74f29699180e
Revises: f88b9a264e4a
Create Date: 2026-11-14 15:38:43.686185

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "74f29699180e"
down_revision: str | Sequence[str] | None = "f88b9a264e4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. First add unique composite constraints on parent tables (github_installations and repositories)
    op.create_unique_constraint(
        "uq_github_installations_id_workspace", "github_installations", ["id", "workspace_id"]
    )
    op.create_unique_constraint(
        "uq_repositories_id_workspace", "repositories", ["id", "workspace_id"]
    )

    # 2. Update repositories foreign key to github_installations (composite: installation_id, workspace_id)
    op.drop_constraint(
        op.f("fk_repositories_installation_id_github_installations"),
        "repositories",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_repositories_installation_workspace",
        "repositories",
        "github_installations",
        ["installation_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )

    # 3. Update engineering_tasks foreign key to repositories (composite: repository_id, workspace_id)
    op.drop_constraint(
        op.f("fk_engineering_tasks_repository_id_repositories"),
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

    # 4. Update pull_request_records foreign key to repositories (composite: repository_id, workspace_id)
    op.drop_constraint(
        op.f("fk_pull_request_records_repository_id_repositories"),
        "pull_request_records",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_pull_request_records_repository_workspace",
        "pull_request_records",
        "repositories",
        ["repository_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )

    # 5. Add workspace_id to repository_members and enforce dual composite foreign keys
    op.add_column("repository_members", sa.Column("workspace_id", sa.Uuid(), nullable=False))
    op.create_index(
        op.f("ix_repository_members_workspace_id"),
        "repository_members",
        ["workspace_id"],
        unique=False,
    )
    op.drop_constraint(
        op.f("fk_repository_members_repository_id_repositories"),
        "repository_members",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_repository_members_user_id_users"), "repository_members", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_repository_members_repository_workspace",
        "repository_members",
        "repositories",
        ["repository_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_repository_members_workspace_id_workspaces"),
        "repository_members",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_repository_members_user_workspace",
        "repository_members",
        "workspace_memberships",
        ["user_id", "workspace_id"],
        ["user_id", "workspace_id"],
        ondelete="CASCADE",
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Drop foreign keys and columns on repository_members
    op.drop_constraint(
        "fk_repository_members_user_workspace", "repository_members", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_repository_members_workspace_id_workspaces"),
        "repository_members",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_repository_members_repository_workspace", "repository_members", type_="foreignkey"
    )
    op.create_foreign_key(
        op.f("fk_repository_members_user_id_users"),
        "repository_members",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_repository_members_repository_id_repositories"),
        "repository_members",
        "repositories",
        ["repository_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index(op.f("ix_repository_members_workspace_id"), table_name="repository_members")
    op.drop_column("repository_members", "workspace_id")

    # 2. Revert pull_request_records foreign keys
    op.drop_constraint(
        "fk_pull_request_records_repository_workspace", "pull_request_records", type_="foreignkey"
    )
    op.create_foreign_key(
        op.f("fk_pull_request_records_repository_id_repositories"),
        "pull_request_records",
        "repositories",
        ["repository_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 3. Revert engineering_tasks foreign keys
    op.drop_constraint(
        "fk_engineering_tasks_repository_workspace", "engineering_tasks", type_="foreignkey"
    )
    op.create_foreign_key(
        op.f("fk_engineering_tasks_repository_id_repositories"),
        "engineering_tasks",
        "repositories",
        ["repository_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 4. Now safe to drop uq_repositories_id_workspace
    op.drop_constraint("uq_repositories_id_workspace", "repositories", type_="unique")

    # 5. Revert repositories foreign key to github_installations
    op.drop_constraint("fk_repositories_installation_workspace", "repositories", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_repositories_installation_id_github_installations"),
        "repositories",
        "github_installations",
        ["installation_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 6. Drop uq_github_installations_id_workspace
    op.drop_constraint(
        "uq_github_installations_id_workspace", "github_installations", type_="unique"
    )
    # ### end Alembic commands ###
