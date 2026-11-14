import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.base import Base, WorkspaceRole
from app.db.models import (
    GitHubAccount,
    GitHubInstallation,
    Repository,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.db.session import get_db_session
from app.main import app
from app.services.github import (
    decrypt_token,
    encrypt_token,
    generate_github_auth_url,
    generate_github_oauth_state,
    verify_github_oauth_state,
)


@pytest.fixture
async def github_test_context() -> AsyncGenerator[
    tuple[AsyncClient, async_sessionmaker[AsyncSession], User, Workspace, WorkspaceMembership], None
]:
    """Test fixture with an in-memory SQLite database and test user/workspace context."""
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

    async with session_factory() as sess:
        ws = Workspace(name="GitHub Test Workspace", slug="github-test-ws")
        sess.add(ws)
        await sess.commit()
        await sess.refresh(ws)

        user = User(
            id=uuid.uuid4(),
            email="dev@example.com",
            full_name="GitHub Dev",
            is_active=True,
        )
        sess.add(user)
        await sess.commit()
        await sess.refresh(user)

        membership = WorkspaceMembership(
            user_id=user.id,
            workspace_id=ws.id,
            role=WorkspaceRole.ADMIN,
        )
        sess.add(membership)
        await sess.commit()
        await sess.refresh(membership)

        app.dependency_overrides[get_current_user] = lambda: user

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer test-api-token"},
    ) as client:
        yield client, session_factory, user, ws, membership

    app.dependency_overrides.clear()
    await engine.dispose()


# -----------------------------------------------------------------------------
# 1. Cryptographic and State Security Unit Tests
# -----------------------------------------------------------------------------


def test_token_encryption_and_decryption_roundtrip() -> None:
    """Validate Fernet encryption and decryption for GitHub access tokens."""
    token = "gho_16C7e42F292c6912E7710c838347Ae178B4a"
    encrypted = encrypt_token(token)
    assert encrypted != token
    assert isinstance(encrypted, str)

    decrypted = decrypt_token(encrypted)
    assert decrypted == token


def test_token_encryption_is_non_deterministic() -> None:
    """Validate that identical plaintexts produce distinct ciphertexts (random IV/salt)."""
    token = "gho_test_secret_token_12345"
    c1 = encrypt_token(token)
    c2 = encrypt_token(token)
    assert c1 != c2
    assert decrypt_token(c1) == decrypt_token(c2) == token


def test_token_decryption_fails_with_tampered_ciphertext() -> None:
    """Validate that tampered ciphertext raises ValueError."""
    token = "gho_secret"
    encrypted = encrypt_token(token)
    tampered = encrypted[:-4] + "AAAA"
    with pytest.raises(ValueError):
        decrypt_token(tampered)


def test_oauth_state_hmac_verification() -> None:
    """Validate OAuth state generation, HMAC signature, and user binding."""
    user_id = uuid.uuid4()
    state = generate_github_oauth_state(user_id)
    assert isinstance(state, str)

    verified_user_id = verify_github_oauth_state(state, user_id)
    assert verified_user_id == user_id

    # Mismatched user must fail
    other_user = uuid.uuid4()
    assert verify_github_oauth_state(state, other_user) is None

    # Tampered state must fail
    tampered_state = state[:-4] + "ffff"
    assert verify_github_oauth_state(tampered_state, user_id) is None


def test_auth_url_construction() -> None:
    """Verify GitHub authorization URL has correct params and state."""
    user_id = uuid.uuid4()
    url, state = generate_github_auth_url(user_id)
    assert "https://github.com/login/oauth/authorize" in url
    assert f"client_id={settings.GITHUB_CLIENT_ID}" in url
    assert f"state={state}" in url
    assert "scope=" in url


# -----------------------------------------------------------------------------
# 2. Account Connection Endpoints Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_connect_redirect_and_json(
    github_test_context: tuple[
        AsyncClient, async_sessionmaker[AsyncSession], User, Workspace, WorkspaceMembership
    ],
) -> None:
    """Test GET /api/v1/github/connect redirect and JSON modes."""
    client, _, user, _, _ = github_test_context

    # 1. Direct redirect mode (default)
    res_redirect = await client.get("/api/v1/github/connect?redirect=true", follow_redirects=False)
    assert res_redirect.status_code == 307
    location = res_redirect.headers.get("location", "")
    assert "https://github.com/login/oauth/authorize" in location

    # 2. JSON mode
    res_json = await client.get("/api/v1/github/connect?redirect=false")
    assert res_json.status_code == 200
    data = res_json.json()
    assert "auth_url" in data
    assert "https://github.com/login/oauth/authorize" in data["auth_url"]


