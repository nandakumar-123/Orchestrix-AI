import asyncio
import logging
import os
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import IndexingJobStatus, utc_now
from app.db.models.repository import Repository
from app.db.models.repository_intelligence import (
    CodeSymbol,
    FileDependency,
    IndexingError,
    IndexingJob,
    RepositoryFile,
    RepositorySnapshot,
)
from app.db.session import get_async_session_factory
from app.services.code_intelligence import PARSER_REGISTRY, analyze_code_content
from app.services.dependency_intelligence import parse_dependency_manifest
from app.services.framework_detection import detect_frameworks
from app.services.github import decrypt_token, get_user_github_account
from app.services.repository_ingestion import (
    detect_language,
    fetch_blob_content,
    fetch_latest_commit_sha,
    fetch_repository_tree,
    is_manifest_file,
    should_skip_file,
)

logger = logging.getLogger("orchestrix.indexing")

# Concurrency semaphore: at most 1 heavy indexing job executing concurrently per backend instance
_INDEXING_SEMAPHORE = asyncio.Semaphore(1)

# Active background tasks dictionary: job_id -> asyncio.Task
_ACTIVE_JOB_TASKS: dict[uuid.UUID, asyncio.Task[None]] = {}

ENTRY_POINT_CANDIDATES = {
    "main.py",
    "app/main.py",
    "src/main.py",
    "run.py",
    "server.py",
    "index.ts",
    "src/index.ts",
    "index.js",
    "src/index.js",
    "server.js",
    "app/layout.tsx",
    "app/page.tsx",
    "pages/index.tsx",
    "src/App.tsx",
    "src/main.ts",
    "Main.java",
    "Application.java",
    "main.go",
    "src/main.rs",
    "main.c",
    "main.cpp",
}


def build_directory_tree(paths: list[str]) -> dict[str, Any]:
    """Build a nested directory dictionary from a list of file paths."""
    tree: dict[str, Any] = {}
    for path in paths:
        parts = path.split("/")
        curr = tree
        for part in parts[:-1]:
            curr = curr.setdefault(part, {})
        curr[parts[-1]] = None  # Leaf file
    return tree


