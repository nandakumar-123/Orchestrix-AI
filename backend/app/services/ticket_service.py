from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import TicketActivityType, TicketPriority, TicketStatus, utc_now
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.ticket import Ticket, TicketActivity

logger = logging.getLogger("orchestrix.services.tickets")

VALID_TICKET_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.OPEN: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.UNDER_REVIEW,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.IN_PROGRESS: {
        TicketStatus.OPEN,
        TicketStatus.UNDER_REVIEW,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.UNDER_REVIEW: {
        TicketStatus.OPEN,
        TicketStatus.IN_PROGRESS,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.RESOLVED: {
        TicketStatus.OPEN,
        TicketStatus.IN_PROGRESS,
        TicketStatus.CLOSED,
    },
    TicketStatus.CLOSED: {
        TicketStatus.OPEN,
        TicketStatus.IN_PROGRESS,
    },
}


class TicketService:
    """Manages workspace-scoped ticket lifecycle, assignment, status transitions, and audit activity."""

    @staticmethod
    async def create_ticket(
        db: AsyncSession,
        workspace_id: uuid.UUID,
        title: str,
        creator_id: uuid.UUID | None = None,
        description: str | None = None,
        priority: TicketPriority = TicketPriority.MEDIUM,
        repository_id: uuid.UUID | None = None,
        assignee_id: uuid.UUID | None = None,
        due_date: datetime | None = None,
        tags: list[str] | None = None,
    ) -> Ticket:
        # 1. Validate repository association if provided
        if repository_id:
            repo_stmt = select(Repository).where(
                Repository.id == repository_id,
                Repository.workspace_id == workspace_id,
                Repository.is_active.is_(True),
            )
            repo = (await db.execute(repo_stmt)).scalar_one_or_none()
            if not repo:
                raise ValueError(f"Repository {repository_id} does not exist or is inactive in this workspace")

        # 2. Validate assignee membership if provided
        if assignee_id:
            member_stmt = select(WorkspaceMembership).where(
                WorkspaceMembership.user_id == assignee_id,
                WorkspaceMembership.workspace_id == workspace_id,
            )
            member = (await db.execute(member_stmt)).scalar_one_or_none()
            if not member:
                raise ValueError(f"Assignee {assignee_id} is not a member of this workspace")

        # 3. Create ticket
        ticket = Ticket(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            repository_id=repository_id,
            title=title.strip(),
            description=description.strip() if description else None,
            priority=priority,
            status=TicketStatus.OPEN,
            creator_id=creator_id,
            assignee_id=assignee_id,
            due_date=due_date,
            tags=tags or [],
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.add(ticket)
        await db.flush()

        # 4. Record creation activity
        activity = TicketActivity(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            workspace_id=workspace_id,
            actor_id=creator_id,
            activity_type=TicketActivityType.CREATED,
            old_value=None,
            new_value=ticket.status.value,
            comment=f"Created ticket with priority {ticket.priority.value}",
            created_at=utc_now(),
        )
        db.add(activity)

        await db.commit()
        return await TicketService.get_ticket(db, workspace_id, ticket.id)  # type: ignore[return-value]

    @staticmethod
    async def list_tickets(
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID | None = None,
        status: TicketStatus | None = None,
        priority: TicketPriority | None = None,
        assignee_id: uuid.UUID | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Ticket], int]:
        filters: list[Any] = [Ticket.workspace_id == workspace_id]

        if repository_id:
            filters.append(Ticket.repository_id == repository_id)
        if status:
            filters.append(Ticket.status == status)
        if priority:
            filters.append(Ticket.priority == priority)
        if assignee_id:
            filters.append(Ticket.assignee_id == assignee_id)
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(or_(Ticket.title.ilike(term), Ticket.description.ilike(term)))

        # Count total
        count_stmt = select(func.count(Ticket.id)).where(*filters)
        total = (await db.execute(count_stmt)).scalar() or 0

        # Query items
        stmt = (
            select(Ticket)
            .where(*filters)
            .options(
                selectinload(Ticket.repository),
                selectinload(Ticket.creator),
                selectinload(Ticket.assignee),
            )
            .order_by(desc(Ticket.created_at))
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        items = list(result.scalars().all())
        return items, total

    @staticmethod
    async def get_ticket(
        db: AsyncSession,
        workspace_id: uuid.UUID,
        ticket_id: uuid.UUID,
    ) -> Ticket | None:
        stmt = (
            select(Ticket)
            .where(
                Ticket.id == ticket_id,
                Ticket.workspace_id == workspace_id,
            )
            .options(
                selectinload(Ticket.repository),
                selectinload(Ticket.creator),
                selectinload(Ticket.assignee),
                selectinload(Ticket.activities).selectinload(TicketActivity.actor),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def update_ticket(
        db: AsyncSession,
        workspace_id: uuid.UUID,
        ticket_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        title: str | None = None,
        description: str | None = None,
        priority: TicketPriority | None = None,
        repository_id: uuid.UUID | None = None,
        due_date: datetime | None = None,
        tags: list[str] | None = None,
    ) -> Ticket:
        ticket = await TicketService.get_ticket(db, workspace_id, ticket_id)
        if not ticket:
            raise LookupError(f"Ticket {ticket_id} not found in workspace")

        if repository_id is not None and repository_id != ticket.repository_id:
            repo_stmt = select(Repository).where(
                Repository.id == repository_id,
                Repository.workspace_id == workspace_id,
                Repository.is_active.is_(True),
            )
            repo = (await db.execute(repo_stmt)).scalar_one_or_none()
            if not repo:
                raise ValueError(f"Repository {repository_id} does not exist in workspace")
            ticket.repository_id = repository_id

        if title is not None:
            ticket.title = title.strip()
        if description is not None:
            ticket.description = description.strip() if description else None
        if due_date is not None:
            ticket.due_date = due_date
        if tags is not None:
            ticket.tags = tags

        if priority is not None and priority != ticket.priority:
            old_p = ticket.priority.value
            ticket.priority = priority
            act = TicketActivity(
                id=uuid.uuid4(),
                ticket_id=ticket.id,
                workspace_id=workspace_id,
                actor_id=actor_id,
                activity_type=TicketActivityType.PRIORITY_CHANGED,
                old_value=old_p,
                new_value=priority.value,
                comment=f"Priority updated from {old_p} to {priority.value}",
                created_at=utc_now(),
            )
            ticket.activities.append(act)
            db.add(act)

        ticket.updated_at = utc_now()
        await db.commit()
        db.expire(ticket, ["activities"])
        return await TicketService.get_ticket(db, workspace_id, ticket.id)  # type: ignore[return-value]

    @staticmethod
    async def update_ticket_status(
        db: AsyncSession,
        workspace_id: uuid.UUID,
        ticket_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        new_status: TicketStatus,
        comment: str | None = None,
    ) -> Ticket:
        ticket = await TicketService.get_ticket(db, workspace_id, ticket_id)
        if not ticket:
            raise LookupError(f"Ticket {ticket_id} not found in workspace")

        old_status = ticket.status.value
        if new_status == ticket.status:
            raise ValueError(f"Ticket is already in '{ticket.status.value}' status")

        allowed_next = VALID_TICKET_TRANSITIONS.get(ticket.status, set())
        if new_status not in allowed_next:
            allowed_str = ", ".join(sorted(s.value for s in allowed_next))
            raise ValueError(
                f"Invalid status transition from '{ticket.status.value}' to '{new_status.value}'. "
                f"Allowed transitions: {allowed_str or 'none'}"
            )

        ticket.status = new_status
        ticket.updated_at = utc_now()

        if new_status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
            ticket.resolved_at = utc_now()
        elif new_status in (TicketStatus.OPEN, TicketStatus.IN_PROGRESS):
            ticket.resolved_at = None

        activity = TicketActivity(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            activity_type=TicketActivityType.STATUS_CHANGED,
            old_value=old_status,
            new_value=new_status.value,
            comment=comment or f"Status changed from {old_status} to {new_status.value}",
            created_at=utc_now(),
        )
        ticket.activities.append(activity)
        db.add(activity)
        await db.commit()
        db.expire(ticket, ["activities"])
        return await TicketService.get_ticket(db, workspace_id, ticket.id)  # type: ignore[return-value]

    @staticmethod
    async def assign_ticket(
        db: AsyncSession,
        workspace_id: uuid.UUID,
        ticket_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        assignee_id: uuid.UUID | None,
        comment: str | None = None,
    ) -> Ticket:
        ticket = await TicketService.get_ticket(db, workspace_id, ticket_id)
        if not ticket:
            raise LookupError(f"Ticket {ticket_id} not found in workspace")

        old_assignee_id = ticket.assignee_id
        assignee_name = None

        if assignee_id:
            member_stmt = (
                select(WorkspaceMembership)
                .options(selectinload(WorkspaceMembership.user))
                .where(
                    WorkspaceMembership.user_id == assignee_id,
                    WorkspaceMembership.workspace_id == workspace_id,
                )
            )
            member = (await db.execute(member_stmt)).scalar_one_or_none()
            if not member:
                raise ValueError(f"User {assignee_id} is not a member of this workspace")
            assignee_name = member.user.full_name or member.user.email if member.user else str(assignee_id)

        ticket.assignee_id = assignee_id
        ticket.updated_at = utc_now()

        activity_msg = (
            f"Assigned to {assignee_name}" if assignee_id else "Unassigned ticket"
        )
        if comment:
            activity_msg += f": {comment}"

        activity = TicketActivity(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            activity_type=TicketActivityType.ASSIGNED,
            old_value=str(old_assignee_id) if old_assignee_id else None,
            new_value=str(assignee_id) if assignee_id else None,
            comment=activity_msg,
            created_at=utc_now(),
        )
        ticket.activities.append(activity)
        db.add(activity)
        await db.commit()
        db.expire(ticket, ["activities"])
        return await TicketService.get_ticket(db, workspace_id, ticket.id)  # type: ignore[return-value]

    @staticmethod
    async def add_comment(
        db: AsyncSession,
        workspace_id: uuid.UUID,
        ticket_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        comment_text: str,
    ) -> TicketActivity:
        ticket = await TicketService.get_ticket(db, workspace_id, ticket_id)
        if not ticket:
            raise LookupError(f"Ticket {ticket_id} not found in workspace")

        clean_comment = comment_text.strip()
        if not clean_comment:
            raise ValueError("Comment cannot be empty")

        activity = TicketActivity(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            activity_type=TicketActivityType.COMMENTED,
            old_value=None,
            new_value=None,
            comment=clean_comment,
            created_at=utc_now(),
        )
        db.add(activity)
        ticket.updated_at = utc_now()
        await db.commit()
        await db.refresh(activity)
        return activity
