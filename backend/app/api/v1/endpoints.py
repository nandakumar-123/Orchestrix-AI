import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    DatabaseHealthResponse,
    EngineeringTaskCreate,
    EngineeringTaskListResponse,
    EngineeringTaskResponse,
    EngineeringTaskUpdate,
    HealthResponse,
    RepositoryCreate,
    RepositoryListResponse,
    RepositoryResponse,
    RepositoryUpdate,
)
from app.core.config import settings
from app.db.base import TaskStatus
from app.db.session import check_database_connection, get_db_session
from app.services.database import (
    create_engineering_task,
    deactivate_repository,
    get_engineering_task_by_id,
    get_repository_by_id,
    list_engineering_tasks,
    list_repositories,
    register_repository,
    update_repository,
    update_task_status,
)

router = APIRouter()


# -----------------------------------------------------------------------------
# Health Check Endpoints
# -----------------------------------------------------------------------------


@router.get(
    "/health", response_model=HealthResponse, tags=["health"], summary="Service Health Check"
)
async def get_health() -> HealthResponse:
    """Return application operational status."""
    return HealthResponse(
        status="ok",
        app=settings.APP_NAME,
        environment=settings.APP_ENV,
        version="0.1.0",
    )


@router.get(
    "/health/database",
    response_model=DatabaseHealthResponse,
    tags=["health"],
    summary="Database Connectivity Health Check",
    responses={
        status.HTTP_200_OK: {"description": "Database is reachable and healthy"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Database connection failed"},
    },
)
async def get_database_health() -> JSONResponse:
    """Check connectivity to PostgreSQL database safely without exposing credentials."""
    is_connected = await check_database_connection(timeout_seconds=3.0)
    db_type = "postgresql" if "postgresql" in settings.async_database_url else "database"

    payload = DatabaseHealthResponse(
        status="healthy" if is_connected else "unavailable",
        database=db_type,
        connected=is_connected,
    )

    status_code = status.HTTP_200_OK if is_connected else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=payload.model_dump())


# -----------------------------------------------------------------------------
# Repository Endpoints
# -----------------------------------------------------------------------------


@router.get(
    "/repositories",
    response_model=RepositoryListResponse,
    tags=["repositories"],
    summary="List connected repositories for a workspace",
)
async def get_repositories(
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
) -> RepositoryListResponse:
    """List all active repositories scoped to a workspace with pagination."""
    items, total = await list_repositories(db, workspace_id, limit=limit, offset=offset)
    return RepositoryListResponse(
        items=[RepositoryResponse.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/repositories/{repository_id}",
    response_model=RepositoryResponse,
    tags=["repositories"],
    summary="Get repository details",
)
async def get_repository(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    db: AsyncSession = Depends(get_db_session),
) -> RepositoryResponse:
    """Retrieve repository by ID, strictly enforcing workspace tenant isolation."""
    repo = await get_repository_by_id(db, workspace_id, repository_id)
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found in the specified workspace",
        )
    return RepositoryResponse.model_validate(repo)


@router.post(
    "/repositories",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["repositories"],
    summary="Connect a new repository to a workspace",
)
async def create_repository(
    payload: RepositoryCreate,
    db: AsyncSession = Depends(get_db_session),
) -> RepositoryResponse:
    """Register a new repository under an authorized workspace and installation."""
    try:
        repo = await register_repository(
            db,
            workspace_id=payload.workspace_id,
            installation_id=payload.installation_id,
            github_repository_id=payload.github_repository_id,
            name=payload.name,
            full_name=payload.full_name,
            owner_login=payload.owner_login,
            description=payload.description,
            default_branch=payload.default_branch,
            html_url=payload.html_url,
            visibility=payload.visibility,
            language=payload.language,
        )
        return RepositoryResponse.model_validate(repo)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        ) from val_err


@router.patch(
    "/repositories/{repository_id}",
    response_model=RepositoryResponse,
    tags=["repositories"],
    summary="Update repository metadata",
)
async def patch_repository(
    repository_id: uuid.UUID,
    payload: RepositoryUpdate,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    db: AsyncSession = Depends(get_db_session),
) -> RepositoryResponse:
    """Update metadata for an existing repository in a workspace."""
    repo = await update_repository(
        db,
        workspace_id=workspace_id,
        repository_id=repository_id,
        **payload.model_dump(exclude_unset=True),
    )
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found in the specified workspace",
        )
    return RepositoryResponse.model_validate(repo)


@router.delete(
    "/repositories/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["repositories"],
    summary="Deactivate a repository",
)
async def delete_repository(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Soft-delete/deactivate a repository within a workspace."""
    success = await deactivate_repository(db, workspace_id, repository_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found in the specified workspace",
        )


# -----------------------------------------------------------------------------
# Engineering Task Endpoints
# -----------------------------------------------------------------------------


@router.get(
    "/tasks",
    response_model=EngineeringTaskListResponse,
    tags=["tasks"],
    summary="List engineering tasks for a workspace",
)
async def get_tasks(
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    status: TaskStatus | None = Query(default=None),
    repository_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
) -> EngineeringTaskListResponse:
    """List engineering tasks scoped to a workspace with optional filters."""
    items, total = await list_engineering_tasks(
        db,
        workspace_id=workspace_id,
        status=status,
        repository_id=repository_id,
        limit=limit,
        offset=offset,
    )
    return EngineeringTaskListResponse(
        items=[EngineeringTaskResponse.model_validate(t) for t in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/tasks",
    response_model=EngineeringTaskResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["tasks"],
    summary="Create an engineering task",
)
async def create_task(
    payload: EngineeringTaskCreate,
    db: AsyncSession = Depends(get_db_session),
) -> EngineeringTaskResponse:
    """Create a new autonomous engineering task in a workspace."""
    try:
        task = await create_engineering_task(
            db,
            workspace_id=payload.workspace_id,
            title=payload.title,
            task_type=payload.task_type,
            priority=payload.priority,
            repository_id=payload.repository_id,
            created_by=payload.created_by,
            description=payload.description,
            assigned_agent=payload.assigned_agent,
            external_issue_id=payload.external_issue_id,
        )
        return EngineeringTaskResponse.model_validate(task)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        ) from val_err


@router.get(
    "/tasks/{task_id}",
    response_model=EngineeringTaskResponse,
    tags=["tasks"],
    summary="Get task details",
)
async def get_task(
    task_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    db: AsyncSession = Depends(get_db_session),
) -> EngineeringTaskResponse:
    """Retrieve an engineering task, strictly scoped to a workspace."""
    task = await get_engineering_task_by_id(db, workspace_id, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Engineering task not found in the specified workspace",
        )
    return EngineeringTaskResponse.model_validate(task)


@router.patch(
    "/tasks/{task_id}",
    response_model=EngineeringTaskResponse,
    tags=["tasks"],
    summary="Update task status or agent assignment",
)
async def patch_task(
    task_id: uuid.UUID,
    payload: EngineeringTaskUpdate,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    db: AsyncSession = Depends(get_db_session),
) -> EngineeringTaskResponse:
    """Update status or assigned agent for a workspace-scoped engineering task."""
    if payload.status is None and payload.assigned_agent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field (status or assigned_agent) must be provided",
        )

    task = await update_task_status(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        new_status=payload.status or TaskStatus.BACKLOG,
        assigned_agent=payload.assigned_agent,
    )
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Engineering task not found in the specified workspace",
        )
    return EngineeringTaskResponse.model_validate(task)
