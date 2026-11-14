import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    enforce_csrf_protection,
    get_current_user,
    require_workspace_membership,
)
from app.api.v1.schemas import (
    CodeSymbolListResponse,
    CodeSymbolResponse,
    FileDependencyListResponse,
    FileDependencyResponse,
    IndexingJobListResponse,
    IndexingJobResponse,
    RepositoryFileResponse,
    RepositoryFilesListResponse,
    RepositoryIntelligenceResponse,
    SupportedLanguageCapability,
    SupportedLanguagesResponse,
)
from app.db.base import WorkspaceRole
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.code_intelligence import PARSER_REGISTRY
from app.services.indexing_service import (
    cancel_indexing_job,
    create_indexing_job,
    get_indexing_job_by_id,
    get_latest_repository_snapshot,
    list_indexing_jobs_for_repository,
    list_repository_dependencies,
    list_repository_files,
    list_repository_symbols,
)

indexing_router = APIRouter(prefix="/repositories", tags=["repository-intelligence"])
logger = logging.getLogger("orchestrix.api.indexing")


@indexing_router.post(
    "/{repository_id}/indexing/start",
    response_model=IndexingJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start repository intelligence indexing job",
)
async def start_repository_indexing(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    force_reindex: bool = Query(
        default=False, description="Whether to re-index already processed commit"
    ),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.ADMIN)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """
    Trigger structural and code intelligence indexing for a connected GitHub repository.
    Enforces ADMIN or OWNER workspace role and double-submit CSRF protection.
    """
    try:
        job, _was_created = await create_indexing_job(
            db=db,
            workspace_id=workspace_id,
            repository_id=repository_id,
            user_id=current_user.id,
            force_reindex=force_reindex,
        )
        return job
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Failed to start indexing for repo %s: %s", repository_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@indexing_router.get(
    "/{repository_id}/indexing/jobs",
    response_model=IndexingJobListResponse,
    summary="List indexing jobs for repository",
)
async def list_indexing_jobs(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    limit: int = Query(default=20, ge=1, le=100),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """List historical and active indexing jobs for a repository."""
    jobs = await list_indexing_jobs_for_repository(
        db=db,
        repository_id=repository_id,
        workspace_id=workspace_id,
        limit=limit,
    )
    return IndexingJobListResponse(
        jobs=[IndexingJobResponse.model_validate(j) for j in jobs], total=len(jobs)
    )


@indexing_router.get(
    "/{repository_id}/indexing/jobs/{job_id}",
    response_model=IndexingJobResponse,
    summary="Get indexing job details",
)
async def get_indexing_job(
    repository_id: uuid.UUID,
    job_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Get status, progress, and metrics for a specific indexing job."""
    job = await get_indexing_job_by_id(db=db, job_id=job_id, workspace_id=workspace_id)
    if not job or job.repository_id != repository_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Indexing job not found")
    return job


@indexing_router.post(
    "/{repository_id}/indexing/jobs/{job_id}/cancel",
    response_model=IndexingJobResponse,
    summary="Cancel active indexing job",
)
async def cancel_job(
    repository_id: uuid.UUID,
    job_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.ADMIN)),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Cancel a pending or running indexing job."""
    try:
        job = await cancel_indexing_job(db=db, job_id=job_id, workspace_id=workspace_id)
        if job.repository_id != repository_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Indexing job not found"
            )
        return job
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@indexing_router.get(
    "/{repository_id}/intelligence",
    response_model=RepositoryIntelligenceResponse,
    summary="Get repository structural intelligence overview",
)
async def get_repository_intelligence(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """
    Retrieve repository intelligence overview including language distribution,
    entry-point candidates, directory structure, and overall statistics.
    """
    repo = await db.get(Repository, repository_id)
    if not repo or repo.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

    snapshot = await get_latest_repository_snapshot(
        db=db, repository_id=repository_id, workspace_id=workspace_id
    )
    if not snapshot:
        return RepositoryIntelligenceResponse(
            repository_id=repository_id,
            workspace_id=workspace_id,
            last_indexed_at=repo.last_indexed_at,
        )

    structure = snapshot.structure_summary or {}
    frameworks = structure.get("frameworks", []) if isinstance(structure, dict) else []

    return RepositoryIntelligenceResponse(
        repository_id=repository_id,
        workspace_id=workspace_id,
        commit_sha=snapshot.commit_sha,
        branch=snapshot.branch,
        total_files=snapshot.total_files,
        total_lines=snapshot.total_lines,
        total_bytes=snapshot.total_bytes,
        total_symbols=snapshot.total_symbols,
        total_dependencies=snapshot.total_dependencies,
        languages_summary=snapshot.languages_summary,
        structure_summary=snapshot.structure_summary,
        entry_points=snapshot.entry_points,
        detected_frameworks=frameworks,
        last_indexed_at=repo.last_indexed_at or snapshot.created_at,
    )


@indexing_router.get(
    "/{repository_id}/intelligence/files",
    response_model=RepositoryFilesListResponse,
    summary="List indexed files for repository",
)
async def get_indexed_files(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    language: str | None = Query(default=None, description="Filter by programming language"),
    search: str | None = Query(default=None, description="Search path keyword"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """List indexed files in the repository snapshot."""
    files, total = await list_repository_files(
        db=db,
        repository_id=repository_id,
        workspace_id=workspace_id,
        language=language,
        search=search,
        limit=limit,
        offset=offset,
    )
    return RepositoryFilesListResponse(
        files=[RepositoryFileResponse.model_validate(f) for f in files],
        total=total,
    )


@indexing_router.get(
    "/{repository_id}/intelligence/symbols",
    response_model=CodeSymbolListResponse,
    summary="List extracted code symbols",
)
async def get_code_symbols(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    symbol_type: str | None = Query(
        default=None, description="Filter: function, class, method, interface"
    ),
    language: str | None = Query(default=None, description="Filter by language"),
    search: str | None = Query(default=None, description="Search symbol name"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """List extracted code symbols from Tree-sitter AST parsing."""
    symbols, total = await list_repository_symbols(
        db=db,
        repository_id=repository_id,
        workspace_id=workspace_id,
        symbol_type=symbol_type,
        language=language,
        search=search,
        limit=limit,
        offset=offset,
    )
    return CodeSymbolListResponse(
        symbols=[CodeSymbolResponse.model_validate(s) for s in symbols],
        total=total,
    )


@indexing_router.get(
    "/{repository_id}/intelligence/dependencies",
    response_model=FileDependencyListResponse,
    summary="List extracted dependencies and imports",
)
async def get_dependencies(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
    dependency_type: str | None = Query(
        default=None, description="Filter: package_dependency, dev_dependency, import"
    ),
    package_manager: str | None = Query(default=None, description="Filter: npm, pip, cargo, go"),
    search: str | None = Query(default=None, description="Search dependency name"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """List dependencies extracted from manifests and source imports."""
    deps, total = await list_repository_dependencies(
        db=db,
        repository_id=repository_id,
        workspace_id=workspace_id,
        dependency_type=dependency_type,
        package_manager=package_manager,
        search=search,
        limit=limit,
        offset=offset,
    )
    return FileDependencyListResponse(
        dependencies=[FileDependencyResponse.model_validate(d) for d in deps],
        total=total,
    )


@indexing_router.get(
    "/intelligence/supported-languages",
    response_model=SupportedLanguagesResponse,
    summary="List all supported languages and parser availability",
)
async def get_supported_languages(
    _user: User = Depends(get_current_user),
) -> Any:
    """
    Query the modular parser registry to retrieve all registered programming,
    markup, and styling languages along with their platform availability.
    """
    lang_names = PARSER_REGISTRY.get_supported_languages()
    caps: list[SupportedLanguageCapability] = []
    for name in lang_names:
        spec = PARSER_REGISTRY.get_language_spec(name)
        if spec:
            parser = PARSER_REGISTRY.get_parser(name)
            caps.append(
                SupportedLanguageCapability(
                    name=spec.canonical_name,
                    package_name=spec.package_name,
                    available=parser is not None,
                    extensions=spec.extensions,
                    category=spec.category,
                    extraction_mode=spec.extraction_mode,
                    adapter_name=spec.adapter.__class__.__name__,
                )
            )

    return SupportedLanguagesResponse(
        total_supported=len(caps),
        languages=caps,
    )
