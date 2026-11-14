import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.db.base import Base, WorkspaceRole
from app.db.models import User, Workspace, WorkspaceMembership


@pytest.fixture
async def test_session() -> AsyncGenerator[AsyncSession, None]:
    """Create an isolated in-memory SQLite database session for unit testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_user_creation_and_fields(test_session: AsyncSession) -> None:
    """Test user creation with UUID, timestamps, and default active state."""
    user = User(
        email="developer@orchestrix.ai",
        full_name="Alex Mercer",
        avatar_url="https://avatar.orchestrix.ai/alex.png",
    )
    test_session.add(user)
    await test_session.commit()
    await test_session.refresh(user)

    assert isinstance(user.id, uuid.UUID)
    assert user.email == "developer@orchestrix.ai"
    assert user.full_name == "Alex Mercer"
    assert user.is_active is True
    assert user.created_at is not None
    assert user.updated_at is not None


@pytest.mark.asyncio
async def test_unique_user_email_constraint(test_session: AsyncSession) -> None:
    """Test that duplicate email addresses are rejected."""
    user1 = User(email="unique@orchestrix.ai", full_name="User One")
    test_session.add(user1)
    await test_session.commit()

    user2 = User(email="unique@orchestrix.ai", full_name="User Two")
    test_session.add(user2)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_workspace_creation_and_slug(test_session: AsyncSession) -> None:
    """Test workspace creation and unique slug enforcement."""
    workspace = Workspace(name="Core Engineering", slug="core-engineering")
    test_session.add(workspace)
    await test_session.commit()
    await test_session.refresh(workspace)

    assert isinstance(workspace.id, uuid.UUID)
    assert workspace.slug == "core-engineering"
    assert workspace.created_at is not None

    # Duplicate slug should fail
    duplicate = Workspace(name="Duplicate Workspace", slug="core-engineering")
    test_session.add(duplicate)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_workspace_membership_relationships(test_session: AsyncSession) -> None:
    """Test user and workspace relationships via WorkspaceMembership with explicit async eager loading."""
    user = User(email="lead@orchestrix.ai", full_name="Lead Architect")
    workspace = Workspace(name="Agent Mesh Team", slug="agent-mesh-team")
    test_session.add_all([user, workspace])
    await test_session.commit()

    membership = WorkspaceMembership(
        user_id=user.id,
        workspace_id=workspace.id,
        role=WorkspaceRole.OWNER,
    )
    test_session.add(membership)
    await test_session.commit()

    # Verify relationships using selectinload for async safe loading
    stmt = select(User).options(selectinload(User.memberships)).where(User.id == user.id)
    result = await test_session.execute(stmt)
    loaded_user = result.scalar_one()

    assert len(loaded_user.memberships) == 1
    assert loaded_user.memberships[0].role == WorkspaceRole.OWNER
    assert loaded_user.memberships[0].workspace_id == workspace.id


@pytest.mark.asyncio
async def test_duplicate_membership_prevention(test_session: AsyncSession) -> None:
    """Test that a user cannot join the same workspace twice."""
    user = User(email="member@orchestrix.ai")
    workspace = Workspace(name="Data Team", slug="data-team")
    test_session.add_all([user, workspace])
    await test_session.commit()

    m1 = WorkspaceMembership(user_id=user.id, workspace_id=workspace.id, role=WorkspaceRole.MEMBER)
    test_session.add(m1)
    await test_session.commit()

    m2 = WorkspaceMembership(user_id=user.id, workspace_id=workspace.id, role=WorkspaceRole.ADMIN)
    test_session.add(m2)
    with pytest.raises(IntegrityError):
        await test_session.commit()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_cascade_delete_user(test_session: AsyncSession) -> None:
    """Test that deleting a user cascades to remove their workspace memberships."""
    user = User(email="temporary@orchestrix.ai")
    workspace = Workspace(name="Test Org", slug="test-org")
    test_session.add_all([user, workspace])
    await test_session.commit()

    membership = WorkspaceMembership(
        user_id=user.id, workspace_id=workspace.id, role=WorkspaceRole.MEMBER
    )
    test_session.add(membership)
    await test_session.commit()

    # Delete user
    await test_session.delete(user)
    await test_session.commit()

    # Membership should no longer exist
    stmt = select(WorkspaceMembership).where(WorkspaceMembership.user_id == user.id)
    res = await test_session.execute(stmt)
    assert res.scalar_one_or_none() is None
