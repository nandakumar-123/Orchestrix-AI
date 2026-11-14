import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PullRequestState, utc_now

if TYPE_CHECKING:
    from app.db.models.engineering_task import EngineeringTask
    from app.db.models.repository import Repository
    from app.db.models.workspace import Workspace


class PullRequestRecord(Base):
    """Pull request synthesized or managed within Orchestrix AI."""

    __tablename__ = "pull_request_records"

    __table_args__ = (
        UniqueConstraint("repository_id", "pr_number", name="uq_pull_requests_repo_number"),
        ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_pull_request_records_repository_workspace",
            ondelete="CASCADE",
        ),
        Index("ix_pull_request_records_workspace_id", "workspace_id"),
        Index("ix_pull_request_records_repository_id", "repository_id"),
        Index("ix_pull_request_records_github_pr_id", "github_pr_id"),
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
        nullable=False,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("engineering_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    github_pr_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    pr_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    html_url: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )
    source_branch: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    target_branch: Mapped[str] = mapped_column(
        String(255),
        default="main",
        nullable=False,
    )
    state: Mapped[PullRequestState] = mapped_column(
        Enum(PullRequestState, name="pullrequeststate", native_enum=False),
        default=PullRequestState.OPEN,
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
    merged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship(
        "Workspace",
    )
    repository: Mapped["Repository"] = relationship(
        "Repository",
        back_populates="pull_requests",
        foreign_keys=[repository_id, workspace_id],
        overlaps="workspace,pull_requests",
    )
    task: Mapped[Optional["EngineeringTask"]] = relationship(
        "EngineeringTask",
        back_populates="pull_requests",
    )

    def __repr__(self) -> str:
        return f"<PullRequestRecord id={self.id} pr_number={self.pr_number} state={self.state}>"
