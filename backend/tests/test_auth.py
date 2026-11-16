import time
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qsl, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base, WorkspaceRole
from app.db.models.membership import WorkspaceMembership
from app.db.models.oauth_transaction import OAuthTransaction
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db_session
from app.main import app
from app.services.auth import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    OAUTH_TRX_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    consume_oauth_transaction,
    create_auth_session,
    create_oauth_transaction,
    exchange_google_code,
    generate_csrf_token,
    generate_google_auth_url,
    hash_secret,
    provision_or_get_google_user,
    validate_session_token,
    verify_google_id_token,
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
        base_url="http://localhost:3000",
    ) as client:
        yield client, session_factory

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_session_lifecycle_and_throttling(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test server-side session creation, validation, expiration, and last_accessed throttling."""
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
        assert session_obj.token_hash == hash_secret(raw_token)
        assert session_obj.is_revoked is False

        # 2. Validate valid session
        val_result = await validate_session_token(db, raw_token)
        assert val_result is not None
        v_sess, v_user = val_result
        assert v_user.id == user.id
        first_accessed = v_sess.last_accessed_at
        assert first_accessed is not None

        # 3. Second validation within 60s should not change last_accessed_at (throttling)
        val_result2 = await validate_session_token(db, raw_token)
        assert val_result2 is not None
        v_sess2, _ = val_result2
        assert v_sess2.last_accessed_at == first_accessed

        # 4. Inactive user fails validation
        user.is_active = False
        await db.commit()
        assert await validate_session_token(db, raw_token) is None
        user.is_active = True
        await db.commit()

        # 5. Revocation
        session_obj.is_revoked = True
        await db.commit()
        assert await validate_session_token(db, raw_token) is None


@pytest.mark.asyncio
async def test_google_login_redirect_creates_server_transaction(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test GET /auth/google/login stores transaction in DB, includes redirect_uri, and sets unguessable cookie."""
    client, session_factory = auth_test_context

    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", "test-google-client-id"),
        patch.object(settings, "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"),
    ):
        response = await client.get("/auth/google/login", follow_redirects=False)
        assert response.status_code == 307
        assert "location" in response.headers
        location = response.headers["location"]
        assert "accounts.google.com" in location
        assert "code_challenge=" in location
        assert "code_challenge_method=S256" in location
        assert "state=" in location
        assert "nonce=" in location
        assert "redirect_uri=" in location

        # Verify decoded redirect_uri exactly matches the configured callback URL
        parsed = urlsplit(location)
        query_params = dict(parse_qsl(parsed.query))
        assert "redirect_uri" in query_params
        assert query_params["redirect_uri"] == "http://localhost:8000/auth/google/callback"

        # Verify browser received only random secret cookie (no verifier/nonce)
        assert OAUTH_TRX_COOKIE_NAME in response.cookies
        cookie_val = response.cookies[OAUTH_TRX_COOKIE_NAME]

    # Verify server-side transaction stored in database
    async with session_factory() as db:
        lookup_hash = hash_secret(cookie_val)
        stmt = select(OAuthTransaction).where(OAuthTransaction.lookup_hash == lookup_hash)
        res = await db.execute(stmt)
        trx = res.scalars().first()
        assert trx is not None
        assert trx.consumed_at is None
        assert trx.code_verifier is not None


