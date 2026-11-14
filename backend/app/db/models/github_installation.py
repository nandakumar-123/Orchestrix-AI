import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.repository import Repository
    from app.db.models.workspace import Workspace


class GitHubInstallation(Base):
    """GitHub App installation metadata bound to a workspace."""

    __tablename__ = "github_installations"

    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_github_installations_id_workspace"),
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
    installation_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
        nullable=False,
    )
    account_login: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    account_type: Mapped[str] = mapped_column(
        String(50),  # "User" or "Organization"
        nullable=False,
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
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
    workspace: Mapped["Workspace"] = relationship(
        "Workspace",
        back_populates="github_installations",
    )
    repositories: Mapped[list["Repository"]] = relationship(
        "Repository",
        back_populates="installation",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<GitHubInstallation id={self.id} installation_id={self.installation_id} account={self.account_login}>"
