import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.repository import Repository
    from app.db.models.repository_intelligence import RepositoryFile, RepositorySnapshot
    from app.db.models.workspace import Workspace

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class SemanticCodeChunk(Base):
    """
    Structure-aware code chunk extracted from AST-parsed repository files
    with vector embedding for semantic search and AI context assembly.
    Enforces tenant workspace isolation and snapshot awareness.
    """

    __tablename__ = "semantic_code_chunks"

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "file_path",
            "chunk_index",
            name="uq_semantic_chunks_snapshot_path_idx",
        ),
        Index("ix_semantic_chunks_workspace_id", "workspace_id"),
        Index("ix_semantic_chunks_repo_snapshot", "repository_id", "snapshot_id"),
        Index("ix_semantic_chunks_file_path", "file_path"),
        Index("ix_semantic_chunks_symbol_name", "symbol_name"),
        Index("ix_semantic_chunks_content_hash", "content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repository_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )
    language: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    symbol_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    symbol_type: Mapped[str | None] = mapped_column(
        String(
            50
        ),  # "function", "method", "class", "interface", "struct", "module", "config", "file_summary"
        nullable=True,
    )
    parent_symbol_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    start_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    end_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON_TYPE,
        nullable=True,
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(384),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    repository: Mapped["Repository"] = relationship("Repository")
    snapshot: Mapped["RepositorySnapshot"] = relationship("RepositorySnapshot")
    file: Mapped["RepositoryFile"] = relationship("RepositoryFile")


class EmbeddingModelMetadata(Base):
    """
    Tracks embedding model, dimension, and indexing lifecycle for a snapshot.
    """

    __tablename__ = "embedding_model_metadata"

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "model_name",
            name="uq_embedding_metadata_snapshot_model",
        ),
        Index("ix_embedding_metadata_repo_snapshot", "repository_id", "snapshot_id"),
        Index("ix_embedding_metadata_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repository_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_name: Mapped[str] = mapped_column(
        String(50),
        default="fastembed",
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(
        String(100),
        default="sentence-transformers/all-MiniLM-L6-v2",
        nullable=False,
    )
    dimension: Mapped[int] = mapped_column(
        Integer,
        default=384,
        nullable=False,
    )
    total_chunks: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="pending",  # "pending", "indexing", "completed", "failed"
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    repository: Mapped["Repository"] = relationship("Repository")
    snapshot: Mapped["RepositorySnapshot"] = relationship("RepositorySnapshot")