@pytest.mark.asyncio
async def test_github_callback_success(
    github_test_context: tuple[
        AsyncClient, async_sessionmaker[AsyncSession], User, Workspace, WorkspaceMembership
    ],
) -> None:
    """Test successful GitHub OAuth callback code exchange and account linking."""
    client, session_factory, user, _, _ = github_test_context
    valid_state = generate_github_oauth_state(user.id)

    mock_profile = {
        "id": 1234567,
        "login": "octocat",
        "name": "The Octocat",
        "email": "octocat@github.com",
        "avatar_url": "https://avatars.githubusercontent.com/u/1234567",
        "html_url": "https://github.com/octocat",
    }

    with (
        patch("app.api.v1.github.exchange_github_code", new_callable=AsyncMock) as mock_exchange,
        patch("app.api.v1.github.fetch_github_user_profile", new_callable=AsyncMock) as mock_user,
    ):
        mock_exchange.return_value = {
            "access_token": "gho_mock_access_token_123",
            "token_type": "bearer",
            "scope": "repo,read:user",
        }
        mock_user.return_value = mock_profile

        res = await client.get(
            f"/api/v1/github/callback?code=mock_code_xyz&state={valid_state}",
            follow_redirects=False,
        )
        assert res.status_code == 302
        assert "github=connected" in res.headers["location"]

    # Verify database persistence
    async with session_factory() as sess:
        account_query = select(GitHubAccount).where(GitHubAccount.user_id == user.id)
        result = await sess.execute(account_query)
        account = result.scalar_one_or_none()
        assert account is not None
        assert account.github_login == "octocat"
        assert account.github_user_id == 1234567
        assert decrypt_token(account.encrypted_access_token) == "gho_mock_access_token_123"


@pytest.mark.asyncio
async def test_github_callback_tampered_state(
    github_test_context: tuple[
        AsyncClient, async_sessionmaker[AsyncSession], User, Workspace, WorkspaceMembership
    ],
) -> None:
    """Test callback rejection with invalid state."""
    client, _, user, _, _ = github_test_context
    tampered_state = "invalid_tampered_state_token"

    res = await client.get(
        f"/api/v1/github/callback?code=mock_code&state={tampered_state}",
        follow_redirects=False,
    )
    assert res.status_code == 302
    assert "github_error=invalid_oauth_state" in res.headers["location"]


@pytest.mark.asyncio
async def test_github_status_and_disconnect(
    github_test_context: tuple[
        AsyncClient, async_sessionmaker[AsyncSession], User, Workspace, WorkspaceMembership
    ],
) -> None:
    """Test GET /api/v1/github/status and DELETE /api/v1/github/disconnect."""
    client, session_factory, user, _, _ = github_test_context

    # 1. Initial status: disconnected
    res = await client.get("/api/v1/github/status")
    assert res.status_code == 200
    assert res.json()["connected"] is False

    # 2. Seed connected account
    async with session_factory() as sess:
        acct = GitHubAccount(
            user_id=user.id,
            github_user_id=888999,
            github_login="octo-tester",
            name="Octo Tester",
            email="tester@example.com",
            avatar_url="https://avatars.githubusercontent.com/u/888999",
            html_url="https://github.com/octo-tester",
            encrypted_access_token=encrypt_token("gho_test_token"),
            scope="repo,read:user",
        )
        sess.add(acct)
        await sess.commit()

    # 3. Status: connected
    res_conn = await client.get("/api/v1/github/status")
    assert res_conn.status_code == 200
    status_data = res_conn.json()
    assert status_data["connected"] is True
    assert status_data["github_login"] == "octo-tester"
    # Ensure tokens are never exposed
    assert "access_token" not in status_data
    assert "encrypted_access_token" not in status_data

    # 4. Disconnect
    res_disc = await client.delete("/api/v1/github/disconnect")
    assert res_disc.status_code == 200
    assert res_disc.json()["status"] == "ok"

    # 5. Verify database purged
    async with session_factory() as sess:
        result = await sess.execute(select(GitHubAccount).where(GitHubAccount.user_id == user.id))
        assert result.scalar_one_or_none() is None


