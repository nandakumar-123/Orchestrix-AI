import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, RepositoryMemberRole, utc_now

if TYPE_CHECKING:
    from app.db.models.repository import Repository
    from app.db.models.user import User


class RepositoryMember(Base):
    """Mapping of workspace users to specific repository access permissions."""

    __tablename__ = "repository_members"

    __table_args__ = (
        UniqueConstraint("repository_id", "user_id", name="uq_repository_members_repo_user"),
        ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_repository_members_repository_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "workspace_id"],
            ["workspace_memberships.user_id", "workspace_memberships.workspace_id"],
            name="fk_repository_members_user_workspace",
            ondelete="CASCADE",
        ),
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
        index=True,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    role: Mapped[RepositoryMemberRole] = mapped_column(
        Enum(RepositoryMemberRole, name="repositorymemberrole", native_enum=False),
        default=RepositoryMemberRole.DEVELOPER,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    repository: Mapped["Repository"] = relationship(
        "Repository",
        back_populates="members",
        foreign_keys=[repository_id, workspace_id],
        overlaps="workspace",
    )
    user: Mapped["User"] = relationship(
        "User",
        back_populates="repository_memberships",
        primaryjoin="RepositoryMember.user_id == User.id",
        foreign_keys=[user_id],
    )

    def __repr__(self) -> str:
        return f"<RepositoryMember repo_id={self.repository_id} user_id={self.user_id} role={self.role}>"
