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
    category: str = "general"
    extraction_mode: str = "validated"
    adapter_name: str = ""


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


# -----------------------------------------------------------------------------
# Semantic Code Intelligence & Retrieval Schemas
# -----------------------------------------------------------------------------


class SemanticIndexRequest(BaseModel):
    """Payload to trigger semantic indexing for a repository snapshot."""

    snapshot_id: uuid.UUID | None = Field(
        default=None, description="Target snapshot ID (defaults to latest if omitted)"
    )
    force_reembed: bool = Field(
        default=False, description="Whether to invalidate and re-embed all content"
    )


class SemanticIndexStatusResponse(BaseModel):
    """Status of semantic indexing for a repository snapshot."""

    repository_id: uuid.UUID
    snapshot_id: uuid.UUID | None
    provider_name: str
    model_name: str
    dimension: int
    total_chunks: int
    status: str  # "pending", "indexing", "completed", "failed", "unindexed"
    error_message: str | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SemanticSearchRequest(BaseModel):
    """Natural-language semantic and hybrid code search query payload."""

    query: str = Field(
        ..., min_length=2, max_length=1000, description="Natural language search query"
    )
    snapshot_id: uuid.UUID | None = Field(default=None, description="Filter by snapshot ID")
    language: str | None = Field(default=None, description="Filter by programming language")
    symbol_type: str | None = Field(
        default=None, description="Filter by symbol type (e.g. function, class)"
    )
    file_path_prefix: str | None = Field(default=None, description="Filter by path prefix")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of results to return")


class SemanticSearchResultItem(BaseModel):
    """Individual retrieved code chunk result."""

    chunk_id: uuid.UUID
    repository_id: uuid.UUID
    repository_name: str
    snapshot_id: uuid.UUID
    file_path: str
    language: str
    symbol_name: str | None = None
    symbol_type: str | None = None
    parent_symbol_name: str | None = None
    start_line: int
    end_line: int
    source_code_excerpt: str
    similarity_score: float
    vector_score: float
    lexical_score: float
    symbol_score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticSearchResponse(BaseModel):
    """Response containing ranked retrieved code chunks."""

    repository_id: uuid.UUID
    query: str
    total_results: int
    results: list[SemanticSearchResultItem]


