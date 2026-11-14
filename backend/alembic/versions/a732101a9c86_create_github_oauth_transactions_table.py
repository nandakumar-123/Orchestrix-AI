"""create_github_oauth_transactions_table

Revision ID: a732101a9c86
Revises: 8c46b9bc43a7
Create Date: 2026-11-14 19:29:27.717562

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a732101a9c86"
down_revision: str | Sequence[str] | None = "8c46b9bc43a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "github_oauth_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("lookup_hash", sa.String(length=64), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_github_oauth_transactions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_github_oauth_transactions")),
    )
    op.create_index(
        "ix_gh_oauth_trx_consumed_at", "github_oauth_transactions", ["consumed_at"], unique=False
    )
    op.create_index(
        "ix_gh_oauth_trx_expires_at", "github_oauth_transactions", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_gh_oauth_trx_lookup_hash", "github_oauth_transactions", ["lookup_hash"], unique=True
    )
    op.create_index(
        "ix_gh_oauth_trx_state_hash", "github_oauth_transactions", ["state_hash"], unique=False
    )
    op.create_index(
        "ix_gh_oauth_trx_user_id", "github_oauth_transactions", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_gh_oauth_trx_user_id", table_name="github_oauth_transactions")
    op.drop_index("ix_gh_oauth_trx_state_hash", table_name="github_oauth_transactions")
    op.drop_index("ix_gh_oauth_trx_lookup_hash", table_name="github_oauth_transactions")
    op.drop_index("ix_gh_oauth_trx_expires_at", table_name="github_oauth_transactions")
    op.drop_index("ix_gh_oauth_trx_consumed_at", table_name="github_oauth_transactions")
    op.drop_table("github_oauth_transactions")
