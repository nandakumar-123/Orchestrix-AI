from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
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
    from app.db.models.user import User
    from app.db.models.workspace import Workspace

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


# =============================================================================
# Enums
# =============================================================================


class MemoryType(enum.StrEnum):
    """Categorization of stored engineering memory."""

    ARCHITECTURE_DECISION = "ARCHITECTURE_DECISION"
    TECHNICAL_DECISION = "TECHNICAL_DECISION"
    VERIFIED_BUGFIX = "VERIFIED_BUGFIX"
    REPO_KNOWLEDGE = "REPO_KNOWLEDGE"
    CODE_EXPLANATION = "CODE_EXPLANATION"
    ENGINEERING_CONVENTION = "ENGINEERING_CONVENTION"
    TASK_OUTCOME = "TASK_OUTCOME"
    IMPLEMENTATION_DISCOVERY = "IMPLEMENTATION_DISCOVERY"
    KNOWN_LIMITATION = "KNOWN_LIMITATION"
    VERIFIED_SOLUTION = "VERIFIED_SOLUTION"


class MemorySourceType(enum.StrEnum):
    """Origin of an ingested engineering memory."""

    AGENT_EXECUTION = "AGENT_EXECUTION"
    CODE_REVIEW = "CODE_REVIEW"
    COMMIT = "COMMIT"
    PULL_REQUEST = "PULL_REQUEST"
    USER_INPUT = "USER_INPUT"
    TEST_FAILURE = "TEST_FAILURE"
    SECURITY_AUDIT = "SECURITY_AUDIT"


class MemoryVerificationStatus(enum.StrEnum):
    """Lifecycle validity and verification state of memory."""

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    OUTDATED = "OUTDATED"
    ARCHIVED = "ARCHIVED"


class EvidenceType(enum.StrEnum):
    """Type of concrete proof or artifact anchoring a memory."""

    CODE_SNIPPET = "CODE_SNIPPET"
    LOG_TRACE = "LOG_TRACE"
    DIFF_PATCH = "DIFF_PATCH"
    TEST_OUTPUT = "TEST_OUTPUT"
    SECURITY_FINDING = "SECURITY_FINDING"
    BENCHMARK_RESULT = "BENCHMARK_RESULT"


class MemoryRelationshipType(enum.StrEnum):
    """Directed semantic relationship linking two engineering memories."""

    EXTENDS = "EXTENDS"
    SUPERSEDES = "SUPERSEDES"
    CONTRADICTS = "CONTRADICTS"
    RELATES_TO = "RELATES_TO"
    CAUSED_BY = "CAUSED_BY"
    RESOLVED_BY = "RESOLVED_BY"


class MemoryConsumerAgent(enum.StrEnum):
    """Agent or actor accessing or citing memory."""

    DEVPILOT = "DEVPILOT"
    IMPACTMIND = "IMPACTMIND"
    TESTPILOT = "TESTPILOT"
    SECUREFLOW = "SECUREFLOW"
    FLOWFORGE = "FLOWFORGE"
    USER = "USER"


class MemoryAccessType(enum.StrEnum):
    """Type of memory access action."""

    RETRIEVE = "RETRIEVE"
    CITE = "CITE"
    APPLY = "APPLY"
    VERIFY = "VERIFY"
    INVALIDATE = "INVALIDATE"


# =============================================================================
# Models
# =============================================================================


