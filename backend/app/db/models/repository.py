import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.engineering_task import EngineeringTask
    from app.db.models.github_installation import GitHubInstallation
    from app.db.models.pull_request import PullRequestRecord
    from app.db.models.repository_member import RepositoryMember
    from app.db.models.workspace import Workspace


class Repository(Base):
    """Connected Git repository belonging to a workspace and installation."""

    __tablename__ = "repositories"

    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_repositories_id_workspace"),
        UniqueConstraint(
            "workspace_id", "github_repository_id", name="uq_repositories_workspace_github_repo"
        ),
        ForeignKeyConstraint(
            ["installation_id", "workspace_id"],
            ["github_installations.id", "github_installations.workspace_id"],
            name="fk_repositories_installation_workspace",
            ondelete="CASCADE",
        ),
        Index("ix_repositories_workspace_id", "workspace_id"),
        Index("ix_repositories_github_repo_id", "github_repository_id"),
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
    installation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    github_repository_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        index=True,
    )
    owner_login: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    default_branch: Mapped[str] = mapped_column(
        String(100),
        default="main",
        nullable=False,
    )
    html_url: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )
    visibility: Mapped[str] = mapped_column(
        String(20),  # "public" or "private"
        default="private",
        nullable=False,
    )
    language: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    last_indexed_at: Mapped[datetime | None] = mapped_column(
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
    workspace: Mapped["Workspace"] = relationship(
        "Workspace",
        back_populates="repositories",
        overlaps="repositories,workspace",
    )
    installation: Mapped["GitHubInstallation"] = relationship(
        "GitHubInstallation",
        back_populates="repositories",
        foreign_keys=[installation_id, workspace_id],
        overlaps="workspace,repositories",
    )
    members: Mapped[list["RepositoryMember"]] = relationship(
        "RepositoryMember",
        back_populates="repository",
        cascade="all, delete-orphan",
    )
    tasks: Mapped[list["EngineeringTask"]] = relationship(
        "EngineeringTask",
        back_populates="repository",
        cascade="all, delete-orphan",
        overlaps="workspace",
    )
    pull_requests: Mapped[list["PullRequestRecord"]] = relationship(
        "PullRequestRecord",
        back_populates="repository",
        cascade="all, delete-orphan",
        overlaps="workspace",
    )

    def __repr__(self) -> str:
        return f"<Repository id={self.id} full_name={self.full_name}>"
