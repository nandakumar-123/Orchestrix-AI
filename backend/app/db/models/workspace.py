import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.audit_log import AuditLog
    from app.db.models.engineering_task import EngineeringTask
    from app.db.models.github_installation import GitHubInstallation
    from app.db.models.membership import WorkspaceMembership
    from app.db.models.repository import Repository
    from app.db.models.ticket import Ticket


class Workspace(Base):
    """Workspace tenant container model."""

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
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
    memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        "WorkspaceMembership",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    github_installations: Mapped[list["GitHubInstallation"]] = relationship(
        "GitHubInstallation",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    repositories: Mapped[list["Repository"]] = relationship(
        "Repository",
        back_populates="workspace",
        cascade="all, delete-orphan",
        overlaps="repositories,workspace",
    )
    engineering_tasks: Mapped[list["EngineeringTask"]] = relationship(
        "EngineeringTask",
        back_populates="workspace",
        cascade="all, delete-orphan",
        overlaps="repository,tasks,workspace",
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    tickets: Mapped[list["Ticket"]] = relationship(
        "Ticket",
        back_populates="workspace",
        cascade="all, delete-orphan",
        overlaps="repository,tickets,workspace",
    )

    def __repr__(self) -> str:
        return f"<Workspace id={self.id} slug={self.slug}>"
