import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.base import RepositoryMemberRole, TaskPriority, TaskStatus, TaskType

# -----------------------------------------------------------------------------
# Common Schemas
# -----------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Health check response payload schema."""

    status: str = Field(..., description="Service status indicator")
    app: str = Field(..., description="Application name")
    environment: str = Field(..., description="Current environment")
    version: str = Field(..., description="API version")


class DatabaseHealthResponse(BaseModel):
    """Database connectivity health check response schema."""

    status: str = Field(..., description="Database status: healthy or unavailable")
    database: str = Field(..., description="Database engine type (e.g. postgresql)")
    connected: bool = Field(..., description="Whether ping was successful")


# -----------------------------------------------------------------------------
# Repository Schemas
# -----------------------------------------------------------------------------


class RepositoryCreate(BaseModel):
    """Payload to register a new repository to a workspace."""

    workspace_id: uuid.UUID
    installation_id: uuid.UUID
    github_repository_id: int
    name: str = Field(..., max_length=255)
    full_name: str = Field(..., max_length=512)
    owner_login: str = Field(..., max_length=255)
    description: str | None = None
    default_branch: str = Field(default="main", max_length=100)
    html_url: str = Field(..., max_length=1024)
    visibility: str = Field(default="private", max_length=20)
    language: str | None = Field(default=None, max_length=100)


class RepositoryUpdate(BaseModel):
    """Payload to update repository metadata."""

    description: str | None = None
    default_branch: str | None = Field(default=None, max_length=100)
    html_url: str | None = Field(default=None, max_length=1024)
    visibility: str | None = Field(default=None, max_length=20)
    language: str | None = Field(default=None, max_length=100)


class RepositoryResponse(BaseModel):
    """Response payload for a repository entity."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    installation_id: uuid.UUID
    github_repository_id: int
    name: str
    full_name: str
    owner_login: str
    description: str | None = None
    default_branch: str
    html_url: str
    visibility: str
    language: str | None = None
    is_active: bool
    last_indexed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RepositoryListResponse(BaseModel):
    """Paginated list of repositories."""

    items: list[RepositoryResponse]
    total: int
    limit: int
    offset: int


# -----------------------------------------------------------------------------
# Repository Member Schemas
# -----------------------------------------------------------------------------


class RepositoryMemberCreate(BaseModel):
    """Payload to assign a workspace user to a repository."""

    user_id: uuid.UUID
    role: RepositoryMemberRole = RepositoryMemberRole.DEVELOPER


class RepositoryMemberResponse(BaseModel):
    """Response payload for a repository member entity."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    repository_id: uuid.UUID
    user_id: uuid.UUID
    role: RepositoryMemberRole
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------------------------------------------
# Engineering Task Schemas
# -----------------------------------------------------------------------------


class EngineeringTaskCreate(BaseModel):
    """Payload to create an engineering task."""

    workspace_id: uuid.UUID
    repository_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    title: str = Field(..., max_length=512)
    description: str | None = None
    task_type: TaskType = TaskType.GENERAL
    priority: TaskPriority = TaskPriority.MEDIUM
    assigned_agent: str | None = Field(default=None, max_length=100)
    external_issue_id: str | None = Field(default=None, max_length=255)


class EngineeringTaskUpdate(BaseModel):
    """Payload to update task status or assignment."""

    status: TaskStatus | None = None
    assigned_agent: str | None = Field(default=None, max_length=100)


class EngineeringTaskResponse(BaseModel):
    """Response payload for an engineering task."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    repository_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    title: str
    description: str | None = None
    task_type: TaskType
    priority: TaskPriority
    status: TaskStatus
    assigned_agent: str | None = None
    external_issue_id: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class EngineeringTaskListResponse(BaseModel):
    """Paginated list of engineering tasks."""

    items: list[EngineeringTaskResponse]
    total: int
    limit: int
    offset: int
