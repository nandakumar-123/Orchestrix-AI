import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.base import (
    RepositoryMemberRole,
    TaskPriority,
    TaskStatus,
    TaskType,
    WorkspaceRole,
)

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


# -----------------------------------------------------------------------------
# Authentication & User Schemas
# -----------------------------------------------------------------------------


class UserWorkspaceMembershipResponse(BaseModel):
    """User membership within a workspace."""

    workspace_id: uuid.UUID
    name: str
    slug: str
    role: WorkspaceRole

    model_config = ConfigDict(from_attributes=True)


class CurrentUserResponse(BaseModel):
    """Current authenticated user profile schema."""

    id: uuid.UUID
    email: str
    full_name: str | None = None
    avatar_url: str | None = None
    email_verified: bool = False
    workspaces: list[UserWorkspaceMembershipResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class LogoutResponse(BaseModel):
    """Logout response schema."""

    status: str = "ok"
    message: str = "Successfully logged out"


class CsrfTokenResponse(BaseModel):
    """CSRF token response schema."""

    csrf_token: str


# -----------------------------------------------------------------------------
# GitHub Integration Schemas
# -----------------------------------------------------------------------------


class GitHubConnectUrlResponse(BaseModel):
    """Payload returning authorization URL to initiate GitHub OAuth."""

    auth_url: str
    state: str


class GitHubStatusResponse(BaseModel):
    """Payload representing connected GitHub account status."""

    connected: bool
    github_login: str | None = None
    name: str | None = None
    avatar_url: str | None = None
    html_url: str | None = None
    scope: str | None = None
    connected_at: datetime | None = None


class GitHubRepositoryItem(BaseModel):
    """Accessible GitHub repository metadata."""

    id: int
    name: str
    full_name: str
    owner_login: str
    owner_avatar_url: str | None = None
    description: str | None = None
    default_branch: str = "main"
    html_url: str
    visibility: str = "public"
    language: str | None = None
    updated_at: str | None = None
    stargazers_count: int = 0
    forks_count: int = 0
    open_issues_count: int = 0
    is_connected: bool = False


class GitHubRepositoryListResponse(BaseModel):
    """List of accessible repositories returned from GitHub."""

    items: list[GitHubRepositoryItem]
    page: int
    per_page: int


class ConnectRepositoryPayload(BaseModel):
    """Payload to connect an accessible GitHub repository to a workspace."""

    workspace_id: uuid.UUID
    github_repository_id: int
    name: str = Field(..., max_length=255)
    full_name: str = Field(..., max_length=512)
    owner_login: str = Field(..., max_length=255)
    description: str | None = None
    default_branch: str = Field(default="main", max_length=100)
    html_url: str = Field(..., max_length=1024)
    visibility: str = Field(default="private", max_length=20)
    language: str | None = Field(default=None, max_length=100)


class GitHubDisconnectResponse(BaseModel):
    """Response payload after disconnecting GitHub account."""

    status: str = "ok"
    message: str = "GitHub account disconnected"


# -----------------------------------------------------------------------------
# Repository Intelligence & Structural Indexing Schemas
# -----------------------------------------------------------------------------


class IndexingJobResponse(BaseModel):
    """Repository intelligence indexing job status."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    repository_id: uuid.UUID
    commit_sha: str
    branch: str
    status: str
    progress_percent: int
    current_step: str
    files_count: int
    symbols_count: int
    dependencies_count: int
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IndexingJobListResponse(BaseModel):
    """List of indexing jobs for a repository."""

    jobs: list[IndexingJobResponse]
    total: int


class SupportedLanguageCapability(BaseModel):
    """Extraction capabilities and platform availability for a programming language."""

    name: str
    package_name: str
    available: bool
    extensions: list[str]


class SupportedLanguagesResponse(BaseModel):
    """List of all registered languages and parser capabilities."""

    total_supported: int
    languages: list[SupportedLanguageCapability]


class RepositoryIntelligenceResponse(BaseModel):
    """Repository structural intelligence overview."""

    repository_id: uuid.UUID
    workspace_id: uuid.UUID
    commit_sha: str | None = None
    branch: str | None = None
    total_files: int = 0
    total_lines: int = 0
    total_bytes: int = 0
    total_symbols: int = 0
    total_dependencies: int = 0
    languages_summary: dict[str, Any] | None = None
    structure_summary: dict[str, Any] | None = None
    entry_points: list[str] | None = None
    detected_frameworks: list[str] = Field(default_factory=list)
    last_indexed_at: datetime | None = None


class RepositoryFileResponse(BaseModel):
    """Metadata for an indexed file in a repository."""

    id: uuid.UUID
    path: str
    file_name: str
    extension: str
    language: str | None = None
    size_bytes: int
    line_count: int
    is_manifest: bool

    model_config = ConfigDict(from_attributes=True)


class RepositoryFilesListResponse(BaseModel):
    """Paginated list of repository files."""

    files: list[RepositoryFileResponse]
    total: int


class CodeSymbolResponse(BaseModel):
    """Extracted code symbol (function, class, method)."""

    id: uuid.UUID
    file_path: str
    name: str
    symbol_type: str
    language: str
    start_line: int
    end_line: int
    signature: str | None = None
    parent_symbol_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CodeSymbolListResponse(BaseModel):
    """Paginated list of code symbols."""

    symbols: list[CodeSymbolResponse]
    total: int


class FileDependencyResponse(BaseModel):
    """Extracted dependency specification."""

    id: uuid.UUID
    source_file_path: str
    name: str
    version_spec: str | None = None
    dependency_type: str
    package_manager: str | None = None
    is_external: bool

    model_config = ConfigDict(from_attributes=True)


class FileDependencyListResponse(BaseModel):
    """Paginated list of dependencies."""

    dependencies: list[FileDependencyResponse]
    total: int
