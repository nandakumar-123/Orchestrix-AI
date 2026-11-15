from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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
    from app.db.models.user import User
    from app.db.models.workspace import Workspace

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


# =============================================================================
# Enums
# =============================================================================


class WorkflowStatus(enum.StrEnum):
    """Lifecycle status of a FlowForge workflow definition."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class WorkflowTriggerType(enum.StrEnum):
    """Type of trigger initiating a workflow execution."""

    WEBHOOK = "WEBHOOK"
    SCHEDULE = "SCHEDULE"
    EVENT = "EVENT"
    MANUAL = "MANUAL"


class WorkflowExecutionStatus(enum.StrEnum):
    """Lifecycle status of a workflow run."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class WorkflowStepStatus(enum.StrEnum):
    """Execution status of an individual workflow node/step."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class WorkflowApprovalStatus(enum.StrEnum):
    """Human-in-the-loop approval decision status."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class WorkflowEventType(enum.StrEnum):
    """Granular audit event categories during workflow execution."""

    EXECUTION_STARTED = "EXECUTION_STARTED"
    STEP_STARTED = "STEP_STARTED"
    STEP_COMPLETED = "STEP_COMPLETED"
    STEP_FAILED = "STEP_FAILED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_DECIDED = "APPROVAL_DECIDED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_CANCELLED = "EXECUTION_CANCELLED"


# =============================================================================
# Models
# =============================================================================


class WorkflowDefinition(Base):
    """
    Visual workflow automation definition orchestrating multi-agent engineering tasks.
    Enforces tenant workspace isolation.
    """

    __tablename__ = "flowforge_workflows"

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_flowforge_workflows_workspace_name"),
        UniqueConstraint("id", "workspace_id", name="uq_flowforge_workflows_id_workspace"),
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'PAUSED', 'ARCHIVED')",
            name="ck_flowforge_workflows_status",
        ),
        Index("ix_flowforge_workflows_workspace_id", "workspace_id"),
        Index("ix_flowforge_workflows_status", "status"),
        Index("ix_flowforge_workflows_created_at", "created_at"),
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
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=WorkflowStatus.DRAFT,
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

    # Relationships
    workspace: Mapped[Workspace] = relationship(
        "Workspace", foreign_keys=[workspace_id], lazy="selectin"
    )
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by], lazy="selectin")
    versions: Mapped[list[WorkflowVersion]] = relationship(
        "WorkflowVersion",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowVersion.version_number",
        foreign_keys="[WorkflowVersion.workflow_id]",
        lazy="selectin",
    )
    triggers: Mapped[list[WorkflowTrigger]] = relationship(
        "WorkflowTrigger",
        back_populates="workflow",
        cascade="all, delete-orphan",
        foreign_keys="[WorkflowTrigger.workflow_id]",
        lazy="selectin",
    )
    executions: Mapped[list[WorkflowExecution]] = relationship(
        "WorkflowExecution",
        back_populates="workflow",
        foreign_keys="[WorkflowExecution.workflow_id]",
        lazy="selectin",
    )


class WorkflowVersion(Base):
    """
    Immutable versioned snapshot of a workflow definition JSON (nodes, edges, parameters).
    Ensures historical executions remain reproducible even after workflow edits.
    """

    __tablename__ = "flowforge_workflow_versions"

    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "version_number",
            name="uq_flowforge_versions_workflow_version",
        ),
        UniqueConstraint("id", "workflow_id", name="uq_flowforge_versions_id_workflow"),
        ForeignKeyConstraint(
            ["workflow_id", "workspace_id"],
            ["flowforge_workflows.id", "flowforge_workflows.workspace_id"],
            name="fk_flowforge_versions_workflow_workspace",
            ondelete="CASCADE",
        ),
        Index("ix_flowforge_versions_workflow_id", "workflow_id"),
        Index("ix_flowforge_versions_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("flowforge_workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    workflow_definition_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
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

    # Relationships
    workflow: Mapped[WorkflowDefinition] = relationship(
        "WorkflowDefinition",
        back_populates="versions",
        foreign_keys=[workflow_id],
        lazy="selectin",
    )
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by], lazy="selectin")