def test_google_auth_url_redirect_uri_verification_and_validation() -> None:
    """Test generate_google_auth_url encodes redirect_uri and enforces required configuration."""
    # 1. Valid generation with default settings includes properly encoded redirect_uri
    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", "mock-client-id.apps.googleusercontent.com"),
        patch.object(settings, "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"),
    ):
        url = generate_google_auth_url(
            state="mock_state",
            nonce="mock_nonce",
            code_challenge="mock_challenge",
        )
        assert "redirect_uri=" in url
        parsed = urlsplit(url)
        params = dict(parse_qsl(parsed.query))
        assert params["redirect_uri"] == "http://localhost:8000/auth/google/callback"
        assert params["client_id"] == "mock-client-id.apps.googleusercontent.com"
        assert params["response_type"] == "code"

    # 2. Explicit redirect_uri override is respected and correctly encoded
    custom_uri = "https://app.orchestrix.ai/auth/google/callback"
    with patch.object(settings, "GOOGLE_CLIENT_ID", "mock-client-id"):
        url_custom = generate_google_auth_url(
            state="mock_state",
            nonce="mock_nonce",
            code_challenge="mock_challenge",
            redirect_uri=custom_uri,
        )
        parsed_custom = urlsplit(url_custom)
        params_custom = dict(parse_qsl(parsed_custom.query))
        assert params_custom["redirect_uri"] == custom_uri

    # 3. Missing or empty redirect_uri raises a clear ValueError instead of silent omission
    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", "mock-client-id"),
        patch.object(settings, "GOOGLE_REDIRECT_URI", ""),
    ):
        with pytest.raises(ValueError, match="Google OAuth redirect_uri is not configured"):
            generate_google_auth_url(
                state="mock_state",
                nonce="mock_nonce",
                code_challenge="mock_challenge",
            )

    # 4. Missing or empty client_id raises a clear ValueError
    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", ""),
        patch.object(settings, "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"),
    ):
        with pytest.raises(ValueError, match="Google OAuth client_id is not configured"):
            generate_google_auth_url(
                state="mock_state",
                nonce="mock_nonce",
                code_challenge="mock_challenge",
            )


