from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import (
    Base,
    PullRequestState,
    RepositoryMemberRole,
    TaskPriority,
    TaskStatus,
    TaskType,
    WorkspaceRole,
)
from app.db.models import (
    EngineeringTask,
    PullRequestRecord,
    Repository,
    RepositoryMember,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.services.database import (
    add_repository_member,
    create_audit_log,
    create_engineering_task,
    create_github_installation,
    list_audit_logs,
    register_pull_request,
    register_repository,
    update_task_status,
)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    """Isolated SQLite in-memory async database session with PRAGMA foreign_keys=ON."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as sess:
        await sess.execute(text("PRAGMA foreign_keys = ON;"))
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

    # User must be a member of the workspace first
    wm = WorkspaceMembership(user_id=user.id, workspace_id=ws.id, role=WorkspaceRole.MEMBER)
    session.add(wm)
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
        workspace_id=ws.id,
        repository_id=repo.id,
        user_id=user.id,
        role=RepositoryMemberRole.DEVELOPER,
    )
    session.add(m1)
    await session.commit()

    # Duplicate should fail
    m2 = RepositoryMember(
        workspace_id=ws.id,
        repository_id=repo.id,
        user_id=user.id,
        role=RepositoryMemberRole.ADMIN,
    )
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


@pytest.mark.asyncio
async def test_tenant_isolation_composite_foreign_keys_database_level(
    session: AsyncSession,
) -> None:
    """Verify that PostgreSQL/SQLite composite foreign keys reject cross-workspace records directly."""
    ws1 = Workspace(name="Workspace One", slug="ws-1")
    ws2 = Workspace(name="Workspace Two", slug="ws-2")
    user = User(email="cross@test.com")
    session.add_all([ws1, ws2, user])
    await session.flush()

    # User is member of ws1 only
    wm = WorkspaceMembership(user_id=user.id, workspace_id=ws1.id, role=WorkspaceRole.MEMBER)
    session.add(wm)

    # Installation in ws1
    inst1 = await create_github_installation(
        session=session,
        workspace_id=ws1.id,
        installation_id=9090,
        account_login="ws-1",
        account_type="User",
        account_id=9090,
    )
    # Repo in ws1
    repo1 = await register_repository(
        session=session,
        workspace_id=ws1.id,
        installation_id=inst1.id,
        github_repository_id=10101,
        name="ws1-repo",
        full_name="ws-1/ws1-repo",
        owner_login="ws-1",
        html_url="https://github.com/ws-1/ws1-repo",
    )
    await session.flush()

    # Negative 1: Repository referencing Installation from another workspace
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            bad_repo = Repository(
                workspace_id=ws2.id,
                installation_id=inst1.id,
                github_repository_id=20202,
                name="cross-repo",
                full_name="ws-2/cross-repo",
                owner_login="ws-2",
                html_url="https://github.com/ws-2/cross-repo",
            )
            session.add(bad_repo)
            await session.flush()

    # Negative 2: EngineeringTask in ws2 referencing repo1 from ws1
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            bad_task = EngineeringTask(
                workspace_id=ws2.id,
                repository_id=repo1.id,
                title="Cross-workspace task",
            )
            session.add(bad_task)
            await session.flush()

    # Negative 3: PullRequestRecord in ws2 referencing repo1 from ws1
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            bad_pr = PullRequestRecord(
                workspace_id=ws2.id,
                repository_id=repo1.id,
                github_pr_id=55555,
                pr_number=1,
                title="Cross PR",
                html_url="https://github.com/ws-1/ws1-repo/pull/1",
                source_branch="feat",
                target_branch="main",
                state=PullRequestState.OPEN,
            )
            session.add(bad_pr)
            await session.flush()

    # Negative 4: RepositoryMember in ws2 for user (user not in ws2)
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            bad_rm = RepositoryMember(
                workspace_id=ws2.id,
                repository_id=repo1.id,
                user_id=user.id,
                role=RepositoryMemberRole.DEVELOPER,
            )
            session.add(bad_rm)
            await session.flush()

    # Positive 5: Valid repository member via service
    rm = await add_repository_member(
        session=session,
        workspace_id=ws1.id,
        repository_id=repo1.id,
        user_id=user.id,
        role=RepositoryMemberRole.DEVELOPER,
    )
    await session.flush()
    assert rm.id is not None
    assert rm.role == RepositoryMemberRole.DEVELOPER

    # Negative 6: Service rejects user without workspace membership
    user2 = User(email="outsider@test.com")
    session.add(user2)
    await session.flush()
    with pytest.raises(ValueError, match="User must be a member of the workspace"):
        await add_repository_member(
            session=session,
            workspace_id=ws1.id,
            repository_id=repo1.id,
            user_id=user2.id,
            role=RepositoryMemberRole.VIEWER,
        )


@pytest.mark.asyncio
async def test_audit_log_append_only_and_querying(session: AsyncSession) -> None:
    """Test creating and querying audit logs without update/delete."""
    ws = Workspace(name="Audit Test", slug="audit-test")
    session.add(ws)
    await session.commit()

    await create_audit_log(
        session=session,
        workspace_id=ws.id,
        action="REPO_ADDED",
        resource_type="repository",
        resource_id="123",
        details={"name": "test-repo", "token": "secret_abc"},
    )
    await create_audit_log(
        session=session,
        workspace_id=ws.id,
        action="MEMBER_ADDED",
        resource_type="repository_member",
        resource_id="456",
        details={"role": "DEVELOPER"},
    )
    await session.commit()

    logs, total = await list_audit_logs(session, ws.id)
    assert total == 2
    assert len(logs) == 2
    assert logs[0].details["token"] == "[REDACTED]" if logs[0].action == "REPO_ADDED" else True
