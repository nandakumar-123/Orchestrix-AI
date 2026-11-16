from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.base import TicketActivityType, TicketPriority, TicketStatus


class TicketCreateRequest(BaseModel):
    workspace_id: uuid.UUID = Field(..., description="Workspace ID")
    title: str = Field(..., min_length=1, max_length=512, description="Ticket title")
    description: str | None = Field(default=None, description="Detailed ticket description")
    priority: TicketPriority = Field(default=TicketPriority.MEDIUM, description="Priority level")
    repository_id: uuid.UUID | None = Field(default=None, description="Optional repository association")
    assignee_id: uuid.UUID | None = Field(default=None, description="Optional assignee user ID")
    due_date: datetime | None = Field(default=None, description="Optional target completion date")
    tags: list[str] = Field(default_factory=list, description="Categorization tags")


class TicketUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = None
    priority: TicketPriority | None = None
    repository_id: uuid.UUID | None = None
    due_date: datetime | None = None
    tags: list[str] | None = None


class TicketStatusUpdateRequest(BaseModel):
    status: TicketStatus = Field(..., description="New lifecycle status")
    comment: str | None = Field(default=None, description="Optional transition note or rationale")


class TicketAssignRequest(BaseModel):
    assignee_id: uuid.UUID | None = Field(..., description="Assigned user ID, or null to unassign")
    comment: str | None = Field(default=None, description="Optional assignment comment")


class TicketCommentRequest(BaseModel):
    comment: str = Field(..., min_length=1, description="Comment message")


class TicketActivityItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    workspace_id: uuid.UUID
    actor_id: uuid.UUID | None = None
    actor_name: str | None = None
    actor_email: str | None = None
    activity_type: TicketActivityType
    old_value: str | None = None
    new_value: str | None = None
    comment: str | None = None
    created_at: datetime


class TicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    repository_id: uuid.UUID | None = None
    repository_name: str | None = None
    title: str
    description: str | None = None
    priority: TicketPriority
    status: TicketStatus
    creator_id: uuid.UUID | None = None
    creator_name: str | None = None
    creator_email: str | None = None
    assignee_id: uuid.UUID | None = None
    assignee_name: str | None = None
    assignee_email: str | None = None
    due_date: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    activities: list[TicketActivityItem] = Field(default_factory=list)


class TicketListResponse(BaseModel):
    items: list[TicketResponse]
    total: int
    limit: int
    offset: int
