import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now


class OAuthTransaction(Base):
    """
    Server-side one-time OAuth 2.0 PKCE transaction.
    Stores cryptographically protected lookup hash (bound to browser cookie),
    state hash, nonce, and PKCE code verifier with atomic one-time consumption.
    """

    __tablename__ = "oauth_transactions"

    __table_args__ = (
        Index("ix_oauth_transactions_lookup_hash", "lookup_hash", unique=True),
        Index("ix_oauth_transactions_state_hash", "state_hash"),
        Index("ix_oauth_transactions_expires_at", "expires_at"),
        Index("ix_oauth_transactions_consumed_at", "consumed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    lookup_hash: Mapped[str] = mapped_column(
        String(64),  # SHA-256 hex digest of browser-binding secret
        nullable=False,
    )
    state_hash: Mapped[str] = mapped_column(
        String(64),  # SHA-256 hex digest of OAuth state
        nullable=False,
    )
    nonce: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    code_verifier: Mapped[str] = mapped_column(
        String(255),
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

    def __repr__(self) -> str:
        return f"<OAuthTransaction id={self.id} consumed={self.consumed_at is not None}>"
