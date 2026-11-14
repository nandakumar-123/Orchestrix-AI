"""create_semantic_intelligence_tables

Revision ID: 4973ddae25ec
Revises: 837736663df1
Create Date: 2026-11-14 23:04:03.533256

"""

from collections.abc import Sequence

import pgvector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4973ddae25ec"
down_revision: str | Sequence[str] | None = "837736663df1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Ensure pgvector extension is available in PostgreSQL
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.create_table(
        "embedding_model_metadata",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_embedding_model_metadata_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["repository_snapshots.id"],
            name=op.f("fk_embedding_model_metadata_snapshot_id_repository_snapshots"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_embedding_model_metadata_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embedding_model_metadata")),
        sa.UniqueConstraint(
            "snapshot_id", "model_name", name="uq_embedding_metadata_snapshot_model"
        ),
    )
    op.create_index(
        "ix_embedding_metadata_repo_snapshot",
        "embedding_model_metadata",
        ["repository_id", "snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_embedding_metadata_workspace_id",
        "embedding_model_metadata",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "semantic_code_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("language", sa.String(length=50), nullable=False),
        sa.Column("symbol_name", sa.String(length=255), nullable=True),
        sa.Column("symbol_type", sa.String(length=50), nullable=True),
        sa.Column("parent_symbol_name", sa.String(length=255), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["repository_files.id"],
            name=op.f("fk_semantic_code_chunks_file_id_repository_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_semantic_code_chunks_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["repository_snapshots.id"],
            name=op.f("fk_semantic_code_chunks_snapshot_id_repository_snapshots"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_semantic_code_chunks_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_semantic_code_chunks")),
        sa.UniqueConstraint(
            "snapshot_id", "file_path", "chunk_index", name="uq_semantic_chunks_snapshot_path_idx"
        ),
    )
    op.create_index(
        "ix_semantic_chunks_content_hash", "semantic_code_chunks", ["content_hash"], unique=False
    )
    op.create_index(
        "ix_semantic_chunks_file_path", "semantic_code_chunks", ["file_path"], unique=False
    )
    op.create_index(
        "ix_semantic_chunks_repo_snapshot",
        "semantic_code_chunks",
        ["repository_id", "snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_semantic_chunks_symbol_name", "semantic_code_chunks", ["symbol_name"], unique=False
    )
    op.create_index(
        "ix_semantic_chunks_workspace_id", "semantic_code_chunks", ["workspace_id"], unique=False
    )

    # Vector cosine similarity index and Full Text Search index for PostgreSQL
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_semantic_chunks_embedding_cosine ON semantic_code_chunks USING hnsw (embedding vector_cosine_ops);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_semantic_chunks_content_fts ON semantic_code_chunks USING gin (to_tsvector('english', content));"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_semantic_chunks_content_fts;")
    op.execute("DROP INDEX IF EXISTS ix_semantic_chunks_embedding_cosine;")
    op.drop_index("ix_semantic_chunks_workspace_id", table_name="semantic_code_chunks")
    op.drop_index("ix_semantic_chunks_symbol_name", table_name="semantic_code_chunks")
    op.drop_index("ix_semantic_chunks_repo_snapshot", table_name="semantic_code_chunks")
    op.drop_index("ix_semantic_chunks_file_path", table_name="semantic_code_chunks")
    op.drop_index("ix_semantic_chunks_content_hash", table_name="semantic_code_chunks")
    op.drop_table("semantic_code_chunks")
    op.drop_index("ix_embedding_metadata_workspace_id", table_name="embedding_model_metadata")
    op.drop_index("ix_embedding_metadata_repo_snapshot", table_name="embedding_model_metadata")
    op.drop_table("embedding_model_metadata")
