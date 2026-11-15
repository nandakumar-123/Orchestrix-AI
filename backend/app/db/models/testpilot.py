from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
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


class TestFramework(enum.StrEnum):
    """Supported testing frameworks detected in repositories."""

    __test__ = False

    PYTEST = "pytest"
    UNITTEST = "unittest"
    JEST = "jest"
    MOCHA = "mocha"
    VITEST = "vitest"
    GO_TEST = "go_test"
    CARGO_TEST = "cargo_test"
    CUSTOM = "custom"


class TestType(enum.StrEnum):
    """Supported categories of generated and managed test cases."""

    __test__ = False

    UNIT = "unit"
    INTEGRATION = "integration"
    REGRESSION = "regression"
    EDGE_CASE = "edge_case"
    NEGATIVE = "negative"


class TestSuiteStatus(enum.StrEnum):
    """Lifecycle states for TestPilot test suites."""

    __test__ = False

    GENERATED = "generated"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class TestExecutionStatus(enum.StrEnum):
    """Supported execution states for TestPilot test execution runs."""

    __test__ = False

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class TestResultOutcome(enum.StrEnum):
    """Individual test outcome results within an execution run."""

    __test__ = False

    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"


class TestPilotSuite(Base):
    """
    Generated or curated test suite for a repository and snapshot.
    Enforces tenant isolation by workspace_id and repository_id,
    with auditable approval lifecycle before execution.
    """

    __test__ = False

    __tablename__ = "testpilot_suites"

    __table_args__ = (
        ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_testpilot_suites_repo_workspace",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "test_type IN ('unit', 'integration', 'regression', 'edge_case', 'negative')",
            name="ck_testpilot_suites_test_type",
        ),
        CheckConstraint(
            "status IN ('generated', 'awaiting_approval', 'approved', 'rejected', 'archived')",
            name="ck_testpilot_suites_status",
        ),
        Index("ix_testpilot_suites_workspace_id", "workspace_id"),
        Index("ix_testpilot_suites_repository_id", "repository_id"),
        Index("ix_testpilot_suites_snapshot_id", "snapshot_id"),
        Index("ix_testpilot_suites_status", "status"),
        Index("ix_testpilot_suites_created_at", "created_at"),
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
    framework: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    test_type: Mapped[str] = mapped_column(
        String(32),
        default=TestType.UNIT,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=TestSuiteStatus.GENERATED,
        nullable=False,
    )
    target_files: Mapped[list[str]] = mapped_column(
        JSON_TYPE,
        default=list,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    workspace: Mapped[Workspace] = relationship(
        "Workspace", foreign_keys=[workspace_id], lazy="selectin"
    )
    repository: Mapped[Repository] = relationship(
        "Repository", foreign_keys=[repository_id], lazy="selectin"
    )
    snapshot: Mapped[RepositorySnapshot | None] = relationship(
        "RepositorySnapshot", lazy="selectin"
    )
    approver: Mapped[User | None] = relationship("User", lazy="selectin")

    cases: Mapped[list[TestPilotCase]] = relationship(
        "TestPilotCase",
        back_populates="suite",
        cascade="all, delete-orphan",
        order_by="TestPilotCase.created_at.asc()",
        lazy="selectin",
    )
    executions: Mapped[list[TestPilotExecution]] = relationship(
        "TestPilotExecution",
        back_populates="suite",
        order_by="TestPilotExecution.created_at.desc()",
        lazy="selectin",
    )


class TestPilotCase(Base):
    """
    Individual test case within a TestPilot test suite.
    Preserves generated code, target symbol, and metadata for review.
    Code is stored as passive text and never executed during persistence.
    """

    __test__ = False

    __tablename__ = "testpilot_cases"

    __table_args__ = (
        CheckConstraint(
            "test_type IN ('unit', 'integration', 'regression', 'edge_case', 'negative')",
            name="ck_testpilot_cases_test_type",
        ),
        Index("ix_testpilot_cases_suite_id", "suite_id"),
        Index("ix_testpilot_cases_status", "status"),
        Index("ix_testpilot_cases_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    suite_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("testpilot_suites.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
    )
    test_type: Mapped[str] = mapped_column(
        String(32),
        default=TestType.UNIT,
        nullable=False,
    )
    target_symbol: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="generated",
        nullable=False,
    )
    is_edge_case: Mapped[bool] = mapped_column(
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
    suite: Mapped[TestPilotSuite] = relationship(
        "TestPilotSuite",
        back_populates="cases",
        lazy="selectin",
    )


class TestPilotExecution(Base):
    """
    Execution run record for a test suite or ad-hoc test execution.
    Preserves execution command, exit code, stdout, stderr, execution duration,
    and granular pass/fail/skip counts with nonnegative constraints.
    """

    __test__ = False

    __tablename__ = "testpilot_executions"

    __table_args__ = (
        ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_testpilot_executions_repo_workspace",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'PASSED', 'FAILED', 'ERROR', 'TIMED_OUT', 'CANCELLED', 'BLOCKED')",
            name="ck_testpilot_executions_status",
        ),
        CheckConstraint(
            "duration_ms >= 0",
            name="ck_testpilot_executions_duration_ms_nonnegative",
        ),
        CheckConstraint(
            "passed_count >= 0",
            name="ck_testpilot_executions_passed_count_nonnegative",
        ),
        CheckConstraint(
            "failed_count >= 0",
            name="ck_testpilot_executions_failed_count_nonnegative",
        ),
        CheckConstraint(
            "skipped_count >= 0",
            name="ck_testpilot_executions_skipped_count_nonnegative",
        ),
        Index("ix_testpilot_executions_workspace_id", "workspace_id"),
        Index("ix_testpilot_executions_repository_id", "repository_id"),
        Index("ix_testpilot_executions_suite_id", "suite_id"),
        Index("ix_testpilot_executions_status", "status"),
        Index("ix_testpilot_executions_created_at", "created_at"),
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
    suite_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("testpilot_suites.id", ondelete="SET NULL"),
        nullable=True,
    )
    command: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=TestExecutionStatus.PENDING,
        nullable=False,
    )
    exit_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    stdout: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
    )
    stderr: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    passed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    failed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    skipped_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    workspace: Mapped[Workspace] = relationship(
        "Workspace", foreign_keys=[workspace_id], lazy="selectin"
    )
    repository: Mapped[Repository] = relationship(
        "Repository", foreign_keys=[repository_id], lazy="selectin"
    )
    suite: Mapped[TestPilotSuite | None] = relationship(
        "TestPilotSuite",
        back_populates="executions",
        lazy="selectin",
    )
    results: Mapped[list[TestPilotResult]] = relationship(
        "TestPilotResult",
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="TestPilotResult.id.asc()",
        lazy="selectin",
    )
    coverage_reports: Mapped[list[TestPilotCoverageReport]] = relationship(
        "TestPilotCoverageReport",
        back_populates="execution",
        lazy="selectin",
    )