class SemanticChunkDetailResponse(BaseModel):
    """Full detail of an individual semantic code chunk."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    repository_id: uuid.UUID
    snapshot_id: uuid.UUID
    file_id: uuid.UUID
    file_path: str
    language: str
    symbol_name: str | None = None
    symbol_type: str | None = None
    parent_symbol_name: str | None = None
    start_line: int
    end_line: int
    chunk_index: int
    content: str
    content_hash: str
    metadata: dict[str, Any] | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssembledContextRequest(BaseModel):
    """Request to assemble structured AI agent context from search query."""

    query: str = Field(..., min_length=2, max_length=1000)
    snapshot_id: uuid.UUID | None = None
    language: str | None = None
    limit: int = Field(default=8, ge=1, le=25)
    max_characters: int = Field(default=32000, ge=1000, le=100000)


class AssembledCodeBlockResponse(BaseModel):
    """Individual assembled code block."""

    file_path: str
    language: str
    start_line: int
    end_line: int
    symbol_name: str | None = None
    symbol_type: str | None = None
    parent_symbol_name: str | None = None
    code: str
    similarity_score: float


class AssembledContextResponse(BaseModel):
    """Context assembly response payload for agent consumption."""

    repository_id: uuid.UUID
    repository_name: str
    query: str
    total_chunks_retrieved: int
    total_blocks_included: int
    total_characters: int
    estimated_tokens: int
    formatted_context_markdown: str
    blocks: list[AssembledCodeBlockResponse]


# -----------------------------------------------------------------------------
# Knowledge Graph & Code Relationship Schemas
# -----------------------------------------------------------------------------


class GraphNodeResponse(BaseModel):
    """Representation of a node in the code knowledge graph."""

    id: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeResponse(BaseModel):
    """Representation of an edge/relationship in the code knowledge graph."""

    source_id: str
    target_id: str
    type: str
    properties: dict[str, Any] = Field(default_factory=dict)


class SubgraphResponse(BaseModel):
    """Subgraph containing matched nodes and interconnecting edges."""

    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]
    total_nodes: int
    total_edges: int


class GraphIndexTriggerRequest(BaseModel):
    """Request to initiate or re-run knowledge graph extraction."""

    snapshot_id: uuid.UUID
    force_reindex: bool = False


class GraphIndexStatusResponse(BaseModel):
    """Status of knowledge graph indexing for a repository snapshot."""

    status: str
    snapshot_id: uuid.UUID
    provider: str
    total_nodes: int
    total_relationships: int
    indexed_at: str | None = None


class GraphQueryRequest(BaseModel):
    """Request for targeted structural graph queries."""

    query_type: str = Field(
        ...,
        description="Type of graph query: callers, implementations, importing_files, dependencies, circular_dependencies, or path",
    )
    snapshot_id: uuid.UUID | None = None
    target_id: str | None = None
    source_id: str | None = None
    file_path: str | None = None
    direction: str = "outgoing"
    max_depth: int = Field(default=3, ge=1, le=5)


class GraphQueryResponse(BaseModel):
    """Results of a structural graph query."""

    query_type: str
    count: int
    results: Any


class ImpactPreviewRequest(BaseModel):
    """Request to evaluate the blast radius of a file or symbol change."""

    snapshot_id: uuid.UUID | None = None
    file_path: str | None = None
    symbol_name: str | None = None
    symbol_id: str | None = None
    max_depth: int = Field(default=3, ge=1, le=5)


class ImpactPreviewResponse(BaseModel):
    """
    Blast Radius & Structural Exposure Score for proposed code modifications.

    Note: The score (0.0 to 100.0) and tiers (LOW, MEDIUM, HIGH, CRITICAL) represent
    a heuristic structural exposure metric based on graph topology, dependency depth,
    callers, exposed public routes, and test verification. It is NOT an empirical or
    statistical regression prediction.
    """

    target_id: str
    target_name: str
    target_type: str
    risk_level: str = Field(..., description="Exposure tier: LOW | MEDIUM | HIGH | CRITICAL")
    risk_score: float = Field(
        ..., description="Blast Radius & Structural Exposure Score (0.0 to 100.0)"
    )
    score_type: str = Field(
        default="heuristic_structural_exposure", description="Classification of metric"
    )
    score_label: str = Field(
        default="Blast Radius & Structural Exposure Score", description="Human-readable score label"
    )
    reasons: list[str]
    direct_dependents: list[dict[str, Any]]
    indirect_dependents: list[dict[str, Any]]
    affected_endpoints: list[dict[str, Any]]
    affected_tests: list[dict[str, Any]]
    affected_database_models: list[dict[str, Any]]
    subgraph: SubgraphResponse


class IntelligenceSearchRequest(BaseModel):
    """Request for unified hybrid semantic + knowledge graph code search."""

    query: str = Field(..., min_length=2, max_length=1000)
    snapshot_id: uuid.UUID | None = None
    language: str | None = None
    symbol_type: str | None = None
    file_path_prefix: str | None = None
    limit: int = Field(default=15, ge=1, le=50)
    top_k: int = Field(default=10, ge=1, le=50)
    include_graph_enrichment: bool = True



# =============================================================================
# ImpactMind Schemas (Phase 11)
# =============================================================================


class ImpactAnalyzeRequest(BaseModel):
    """Request to analyze code changes and compute blast radius & regression tests."""

    diff_text: str | None = Field(default=None, description="Raw unified diff text to inspect")
    base_commit_sha: str | None = Field(default=None, description="Base commit SHA")
    target_commit_sha: str | None = Field(default=None, description="Target/head commit SHA")
    comparison_mode: str = Field(
        default="diff_input",
        description="Mode: diff_input | commit_range | working_tree",
    )
    snapshot_id: uuid.UUID | None = Field(
        default=None, description="Target snapshot to evaluate against"
    )
    file_contents_before: dict[str, str] | None = Field(
        default=None, description="Optional map of file paths to before-change source text"
    )
    file_contents_after: dict[str, str] | None = Field(
        default=None, description="Optional map of file paths to after-change source text"
    )


class ChangeClassificationItem(BaseModel):
    """Classified code modification."""

    id: uuid.UUID
    file_path: str
    symbol_name: str | None = None
    symbol_id: str | None = None
    category: str
    is_breaking: bool = False
    breaking_reason: str | None = None
    confidence: float = 1.0
    evidence: str | None = None
    status: str = "resolved"


class ImpactedEntityItem(BaseModel):
    """Downstream affected graph entity."""

    id: uuid.UUID
    entity_id: str
    name: str
    label: str
    file_path: str | None = None
    impact_type: str
    depth: int = 1
    relationship_type: str | None = None
    confidence: float = 1.0
    evidence: str | None = None


class TestRecommendationItem(BaseModel):
    """Ranked regression test case recommended for execution."""

    id: uuid.UUID
    test_file: str
    test_name: str | None = None
    test_framework: str = "pytest"
    priority: str = "MEDIUM"  # CRITICAL | HIGH | MEDIUM | LOW
    reason: str
    related_symbol: str | None = None
    evidence_source: str
    confidence: float = 1.0


class TestExecutionRunItem(BaseModel):
    """Execution run of approved regression tests."""

    id: uuid.UUID
    command: str
    status: str  # PENDING | RUNNING | PASSED | FAILED | TIMED_OUT | CANCELLED | SKIPPED
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    duration_ms: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ImpactAssessmentResponse(BaseModel):
    """Comprehensive ImpactMind Change Impact Assessment Report."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    repository_id: uuid.UUID
    snapshot_id: uuid.UUID | None = None
    base_commit_sha: str | None = None
    target_commit_sha: str | None = None
    comparison_mode: str
    status: str
    structural_exposure_score: float = Field(
        ..., description="Blast Radius & Structural Exposure Score (0.0 to 100.0, heuristic)"
    )
    exposure_tier: str = Field(..., description="Exposure tier: LOW | MEDIUM | HIGH | CRITICAL")
    score_type: str = "heuristic_structural_exposure"
    score_label: str = "Blast Radius & Structural Exposure Score"
    change_summary: dict[str, Any]
    reasons: list[str]
    recommended_actions: list[str]
    error_message: str | None = None
    classifications: list[ChangeClassificationItem] = []
    impacted_entities: list[ImpactedEntityItem] = []
    test_recommendations: list[TestRecommendationItem] = []
    test_executions: list[TestExecutionRunItem] = []
    created_at: datetime
    completed_at: datetime | None = None


class ImpactAssessmentListResponse(BaseModel):
    """List of historical impact assessments."""

    assessments: list[ImpactAssessmentResponse]
    total: int
    limit: int
    offset: int


class RunTestsRequest(BaseModel):
    """Request to execute approved regression tests in controlled environment."""

    run_approved: bool = Field(..., description="Explicit user approval to execute tests")
    working_dir: str | None = Field(default=None, description="Controlled working directory")
    custom_command: str | None = Field(default=None, description="Optional custom command")
    timeout_seconds: float = Field(default=60.0, ge=5.0, le=300.0)


class CancelTestsRequest(BaseModel):
    """Request to cancel ongoing test execution."""

    execution_id: uuid.UUID

