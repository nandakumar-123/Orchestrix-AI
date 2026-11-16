from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    TicketActivityType,
    TicketPriority,
    TicketStatus,
    utc_now,
)

if TYPE_CHECKING:
    from app.db.models.repository import Repository
    from app.db.models.user import User
    from app.db.models.workspace import Workspace


class Ticket(Base):
    """Production ticket / issue entity scoped to a workspace and optional repository."""

    __tablename__ = "tickets"

    __table_args__ = (
        ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_tickets_repository_workspace",
            ondelete="SET NULL",
        ),
        Index("ix_tickets_workspace_id", "workspace_id"),
        Index("ix_tickets_repository_id", "repository_id"),
        Index("ix_tickets_status", "status"),
        Index("ix_tickets_priority", "priority"),
        Index("ix_tickets_created_at", "created_at"),
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
        nullable=True,
    )
    title: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    priority: Mapped[TicketPriority] = mapped_column(
        Enum(TicketPriority, name="ticketpriority", native_enum=False),
        default=TicketPriority.MEDIUM,
        nullable=False,
    )
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticketstatus", native_enum=False),
        default=TicketStatus.OPEN,
        nullable=False,
    )
    creator_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    tags: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
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
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    workspace: Mapped[Workspace] = relationship(
        "Workspace",
        back_populates="tickets",
    )
    repository: Mapped[Repository | None] = relationship(
        "Repository",
        foreign_keys=[repository_id, workspace_id],
        overlaps="workspace,tickets",
    )
    creator: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[creator_id],
    )
    assignee: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[assignee_id],
    )
    activities: Mapped[list[TicketActivity]] = relationship(
        "TicketActivity",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="desc(TicketActivity.created_at)",
    )

    def __repr__(self) -> str:
        return f"<Ticket id={self.id} title={self.title} status={self.status}>"


class TicketActivity(Base):
    """Audit and activity log tracking lifecycle events and comments on a ticket."""

    __tablename__ = "ticket_activities"

    __table_args__ = (
        Index("ix_ticket_activities_ticket_id", "ticket_id"),
        Index("ix_ticket_activities_workspace_id", "workspace_id"),
        Index("ix_ticket_activities_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    activity_type: Mapped[TicketActivityType] = mapped_column(
        Enum(TicketActivityType, name="ticketactivitytype", native_enum=False),
        nullable=False,
    )
    old_value: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    new_value: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    ticket: Mapped[Ticket] = relationship(
        "Ticket",
        back_populates="activities",
    )
    actor: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[actor_id],
    )

    def __repr__(self) -> str:
        return f"<TicketActivity id={self.id} ticket_id={self.ticket_id} type={self.activity_type}>"
