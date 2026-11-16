"""create_tickets_and_ticket_activities

Revision ID: d4e5f6a7b8c9
Revises: c783c3e6f218
Create Date: 2026-11-16 11:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c783c3e6f218"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create tickets table
    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=True),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_tickets_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_tickets_repository_workspace",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["users.id"],
            name="fk_tickets_creator_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name="fk_tickets_assignee_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tickets"),
    )
    op.create_index("ix_tickets_workspace_id", "tickets", ["workspace_id"], unique=False)
    op.create_index("ix_tickets_repository_id", "tickets", ["repository_id"], unique=False)
    op.create_index("ix_tickets_status", "tickets", ["status"], unique=False)
    op.create_index("ix_tickets_priority", "tickets", ["priority"], unique=False)
    op.create_index("ix_tickets_creator_id", "tickets", ["creator_id"], unique=False)
    op.create_index("ix_tickets_assignee_id", "tickets", ["assignee_id"], unique=False)
    op.create_index("ix_tickets_created_at", "tickets", ["created_at"], unique=False)

    # 2. Create ticket_activities table
    op.create_table(
        "ticket_activities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("activity_type", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.String(length=255), nullable=True),
        sa.Column("new_value", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name="fk_ticket_activities_ticket_id_tickets",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_ticket_activities_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_ticket_activities_actor_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ticket_activities"),
    )
    op.create_index(
        "ix_ticket_activities_ticket_id", "ticket_activities", ["ticket_id"], unique=False
    )
    op.create_index(
        "ix_ticket_activities_workspace_id", "ticket_activities", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_ticket_activities_actor_id", "ticket_activities", ["actor_id"], unique=False
    )
    op.create_index(
        "ix_ticket_activities_created_at", "ticket_activities", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_table("ticket_activities")
    op.drop_table("tickets")