class WorkflowTrigger(Base):
    """
    Automated dispatch trigger for a workflow (Webhook, Schedule, Event, or Manual).
    """

    __tablename__ = "flowforge_workflow_triggers"

    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "workspace_id"],
            ["flowforge_workflows.id", "flowforge_workflows.workspace_id"],
            name="fk_flowforge_triggers_workflow_workspace",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "trigger_type IN ('WEBHOOK', 'SCHEDULE', 'EVENT', 'MANUAL')",
            name="ck_flowforge_triggers_type",
        ),
        Index(
            "ix_flowforge_triggers_workflow_type",
            "workflow_id",
            "trigger_type",
            "enabled",
        ),
        Index("ix_flowforge_triggers_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("flowforge_workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    trigger_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    configuration_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
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
    workflow: Mapped[WorkflowDefinition] = relationship(
        "WorkflowDefinition",
        back_populates="triggers",
        foreign_keys=[workflow_id],
        lazy="selectin",
    )


class WorkflowExecution(Base):
    """
    Record of a single workflow execution instance.
    Preserves audit history: uses RESTRICT on workflow definition delete.
    """

    __tablename__ = "flowforge_workflow_executions"

    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_flowforge_executions_id_workspace"),
        ForeignKeyConstraint(
            ["workflow_version_id", "workflow_id"],
            [
                "flowforge_workflow_versions.id",
                "flowforge_workflow_versions.workflow_id",
            ],
            name="fk_flowforge_executions_version",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'WAITING_FOR_APPROVAL', 'COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT')",
            name="ck_flowforge_executions_status",
        ),
        Index(
            "ix_flowforge_executions_workspace_workflow",
            "workspace_id",
            "workflow_id",
            "status",
        ),
        Index("ix_flowforge_executions_status", "status"),
        Index("ix_flowforge_executions_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("flowforge_workflows.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("flowforge_workflow_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    trigger_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("flowforge_workflow_triggers.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=WorkflowExecutionStatus.PENDING,
        nullable=False,
    )
    context_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
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
    error_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    workflow: Mapped[WorkflowDefinition] = relationship(
        "WorkflowDefinition",
        back_populates="executions",
        foreign_keys=[workflow_id],
        lazy="selectin",
    )
    version: Mapped[WorkflowVersion] = relationship(
        "WorkflowVersion", foreign_keys=[workflow_version_id], lazy="selectin"
    )
    trigger: Mapped[WorkflowTrigger | None] = relationship(
        "WorkflowTrigger", foreign_keys=[trigger_id], lazy="selectin"
    )
    steps: Mapped[list[WorkflowStepExecution]] = relationship(
        "WorkflowStepExecution",
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="WorkflowStepExecution.created_at",
        foreign_keys="[WorkflowStepExecution.execution_id]",
        lazy="selectin",
    )
    approvals: Mapped[list[WorkflowApproval]] = relationship(
        "WorkflowApproval",
        back_populates="execution",
        cascade="all, delete-orphan",
        foreign_keys="[WorkflowApproval.execution_id]",
        lazy="selectin",
    )
    events: Mapped[list[WorkflowEvent]] = relationship(
        "WorkflowEvent",
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="WorkflowEvent.created_at",
        foreign_keys="[WorkflowEvent.execution_id]",
        lazy="selectin",
    )


class WorkflowStepExecution(Base):
    """
    Execution state and results of a discrete step or node within a workflow execution.
    """

    __tablename__ = "flowforge_step_executions"

    __table_args__ = (
        UniqueConstraint("id", "execution_id", name="uq_flowforge_steps_id_execution"),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'WAITING_FOR_APPROVAL', 'COMPLETED', 'FAILED', 'SKIPPED', 'CANCELLED')",
            name="ck_flowforge_steps_status",
        ),
        Index(
            "ix_flowforge_steps_exec_node_attempt",
            "execution_id",
            "node_id",
            "attempt_number",
        ),
        Index("ix_flowforge_steps_status", "status"),
        Index("ix_flowforge_steps_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("flowforge_workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    node_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    agent_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,  # DEVPILOT, TESTPILOT, SECUREFLOW, IMPACTMIND, SYSTEM, HUMAN
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=WorkflowStepStatus.PENDING,
        nullable=False,
    )
    input_reference: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        nullable=True,
    )
    output_reference: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        nullable=True,
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    execution: Mapped[WorkflowExecution] = relationship(
        "WorkflowExecution",
        back_populates="steps",
        foreign_keys=[execution_id],
        lazy="selectin",
    )
    approvals: Mapped[list[WorkflowApproval]] = relationship(
        "WorkflowApproval",
        back_populates="step_execution",
        foreign_keys="[WorkflowApproval.step_execution_id]",
        lazy="selectin",
    )


class WorkflowApproval(Base):
    """
    Human-in-the-loop checkpoint requiring explicit authorization before continuing.
    """

    __tablename__ = "flowforge_approvals"

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'CANCELLED')",
            name="ck_flowforge_approvals_status",
        ),
        Index("ix_flowforge_approvals_execution_id", "execution_id", "status"),
        Index("ix_flowforge_approvals_step_id", "step_execution_id"),
        Index("ix_flowforge_approvals_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("flowforge_workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("flowforge_step_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=WorkflowApprovalStatus.PENDING,
        nullable=False,
    )
    decision_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    execution: Mapped[WorkflowExecution] = relationship(
        "WorkflowExecution",
        back_populates="approvals",
        foreign_keys=[execution_id],
        lazy="selectin",
    )
    step_execution: Mapped[WorkflowStepExecution] = relationship(
        "WorkflowStepExecution",
        back_populates="approvals",
        foreign_keys=[step_execution_id],
        lazy="selectin",
    )
    requester: Mapped[User | None] = relationship(
        "User", foreign_keys=[requested_by], lazy="selectin"
    )
    approver: Mapped[User | None] = relationship(
        "User", foreign_keys=[approved_by], lazy="selectin"
    )


class WorkflowEvent(Base):
    """
    Append-only audit and observability event log for workflow executions.
    """

    __tablename__ = "flowforge_events"

    __table_args__ = (
        Index("ix_flowforge_events_execution_created", "execution_id", "created_at"),
        Index("ix_flowforge_events_workspace_id", "workspace_id"),
        Index("ix_flowforge_events_event_type", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("flowforge_workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    execution: Mapped[WorkflowExecution] = relationship(
        "WorkflowExecution",
        back_populates="events",
        foreign_keys=[execution_id],
        lazy="selectin",
    )
