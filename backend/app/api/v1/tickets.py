from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    enforce_csrf_protection,
    get_current_user,
    require_workspace_membership,
)
from app.api.v1.schemas_tickets import (
    TicketActivityItem,
    TicketAssignRequest,
    TicketCommentRequest,
    TicketCreateRequest,
    TicketListResponse,
    TicketResponse,
    TicketStatusUpdateRequest,
    TicketUpdateRequest,
)
from app.db.base import TicketPriority, TicketStatus, WorkspaceRole
from app.db.models.membership import WorkspaceMembership
from app.db.models.ticket import Ticket
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.auth import verify_workspace_membership
from app.services.ticket_service import TicketService

logger = logging.getLogger("orchestrix.api.tickets")

tickets_router = APIRouter(prefix="/tickets", tags=["tickets"])


def _format_ticket_response(ticket: Ticket) -> TicketResponse:
    activities: list[TicketActivityItem] = []
    ticket_activities = getattr(ticket, "activities", None) or []
    for a in ticket_activities:
        actor = getattr(a, "actor", None)
        actor_name = actor.full_name if actor is not None else None
        actor_email = actor.email if actor is not None else None
        activities.append(
            TicketActivityItem(
                id=a.id,
                ticket_id=a.ticket_id,
                workspace_id=a.workspace_id,
                actor_id=a.actor_id,
                actor_name=actor_name,
                actor_email=actor_email,
                activity_type=a.activity_type,
                old_value=a.old_value,
                new_value=a.new_value,
                comment=a.comment,
                created_at=a.created_at,
            )
        )

    repo = getattr(ticket, "repository", None)
    repo_name = repo.name if repo is not None else None

    creator = getattr(ticket, "creator", None)
    creator_name = creator.full_name if creator is not None else None
    creator_email = creator.email if creator is not None else None

    assignee = getattr(ticket, "assignee", None)
    assignee_name = assignee.full_name if assignee is not None else None
    assignee_email = assignee.email if assignee is not None else None

    return TicketResponse(
        id=ticket.id,
        workspace_id=ticket.workspace_id,
        repository_id=ticket.repository_id,
        repository_name=repo_name,
        title=ticket.title,
        description=ticket.description,
        priority=ticket.priority,
        status=ticket.status,
        creator_id=ticket.creator_id,
        creator_name=creator_name,
        creator_email=creator_email,
        assignee_id=ticket.assignee_id,
        assignee_name=assignee_name,
        assignee_email=assignee_email,
        due_date=ticket.due_date,
        tags=ticket.tags or [],
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        resolved_at=ticket.resolved_at,
        activities=activities,
    )


@tickets_router.get(
    "",
    response_model=TicketListResponse,
    status_code=status.HTTP_200_OK,
    summary="List tickets for a workspace",
)
async def list_tickets(
    workspace_id: Annotated[uuid.UUID, Query(description="Workspace tenant identifier")],
    repository_id: Annotated[uuid.UUID | None, Query(description="Filter by repository")] = None,
    status: Annotated[TicketStatus | None, Query(description="Filter by ticket status")] = None,
    priority: Annotated[TicketPriority | None, Query(description="Filter by priority")] = None,
    assignee_id: Annotated[uuid.UUID | None, Query(description="Filter by assignee")] = None,
    search: Annotated[str | None, Query(description="Search in title or description")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> TicketListResponse:
    """Retrieve paginated tickets scoped to a workspace with optional filters."""
    items, total = await TicketService.list_tickets(
        db,
        workspace_id=workspace_id,
        repository_id=repository_id,
        status=status,
        priority=priority,
        assignee_id=assignee_id,
        search=search,
        limit=limit,
        offset=offset,
    )
    return TicketListResponse(
        items=[_format_ticket_response(t) for t in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@tickets_router.post(
    "",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new workspace ticket",
)
async def create_ticket(
    payload: TicketCreateRequest,
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
) -> TicketResponse:
    """Create a new ticket in the workspace."""
    await verify_workspace_membership(
        db=db,
        user_id=current_user.id,
        workspace_id=payload.workspace_id,
        min_role=WorkspaceRole.MEMBER,
    )
    try:
        ticket = await TicketService.create_ticket(
            db,
            workspace_id=payload.workspace_id,
            title=payload.title,
            creator_id=current_user.id,
            description=payload.description,
            priority=payload.priority,
            repository_id=payload.repository_id,
            assignee_id=payload.assignee_id,
            due_date=payload.due_date,
            tags=payload.tags,
        )
        return _format_ticket_response(ticket)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        ) from val_err


@tickets_router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    status_code=status.HTTP_200_OK,
    summary="Get ticket details and activity history",
)
async def get_ticket(
    ticket_id: uuid.UUID,
    workspace_id: Annotated[uuid.UUID, Query(description="Workspace tenant identifier")],
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> TicketResponse:
    """Retrieve detailed ticket with complete activity audit trail."""
    ticket = await TicketService.get_ticket(db, workspace_id, ticket_id)
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket {ticket_id} not found in workspace",
        )
    return _format_ticket_response(ticket)


@tickets_router.patch(
    "/{ticket_id}",
    response_model=TicketResponse,
    status_code=status.HTTP_200_OK,
    summary="Update ticket metadata",
)
async def update_ticket(
    ticket_id: uuid.UUID,
    payload: TicketUpdateRequest,
    workspace_id: Annotated[uuid.UUID, Query(description="Workspace tenant identifier")],
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
) -> TicketResponse:
    """Update ticket attributes."""
    try:
        ticket = await TicketService.update_ticket(
            db,
            workspace_id=workspace_id,
            ticket_id=ticket_id,
            actor_id=current_user.id,
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            repository_id=payload.repository_id,
            due_date=payload.due_date,
            tags=payload.tags,
        )
        return _format_ticket_response(ticket)
    except LookupError as lookup_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(lookup_err),
        ) from lookup_err
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        ) from val_err