@pytest.mark.asyncio
async def test_google_login_endpoint_unconfigured_error(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test GET /auth/google/login fails fast with 500 when configuration is incomplete."""
    client, _ = auth_test_context

    # 1. Missing GOOGLE_CLIENT_ID
    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", ""),
        patch.object(settings, "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"),
    ):
        res1 = await client.get("/auth/google/login", follow_redirects=False)
        assert res1.status_code == 500
        assert "not configured" in res1.json()["detail"]

    # 2. Missing GOOGLE_REDIRECT_URI
    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", "test-client-id"),
        patch.object(settings, "GOOGLE_REDIRECT_URI", ""),
    ):
        res2 = await client.get("/auth/google/login", follow_redirects=False)
        assert res2.status_code == 500
        assert "missing client_id or redirect_uri" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_google_token_exchange_missing_redirect_uri() -> None:
    """Test exchange_google_code enforces non-empty redirect_uri configuration."""
    with patch.object(settings, "GOOGLE_REDIRECT_URI", ""):
        with pytest.raises(ValueError, match="Google OAuth redirect_uri is not configured"):
            await exchange_google_code("mock_code", "mock_verifier")


@pytest.mark.asyncio
async def test_oauth_transaction_atomic_consumption_and_replay(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test atomic one-time consumption: first call succeeds, replay and tampered requests fail."""
    _, session_factory = auth_test_context

    async with session_factory() as db:
        trx, browser_secret, state, _ = await create_oauth_transaction(db)

        # 1. First valid consumption succeeds
        consumed, err = await consume_oauth_transaction(db, browser_secret, state)
        assert err is None
        assert consumed is not None
        assert consumed.consumed_at is not None

        # 2. Replay attempt fails immediately
        consumed_replay, err_replay = await consume_oauth_transaction(db, browser_secret, state)
        assert consumed_replay is None
        assert err_replay == "replay_detected"

        # 3. State mismatch fails
        trx2, secret2, state2, _ = await create_oauth_transaction(db)
        consumed_mismatch, err_mismatch = await consume_oauth_transaction(
            db, secret2, "wrong_state"
        )
        assert consumed_mismatch is None
        assert err_mismatch == "state_mismatch"

        # 4. Unknown browser secret fails
        consumed_unknown, err_unknown = await consume_oauth_transaction(
            db, "unknown_secret", state2
        )
        assert consumed_unknown is None
        assert err_unknown == "transaction_not_found"


@pytest.mark.asyncio
async def test_google_callback_rejected_scenarios(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test callback rejects missing cookie, error from Google, and clears transaction cookie."""
    client, _ = auth_test_context

    # 1. Error param from Google
    resp1 = await client.get("/auth/google/callback?error=access_denied", follow_redirects=False)
    assert resp1.status_code == 302
    assert "error=access_denied" in resp1.headers["location"]

    # 2. Missing transaction cookie
    resp2 = await client.get("/auth/google/callback?code=abc&state=xyz", follow_redirects=False)
    assert resp2.status_code == 302
    assert "error=missing_oauth_params" in resp2.headers["location"]


@pytest.mark.asyncio
async def test_google_callback_unverified_email_rejected(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test callback rejects Google accounts with email_verified=False."""
    client, session_factory = auth_test_context

    async with session_factory() as db:
        _, browser_secret, state, _ = await create_oauth_transaction(db)

    client.cookies.set(OAUTH_TRX_COOKIE_NAME, browser_secret)

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
            f"/auth/google/callback?code=auth_code_123&state={state}",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "error=unverified_email" in response.headers["location"]


@pytest.mark.asyncio
async def test_google_account_linking_integrity_and_conflicts(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test account linking integrity: safe linking on matching verified email, conflict on different sub."""
    _, session_factory = auth_test_context

    async with session_factory() as db:
        # Pre-existing user with email but no google_sub
        existing_user = User(
            id=uuid.uuid4(),
            email="developer@example.com",
            google_sub=None,
            email_verified=False,
            full_name="Existing Dev",
            is_active=True,
        )
        db.add(existing_user)
        await db.commit()

        # 1. Successfully link existing user via verified Google email
        linked_user, _, _ = await provision_or_get_google_user(
            db=db,
            sub="google-sub-first",
            email="developer@example.com",
            email_verified=True,
            full_name="Existing Dev Updated",
        )
        assert linked_user.id == existing_user.id
        assert linked_user.google_sub == "google-sub-first"
        assert linked_user.email_verified is True

        # 2. Conflicting Google sub attempt on the same account must raise 409 Conflict
        with pytest.raises(Exception) as exc_info:
            await provision_or_get_google_user(
                db=db,
                sub="google-sub-DIFFERENT",
                email="developer@example.com",
                email_verified=True,
            )
        assert "409" in str(exc_info.value) or "already linked" in str(exc_info.value)

        # 3. Deactivated account must be rejected with 403 Forbidden
        existing_user.is_active = False
        await db.commit()
        with pytest.raises(Exception) as exc_inactive:
            await provision_or_get_google_user(
                db=db,
                sub="google-sub-first",
                email="developer@example.com",
                email_verified=True,
            )
        assert "403" in str(exc_inactive.value) or "deactivated" in str(exc_inactive.value)


@pytest.mark.asyncio
async def test_google_callback_success_and_replay_protection(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test successful callback provisions user, sets session and CSRF cookies, and blocks replay."""
    client, session_factory = auth_test_context

    async with session_factory() as db:
        _, browser_secret, state, _ = await create_oauth_transaction(db)

    client.cookies.set(OAUTH_TRX_COOKIE_NAME, browser_secret)

    mock_claims = {
        "sub": "sub-google-hardened-1",
        "email": "sarah.connor@example.com",
        "email_verified": True,
        "name": "Sarah Connor",
        "picture": "https://example.com/avatar.png",
    }

    with (
        patch("app.api.v1.auth.exchange_google_code", return_value={"id_token": "valid_token"}),
        patch("app.api.v1.auth.verify_google_id_token", return_value=mock_claims),
    ):
        # 1. First callback succeeds
        response = await client.get(
            f"/auth/google/callback?code=mock_code&state={state}",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"].endswith("/dashboard")
        assert SESSION_COOKIE_NAME in response.cookies
        assert CSRF_COOKIE_NAME in response.cookies
        assert response.cookies[SESSION_COOKIE_NAME]

        # Verify that /api/v1/auth/me returns 200 OK after successful login
        me_resp = await client.get("/api/v1/auth/me")
        assert me_resp.status_code == 200
        me_json = me_resp.json()
        assert me_json["email"] == "sarah.connor@example.com"
        assert me_json["full_name"] == "Sarah Connor"
        assert len(me_json["workspaces"]) >= 1

        # 2. Replaying the EXACT same callback must fail with replay_detected
        client.cookies.set(OAUTH_TRX_COOKIE_NAME, browser_secret)
        replay_response = await client.get(
            f"/auth/google/callback?code=mock_code&state={state}",
            follow_redirects=False,
        )
        assert replay_response.status_code == 302
        assert "error=replay_detected" in replay_response.headers["location"]


@pytest.mark.asyncio
async def test_csrf_protection_and_token_validation(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test CSRF protection: Origin verification, missing token, invalid signature, and safe GET."""
    client, session_factory = auth_test_context

    async with session_factory() as db:
        user = User(id=uuid.uuid4(), email="csrf_user@example.com", is_active=True)
        db.add(user)
        await db.commit()
        _, raw_session = await create_auth_session(db, user.id)

    # 1. Safe GET request succeeds without CSRF headers
    client.cookies.set(SESSION_COOKIE_NAME, raw_session)
    me_res = await client.get("/api/v1/auth/me")
    assert me_res.status_code == 200

    # 2. Fetch fresh CSRF token
    csrf_res = await client.get("/api/v1/auth/csrf")
    assert csrf_res.status_code == 200
    csrf_token = csrf_res.json()["csrf_token"]
    assert CSRF_COOKIE_NAME in csrf_res.cookies

    # 3. State-changing POST without CSRF header fails with 403 Forbidden
    post_no_csrf = await client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "http://localhost:3000"},
    )
    assert post_no_csrf.status_code == 403
    assert "CSRF" in post_no_csrf.json()["detail"]

    # 4. State-changing POST with disallowed Origin fails with 403 Forbidden
    post_bad_origin = await client.post(
        "/api/v1/auth/logout",
        headers={
            "Origin": "http://malicious-site.com",
            CSRF_HEADER_NAME: csrf_token,
        },
    )
    assert post_bad_origin.status_code == 403
    assert "Origin not permitted" in post_bad_origin.json()["detail"]

    # 5. State-changing POST with invalid signature fails with 403 Forbidden
    client.cookies.delete(CSRF_COOKIE_NAME)
    client.cookies.set(CSRF_COOKIE_NAME, "forged_raw.forged_signature")
    post_invalid_sig = await client.post(
        "/api/v1/auth/logout",
        headers={
            "Origin": "http://localhost:3000",
            CSRF_HEADER_NAME: "forged_raw.forged_signature",
        },
    )
    assert post_invalid_sig.status_code == 403
    assert "Invalid token signature" in post_invalid_sig.json()["detail"]

    # 6. Valid state-changing POST with matching CSRF cookie, header, and allowed Origin succeeds
    valid_token = generate_csrf_token()
    client.cookies.delete(CSRF_COOKIE_NAME)
    client.cookies.set(CSRF_COOKIE_NAME, valid_token)
    post_valid = await client.post(
        "/api/v1/auth/logout",
        headers={
            "Origin": "http://localhost:3000",
            CSRF_HEADER_NAME: valid_token,
        },
    )
    assert post_valid.status_code == 200
    assert post_valid.json()["status"] == "ok"
    assert post_valid.status_code == 200
    assert post_valid.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_workspace_membership_authorization(
    auth_test_context: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    """Test role hierarchy and cross-workspace tenant authorization."""
    client, session_factory = auth_test_context

    async with session_factory() as db:
        ws1 = Workspace(name="Workspace One", slug="ws-one")
        ws2 = Workspace(name="Workspace Two", slug="ws-two")
        db.add_all([ws1, ws2])
        await db.commit()

        user1 = User(id=uuid.uuid4(), email="user1@example.com", is_active=True)
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
    csrf_token = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    resp_create_insufficient = await client.post(
        "/api/v1/repositories",
        headers={
            "Origin": "http://localhost:3000",
            CSRF_HEADER_NAME: csrf_token,
        },
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


@pytest.mark.asyncio
async def test_verify_google_id_token_clock_skew_tolerance() -> None:
    """Test verify_google_id_token succeeds when token iat is slightly in the future due to clock skew."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    now = int(time.time())
    # iat is 15 seconds in future (common clock drift)
    payload = {
        "sub": "google-user-skew-1",
        "email": "skew.user@example.com",
        "email_verified": True,
        "aud": "test-google-client-id",
        "iss": "https://accounts.google.com",
        "iat": now + 15,
        "exp": now + 3600,
        "nonce": "test-nonce-123",
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")

    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key

    with (
        patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=mock_signing_key),
        patch.object(settings, "GOOGLE_CLIENT_ID", "test-google-client-id"),
    ):
        # 1. With standard clock skew leeway (default 60s), verification succeeds
        claims = await verify_google_id_token(token, expected_nonce="test-nonce-123")
        assert claims["sub"] == "google-user-skew-1"
        assert claims["email"] == "skew.user@example.com"

        # 2. When leeway is 0, iat in the future must fail with ValueError
        with pytest.raises(ValueError, match="Invalid Google ID token signature or claims") as exc_info:
            await verify_google_id_token(token, expected_nonce="test-nonce-123", leeway=0)
        assert "The token is not yet valid (iat)" in str(exc_info.value.__cause__)


@pytest.mark.asyncio
async def test_verify_google_id_token_strict_security_enforcement() -> None:
    """Verify that signature, audience, expiration, issuer, nonce, and email_verified remain strictly enforced."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key

    now = int(time.time())

    with (
        patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=mock_signing_key),
        patch.object(settings, "GOOGLE_CLIENT_ID", "test-google-client-id"),
    ):
        # 1. Excessive clock drift (> 60s in future) is rejected
        payload_future = {
            "sub": "user-future",
            "email": "future@example.com",
            "email_verified": True,
            "aud": "test-google-client-id",
            "iss": "https://accounts.google.com",
            "iat": now + 120,
            "exp": now + 3600,
        }
        token_future = jwt.encode(payload_future, private_key, algorithm="RS256")
        with pytest.raises(ValueError, match="Invalid Google ID token signature or claims"):
            await verify_google_id_token(token_future)

        # 2. Expired token (> 60s in past) is rejected
        payload_expired = {
            "sub": "user-expired",
            "email": "expired@example.com",
            "email_verified": True,
            "aud": "test-google-client-id",
            "iss": "https://accounts.google.com",
            "iat": now - 3600,
            "exp": now - 120,
        }
        token_expired = jwt.encode(payload_expired, private_key, algorithm="RS256")
        with pytest.raises(ValueError, match="Invalid Google ID token signature or claims"):
            await verify_google_id_token(token_expired)

        # 3. Audience mismatch is rejected
        payload_wrong_aud = {
            "sub": "user-wrong-aud",
            "email": "wrongaud@example.com",
            "email_verified": True,
            "aud": "unauthorized-client-id",
            "iss": "https://accounts.google.com",
            "iat": now,
            "exp": now + 3600,
        }
        token_wrong_aud = jwt.encode(payload_wrong_aud, private_key, algorithm="RS256")
        with pytest.raises(ValueError, match="Invalid Google ID token signature or claims"):
            await verify_google_id_token(token_wrong_aud)

        # 4. Nonce mismatch is rejected
        payload_valid = {
            "sub": "user-valid",
            "email": "valid@example.com",
            "email_verified": True,
            "aud": "test-google-client-id",
            "iss": "https://accounts.google.com",
            "iat": now,
            "exp": now + 3600,
            "nonce": "expected-nonce",
        }
        token_valid = jwt.encode(payload_valid, private_key, algorithm="RS256")
        with pytest.raises(ValueError, match="OAuth nonce mismatch"):
            await verify_google_id_token(token_valid, expected_nonce="different-nonce")

        # 5. Unverified email is rejected
        payload_unverified = {
            **payload_valid,
            "email_verified": False,
        }
        token_unverified = jwt.encode(payload_unverified, private_key, algorithm="RS256")
        with pytest.raises(ValueError, match="Google account email is not verified"):
            await verify_google_id_token(token_unverified, expected_nonce="expected-nonce")

