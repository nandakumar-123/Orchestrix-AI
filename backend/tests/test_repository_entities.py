from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import (
    Base,
    PullRequestState,
    RepositoryMemberRole,
    TaskPriority,
    TaskStatus,
    TaskType,
)
from app.db.models import (
    PullRequestRecord,
    Repository,
    RepositoryMember,
    User,
    Workspace,
)
from app.services.database import (
    create_audit_log,
    create_engineering_task,
    create_github_installation,
    register_pull_request,
    register_repository,
    update_task_status,
)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    """Isolated SQLite in-memory async database session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as sess:
        yield sess

    await engine.dispose()


@pytest.mark.asyncio
async def test_github_installation_and_repository_lifecycle(session: AsyncSession) -> None:
    """Test creating an installation and connecting a repository to a workspace."""
    workspace = Workspace(name="Acme Corp", slug="acme-corp")
    session.add(workspace)
    await session.commit()

    installation = await create_github_installation(
        session=session,
        workspace_id=workspace.id,
        installation_id=98765432,
        account_login="acme-corp",
        account_type="Organization",
        account_id=123456,
    )
    await session.commit()
    assert installation.installation_id == 98765432

    # Register repository
    repo = await register_repository(
        session=session,
        workspace_id=workspace.id,
        installation_id=installation.id,
        github_repository_id=555111,
        name="web-frontend",
        full_name="acme-corp/web-frontend",
        owner_login="acme-corp",
        default_branch="main",
        html_url="https://github.com/acme-corp/web-frontend",
    )
    await session.commit()

    assert repo.id is not None
    assert repo.full_name == "acme-corp/web-frontend"
    assert repo.is_active is True

    # Duplicate repo under same workspace should fail unique constraint
    with pytest.raises(IntegrityError):
        duplicate_repo = Repository(
            workspace_id=workspace.id,
            installation_id=installation.id,
            github_repository_id=555111,
            name="duplicate",
            full_name="acme-corp/web-frontend",
            owner_login="acme-corp",
            html_url="https://github.com/acme-corp/web-frontend",
        )
        session.add(duplicate_repo)
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_tenant_isolation_cross_workspace_installation_rejection(
    session: AsyncSession,
) -> None:
    """Verify that registering a repository under an installation belonging to another workspace is rejected."""
    ws1 = Workspace(name="Workspace One", slug="ws-one")
    ws2 = Workspace(name="Workspace Two", slug="ws-two")
    session.add_all([ws1, ws2])
    await session.commit()

    inst1 = await create_github_installation(
        session=session,
        workspace_id=ws1.id,
        installation_id=1111,
        account_login="ws1",
        account_type="User",
        account_id=1111,
    )
    await session.commit()

    # Attempt to register repo in ws2 using inst1 (from ws1)
    with pytest.raises(ValueError, match="Installation does not belong"):
        await register_repository(
            session=session,
            workspace_id=ws2.id,
            installation_id=inst1.id,
            github_repository_id=9999,
            name="cross-repo",
            full_name="org/cross-repo",
            owner_login="org",
            html_url="https://github.com/org/cross-repo",
        )


@pytest.mark.asyncio
async def test_repository_membership_and_uniqueness(session: AsyncSession) -> None:
    """Test assigning a user to a repository and preventing duplicates."""
    ws = Workspace(name="Dev Org", slug="dev-org")
    user = User(email="dev@acme.com")
    session.add_all([ws, user])
    await session.commit()

    inst = await create_github_installation(
        session=session,
        workspace_id=ws.id,
        installation_id=2222,
        account_login="dev-org",
        account_type="Organization",
        account_id=2222,
    )
    repo = await register_repository(
        session=session,
        workspace_id=ws.id,
        installation_id=inst.id,
        github_repository_id=4444,
        name="backend-api",
        full_name="dev-org/backend-api",
        owner_login="dev-org",
        html_url="https://github.com/dev-org/backend-api",
    )
    await session.commit()

    m1 = RepositoryMember(
        repository_id=repo.id, user_id=user.id, role=RepositoryMemberRole.DEVELOPER
    )
    session.add(m1)
    await session.commit()

    # Duplicate should fail
    m2 = RepositoryMember(repository_id=repo.id, user_id=user.id, role=RepositoryMemberRole.ADMIN)
    session.add(m2)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_engineering_task_lifecycle_and_tenant_scoping(session: AsyncSession) -> None:
    """Test task creation, cross-workspace repository rejection, and status transitions."""
    ws_alpha = Workspace(name="Alpha", slug="alpha")
    ws_beta = Workspace(name="Beta", slug="beta")
    session.add_all([ws_alpha, ws_beta])
    await session.commit()

    inst = await create_github_installation(
        session=session,
        workspace_id=ws_alpha.id,
        installation_id=3333,
        account_login="alpha",
        account_type="User",
        account_id=3333,
    )
    repo_alpha = await register_repository(
        session=session,
        workspace_id=ws_alpha.id,
        installation_id=inst.id,
        github_repository_id=8888,
        name="alpha-core",
        full_name="alpha/alpha-core",
        owner_login="alpha",
        html_url="https://github.com/alpha/alpha-core",
    )
    await session.commit()

    # Reject task in Beta workspace pointing to Alpha's repository
    with pytest.raises(ValueError, match="Repository does not belong"):
        await create_engineering_task(
            session=session,
            workspace_id=ws_beta.id,
            repository_id=repo_alpha.id,
            title="Cross-tenant task",
        )

    # Valid task in Alpha workspace
    task = await create_engineering_task(
        session=session,
        workspace_id=ws_alpha.id,
        repository_id=repo_alpha.id,
        title="Refactor auth middleware",
        task_type=TaskType.REFACTOR,
        priority=TaskPriority.HIGH,
        assigned_agent="DevPilot",
    )
    await session.commit()

    assert task.status == TaskStatus.BACKLOG
    assert task.assigned_agent == "DevPilot"

    # Update status to RUNNING then COMPLETED
    updated = await update_task_status(session, ws_alpha.id, task.id, TaskStatus.RUNNING)
    assert updated is not None
    assert updated.status == TaskStatus.RUNNING

    completed = await update_task_status(session, ws_alpha.id, task.id, TaskStatus.COMPLETED)
    assert completed is not None
    assert completed.status == TaskStatus.COMPLETED
    assert completed.completed_at is not None


@pytest.mark.asyncio
async def test_pull_request_record_and_uniqueness(session: AsyncSession) -> None:
    """Test tracking a pull request record and enforcing uniqueness of repo + pr_number."""
    ws = Workspace(name="PR Org", slug="pr-org")
    session.add(ws)
    await session.commit()

    inst = await create_github_installation(
        session=session,
        workspace_id=ws.id,
        installation_id=4444,
        account_login="pr-org",
        account_type="Organization",
        account_id=4444,
    )
    repo = await register_repository(
        session=session,
        workspace_id=ws.id,
        installation_id=inst.id,
        github_repository_id=7777,
        name="pr-repo",
        full_name="pr-org/pr-repo",
        owner_login="pr-org",
        html_url="https://github.com/pr-org/pr-repo",
    )
    await session.commit()

    pr1 = await register_pull_request(
        session=session,
        workspace_id=ws.id,
        repository_id=repo.id,
        github_pr_id=1234567,
        pr_number=42,
        title="feat: synthesized auth endpoint",
        html_url="https://github.com/pr-org/pr-repo/pull/42",
        source_branch="feature/auth",
        target_branch="main",
        state=PullRequestState.OPEN,
    )
    await session.commit()
    assert pr1.pr_number == 42

    # Duplicate PR #42 in same repository should fail
    with pytest.raises(IntegrityError):
        duplicate_pr = PullRequestRecord(
            workspace_id=ws.id,
            repository_id=repo.id,
            github_pr_id=9999999,
            pr_number=42,
            title="duplicate",
            html_url="https://github.com/pr-org/pr-repo/pull/42",
            source_branch="feature/auth",
            target_branch="main",
            state=PullRequestState.OPEN,
        )
        session.add(duplicate_pr)
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_audit_log_creation_and_credential_sanitization(session: AsyncSession) -> None:
    """Test writing audit records and verifying sensitive secrets are sanitized automatically."""
    ws = Workspace(name="Security Org", slug="sec-org")
    session.add(ws)
    await session.commit()

    audit = await create_audit_log(
        session=session,
        workspace_id=ws.id,
        action="REPOSITORY_CONNECTED",
        resource_type="repository",
        resource_id="acme/api",
        details={
            "repo_name": "acme/api",
            "api_key": "super_secret_token_value",
            "app_secret": "my_secret",
            "safe_metadata": "enabled",
        },
    )
    await session.commit()

    assert audit.action == "REPOSITORY_CONNECTED"
    assert audit.details["safe_metadata"] == "enabled"
    assert audit.details["api_key"] == "[REDACTED]"
    assert audit.details["app_secret"] == "[REDACTED]"
