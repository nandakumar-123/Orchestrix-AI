import uuid
from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base, WorkspaceRole
from app.db.models.membership import WorkspaceMembership
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db_session
from app.main import app
from app.services.auth import (
    OAUTH_TRANSIT_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    create_auth_session,
    encode_transit_token,
    hash_session_token,
    validate_session_token,
)


@pytest.fixture
async def auth_test_context() -> AsyncGenerator[
    tuple[AsyncClient, async_sessionmaker[AsyncSession]], None
]:
    """Test harness using an isolated in-memory SQLite database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_get_db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, session_factory

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_session_lifecycle(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test server-side session creation, validation, expiration, and revocation."""
    _, session_factory = auth_test_context

    async with session_factory() as db:
        user = User(
            id=uuid.uuid4(),
            email="testuser@example.com",
            full_name="Test User",
            is_active=True,
        )
        db.add(user)
        await db.commit()

        # 1. Create session
        session_obj, raw_token = await create_auth_session(
            db=db,
            user_id=user.id,
            ip_address="127.0.0.1",
            user_agent="pytest",
        )
        assert session_obj.token_hash == hash_session_token(raw_token)
        assert session_obj.is_revoked is False

        # 2. Validate valid session
        val_result = await validate_session_token(db, raw_token)
        assert val_result is not None
        v_sess, v_user = val_result
        assert v_user.id == user.id
        assert v_sess.last_accessed_at is not None

        # 3. Inactive user fails validation
        user.is_active = False
        await db.commit()
        assert await validate_session_token(db, raw_token) is None
        user.is_active = True
        await db.commit()

        # 4. Revocation
        session_obj.is_revoked = True
        await db.commit()
        assert await validate_session_token(db, raw_token) is None


