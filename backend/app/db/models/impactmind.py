import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.repository import Repository
    from app.db.models.repository_intelligence import RepositorySnapshot
    from app.db.models.user import User
    from app.db.models.workspace import Workspace

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class ImpactAssessment(Base):
    """
    Persisted record of an ImpactMind change impact analysis execution.
    Maintains tenant isolation, commit range, structural exposure score,
    breaking changes count, and child relationships.
    """

    __tablename__ = "impact_assessments"

    __table_args__ = (
        Index("ix_impact_assessments_workspace_id", "workspace_id"),
        Index("ix_impact_assessments_repo_id", "repository_id"),
        Index("ix_impact_assessments_snapshot_id", "snapshot_id"),
        Index("ix_impact_assessments_status", "status"),
        Index("ix_impact_assessments_created_at", "created_at"),
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
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repository_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    initiated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    base_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    comparison_mode: Mapped[str] = mapped_column(
        String(32), default="diff_input", nullable=False
    )  # commit_range, working_tree, diff_input
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )  # pending, analyzing, completed, failed

    structural_exposure_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    exposure_tier: Mapped[str] = mapped_column(
        String(16), default="LOW", nullable=False
    )  # LOW, MEDIUM, HIGH, CRITICAL

    change_summary: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    reasons: Mapped[list[Any]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    recommended_actions: Mapped[list[Any]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", lazy="selectin")
    repository: Mapped["Repository"] = relationship("Repository", lazy="selectin")
    snapshot: Mapped["RepositorySnapshot | None"] = relationship(
        "RepositorySnapshot", lazy="selectin"
    )
    user: Mapped["User | None"] = relationship("User", lazy="selectin")

    classifications: Mapped[list["ChangeClassification"]] = relationship(
        "ChangeClassification",
        back_populates="assessment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    impacted_entities: Mapped[list["ImpactedEntity"]] = relationship(
        "ImpactedEntity",
        back_populates="assessment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    test_recommendations: Mapped[list["TestRecommendation"]] = relationship(
        "TestRecommendation",
        back_populates="assessment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    test_executions: Mapped[list["TestExecutionRun"]] = relationship(
        "TestExecutionRun",
        back_populates="assessment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ChangeClassification(Base):
    """
    AST-classified change for an individual file or symbol within an assessment.
    """

    __tablename__ = "impact_change_classifications"

    __table_args__ = (
        Index("ix_impact_changes_assessment_id", "assessment_id"),
        Index("ix_impact_changes_category", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("impact_assessments.id", ondelete="CASCADE"),
        nullable=False,
    )

    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    symbol_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    symbol_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    is_breaking: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    breaking_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="resolved", nullable=False)

    assessment: Mapped["ImpactAssessment"] = relationship(
        "ImpactAssessment", back_populates="classifications"
    )


class ImpactedEntity(Base):
    """
    Downstream entity impacted by the change (caller, exposed endpoint, database table, etc.).
    """

    __tablename__ = "impact_impacted_entities"

    __table_args__ = (
        Index("ix_impacted_entities_assessment_id", "assessment_id"),
        Index("ix_impacted_entities_type", "impact_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("impact_assessments.id", ondelete="CASCADE"),
        nullable=False,
    )

    entity_id: Mapped[str] = mapped_column(String(512), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    impact_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # direct_dependent, indirect_dependent, exposed_endpoint, database_model, semantic_match
    depth: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    relationship_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment: Mapped["ImpactAssessment"] = relationship(
        "ImpactAssessment", back_populates="impacted_entities"
    )


class TestRecommendation(Base):
    """
    Recommended regression test selected by ImpactMind test selection engine.
    """

    __tablename__ = "impact_test_recommendations"
    __test__ = False

    __table_args__ = (
        Index("ix_test_recommendations_assessment_id", "assessment_id"),
        Index("ix_test_recommendations_priority", "priority"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("impact_assessments.id", ondelete="CASCADE"),
        nullable=False,
    )

    test_file: Mapped[str] = mapped_column(String(1024), nullable=False)
    test_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    test_framework: Mapped[str] = mapped_column(String(64), default="pytest", nullable=False)
    priority: Mapped[str] = mapped_column(
        String(16), default="MEDIUM", nullable=False
    )  # CRITICAL, HIGH, MEDIUM, LOW
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    related_symbol: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_source: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    assessment: Mapped["ImpactAssessment"] = relationship(
        "ImpactAssessment", back_populates="test_recommendations"
    )


class TestExecutionRun(Base):
    """
    Execution run of approved regression tests in a controlled environment.
    """

    __tablename__ = "impact_test_executions"
    __test__ = False

    __table_args__ = (
        Index("ix_test_executions_assessment_id", "assessment_id"),
        Index("ix_test_executions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("impact_assessments.id", ondelete="CASCADE"),
        nullable=False,
    )

    command: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", nullable=False
    )  # PENDING, RUNNING, PASSED, FAILED, TIMED_OUT, CANCELLED, SKIPPED
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)

    passed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assessment: Mapped["ImpactAssessment"] = relationship(
        "ImpactAssessment", back_populates="test_executions"
    )
