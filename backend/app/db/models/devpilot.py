from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
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
    from app.db.models.user import User
    from app.db.models.workspace import Workspace

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class DevPilotTask(Base):
    """
    Autonomous software engineering task dispatched to DevPilot.
    Tenant-isolated by workspace_id and repository_id.
    """

    __tablename__ = "devpilot_tasks"

    __table_args__ = (
        Index("ix_devpilot_tasks_workspace_id", "workspace_id"),
        Index("ix_devpilot_tasks_repository_id", "repository_id"),
        Index("ix_devpilot_tasks_status", "status"),
        Index("ix_devpilot_tasks_created_at", "created_at"),
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
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(
        String(64),
        default="FEATURE",
        nullable=False,  # FEATURE, BUGFIX, REFACTOR, TESTS, API, PERFORMANCE, DOCS
    )
    status: Mapped[str] = mapped_column(
        String(64),
        default="CREATED",
        nullable=False,
        # CREATED, ANALYZING, PLANNING, AWAITING_APPROVAL, GENERATING,
        # REVIEWING, AWAITING_MODIFICATION_APPROVAL, APPLYING, VALIDATING,
        # COMPLETED, FAILED, CANCELLED, BLOCKED, NEEDS_CLARIFICATION
    )

    base_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    isolated_workspace_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    clarification_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    workspace: Mapped[Workspace] = relationship("Workspace")
    repository: Mapped[Repository] = relationship("Repository")
    creator: Mapped[User | None] = relationship("User")

    plans: Mapped[list[EngineeringPlan]] = relationship(
        "EngineeringPlan",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="EngineeringPlan.created_at.desc()",
        lazy="selectin",
    )
    generation_results: Mapped[list[CodeGenerationResult]] = relationship(
        "CodeGenerationResult",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    review_findings: Mapped[list[CodeReviewFinding]] = relationship(
        "CodeReviewFinding",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    validation_runs: Mapped[list[DevPilotValidationRun]] = relationship(
        "DevPilotValidationRun",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    approvals: Mapped[list[DevPilotApproval]] = relationship(
        "DevPilotApproval",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    events: Mapped[list[DevPilotEvent]] = relationship(
        "DevPilotEvent",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="DevPilotEvent.created_at.asc()",
        lazy="selectin",
    )


class EngineeringPlan(Base):
    """
    Structured implementation plan produced by DevPilot before any code modification.
    Requires explicit human approval before code generation/modification proceeds.
    """

    __tablename__ = "devpilot_engineering_plans"

    __table_args__ = (
        Index("ix_devpilot_plans_task_id", "task_id"),
        Index("ix_devpilot_plans_workspace_id", "workspace_id"),
        Index("ix_devpilot_plans_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devpilot_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    task_understanding: Mapped[str] = mapped_column(Text, nullable=False)
    existing_implementation_analysis: Mapped[str] = mapped_column(Text, nullable=False)
    security_implications: Mapped[str] = mapped_column(Text, nullable=False)

    impact_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    exposure_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    exposure_tier: Mapped[str] = mapped_column(String(32), default="LOW", nullable=False)

    status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING",
        nullable=False,  # PENDING, APPROVED, REJECTED
    )
    approval_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    task: Mapped[DevPilotTask] = relationship("DevPilotTask", back_populates="plans")
    steps: Mapped[list[EngineeringPlanStep]] = relationship(
        "EngineeringPlanStep",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="EngineeringPlanStep.step_number.asc()",
        lazy="selectin",
    )


class EngineeringPlanStep(Base):
    """Granular action item within an approved engineering plan."""

    __tablename__ = "devpilot_plan_steps"

    __table_args__ = (
        Index("ix_devpilot_plan_steps_plan_id", "plan_id"),
        Index("ix_devpilot_plan_steps_step_number", "step_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devpilot_engineering_plans.id", ondelete="CASCADE"),
        nullable=False,
    )

    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    target_files: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    affected_symbols: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list, nullable=False)
    action_type: Mapped[str] = mapped_column(
        String(32),
        default="MODIFY_FILE",
        nullable=False,  # CREATE_FILE, MODIFY_FILE, DELETE_FILE, REFACTOR_SYMBOL, ADD_TEST, RUN_MIGRATION
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(
        String(32),
        default="LOW",
        nullable=False,  # LOW, MEDIUM, HIGH, CRITICAL
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="PLANNED",
        nullable=False,  # PLANNED, IN_PROGRESS, COMPLETED, FAILED, SKIPPED
    )

    plan: Mapped[EngineeringPlan] = relationship("EngineeringPlan", back_populates="steps")


class CodeGenerationResult(Base):
    """Aggregated result of AI code generation for a task."""

    __tablename__ = "devpilot_generation_results"

    __table_args__ = (
        Index("ix_devpilot_gen_results_task_id", "task_id"),
        Index("ix_devpilot_gen_results_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devpilot_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider_used: Mapped[str] = mapped_column(String(64), nullable=False)
    model_used: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_files_changed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unified_diff: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="GENERATED",
        nullable=False,  # GENERATED, APPROVED, REJECTED, APPLIED
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    task: Mapped[DevPilotTask] = relationship("DevPilotTask", back_populates="generation_results")
    changes: Mapped[list[CodeChange]] = relationship(
        "CodeChange",
        back_populates="generation_result",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CodeChange(Base):
    """Individual file modification generated by DevPilot."""

    __tablename__ = "devpilot_code_changes"

    __table_args__ = (
        Index("ix_devpilot_code_changes_gen_id", "generation_result_id"),
        Index("ix_devpilot_code_changes_file_path", "file_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    generation_result_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devpilot_generation_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )

    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    change_type: Mapped[str] = mapped_column(
        String(32),
        default="MODIFY",
        nullable=False,  # CREATE, MODIFY, DELETE, RENAME
    )
    old_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff_hunk: Mapped[str | None] = mapped_column(Text, nullable=True)

    generation_result: Mapped[CodeGenerationResult] = relationship(
        "CodeGenerationResult", back_populates="changes"
    )


class CodeReviewFinding(Base):
    """Automated code review finding generated for proposed modifications."""

    __tablename__ = "devpilot_review_findings"

    __table_args__ = (
        Index("ix_devpilot_review_task_id", "task_id"),
        Index("ix_devpilot_review_severity", "severity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devpilot_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )

    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severity: Mapped[str] = mapped_column(
        String(32),
        default="INFO",
        nullable=False,  # INFO, LOW, MEDIUM, HIGH, CRITICAL
    )
    category: Mapped[str] = mapped_column(
        String(64),
        default="CORRECTNESS",
        nullable=False,  # CORRECTNESS, SECURITY, INPUT_VALIDATION, ERROR_HANDLING, TYPE_SAFETY, PERFORMANCE, ARCHITECTURE, DUPLICATION
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_correction: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    task: Mapped[DevPilotTask] = relationship("DevPilotTask", back_populates="review_findings")


class DevPilotValidationRun(Base):
    """Record of a validation stage execution for a task in the isolated workspace."""

    __tablename__ = "devpilot_validation_runs"

    __table_args__ = (
        Index("ix_devpilot_val_runs_task_id", "task_id"),
        Index("ix_devpilot_val_runs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devpilot_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )

    stage: Mapped[str] = mapped_column(
        String(64),
        nullable=False,  # SYNTAX, AST_PARSER, LINT, TYPE_CHECK, UNIT_TESTS, IMPACTMIND_REGRESSION
    )
    command: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="PASSED",
        nullable=False,  # PASSED, FAILED, SKIPPED, CANCELLED
    )
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    task: Mapped[DevPilotTask] = relationship("DevPilotTask", back_populates="validation_runs")


class DevPilotApproval(Base):
    """Audit log of human-in-the-loop approvals or rejections."""

    __tablename__ = "devpilot_approvals"

    __table_args__ = (
        Index("ix_devpilot_approvals_task_id", "task_id"),
        Index("ix_devpilot_approvals_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devpilot_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    approval_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,  # PLAN_APPROVAL, MODIFICATION_APPROVAL, VALIDATION_APPROVAL
    )
    decision: Mapped[str] = mapped_column(
        String(32),
        nullable=False,  # APPROVED, REJECTED
    )
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    task: Mapped[DevPilotTask] = relationship("DevPilotTask", back_populates="approvals")
    user: Mapped[User] = relationship("User")


class DevPilotEvent(Base):
    """Granular execution timeline and state transition event log for a task."""

    __tablename__ = "devpilot_events"

    __table_args__ = (
        Index("ix_devpilot_events_task_id", "task_id"),
        Index("ix_devpilot_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devpilot_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    task: Mapped[DevPilotTask] = relationship("DevPilotTask", back_populates="events")