class TestPilotResult(Base):
    """
    Individual test execution outcome within a TestPilot execution run.
    Records duration, failure messages, and traceback safely.
    """

    __test__ = False

    __tablename__ = "testpilot_results"

    __table_args__ = (
        CheckConstraint(
            "status IN ('PASSED', 'FAILED', 'ERROR', 'SKIPPED', 'BLOCKED')",
            name="ck_testpilot_results_status",
        ),
        CheckConstraint(
            "duration_ms >= 0",
            name="ck_testpilot_results_duration_ms_nonnegative",
        ),
        Index("ix_testpilot_results_execution_id", "execution_id"),
        Index("ix_testpilot_results_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("testpilot_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    test_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    failure_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    traceback: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationships
    execution: Mapped[TestPilotExecution] = relationship(
        "TestPilotExecution",
        back_populates="results",
        lazy="selectin",
    )


class TestPilotCoverageReport(Base):
    """
    Code coverage report associated with a TestPilot execution or repository.
    Enforces valid range [0, 100] for line and branch percentages.
    Null signifies coverage was not computed or unavailable (never fabricated as zero).
    """

    __test__ = False

    __tablename__ = "testpilot_coverage_reports"

    __table_args__ = (
        ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_testpilot_coverage_reports_repo_workspace",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "line_coverage_pct IS NULL OR (line_coverage_pct >= 0.0 AND line_coverage_pct <= 100.0)",
            name="ck_testpilot_coverage_reports_line_coverage_pct",
        ),
        CheckConstraint(
            "branch_coverage_pct IS NULL OR (branch_coverage_pct >= 0.0 AND branch_coverage_pct <= 100.0)",
            name="ck_testpilot_coverage_reports_branch_coverage_pct",
        ),
        Index("ix_testpilot_coverage_reports_workspace_id", "workspace_id"),
        Index("ix_testpilot_coverage_reports_repository_id", "repository_id"),
        Index("ix_testpilot_coverage_reports_execution_id", "execution_id"),
        Index("ix_testpilot_coverage_reports_created_at", "created_at"),
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
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("testpilot_executions.id", ondelete="SET NULL"),
        nullable=True,
    )
    line_coverage_pct: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    branch_coverage_pct: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    uncovered_files: Mapped[list[str]] = mapped_column(
        JSON_TYPE,
        default=list,
        nullable=False,
    )
    uncovered_functions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_TYPE,
        default=list,
        nullable=False,
    )
    raw_report: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    workspace: Mapped[Workspace] = relationship(
        "Workspace", foreign_keys=[workspace_id], lazy="selectin"
    )
    repository: Mapped[Repository] = relationship(
        "Repository", foreign_keys=[repository_id], lazy="selectin"
    )
    execution: Mapped[TestPilotExecution | None] = relationship(
        "TestPilotExecution",
        back_populates="coverage_reports",
        lazy="selectin",
    )