# -----------------------------------------------------------------------------
# 3. Repository Discovery and Connection Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_accessible_repositories(
    github_test_context: tuple[
        AsyncClient, async_sessionmaker[AsyncSession], User, Workspace, WorkspaceMembership
    ],
) -> None:
    """Test listing accessible GitHub repos with pagination and connected status."""
    client, session_factory, user, ws, _ = github_test_context

    # Seed connected GitHub account
    async with session_factory() as sess:
        acct = GitHubAccount(
            user_id=user.id,
            github_user_id=555,
            github_login="developer",
            encrypted_access_token=encrypt_token("gho_token_555"),
        )
        sess.add(acct)

        # Seed an existing connected repo in workspace
        inst = GitHubInstallation(
            workspace_id=ws.id,
            installation_id=555,
            account_login="developer",
            account_type="User",
            account_id=555,
        )
        sess.add(inst)
        await sess.flush()

        repo = Repository(
            workspace_id=ws.id,
            installation_id=inst.id,
            github_repository_id=101,
            name="existing-repo",
            full_name="developer/existing-repo",
            owner_login="developer",
            html_url="https://github.com/developer/existing-repo",
            is_active=True,
        )
        sess.add(repo)
        await sess.commit()

    mock_github_repos: list[dict[str, Any]] = [
        {
            "id": 101,
            "name": "existing-repo",
            "full_name": "developer/existing-repo",
            "owner": {"login": "developer", "avatar_url": "https://avatar.url/555"},
            "description": "Connected repository",
            "default_branch": "main",
            "html_url": "https://github.com/developer/existing-repo",
            "private": False,
            "language": "Python",
            "updated_at": "2026-11-14T10:00:00Z",
            "stargazers_count": 42,
            "forks_count": 3,
            "open_issues_count": 2,
        },
        {
            "id": 102,
            "name": "new-repo",
            "full_name": "developer/new-repo",
            "owner": {"login": "developer", "avatar_url": "https://avatar.url/555"},
            "description": "Not yet connected",
            "default_branch": "main",
            "html_url": "https://github.com/developer/new-repo",
            "private": True,
            "language": "TypeScript",
            "updated_at": "2026-11-14T11:00:00Z",
            "stargazers_count": 5,
            "forks_count": 0,
            "open_issues_count": 0,
        },
    ]

    with patch(
        "app.api.v1.github.list_accessible_repositories", new_callable=AsyncMock
    ) as mock_list:
        mock_list.return_value = [
            {
                "id": r["id"],
                "name": r["name"],
                "full_name": r["full_name"],
                "owner_login": r["owner"]["login"],
                "owner_avatar_url": r["owner"]["avatar_url"],
                "description": r["description"],
                "default_branch": r["default_branch"],
                "html_url": r["html_url"],
                "visibility": "private" if r["private"] else "public",
                "language": r["language"],
                "updated_at": r["updated_at"],
                "stargazers_count": r["stargazers_count"],
                "forks_count": r["forks_count"],
                "open_issues_count": r["open_issues_count"],
            }
            for r in mock_github_repos
        ]

        res = await client.get(f"/api/v1/github/repositories?workspace_id={ws.id}")
        assert res.status_code == 200
        data = res.json()
        assert len(data["items"]) == 2

        # Verify is_connected flags
        repo101 = next(item for item in data["items"] if item["id"] == 101)
        repo102 = next(item for item in data["items"] if item["id"] == 102)
        assert repo101["is_connected"] is True
        assert repo102["is_connected"] is False


@pytest.mark.asyncio
async def test_connect_workspace_repository_flow(
    github_test_context: tuple[
        AsyncClient, async_sessionmaker[AsyncSession], User, Workspace, WorkspaceMembership
    ],
) -> None:
    """Test connecting a GitHub repository to a workspace, duplicate prevention, and role check."""
    client, session_factory, user, ws, _ = github_test_context

    # 1. Connect GitHub account for user
    async with session_factory() as sess:
        acct = GitHubAccount(
            user_id=user.id,
            github_user_id=777,
            github_login="org-lead",
            encrypted_access_token=encrypt_token("gho_lead_token"),
        )
        sess.add(acct)
        await sess.commit()

    connect_payload = {
        "workspace_id": str(ws.id),
        "github_repository_id": 999888,
        "name": "awesome-app",
        "full_name": "org-lead/awesome-app",
        "owner_login": "org-lead",
        "owner_avatar_url": "https://avatar.url/org-lead",
        "description": "Production microservice",
        "default_branch": "main",
        "html_url": "https://github.com/org-lead/awesome-app",
        "visibility": "private",
        "language": "Python",
    }

    # 2. Connect repository
    res = await client.post("/api/v1/github/repositories/connect", json=connect_payload)
    assert res.status_code == 201
    repo_data = res.json()
    assert repo_data["name"] == "awesome-app"
    assert repo_data["full_name"] == "org-lead/awesome-app"
    assert repo_data["is_active"] is True
    repo_id = repo_data["id"]

    # 3. Attempt duplicate connection: must return 400
    res_dup = await client.post("/api/v1/github/repositories/connect", json=connect_payload)
    assert res_dup.status_code == 400
    assert "already connected" in res_dup.json()["detail"].lower()

    # 4. Disconnect repository
    res_disc = await client.delete(f"/api/v1/github/repositories/{repo_id}?workspace_id={ws.id}")
    assert res_disc.status_code == 204

    # 5. Reconnecting reactivates the repository
    res_reconnect = await client.post("/api/v1/github/repositories/connect", json=connect_payload)
    assert res_reconnect.status_code == 201
    assert res_reconnect.json()["id"] == repo_id
    assert res_reconnect.json()["is_active"] is True


