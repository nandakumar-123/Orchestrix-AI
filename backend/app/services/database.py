import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import (
    PullRequestState,
    RepositoryMemberRole,
    TaskPriority,
    TaskStatus,
    TaskType,
    utc_now,
)
from app.db.models import (
    AuditLog,
    EngineeringTask,
    GitHubInstallation,
    PullRequestRecord,
    Repository,
    RepositoryMember,
)

# -----------------------------------------------------------------------------
# GitHub Installation Services
# -----------------------------------------------------------------------------


async def create_github_installation(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    installation_id: int,
    account_login: str,
    account_type: str,
    account_id: int,
) -> GitHubInstallation:
    """Create a new GitHub App installation record for a workspace."""
    installation = GitHubInstallation(
        workspace_id=workspace_id,
        installation_id=installation_id,
        account_login=account_login,
        account_type=account_type,
        account_id=account_id,
    )
    session.add(installation)
    await session.flush()
    return installation


async def get_github_installation(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    installation_id: int,
) -> GitHubInstallation | None:
    """Retrieve an installation scoped by workspace and GitHub installation ID."""
    stmt = select(GitHubInstallation).where(
        GitHubInstallation.workspace_id == workspace_id,
        GitHubInstallation.installation_id == installation_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# -----------------------------------------------------------------------------
# Repository Services
# -----------------------------------------------------------------------------


async def register_repository(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    installation_id: uuid.UUID,
    github_repository_id: int,
    name: str,
    full_name: str,
    owner_login: str,
    description: str | None = None,
    default_branch: str = "main",
    html_url: str = "",
    visibility: str = "private",
    language: str | None = None,
) -> Repository:
    """
    Register a GitHub repository to a workspace under an authorized installation.
    Validates that the installation belongs to the workspace.
    """
    # Enforce tenant isolation between installation and workspace
    inst_stmt = select(GitHubInstallation).where(
        GitHubInstallation.id == installation_id,
        GitHubInstallation.workspace_id == workspace_id,
    )
    inst_res = await session.execute(inst_stmt)
    installation = inst_res.scalar_one_or_none()
    if not installation:
        raise ValueError("Installation does not belong to the target workspace")

    repo = Repository(
        workspace_id=workspace_id,
        installation_id=installation_id,
        github_repository_id=github_repository_id,
        name=name,
        full_name=full_name,
        owner_login=owner_login,
        description=description,
        default_branch=default_branch,
        html_url=html_url,
        visibility=visibility,
        language=language,
    )
    session.add(repo)
    await session.flush()
    return repo


async def list_repositories(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Repository], int]:
    """List active repositories in a workspace with pagination and total count."""
    count_stmt = select(func.count(Repository.id)).where(
        Repository.workspace_id == workspace_id,
        Repository.is_active.is_(True),
    )
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = (
        select(Repository)
        .where(
            Repository.workspace_id == workspace_id,
            Repository.is_active.is_(True),
        )
        .order_by(Repository.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def get_repository_by_id(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    repository_id: uuid.UUID,
) -> Repository | None:
    """Retrieve an active repository strictly scoped to the workspace."""
    stmt = select(Repository).where(
        Repository.id == repository_id,
        Repository.workspace_id == workspace_id,
        Repository.is_active.is_(True),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_repository(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    repository_id: uuid.UUID,
    **kwargs: Any,
) -> Repository | None:
    """Update metadata fields of a workspace-scoped repository."""
    repo = await get_repository_by_id(session, workspace_id, repository_id)
    if not repo:
        return None

    for key, value in kwargs.items():
        if hasattr(repo, key) and value is not None:
            setattr(repo, key, value)

    await session.flush()
    return repo


async def deactivate_repository(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    repository_id: uuid.UUID,
) -> bool:
    """Soft-delete/deactivate a repository within a workspace."""
    repo = await get_repository_by_id(session, workspace_id, repository_id)
    if not repo:
        return False

    repo.is_active = False
    await session.flush()
    return True


# -----------------------------------------------------------------------------
# Repository Member Services
# -----------------------------------------------------------------------------


async def add_repository_member(
    session: AsyncSession,
    repository_id: uuid.UUID,
    user_id: uuid.UUID,
    role: RepositoryMemberRole = RepositoryMemberRole.DEVELOPER,
) -> RepositoryMember:
    """Assign an access role to a workspace member for a specific repository."""
    member = RepositoryMember(
        repository_id=repository_id,
        user_id=user_id,
        role=role,
    )
    session.add(member)
    await session.flush()
    return member


# -----------------------------------------------------------------------------
# Engineering Task Services
# -----------------------------------------------------------------------------


async def create_engineering_task(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    title: str,
    task_type: TaskType = TaskType.GENERAL,
    priority: TaskPriority = TaskPriority.MEDIUM,
    repository_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    description: str | None = None,
    assigned_agent: str | None = None,
    external_issue_id: str | None = None,
) -> EngineeringTask:
    """
    Create an engineering task in a workspace.
    If repository_id is provided, verifies that the repository belongs to the workspace.
    """
    if repository_id is not None:
        repo = await get_repository_by_id(session, workspace_id, repository_id)
        if not repo:
            raise ValueError("Repository does not belong to the target workspace")

    task = EngineeringTask(
        workspace_id=workspace_id,
        repository_id=repository_id,
        created_by=created_by,
        title=title,
        description=description,
        task_type=task_type,
        priority=priority,
        status=TaskStatus.BACKLOG,
        assigned_agent=assigned_agent,
        external_issue_id=external_issue_id,
    )
    session.add(task)
    await session.flush()
    return task


async def list_engineering_tasks(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    status: TaskStatus | None = None,
    repository_id: uuid.UUID | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[EngineeringTask], int]:
    """List engineering tasks scoped to a workspace with filters and pagination."""
    filters = [EngineeringTask.workspace_id == workspace_id]
    if status is not None:
        filters.append(EngineeringTask.status == status)
    if repository_id is not None:
        filters.append(EngineeringTask.repository_id == repository_id)

    count_stmt = select(func.count(EngineeringTask.id)).where(*filters)
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = (
        select(EngineeringTask)
        .where(*filters)
        .order_by(EngineeringTask.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def get_engineering_task_by_id(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
) -> EngineeringTask | None:
    """Retrieve an engineering task strictly scoped to a workspace."""
    stmt = select(EngineeringTask).where(
        EngineeringTask.id == task_id,
        EngineeringTask.workspace_id == workspace_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_task_status(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
    new_status: TaskStatus,
    assigned_agent: str | None = None,
) -> EngineeringTask | None:
    """Update status and assignment of a workspace-scoped engineering task."""
    task = await get_engineering_task_by_id(session, workspace_id, task_id)
    if not task:
        return None

    task.status = new_status
    if assigned_agent is not None:
        task.assigned_agent = assigned_agent

    if new_status == TaskStatus.COMPLETED and task.completed_at is None:
        task.completed_at = utc_now()

    await session.flush()
    return task


# -----------------------------------------------------------------------------
# Pull Request Record Services
# -----------------------------------------------------------------------------


async def register_pull_request(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    repository_id: uuid.UUID,
    github_pr_id: int,
    pr_number: int,
    title: str,
    html_url: str,
    source_branch: str,
    target_branch: str = "main",
    state: PullRequestState = PullRequestState.OPEN,
    task_id: uuid.UUID | None = None,
) -> PullRequestRecord:
    """
    Register a GitHub pull request record scoped to a workspace and repository.
    Verifies that the repository and task (if given) belong to the workspace.
    """
    repo = await get_repository_by_id(session, workspace_id, repository_id)
    if not repo:
        raise ValueError("Repository does not belong to the target workspace")

    if task_id is not None:
        task = await get_engineering_task_by_id(session, workspace_id, task_id)
        if not task:
            raise ValueError("Task does not belong to the target workspace")

    pr_record = PullRequestRecord(
        workspace_id=workspace_id,
        repository_id=repository_id,
        task_id=task_id,
        github_pr_id=github_pr_id,
        pr_number=pr_number,
        title=title,
        html_url=html_url,
        source_branch=source_branch,
        target_branch=target_branch,
        state=state,
    )
    session.add(pr_record)
    await session.flush()
    return pr_record


# -----------------------------------------------------------------------------
# Audit Log Services
# -----------------------------------------------------------------------------


async def create_audit_log(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    action: str,
    resource_type: str,
    actor_user_id: uuid.UUID | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """
    Record an immutable audit log entry scoped to a workspace.
    Safely sanitizes input to ensure no sensitive credentials or keys are logged.
    """
    sanitized_details = details.copy() if details else {}
    for key in list(sanitized_details.keys()):
        if any(
            secret_term in key.lower() for secret_term in ("token", "key", "secret", "password")
        ):
            sanitized_details[key] = "[REDACTED]"

    log = AuditLog(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=sanitized_details,
    )
    session.add(log)
    await session.flush()
    return log