@tickets_router.post(
    "/{ticket_id}/status",
    response_model=TicketResponse,
    status_code=status.HTTP_200_OK,
    summary="Update ticket status lifecycle",
)
async def update_ticket_status(
    ticket_id: uuid.UUID,
    payload: TicketStatusUpdateRequest,
    workspace_id: Annotated[uuid.UUID, Query(description="Workspace tenant identifier")],
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
) -> TicketResponse:
    """Transition ticket to a new lifecycle status with optional transition reason."""
    try:
        ticket = await TicketService.update_ticket_status(
            db,
            workspace_id=workspace_id,
            ticket_id=ticket_id,
            actor_id=current_user.id,
            new_status=payload.status,
            comment=payload.comment,
        )
        return _format_ticket_response(ticket)
    except LookupError as lookup_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(lookup_err),
        ) from lookup_err
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        ) from val_err


@tickets_router.post(
    "/{ticket_id}/assign",
    response_model=TicketResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign or reassign ticket",
)
async def assign_ticket(
    ticket_id: uuid.UUID,
    payload: TicketAssignRequest,
    workspace_id: Annotated[uuid.UUID, Query(description="Workspace tenant identifier")],
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
) -> TicketResponse:
    """Assign ticket to a member of the workspace or unassign."""
    try:
        ticket = await TicketService.assign_ticket(
            db,
            workspace_id=workspace_id,
            ticket_id=ticket_id,
            actor_id=current_user.id,
            assignee_id=payload.assignee_id,
            comment=payload.comment,
        )
        return _format_ticket_response(ticket)
    except LookupError as lookup_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(lookup_err),
        ) from lookup_err
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        ) from val_err


@tickets_router.post(
    "/{ticket_id}/comments",
    response_model=TicketActivityItem,
    status_code=status.HTTP_201_CREATED,
    summary="Add a comment to ticket activity trail",
)
async def add_ticket_comment(
    ticket_id: uuid.UUID,
    payload: TicketCommentRequest,
    workspace_id: Annotated[uuid.UUID, Query(description="Workspace tenant identifier")],
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.MEMBER)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
) -> TicketActivityItem:
    """Add a discussion or review comment to the ticket activity thread."""
    try:
        activity = await TicketService.add_comment(
            db,
            workspace_id=workspace_id,
            ticket_id=ticket_id,
            actor_id=current_user.id,
            comment_text=payload.comment,
        )
        return TicketActivityItem(
            id=activity.id,
            ticket_id=activity.ticket_id,
            workspace_id=activity.workspace_id,
            actor_id=activity.actor_id,
            actor_name=current_user.full_name,
            actor_email=current_user.email,
            activity_type=activity.activity_type,
            old_value=activity.old_value,
            new_value=activity.new_value,
            comment=activity.comment,
            created_at=activity.created_at,
        )
    except LookupError as lookup_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(lookup_err),
        ) from lookup_err
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        ) from val_err
