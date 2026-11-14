import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TaskPriority, TaskStatus, TaskType, utc_now

if TYPE_CHECKING:
    from app.db.models.pull_request import PullRequestRecord
    from app.db.models.repository import Repository
    from app.db.models.user import User
    from app.db.models.workspace import Workspace


class EngineeringTask(Base):
    """Autonomous engineering task dispatched to AI agents or workspace users."""

    __tablename__ = "engineering_tasks"

    __table_args__ = (
        Index("ix_engineering_tasks_workspace_id", "workspace_id"),
        Index("ix_engineering_tasks_repository_id", "repository_id"),
        Index("ix_engineering_tasks_status", "status"),
        Index("ix_engineering_tasks_created_at", "created_at"),
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
        ForeignKey("repositories.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    task_type: Mapped[TaskType] = mapped_column(
        Enum(TaskType, name="tasktype", native_enum=False),
        default=TaskType.GENERAL,
        nullable=False,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, name="taskpriority", native_enum=False),
        default=TaskPriority.MEDIUM,
        nullable=False,
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="taskstatus", native_enum=False),
        default=TaskStatus.BACKLOG,
        nullable=False,
    )
    assigned_agent: Mapped[str | None] = mapped_column(
        String(100),  # e.g., "DevPilot", "ImpactMind", "TestPilot"
        nullable=True,
        index=True,
    )
    external_issue_id: Mapped[str | None] = mapped_column(
        String(255),
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
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship(
        "Workspace",
        back_populates="engineering_tasks",
    )
    repository: Mapped[Optional["Repository"]] = relationship(
        "Repository",
        back_populates="tasks",
    )
    creator: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="created_tasks",
        foreign_keys=[created_by],
    )
    pull_requests: Mapped[list["PullRequestRecord"]] = relationship(
        "PullRequestRecord",
        back_populates="task",
    )

    def __repr__(self) -> str:
        return f"<EngineeringTask id={self.id} title={self.title} status={self.status}>"