async def create_indexing_job(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    repository_id: uuid.UUID,
    user_id: uuid.UUID,
    force_reindex: bool = False,
) -> tuple[IndexingJob, bool]:
    """
    Initiate or return an existing indexing job for a repository.
    Returns (job, was_created).
    """
    # 1. Verify repository exists in workspace
    repo_stmt = select(Repository).where(
        Repository.id == repository_id,
        Repository.workspace_id == workspace_id,
    )
    res = await db.execute(repo_stmt)
    repo = res.scalars().first()
    if not repo:
        raise LookupError(f"Repository {repository_id} not found in workspace {workspace_id}")

    # 2. Get user's connected GitHub account & decrypted access token
    gh_account = await get_user_github_account(db, user_id)
    if not gh_account:
        raise PermissionError("User does not have an active GitHub account connected")

    token = decrypt_token(gh_account.encrypted_access_token)

    # 3. Resolve latest commit SHA on default branch
    try:
        commit_sha = await fetch_latest_commit_sha(
            access_token=token,
            owner=repo.owner_login,
            repo=repo.name,
            branch=repo.default_branch,
        )
    except Exception as exc:
        logger.error("Failed to resolve commit SHA for %s: %s", repo.full_name, exc)
        raise

    # 4. Check for active (PENDING / RUNNING) job for this repository
    active_stmt = select(IndexingJob).where(
        IndexingJob.repository_id == repository_id,
        IndexingJob.status.in_([IndexingJobStatus.PENDING, IndexingJobStatus.RUNNING]),
    )
    active_res = await db.execute(active_stmt)
    active_job = active_res.scalars().first()
    if active_job:
        logger.info("Reusing active indexing job %s for repo %s", active_job.id, repo.full_name)
        return active_job, False

    # 5. Check if already indexed for this exact commit SHA and not force_reindex
    if not force_reindex:
        existing_snapshot_stmt = select(RepositorySnapshot).where(
            RepositorySnapshot.repository_id == repository_id,
            RepositorySnapshot.commit_sha == commit_sha,
        )
        existing_res = await db.execute(existing_snapshot_stmt)
        if existing_res.scalars().first() is not None:
            # Check latest completed job
            latest_job_stmt = (
                select(IndexingJob)
                .where(
                    IndexingJob.repository_id == repository_id,
                    IndexingJob.commit_sha == commit_sha,
                    IndexingJob.status == IndexingJobStatus.COMPLETED,
                )
                .order_by(desc(IndexingJob.created_at))
            )
            latest_job = (await db.execute(latest_job_stmt)).scalars().first()
            if latest_job:
                logger.info("Commit %s already indexed for repo %s", commit_sha, repo.full_name)
                return latest_job, False

    # 6. Create new IndexingJob record
    job = IndexingJob(
        workspace_id=workspace_id,
        repository_id=repository_id,
        commit_sha=commit_sha,
        branch=repo.default_branch,
        status=IndexingJobStatus.PENDING,
        progress_percent=0,
        current_step="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # 7. Launch background task asynchronously
    task = asyncio.create_task(
        _execute_indexing_job_background(
            job_id=job.id,
            workspace_id=workspace_id,
            repository_id=repository_id,
            owner=repo.owner_login,
            repo_name=repo.name,
            default_branch=repo.default_branch,
            commit_sha=commit_sha,
            access_token=token,
        )
    )
    _ACTIVE_JOB_TASKS[job.id] = task

    return job, True


async def cancel_indexing_job(
    db: AsyncSession,
    job_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> IndexingJob:
    """Cancel a pending or running indexing job."""
    stmt = select(IndexingJob).where(
        IndexingJob.id == job_id,
        IndexingJob.workspace_id == workspace_id,
    )
    res = await db.execute(stmt)
    job = res.scalars().first()
    if not job:
        raise LookupError(f"Indexing job {job_id} not found in workspace")

    if job.status in (
        IndexingJobStatus.COMPLETED,
        IndexingJobStatus.FAILED,
        IndexingJobStatus.CANCELLED,
    ):
        return job

    job.status = IndexingJobStatus.CANCELLED
    job.error_message = "Indexing job cancelled by user"
    job.completed_at = utc_now()
    await db.commit()
    await db.refresh(job)

    # Cancel active background task if running
    task = _ACTIVE_JOB_TASKS.get(job_id)
    if task and not task.done():
        task.cancel()

    return job


async def _execute_indexing_job_background(
    job_id: uuid.UUID,
    workspace_id: uuid.UUID,
    repository_id: uuid.UUID,
    owner: str,
    repo_name: str,
    default_branch: str,
    commit_sha: str,
    access_token: str,
) -> None:
    """
    Main asynchronous background worker that processes repository tree,
    extracts code intelligence via Tree-sitter, parses manifests, and persists snapshots.
    """
    async with _INDEXING_SEMAPHORE:
        session_factory = get_async_session_factory()
        async with session_factory() as db:
            try:
                # 1. Update status to RUNNING
                job = await db.get(IndexingJob, job_id)
                if not job or job.status == IndexingJobStatus.CANCELLED:
                    return

                job.status = IndexingJobStatus.RUNNING
                job.started_at = utc_now()
                job.progress_percent = 5
                job.current_step = "fetching_tree"
                await db.commit()

                # 2. Fetch Git tree
                tree_items = await fetch_repository_tree(
                    access_token=access_token,
                    owner=owner,
                    repo=repo_name,
                    commit_sha=commit_sha,
                )

                # Filter out tree nodes, keep blobs
                blob_items = [item for item in tree_items if item.get("type") == "blob"]
                total_blobs = len(blob_items)

                job.progress_percent = 15
                job.current_step = f"filtering_files ({total_blobs} items found)"
                await db.commit()

                # 3. Filter valid files
                eligible_files: list[dict[str, Any]] = []
                for item in blob_items:
                    path = item.get("path", "")
                    size = item.get("size", 0)
                    skip, reason = should_skip_file(path, size)
                    if skip:
                        if reason.startswith("file_size_exceeded"):
                            error = IndexingError(
                                job_id=job.id,
                                file_path=path,
                                error_type="file_too_large",
                                message=f"File exceeds size threshold ({size} bytes)",
                            )
                            db.add(error)
                        continue
                    eligible_files.append(item)

                total_files_to_index = len(eligible_files)
                job.progress_percent = 25
                job.current_step = f"indexing_files (0/{total_files_to_index})"
                await db.commit()

                # 4. Prepare / Replace Snapshot
                # Delete any previous snapshot for this commit SHA to prevent duplicates
                del_snapshot_stmt = delete(RepositorySnapshot).where(
                    RepositorySnapshot.repository_id == repository_id,
                    RepositorySnapshot.commit_sha == commit_sha,
                )
                await db.execute(del_snapshot_stmt)
                await db.flush()

                snapshot = RepositorySnapshot(
                    workspace_id=workspace_id,
                    repository_id=repository_id,
                    commit_sha=commit_sha,
                    branch=default_branch,
                )
                db.add(snapshot)
                await db.flush()
                await db.refresh(snapshot)

                # 5. Process files, parse AST, and extract dependencies
                languages_stat: dict[str, dict[str, int]] = defaultdict(
                    lambda: {"files": 0, "lines": 0}
                )
                all_paths: list[str] = []
                all_dep_names: set[str] = set()
                detected_entry_points: list[str] = []

                total_lines_count = 0
                total_bytes_count = 0
                total_symbols_count = 0
                total_deps_count = 0

                for idx, item in enumerate(eligible_files):
                    # Check for cancellation
                    await db.refresh(job)
                    if job.status == IndexingJobStatus.CANCELLED:
                        logger.info("Indexing job %s was cancelled during execution", job_id)
                        return

                    path = item.get("path", "")
                    sha = item.get("sha", "")
                    size = item.get("size", 0)
                    filename = os.path.basename(path)
                    _, ext = os.path.splitext(filename)
                    lang = detect_language(path)
                    is_manifest = is_manifest_file(path)

                    all_paths.append(path)
                    if path.lower() in {ep.lower() for ep in ENTRY_POINT_CANDIDATES}:
                        detected_entry_points.append(path)

                    # Fetch file content
                    try:
                        content_bytes = await fetch_blob_content(
                            access_token=access_token,
                            owner=owner,
                            repo=repo_name,
                            blob_sha=sha,
                        )
                    except Exception as fetch_err:
                        error = IndexingError(
                            job_id=job.id,
                            file_path=path,
                            error_type="fetch_error",
                            message=f"Failed to fetch blob from GitHub: {fetch_err}",
                        )
                        db.add(error)
                        continue

                    # Record RepositoryFile
                    line_count = len(content_bytes.splitlines()) if content_bytes else 0
                    total_lines_count += line_count
                    total_bytes_count += size

                    if lang:
                        languages_stat[lang]["files"] += 1
                        languages_stat[lang]["lines"] += line_count

                    repo_file = RepositoryFile(
                        workspace_id=workspace_id,
                        repository_id=repository_id,
                        snapshot_id=snapshot.id,
                        path=path,
                        file_name=filename,
                        extension=ext,
                        language=lang,
                        size_bytes=size,
                        line_count=line_count,
                        sha=sha,
                        is_binary=False,
                        is_manifest=is_manifest,
                    )
                    db.add(repo_file)
                    await db.flush()
                    await db.refresh(repo_file)

                    # Code Intelligence via modular Tree-sitter Registry
                    if lang and PARSER_REGISTRY.get_language_spec(lang):
                        file_intel = analyze_code_content(content_bytes, lang)
                        if file_intel.parse_error:
                            error = IndexingError(
                                job_id=job.id,
                                file_path=path,
                                error_type="parse_error",
                                message=file_intel.parse_error,
                            )
                            db.add(error)

                        # Persist symbols
                        for sym in file_intel.symbols:
                            code_sym = CodeSymbol(
                                workspace_id=workspace_id,
                                repository_id=repository_id,
                                snapshot_id=snapshot.id,
                                file_id=repo_file.id,
                                file_path=path,
                                name=sym.name,
                                symbol_type=sym.symbol_type,
                                language=lang,
                                start_line=sym.start_line,
                                end_line=sym.end_line,
                                start_column=sym.start_column,
                                end_column=sym.end_column,
                                signature=sym.signature,
                                parent_symbol_name=sym.parent_symbol_name,
                            )
                            db.add(code_sym)
                            total_symbols_count += 1

                        # Persist imports as file dependencies
                        for imp in file_intel.imports:
                            file_dep = FileDependency(
                                workspace_id=workspace_id,
                                repository_id=repository_id,
                                snapshot_id=snapshot.id,
                                file_id=repo_file.id,
                                source_file_path=path,
                                name=imp.module_name,
                                version_spec=None,
                                dependency_type="import",
                                package_manager=None,
                                is_external=imp.is_external,
                            )
                            db.add(file_dep)
                            total_deps_count += 1

                    # Manifest Dependency Intelligence
                    if is_manifest:
                        try:
                            manifest_text = content_bytes.decode("utf-8", errors="replace")
                            manifest_deps = parse_dependency_manifest(path, manifest_text)
                            for m_dep in manifest_deps:
                                all_dep_names.add(m_dep.name)
                                file_dep = FileDependency(
                                    workspace_id=workspace_id,
                                    repository_id=repository_id,
                                    snapshot_id=snapshot.id,
                                    file_id=repo_file.id,
                                    source_file_path=path,
                                    name=m_dep.name,
                                    version_spec=m_dep.version_spec,
                                    dependency_type=m_dep.dependency_type,
                                    package_manager=m_dep.package_manager,
                                    is_external=True,
                                )
                                db.add(file_dep)
                                total_deps_count += 1
                        except Exception as m_err:
                            error = IndexingError(
                                job_id=job.id,
                                file_path=path,
                                error_type="manifest_error",
                                message=f"Failed to parse manifest {path}: {m_err}",
                            )
                            db.add(error)

                    # Update progress every 10 files
                    if idx % 10 == 0 or idx == total_files_to_index - 1:
                        pct = int(25 + (65 * (idx + 1) / max(total_files_to_index, 1)))
                        job.progress_percent = min(pct, 90)
                        job.current_step = f"indexing_files ({idx + 1}/{total_files_to_index})"
                        job.files_count = idx + 1
                        job.symbols_count = total_symbols_count
                        job.dependencies_count = total_deps_count
                        await db.commit()

                # 6. Finalize Snapshot and Repository Record
                job.current_step = "finalizing"
                job.progress_percent = 95
                await db.commit()

                structure_summary = build_directory_tree(all_paths)
                detected_frameworks = detect_frameworks(all_paths, all_dep_names)
                if structure_summary is None:
                    structure_summary = {}
                structure_summary["frameworks"] = detected_frameworks

                snapshot.total_files = len(eligible_files)
                snapshot.total_lines = total_lines_count
                snapshot.total_bytes = total_bytes_count
                snapshot.total_symbols = total_symbols_count
                snapshot.total_dependencies = total_deps_count
                snapshot.languages_summary = dict(languages_stat)
                snapshot.structure_summary = structure_summary
                snapshot.entry_points = detected_entry_points

                # Update Repository last_indexed_at
                repo_obj = await db.get(Repository, repository_id)
                if repo_obj:
                    repo_obj.last_indexed_at = utc_now()

                # Complete Job
                job.status = IndexingJobStatus.COMPLETED
                job.progress_percent = 100
                job.current_step = "completed"
                job.files_count = len(eligible_files)
                job.symbols_count = total_symbols_count
                job.dependencies_count = total_deps_count
                job.completed_at = utc_now()

                await db.commit()
                logger.info(
                    "Indexing completed for %s/%s at commit %s. Files: %d, Symbols: %d, Deps: %d",
                    owner,
                    repo_name,
                    commit_sha,
                    len(eligible_files),
                    total_symbols_count,
                    total_deps_count,
                )

            except Exception as exc:
                logger.error("Indexing failed for job %s: %s", job_id, exc, exc_info=True)
                await db.rollback()
                try:
                    job = await db.get(IndexingJob, job_id)
                    if job:
                        job.status = IndexingJobStatus.FAILED
                        job.error_message = str(exc)
                        job.completed_at = utc_now()
                        await db.commit()
                except Exception:
                    pass
            finally:
                _ACTIVE_JOB_TASKS.pop(job_id, None)


# -----------------------------------------------------------------------------
# Read / Query APIs for Intelligence Data
# -----------------------------------------------------------------------------


async def get_indexing_job_by_id(
    db: AsyncSession,
    job_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> IndexingJob | None:
    """Retrieve indexing job details with tenant isolation."""
    stmt = select(IndexingJob).where(
        IndexingJob.id == job_id,
        IndexingJob.workspace_id == workspace_id,
    )
    res = await db.execute(stmt)
    return res.scalars().first()


async def list_indexing_jobs_for_repository(
    db: AsyncSession,
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID,
    limit: int = 20,
) -> list[IndexingJob]:
    """Retrieve indexing job history for a repository."""
    stmt = (
        select(IndexingJob)
        .where(
            IndexingJob.repository_id == repository_id,
            IndexingJob.workspace_id == workspace_id,
        )
        .order_by(desc(IndexingJob.created_at))
        .limit(limit)
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def get_latest_repository_snapshot(
    db: AsyncSession,
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> RepositorySnapshot | None:
    """Retrieve latest intelligence snapshot for a repository."""
    stmt = (
        select(RepositorySnapshot)
        .where(
            RepositorySnapshot.repository_id == repository_id,
            RepositorySnapshot.workspace_id == workspace_id,
        )
        .order_by(desc(RepositorySnapshot.created_at))
    )
    res = await db.execute(stmt)
    return res.scalars().first()


async def list_repository_files(
    db: AsyncSession,
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID,
    language: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[RepositoryFile], int]:
    """List indexed files for the latest snapshot with optional filtering."""
    snapshot = await get_latest_repository_snapshot(db, repository_id, workspace_id)
    if not snapshot:
        return [], 0

    query = select(RepositoryFile).where(RepositoryFile.snapshot_id == snapshot.id)
    count_query = select(func.count(RepositoryFile.id)).where(
        RepositoryFile.snapshot_id == snapshot.id
    )

    if language:
        query = query.where(RepositoryFile.language == language)
        count_query = count_query.where(RepositoryFile.language == language)
    if search:
        query = query.where(RepositoryFile.path.ilike(f"%{search}%"))
        count_query = count_query.where(RepositoryFile.path.ilike(f"%{search}%"))

    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(RepositoryFile.path).limit(limit).offset(offset)
    files = (await db.execute(query)).scalars().all()
    return list(files), total


async def list_repository_symbols(
    db: AsyncSession,
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID,
    symbol_type: str | None = None,
    language: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[CodeSymbol], int]:
    """List extracted code symbols for latest snapshot with optional filtering."""
    snapshot = await get_latest_repository_snapshot(db, repository_id, workspace_id)
    if not snapshot:
        return [], 0

    query = select(CodeSymbol).where(CodeSymbol.snapshot_id == snapshot.id)
    count_query = select(func.count(CodeSymbol.id)).where(CodeSymbol.snapshot_id == snapshot.id)

    if symbol_type:
        query = query.where(CodeSymbol.symbol_type == symbol_type)
        count_query = count_query.where(CodeSymbol.symbol_type == symbol_type)
    if language:
        query = query.where(CodeSymbol.language == language)
        count_query = count_query.where(CodeSymbol.language == language)
    if search:
        query = query.where(CodeSymbol.name.ilike(f"%{search}%"))
        count_query = count_query.where(CodeSymbol.name.ilike(f"%{search}%"))

    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(CodeSymbol.file_path, CodeSymbol.start_line).limit(limit).offset(offset)
    symbols = (await db.execute(query)).scalars().all()
    return list(symbols), total


async def list_repository_dependencies(
    db: AsyncSession,
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID,
    dependency_type: str | None = None,
    package_manager: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[FileDependency], int]:
    """List extracted dependencies for latest snapshot."""
    snapshot = await get_latest_repository_snapshot(db, repository_id, workspace_id)
    if not snapshot:
        return [], 0

    query = select(FileDependency).where(FileDependency.snapshot_id == snapshot.id)
    count_query = select(func.count(FileDependency.id)).where(
        FileDependency.snapshot_id == snapshot.id
    )

    if dependency_type:
        query = query.where(FileDependency.dependency_type == dependency_type)
        count_query = count_query.where(FileDependency.dependency_type == dependency_type)
    if package_manager:
        query = query.where(FileDependency.package_manager == package_manager)
        count_query = count_query.where(FileDependency.package_manager == package_manager)
    if search:
        query = query.where(FileDependency.name.ilike(f"%{search}%"))
        count_query = count_query.where(FileDependency.name.ilike(f"%{search}%"))

    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(FileDependency.name).limit(limit).offset(offset)
    deps = (await db.execute(query)).scalars().all()
    return list(deps), total