class EngineeringMemory(Base):
    """
    Persistent engineering memory captured by Orchestrix agents.
    Supports semantic vector retrieval, workspace/repository isolation,
    evidence linkage, and knowledge-graph relationships.
    """

    __tablename__ = "engineering_memories"

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "content_hash", name="uq_devmemory_workspace_content_hash"
        ),
        UniqueConstraint("id", "workspace_id", name="uq_devmemory_id_workspace"),
        CheckConstraint(
            "confidence_score >= 0.0 AND confidence_score <= 1.0",
            name="ck_devmemory_confidence_range",
        ),
        CheckConstraint(
            "verification_status IN ('UNVERIFIED', 'VERIFIED', 'OUTDATED', 'ARCHIVED')",
            name="ck_devmemory_verification_status",
        ),
        CheckConstraint(
            "memory_type IN ('ARCHITECTURE_DECISION', 'TECHNICAL_DECISION', 'VERIFIED_BUGFIX', 'REPO_KNOWLEDGE', 'CODE_EXPLANATION', 'ENGINEERING_CONVENTION', 'TASK_OUTCOME', 'IMPLEMENTATION_DISCOVERY', 'KNOWN_LIMITATION', 'VERIFIED_SOLUTION')",
            name="ck_devmemory_memory_type",
        ),
        CheckConstraint(
            "source_type IN ('AGENT_EXECUTION', 'CODE_REVIEW', 'COMMIT', 'PULL_REQUEST', 'USER_INPUT', 'TEST_FAILURE', 'SECURITY_AUDIT')",
            name="ck_devmemory_source_type",
        ),
        Index("ix_devmemory_workspace_id", "workspace_id"),
        Index("ix_devmemory_workspace_repo", "workspace_id", "repository_id"),
        Index("ix_devmemory_memory_type", "workspace_id", "memory_type"),
        Index("ix_devmemory_verification", "workspace_id", "verification_status"),
        Index("ix_devmemory_content_hash", "content_hash"),
        Index("ix_devmemory_created_at", "created_at"),
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
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=True,
    )
    memory_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    source_reference: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    confidence_score: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        nullable=False,
    )
    verification_status: Mapped[str] = mapped_column(
        String(32),
        default=MemoryVerificationStatus.UNVERIFIED,
        nullable=False,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
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
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    # Relationships
    workspace: Mapped[Workspace] = relationship(
        "Workspace", foreign_keys=[workspace_id], lazy="selectin"
    )
    repository: Mapped[Repository | None] = relationship(
        "Repository", foreign_keys=[repository_id], lazy="selectin"
    )
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by], lazy="selectin")
    evidence: Mapped[list[MemoryEvidence]] = relationship(
        "MemoryEvidence",
        back_populates="memory",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    outgoing_relationships: Mapped[list[MemoryRelationship]] = relationship(
        "MemoryRelationship",
        foreign_keys="MemoryRelationship.source_memory_id",
        back_populates="source_memory",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    incoming_relationships: Mapped[list[MemoryRelationship]] = relationship(
        "MemoryRelationship",
        foreign_keys="MemoryRelationship.target_memory_id",
        back_populates="target_memory",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    access_logs: Mapped[list[MemoryAccessLog]] = relationship(
        "MemoryAccessLog",
        back_populates="memory",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class MemoryEvidence(Base):
    """
    Concrete code or artifact evidence corroborating an engineering memory.
    """

    __tablename__ = "memory_evidence"

    __table_args__ = (
        CheckConstraint(
            "evidence_type IN ('CODE_SNIPPET', 'LOG_TRACE', 'DIFF_PATCH', 'TEST_OUTPUT', 'SECURITY_FINDING', 'BENCHMARK_RESULT')",
            name="ck_devmemory_evidence_type",
        ),
        Index("ix_memory_evidence_memory_id", "memory_id", "evidence_type"),
        Index("ix_memory_evidence_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("engineering_memories.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    evidence_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    source_reference: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    evidence_content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    memory: Mapped[EngineeringMemory] = relationship(
        "EngineeringMemory", back_populates="evidence", lazy="selectin"
    )


class MemoryRelationship(Base):
    """
    Directional semantic connection between two engineering memories
    (e.g., Memory A SUPERSEDES Memory B, or Memory C RELATES_TO Memory D).
    """

    __tablename__ = "memory_relationships"

    __table_args__ = (
        UniqueConstraint(
            "source_memory_id",
            "target_memory_id",
            "relationship_type",
            name="uq_devmemory_rel_source_target_type",
        ),
        CheckConstraint(
            "confidence_score >= 0.0 AND confidence_score <= 1.0",
            name="ck_devmemory_rel_confidence_range",
        ),
        CheckConstraint(
            "relationship_type IN ('EXTENDS', 'SUPERSEDES', 'CONTRADICTS', 'RELATES_TO', 'CAUSED_BY', 'RESOLVED_BY')",
            name="ck_devmemory_rel_type",
        ),
        CheckConstraint(
            "source_memory_id != target_memory_id",
            name="ck_devmemory_rel_no_self_loop",
        ),
        Index(
            "ix_memory_relationships_source_target",
            "source_memory_id",
            "target_memory_id",
        ),
        Index("ix_memory_relationships_workspace_id", "workspace_id"),
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
    source_memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("engineering_memories.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("engineering_memories.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    confidence_score: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    source_memory: Mapped[EngineeringMemory] = relationship(
        "EngineeringMemory",
        foreign_keys=[source_memory_id],
        back_populates="outgoing_relationships",
        lazy="selectin",
    )
    target_memory: Mapped[EngineeringMemory] = relationship(
        "EngineeringMemory",
        foreign_keys=[target_memory_id],
        back_populates="incoming_relationships",
        lazy="selectin",
    )


class MemoryAccessLog(Base):
    """
    Observability and citation audit log tracking agent accesses to engineering memories.
    """

    __tablename__ = "memory_access_logs"

    __table_args__ = (
        CheckConstraint(
            "agent_type IN ('DEVPILOT', 'IMPACTMIND', 'TESTPILOT', 'SECUREFLOW', 'FLOWFORGE', 'USER')",
            name="ck_devmemory_access_agent_type",
        ),
        CheckConstraint(
            "access_type IN ('RETRIEVE', 'CITE', 'APPLY', 'VERIFY', 'INVALIDATE')",
            name="ck_devmemory_access_type",
        ),
        Index(
            "ix_memory_access_logs_memory_workspace",
            "memory_id",
            "workspace_id",
            "accessed_at",
        ),
        Index("ix_memory_access_logs_workspace_agent", "workspace_id", "agent_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("engineering_memories.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    access_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    context_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        nullable=True,
    )
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    memory: Mapped[EngineeringMemory] = relationship(
        "EngineeringMemory", back_populates="access_logs", lazy="selectin"
    )
