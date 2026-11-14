import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
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

from app.db.base import Base, IndexingJobStatus, utc_now

if TYPE_CHECKING:
    from app.db.models.repository import Repository
    from app.db.models.workspace import Workspace

# Use JSONB for PostgreSQL, JSON fallback for SQLite in unit tests
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class IndexingJob(Base):
    """
    Tracks execution and lifecycle of a repository intelligence indexing job.
    Enforces workspace tenant isolation.
    """

    __tablename__ = "indexing_jobs"

    __table_args__ = (
        Index("ix_indexing_jobs_workspace_id", "workspace_id"),
        Index("ix_indexing_jobs_repo_status", "repository_id", "status"),
        Index("ix_indexing_jobs_repo_commit", "repository_id", "commit_sha"),
        Index("ix_indexing_jobs_created_at", "created_at"),
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
    commit_sha: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    branch: Mapped[str] = mapped_column(
        String(100),
        default="main",
        nullable=False,
    )
    status: Mapped[IndexingJobStatus] = mapped_column(
        String(20),
        default=IndexingJobStatus.PENDING,
        nullable=False,
    )
    progress_percent: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    current_step: Mapped[str] = mapped_column(
        String(100),
        default="pending",
        nullable=False,
    )
    files_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    symbols_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    dependencies_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    repository: Mapped["Repository"] = relationship("Repository")
    errors: Mapped[list["IndexingError"]] = relationship(
        "IndexingError",
        back_populates="job",
        cascade="all, delete-orphan",
    )


class RepositorySnapshot(Base):
    """
    Immutable snapshot of repository intelligence for a specific commit SHA.
    Contains summary metrics, language breakdowns, and structural metadata.
    """

    __tablename__ = "repository_snapshots"

    __table_args__ = (
        UniqueConstraint("repository_id", "commit_sha", name="uq_repository_snapshots_repo_commit"),
        Index("ix_repo_snapshots_workspace_id", "workspace_id"),
        Index("ix_repo_snapshots_repository_id", "repository_id"),
        Index("ix_repo_snapshots_commit_sha", "commit_sha"),
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
    commit_sha: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    branch: Mapped[str] = mapped_column(
        String(100),
        default="main",
        nullable=False,
    )
    total_files: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    total_lines: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    total_bytes: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        nullable=False,
    )
    total_symbols: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    total_dependencies: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    languages_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        nullable=True,
    )
    structure_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        nullable=True,
    )
    entry_points: Mapped[list[str] | None] = mapped_column(
        JSON_TYPE,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    repository: Mapped["Repository"] = relationship("Repository")
    files: Mapped[list["RepositoryFile"]] = relationship(
        "RepositoryFile",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )
    symbols: Mapped[list["CodeSymbol"]] = relationship(
        "CodeSymbol",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )
    dependencies: Mapped[list["FileDependency"]] = relationship(
        "FileDependency",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class RepositoryFile(Base):
    """
    Indexed source file within a repository snapshot.
    """

    __tablename__ = "repository_files"

    __table_args__ = (
        Index("ix_repo_files_snapshot_path", "snapshot_id", "path"),
        Index("ix_repo_files_repo_lang", "repository_id", "language"),
        Index("ix_repo_files_workspace_id", "workspace_id"),
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
    path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    extension: Mapped[str] = mapped_column(
        String(50),
        default="",
        nullable=False,
    )
    language: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    line_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    sha: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    is_binary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    is_manifest: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    snapshot: Mapped["RepositorySnapshot"] = relationship(
        "RepositorySnapshot", back_populates="files"
    )
    symbols: Mapped[list["CodeSymbol"]] = relationship(
        "CodeSymbol",
        back_populates="file",
        cascade="all, delete-orphan",
    )


class CodeSymbol(Base):
    """
    Extracted code symbol (function, class, method, etc.) via Tree-sitter parsing.
    """

    __tablename__ = "code_symbols"

    __table_args__ = (
        Index("ix_code_symbols_snapshot_id", "snapshot_id"),
        Index("ix_code_symbols_name", "name"),
        Index("ix_code_symbols_type", "symbol_type"),
        Index("ix_code_symbols_file_id", "file_id"),
        Index("ix_code_symbols_workspace_id", "workspace_id"),
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
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    symbol_type: Mapped[str] = mapped_column(
        String(50),  # "function", "class", "method", "interface", "export"
        nullable=False,
    )
    language: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    start_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    end_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    start_column: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    end_column: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    signature: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    parent_symbol_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    snapshot: Mapped["RepositorySnapshot"] = relationship(
        "RepositorySnapshot", back_populates="symbols"
    )
    file: Mapped["RepositoryFile"] = relationship("RepositoryFile", back_populates="symbols")


class FileDependency(Base):
    """
    Extracted dependency from dependency manifests (package.json, pyproject.toml, etc.)
    or source code imports.
    """

    __tablename__ = "file_dependencies"

    __table_args__ = (
        Index("ix_file_dependencies_snapshot_id", "snapshot_id"),
        Index("ix_file_dependencies_name", "name"),
        Index("ix_file_dependencies_type", "dependency_type"),
        Index("ix_file_dependencies_workspace_id", "workspace_id"),
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
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_file_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    version_spec: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    dependency_type: Mapped[str] = mapped_column(
        String(50),  # "package_dependency", "dev_dependency", "import"
        default="package_dependency",
        nullable=False,
    )
    package_manager: Mapped[str | None] = mapped_column(
        String(50),  # "npm", "pip", "cargo", "go", "maven"
        nullable=True,
    )
    is_external: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    snapshot: Mapped["RepositorySnapshot"] = relationship(
        "RepositorySnapshot", back_populates="dependencies"
    )


class IndexingError(Base):
    """
    Non-fatal warning or error captured during repository indexing.
    """

    __tablename__ = "indexing_errors"

    __table_args__ = (Index("ix_indexing_errors_job_id", "job_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("indexing_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_path: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    error_type: Mapped[str] = mapped_column(
        String(100),  # "parse_error", "file_too_large", "unsupported_language", "fetch_error"
        nullable=False,
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    job: Mapped["IndexingJob"] = relationship("IndexingJob", back_populates="errors")