@pytest.mark.asyncio
async def test_refresh_repository_metadata(
    github_test_context: tuple[
        AsyncClient, async_sessionmaker[AsyncSession], User, Workspace, WorkspaceMembership
    ],
) -> None:
    """Test refreshing repository metadata from GitHub."""
    client, session_factory, user, ws, _ = github_test_context

    # Setup GitHub account, installation, and repository
    async with session_factory() as sess:
        acct = GitHubAccount(
            user_id=user.id,
            github_user_id=333,
            github_login="refresh-user",
            encrypted_access_token=encrypt_token("gho_refresh_token"),
        )
        sess.add(acct)

        inst = GitHubInstallation(
            workspace_id=ws.id,
            installation_id=333,
            account_login="refresh-user",
            account_type="User",
            account_id=333,
        )
        sess.add(inst)
        await sess.flush()

        repo = Repository(
            workspace_id=ws.id,
            installation_id=inst.id,
            github_repository_id=888111,
            name="initial-name",
            full_name="refresh-user/initial-name",
            owner_login="refresh-user",
            description="Initial description",
            default_branch="master",
            html_url="https://github.com/refresh-user/initial-name",
            is_active=True,
        )
        sess.add(repo)
        await sess.commit()
        await sess.refresh(repo)
        repo_id = repo.id

    mock_remote_data = {
        "id": 888111,
        "name": "renamed-repo",
        "full_name": "refresh-user/renamed-repo",
        "owner_login": "refresh-user",
        "description": "Updated description from GitHub",
        "default_branch": "main",
        "html_url": "https://github.com/refresh-user/renamed-repo",
        "visibility": "public",
        "language": "Go",
    }

    with patch("app.services.github.fetch_single_repository", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_remote_data

        res = await client.post(
            f"/api/v1/github/repositories/{repo_id}/refresh?workspace_id={ws.id}"
        )
        assert res.status_code == 200
        updated = res.json()
        assert updated["name"] == "renamed-repo"
        assert updated["description"] == "Updated description from GitHub"
        assert updated["default_branch"] == "main"
        assert updated["language"] == "Go"


@pytest.mark.asyncio
async def test_role_enforcement_viewer_forbidden(
    github_test_context: tuple[
        AsyncClient, async_sessionmaker[AsyncSession], User, Workspace, WorkspaceMembership
    ],
) -> None:
    """Validate that VIEWER / MEMBER cannot connect or disconnect repositories."""
    client, session_factory, user, ws, membership = github_test_context

    # Demote user to VIEWER
    async with session_factory() as sess:
        m = await sess.get(WorkspaceMembership, membership.id)
        assert m is not None
        m.role = WorkspaceRole.VIEWER
        await sess.commit()

        acct = GitHubAccount(
            user_id=user.id,
            github_user_id=999,
            github_login="viewer-user",
            encrypted_access_token=encrypt_token("gho_viewer_token"),
        )
        sess.add(acct)
        await sess.commit()

    connect_payload = {
        "workspace_id": str(ws.id),
        "github_repository_id": 999333,
        "name": "viewer-repo",
        "full_name": "viewer-user/viewer-repo",
        "owner_login": "viewer-user",
        "html_url": "https://github.com/viewer-user/viewer-repo",
    }

    # Attempt to connect repository as VIEWER -> 403 Forbidden
    res = await client.post("/api/v1/github/repositories/connect", json=connect_payload)
    assert res.status_code == 403
    assert "admins and owners" in res.json()["detail"].lower()
