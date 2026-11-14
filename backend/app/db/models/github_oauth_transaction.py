import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.user import User


class GitHubOAuthTransaction(Base):
    """
    Server-side one-time GitHub OAuth 2.0 transaction.
    Binds the OAuth flow to the initiating Orchestrix user and browser session.
    Provides atomic single-use consumption and replay protection.
    """

    __tablename__ = "github_oauth_transactions"

    __table_args__ = (
        Index("ix_gh_oauth_trx_lookup_hash", "lookup_hash", unique=True),
        Index("ix_gh_oauth_trx_state_hash", "state_hash"),
        Index("ix_gh_oauth_trx_user_id", "user_id"),
        Index("ix_gh_oauth_trx_expires_at", "expires_at"),
        Index("ix_gh_oauth_trx_consumed_at", "consumed_at"),
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
    )
    lookup_hash: Mapped[str] = mapped_column(
        String(64),  # SHA-256 hex digest of browser secret
        nullable=False,
    )
    state_hash: Mapped[str] = mapped_column(
        String(64),  # SHA-256 hex digest of OAuth state
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    user: Mapped["User"] = relationship("User", lazy="raise")

    def __repr__(self) -> str:
        return (
            f"<GitHubOAuthTransaction id={self.id} user_id={self.user_id} "
            f"consumed={self.consumed_at is not None}>"
        )
