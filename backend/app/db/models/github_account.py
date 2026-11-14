import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.user import User


class GitHubAccount(Base):
    """
    Connected GitHub user account and encrypted OAuth access credentials.
    Belongs to an authenticated User (one-to-one).
    """

    __tablename__ = "github_accounts"

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_github_accounts_user_id"),
        Index("ix_github_accounts_user_id", "user_id"),
        Index("ix_github_accounts_github_user_id", "github_user_id"),
        Index("ix_github_accounts_github_login", "github_login"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    github_user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    github_login: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    avatar_url: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    html_url: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    encrypted_access_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    token_type: Mapped[str] = mapped_column(
        String(50),
        default="bearer",
        nullable=False,
    )
    scope: Mapped[str | None] = mapped_column(
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

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="github_account")

    def __repr__(self) -> str:
        return f"<GitHubAccount id={self.id} login={self.github_login} user_id={self.user_id}>"
