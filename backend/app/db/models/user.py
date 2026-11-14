import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.audit_log import AuditLog
    from app.db.models.engineering_task import EngineeringTask
    from app.db.models.membership import WorkspaceMembership
    from app.db.models.repository_member import RepositoryMember


class User(Base):
    """User account model."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    full_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    avatar_url: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
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
    memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        "WorkspaceMembership",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    repository_memberships: Mapped[list["RepositoryMember"]] = relationship(
        "RepositoryMember",
        back_populates="user",
        primaryjoin="User.id == RepositoryMember.user_id",
        foreign_keys="RepositoryMember.user_id",
        cascade="all, delete-orphan",
    )
    created_tasks: Mapped[list["EngineeringTask"]] = relationship(
        "EngineeringTask",
        back_populates="creator",
        foreign_keys="EngineeringTask.created_by",
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="actor",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"