@pytest.mark.asyncio
async def test_google_login_redirect(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test GET /auth/google/login sets transit cookie and redirects to Google."""
    client, _ = auth_test_context

    with patch.object(settings, "GOOGLE_CLIENT_ID", "test-google-client-id"):
        response = await client.get("/auth/google/login", follow_redirects=False)
        assert response.status_code == 307
        assert "location" in response.headers
        location = response.headers["location"]
        assert "accounts.google.com" in location
        assert "code_challenge=" in location
        assert "code_challenge_method=S256" in location
        assert "state=" in location
        assert "nonce=" in location

        # Verify transit cookie set
        assert OAUTH_TRANSIT_COOKIE_NAME in response.cookies


@pytest.mark.asyncio
async def test_google_callback_security_checks(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test callback rejects invalid state, missing transit cookie, or Google errors."""
    client, _ = auth_test_context

    # 1. Error returned from Google
    resp1 = await client.get("/auth/google/callback?error=access_denied", follow_redirects=False)
    assert resp1.status_code == 302
    assert "error=access_denied" in resp1.headers["location"]

    # 2. Missing transit cookie
    resp2 = await client.get("/auth/google/callback?code=abc&state=xyz", follow_redirects=False)
    assert resp2.status_code == 302
    assert "error=invalid_oauth_state" in resp2.headers["location"]

    # 3. State mismatch
    transit_token = encode_transit_token("valid_state", "valid_nonce", "valid_verifier")
    client.cookies.set(OAUTH_TRANSIT_COOKIE_NAME, transit_token)
    resp3 = await client.get(
        "/auth/google/callback?code=abc&state=wrong_state", follow_redirects=False
    )
    assert resp3.status_code == 302
    assert "error=state_mismatch" in resp3.headers["location"]


@pytest.mark.asyncio
async def test_google_callback_unverified_email(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test callback rejects Google accounts with email_verified=False."""
    client, _ = auth_test_context

    transit_token = encode_transit_token("mystate", "mynonce", "myverifier")
    client.cookies.set(OAUTH_TRANSIT_COOKIE_NAME, transit_token)

    mock_claims = {
        "sub": "sub-12345",
        "email": "unverified@example.com",
        "email_verified": False,
        "name": "Unverified User",
    }

    with (
        patch("app.api.v1.auth.exchange_google_code", return_value={"id_token": "mock_id_token"}),
        patch("app.api.v1.auth.verify_google_id_token", return_value=mock_claims),
    ):
        response = await client.get(
            "/auth/google/callback?code=auth_code_123&state=mystate",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "error=unverified_email" in response.headers["location"]


@pytest.mark.asyncio
async def test_google_callback_success_provisions_user_and_workspace(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test successful OAuth exchange provisions user, default workspace, and sets session cookie."""
    client, session_factory = auth_test_context

    transit_token = encode_transit_token("state_abc", "nonce_abc", "verifier_abc")
    client.cookies.set(OAUTH_TRANSIT_COOKIE_NAME, transit_token)

    mock_claims = {
        "sub": "sub-google-99999",
        "email": "sarah.connor@example.com",
        "email_verified": True,
        "name": "Sarah Connor",
        "picture": "https://example.com/avatar.png",
    }

    with (
        patch("app.api.v1.auth.exchange_google_code", return_value={"id_token": "valid_token"}),
        patch("app.api.v1.auth.verify_google_id_token", return_value=mock_claims),
    ):
        response = await client.get(
            "/auth/google/callback?code=mock_code&state=state_abc",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"].endswith("/dashboard")
        assert SESSION_COOKIE_NAME in response.cookies
        session_token = response.cookies[SESSION_COOKIE_NAME]

    # Verify database records
    async with session_factory() as db:
        user_sess = await validate_session_token(db, session_token)
        assert user_sess is not None
        _, user = user_sess
        assert user.email == "sarah.connor@example.com"
        assert user.google_sub == "sub-google-99999"
        assert user.email_verified is True
        assert user.full_name == "Sarah Connor"

        # Check /api/v1/auth/me endpoint with this session cookie
        client.cookies.set(SESSION_COOKIE_NAME, session_token)
        me_resp = await client.get("/api/v1/auth/me")
        assert me_resp.status_code == 200
        me_data = me_resp.json()
        assert me_data["email"] == "sarah.connor@example.com"
        assert len(me_data["workspaces"]) == 1
        assert me_data["workspaces"][0]["role"] == "OWNER"
        assert "Sarah Connor" in me_data["workspaces"][0]["name"]


@pytest.mark.asyncio
async def test_auth_logout(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test POST /api/v1/auth/logout revokes session in DB and clears session cookie."""
    client, session_factory = auth_test_context

    # Create user and session
    async with session_factory() as db:
        user = User(
            id=uuid.uuid4(),
            email="logout_test@example.com",
            full_name="Logout User",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        _, raw_token = await create_auth_session(db, user.id)

    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    # Validate active
    me_before = await client.get("/api/v1/auth/me")
    assert me_before.status_code == 200

    # Logout
    logout_resp = await client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 200
    assert logout_resp.json()["status"] == "ok"

    # Validate unauthenticated afterwards
    me_after = await client.get("/api/v1/auth/me")
    assert me_after.status_code == 401


@pytest.mark.asyncio
async def test_workspace_membership_authorization(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test role hierarchy and cross-workspace tenant authorization."""
    client, session_factory = auth_test_context

    async with session_factory() as db:
        # Workspace 1 & 2
        ws1 = Workspace(name="Workspace One", slug="ws-one")
        ws2 = Workspace(name="Workspace Two", slug="ws-two")
        db.add_all([ws1, ws2])
        await db.commit()
        await db.refresh(ws1)
        await db.refresh(ws2)

        # User 1: MEMBER in ws1, OWNER in ws2
        user1 = User(id=uuid.uuid4(), email="user1@example.com", is_active=True)
        # User 2: not member in ws1
        user2 = User(id=uuid.uuid4(), email="user2@example.com", is_active=True)
        db.add_all([user1, user2])
        await db.commit()

        m1 = WorkspaceMembership(user_id=user1.id, workspace_id=ws1.id, role=WorkspaceRole.MEMBER)
        m2 = WorkspaceMembership(user_id=user1.id, workspace_id=ws2.id, role=WorkspaceRole.OWNER)
        db.add_all([m1, m2])
        await db.commit()

        _, token_user1 = await create_auth_session(db, user1.id)
        _, token_user2 = await create_auth_session(db, user2.id)

    # 1. Unauthenticated request -> 401
    resp_unauth = await client.get(f"/api/v1/repositories?workspace_id={ws1.id}")
    assert resp_unauth.status_code == 401

    # 2. User 2 is not member of ws1 -> 403 Forbidden
    client.cookies.set(SESSION_COOKIE_NAME, token_user2)
    resp_forbidden = await client.get(f"/api/v1/repositories?workspace_id={ws1.id}")
    assert resp_forbidden.status_code == 403
    assert "not a member of this workspace" in resp_forbidden.json()["detail"]

    # 3. User 1 is MEMBER in ws1 (can read repositories requiring VIEWER)
    client.cookies.set(SESSION_COOKIE_NAME, token_user1)
    resp_member_read = await client.get(f"/api/v1/repositories?workspace_id={ws1.id}")
    assert resp_member_read.status_code == 200

    # 4. User 1 tries to create repository in ws1 (MEMBER < ADMIN required) -> 403 Forbidden
    resp_create_insufficient = await client.post(
        "/api/v1/repositories",
        json={
            "workspace_id": str(ws1.id),
            "installation_id": str(uuid.uuid4()),
            "github_repository_id": 12345,
            "name": "test-repo",
            "full_name": "org/test-repo",
            "owner_login": "org",
            "html_url": "https://github.com/org/test-repo",
        },
    )
    assert resp_create_insufficient.status_code == 403
    assert "ADMIN permission" in resp_create_insufficient.json()["detail"]
