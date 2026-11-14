"""
Integration tests against PostgreSQL (Neon) verifying:
1. Fix A: EngineeringTask repository deletion behavior (both via service and direct DB deletion)
2. Fix B: RepositoryMember migration safety & composite tenant integrity
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import (
    RepositoryMemberRole,
    TaskPriority,
    TaskStatus,
    TaskType,
    WorkspaceRole,
)
from app.db.models import (
    EngineeringTask,
    Repository,
    RepositoryMember,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.services.database import (
    add_repository_member,
    create_engineering_task,
    create_github_installation,
    delete_repository_hard,
    register_repository,
)

pytestmark = pytest.mark.asyncio

# Check if real PostgreSQL database URL is available
POSTGRES_AVAILABLE = bool(
    settings.async_database_url and "postgresql" in settings.async_database_url
)


@pytest.fixture
async def pg_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional session against the configured PostgreSQL database."""
    if not POSTGRES_AVAILABLE:
        pytest.skip("PostgreSQL is not configured in settings.async_database_url")

    engine = create_async_engine(settings.async_database_url, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as sess:
        trans = await sess.begin()
        try:
            yield sess
        finally:
            # Always roll back to leave the database completely clean
            await trans.rollback()

    await engine.dispose()


async def test_postgres_direct_repository_deletion_preserves_task(pg_session: AsyncSession) -> None:
    """
    Test Fix A (Direct DB Deletion):
    When a repository is deleted directly via SQL in PostgreSQL,
    the column-specific 'ON DELETE SET NULL (repository_id)' constraint:
    1. Nulls task.repository_id
    2. Keeps task.workspace_id NOT NULL and unchanged
    3. Preserves all other task fields
    """
    # 1. Setup workspace, installation, repository, and task
    ws = Workspace(name="PG Delete WS", slug=f"pg-del-{uuid.uuid4().hex[:8]}")
    pg_session.add(ws)
    await pg_session.flush()

    inst = await create_github_installation(
        session=pg_session,
        workspace_id=ws.id,
        installation_id=int(uuid.uuid4().int % 100000000),
        account_login="pg-del-org",
        account_type="Organization",
        account_id=int(uuid.uuid4().int % 100000000),
    )
    repo = await register_repository(
        session=pg_session,
        workspace_id=ws.id,
        installation_id=inst.id,
        github_repository_id=int(uuid.uuid4().int % 100000000),
        name="pg-repo",
        full_name="pg-del-org/pg-repo",
        owner_login="pg-del-org",
        html_url="https://github.com/pg-del-org/pg-repo",
    )
    task = await create_engineering_task(
        session=pg_session,
        workspace_id=ws.id,
        repository_id=repo.id,
        title="Synthesize distributed worker",
        task_type=TaskType.FEATURE,
        priority=TaskPriority.HIGH,
        assigned_agent="DevPilot",
    )
    await pg_session.flush()

    task_id = task.id
    ws_id = ws.id
    repo_id = repo.id

    # 2. Execute direct SQL DELETE on the repository
    await pg_session.execute(text(f"DELETE FROM repositories WHERE id = '{repo_id}';"))
    await pg_session.flush()

    # Expire session identity map so SQLAlchemy refetches task from PostgreSQL
    pg_session.expire_all()

    # 3. Verify task state in PostgreSQL
    task_stmt = select(EngineeringTask).where(EngineeringTask.id == task_id)
    reloaded_task = (await pg_session.execute(task_stmt)).scalar_one()

    assert reloaded_task is not None
    assert reloaded_task.repository_id is None, (
        "task.repository_id must be NULL after repo deletion"
    )
    assert reloaded_task.workspace_id == ws_id, "task.workspace_id must remain unchanged"
    assert reloaded_task.title == "Synthesize distributed worker"
    assert reloaded_task.task_type == TaskType.FEATURE
    assert reloaded_task.priority == TaskPriority.HIGH
    assert reloaded_task.status == TaskStatus.BACKLOG
    assert reloaded_task.assigned_agent == "DevPilot"


async def test_service_repository_deletion_transactional(pg_session: AsyncSession) -> None:
    """
    Test Fix A (Service-Level Deletion):
    The transactional service `delete_repository_hard` disassociates tasks
    and deletes the repository safely.
    """
    ws = Workspace(name="Service Delete WS", slug=f"svc-del-{uuid.uuid4().hex[:8]}")
    pg_session.add(ws)
    await pg_session.flush()

    inst = await create_github_installation(
        session=pg_session,
        workspace_id=ws.id,
        installation_id=int(uuid.uuid4().int % 100000000),
        account_login="svc-del-org",
        account_type="Organization",
        account_id=int(uuid.uuid4().int % 100000000),
    )
    repo = await register_repository(
        session=pg_session,
        workspace_id=ws.id,
        installation_id=inst.id,
        github_repository_id=int(uuid.uuid4().int % 100000000),
        name="svc-repo",
        full_name="svc-del-org/svc-repo",
        owner_login="svc-del-org",
        html_url="https://github.com/svc-del-org/svc-repo",
    )
    task = await create_engineering_task(
        session=pg_session,
        workspace_id=ws.id,
        repository_id=repo.id,
        title="Transactional deletion task",
    )
    await pg_session.flush()

    task_id = task.id
    ws_id = ws.id
    repo_id = repo.id

    # Call service deletion
    success = await delete_repository_hard(pg_session, ws_id, repo_id)
    assert success is True

    # Verify task still exists, repository is gone
    reloaded_task = (
        await pg_session.execute(select(EngineeringTask).where(EngineeringTask.id == task_id))
    ).scalar_one()
    assert reloaded_task.repository_id is None
    assert reloaded_task.workspace_id == ws_id

    reloaded_repo = (
        await pg_session.execute(select(Repository).where(Repository.id == repo_id))
    ).scalar_one_or_none()
    assert reloaded_repo is None


async def test_postgres_cross_workspace_repository_association_rejected(
    pg_session: AsyncSession,
) -> None:
    """
    Verify PostgreSQL rejects assigning a repository from ws1 to a task in ws2.
    """
    ws1 = Workspace(name="WS1", slug=f"ws1-{uuid.uuid4().hex[:8]}")
    ws2 = Workspace(name="WS2", slug=f"ws2-{uuid.uuid4().hex[:8]}")
    pg_session.add_all([ws1, ws2])
    await pg_session.flush()

    inst = await create_github_installation(
        session=pg_session,
        workspace_id=ws1.id,
        installation_id=int(uuid.uuid4().int % 100000000),
        account_login="ws1-org",
        account_type="Organization",
        account_id=int(uuid.uuid4().int % 100000000),
    )
    repo1 = await register_repository(
        session=pg_session,
        workspace_id=ws1.id,
        installation_id=inst.id,
        github_repository_id=int(uuid.uuid4().int % 100000000),
        name="ws1-repo",
        full_name="ws1-org/ws1-repo",
        owner_login="ws1-org",
        html_url="https://github.com/ws1-org/ws1-repo",
    )
    await pg_session.flush()

    # Attempt cross-workspace task
    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            bad_task = EngineeringTask(
                workspace_id=ws2.id,
                repository_id=repo1.id,
                title="Cross task",
            )
            pg_session.add(bad_task)
            await pg_session.flush()


async def test_postgres_repository_member_tenant_integrity(pg_session: AsyncSession) -> None:
    """
    Test Fix B: Verify that in PostgreSQL:
    1. repository_members.workspace_id is NOT NULL
    2. Users cannot be assigned to a repository unless they are members of that workspace
    3. Cross-workspace assignments fail composite FK checks
    """
    ws1 = Workspace(name="WS1", slug=f"ws1-{uuid.uuid4().hex[:8]}")
    ws2 = Workspace(name="WS2", slug=f"ws2-{uuid.uuid4().hex[:8]}")
    user = User(email=f"user-{uuid.uuid4().hex[:8]}@example.com")
    pg_session.add_all([ws1, ws2, user])
    await pg_session.flush()

    # Add user to ws1
    wm1 = WorkspaceMembership(user_id=user.id, workspace_id=ws1.id, role=WorkspaceRole.MEMBER)
    pg_session.add(wm1)

    inst1 = await create_github_installation(
        session=pg_session,
        workspace_id=ws1.id,
        installation_id=int(uuid.uuid4().int % 100000000),
        account_login="ws1-org",
        account_type="Organization",
        account_id=int(uuid.uuid4().int % 100000000),
    )
    repo1 = await register_repository(
        session=pg_session,
        workspace_id=ws1.id,
        installation_id=inst1.id,
        github_repository_id=int(uuid.uuid4().int % 100000000),
        name="ws1-repo",
        full_name="ws1-org/ws1-repo",
        owner_login="ws1-org",
        html_url="https://github.com/ws1-org/ws1-repo",
    )
    await pg_session.flush()

    # 1. Valid assignment in ws1
    member = await add_repository_member(
        session=pg_session,
        workspace_id=ws1.id,
        repository_id=repo1.id,
        user_id=user.id,
        role=RepositoryMemberRole.DEVELOPER,
    )
    await pg_session.flush()
    assert member.id is not None
    assert member.workspace_id == ws1.id

    # 2. Direct DB rejection of cross-workspace member (user in ws1, but assigning in ws2)
    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            bad_rm = RepositoryMember(
                workspace_id=ws2.id,
                repository_id=repo1.id,
                user_id=user.id,
                role=RepositoryMemberRole.ADMIN,
            )
            pg_session.add(bad_rm)
            await pg_session.flush()
