import base64
import hashlib
import hmac
import logging
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
import jwt
from fastapi import HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.base import WorkspaceRole, utc_now
from app.db.models.auth_session import AuthSession
from app.db.models.membership import WorkspaceMembership
from app.db.models.oauth_transaction import OAuthTransaction
from app.db.models.user import User
from app.db.models.workspace import Workspace

# Security Audit Logger
security_logger = logging.getLogger("orchestrix.security")

# Cookie & Header Names
SESSION_COOKIE_NAME = "orchestrix_session"
OAUTH_TRX_COOKIE_NAME = settings.OAUTH_TRX_COOKIE_NAME
CSRF_COOKIE_NAME = settings.CSRF_COOKIE_NAME
CSRF_HEADER_NAME = "X-CSRF-Token"

# Workspace role hierarchy for authorization
ROLE_RANK: dict[WorkspaceRole, int] = {
    WorkspaceRole.VIEWER: 1,
    WorkspaceRole.MEMBER: 2,
    WorkspaceRole.ADMIN: 3,
    WorkspaceRole.OWNER: 4,
}

# -----------------------------------------------------------------------------
# Cryptographic Hashing Helpers
# -----------------------------------------------------------------------------


def hash_secret(raw_value: str) -> str:
    """Compute SHA-256 hex digest of a raw secret."""
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


# Alias for backwards compatibility
hash_session_token = hash_secret


# -----------------------------------------------------------------------------
# Session Management
# -----------------------------------------------------------------------------


async def create_auth_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
    ttl_seconds: int | None = None,
) -> tuple[AuthSession, str]:
    """
    Generate a cryptographically secure 32-byte opaque session token,
    store its SHA-256 digest in the database, and return (session_record, raw_token).
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_secret(raw_token)
    ttl = ttl_seconds if ttl_seconds is not None else settings.SESSION_TTL_SECONDS
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl)

    auth_session = AuthSession(
        user_id=user_id,
        token_hash=token_hash,
        ip_address=ip_address[:45] if ip_address else None,
        user_agent=user_agent[:512] if user_agent else None,
        is_revoked=False,
        expires_at=expires_at,
    )
    db.add(auth_session)
    await db.commit()
    await db.refresh(auth_session)
    return auth_session, raw_token


async def validate_session_token(
    db: AsyncSession,
    raw_token: str,
) -> tuple[AuthSession, User] | None:
    """
    Validate an opaque session token against the database.
    Checks: token existence, revocation status, expiration, and user active status.
    Throttles last_accessed_at updates to avoid unnecessary database load (at most once every 60s).
    """
    if not raw_token or len(raw_token.strip()) == 0:
        return None

    token_hash = hash_secret(raw_token)
    stmt = (
        select(AuthSession)
        .options(selectinload(AuthSession.user))
        .where(
            AuthSession.token_hash == token_hash,
            AuthSession.is_revoked.is_(False),
        )
    )
    result = await db.execute(stmt)
    session_record = result.scalars().first()

    if session_record is None:
        return None

    now = datetime.now(UTC)
    # Check expiration (safely handle timezone-naive engines like SQLite in tests)
    expires_at = session_record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        return None

    # Check associated user
    user = session_record.user
    if user is None or not user.is_active:
        return None

    # Throttle last_accessed_at update to reduce write amplification
    last_accessed = session_record.last_accessed_at
    if last_accessed is not None and last_accessed.tzinfo is None:
        last_accessed = last_accessed.replace(tzinfo=UTC)

    if last_accessed is None or (now - last_accessed) > timedelta(seconds=60):
        session_record.last_accessed_at = now
        await db.commit()

    return session_record, user


async def revoke_session_token(db: AsyncSession, raw_token: str) -> bool:
    """Revoke a session by token hash."""
    if not raw_token:
        return False

    token_hash = hash_secret(raw_token)
    stmt = update(AuthSession).where(AuthSession.token_hash == token_hash).values(is_revoked=True)
    result = await db.execute(stmt)
    await db.commit()
    count = getattr(result, "rowcount", 0)
    revoked = bool(count and count > 0)
    if revoked:
        security_logger.info("security_event=session_revoked token_hash_prefix=%s", token_hash[:8])
    return revoked


async def revoke_all_user_sessions(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Revoke all active sessions for a user."""
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.is_revoked.is_(False))
        .values(is_revoked=True)
    )
    result = await db.execute(stmt)
    await db.commit()
    count = getattr(result, "rowcount", 0)
    security_logger.info("security_event=all_sessions_revoked user_id=%s count=%s", user_id, count)
    return int(count)


# -----------------------------------------------------------------------------
# Server-Side OAuth 2.0 PKCE Transactions (Replay & Tamper Protection)
# -----------------------------------------------------------------------------


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier (64 bytes) and code_challenge (S256)."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return code_verifier, code_challenge


async def create_oauth_transaction(
    db: AsyncSession,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[OAuthTransaction, str, str, str]:
    """
    Create a server-side one-time OAuth 2.0 transaction in PostgreSQL.
    Returns (transaction_record, browser_secret, state, code_challenge).
    - Browser receives only an unguessable browser_secret bound to lookup_hash.
    - Raw PKCE code_verifier and nonce are stored server-side.
    """
    browser_secret = secrets.token_urlsafe(32)
    lookup_hash = hash_secret(browser_secret)

    state = secrets.token_urlsafe(32)
    state_hash = hash_secret(state)

    nonce = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce_pair()

    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=10)

    trx = OAuthTransaction(
        lookup_hash=lookup_hash,
        state_hash=state_hash,
        nonce=nonce,
        code_verifier=code_verifier,
        created_at=now,
        expires_at=expires_at,
        ip_address=ip_address[:45] if ip_address else None,
        user_agent=user_agent[:512] if user_agent else None,
    )
    db.add(trx)
    await db.commit()
    await db.refresh(trx)

    security_logger.info(
        "security_event=oauth_transaction_created transaction_id=%s ip=%s",
        trx.id,
        ip_address,
    )
    return trx, browser_secret, state, code_challenge


async def consume_oauth_transaction(
    db: AsyncSession,
    browser_secret: str | None,
    state: str | None,
) -> tuple[OAuthTransaction | None, str | None]:
    """
    Atomically consume a one-time OAuth transaction from PostgreSQL.
    Enforces atomic one-time consumption to prevent replay and race conditions.
    Returns (transaction, error_code).
    """
    if not browser_secret or not state:
        return None, "missing_params"

    lookup_hash = hash_secret(browser_secret)
    state_hash = hash_secret(state)
    now = datetime.now(UTC)

    # Atomic UPDATE with WHERE consumed_at IS NULL RETURNING
    stmt = (
        update(OAuthTransaction)
        .where(
            OAuthTransaction.lookup_hash == lookup_hash,
            OAuthTransaction.state_hash == state_hash,
            OAuthTransaction.consumed_at.is_(None),
            OAuthTransaction.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(OAuthTransaction)
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    trx = result.scalars().first()
    await db.commit()

    if trx is not None:
        await db.refresh(trx)
        security_logger.info(
            "security_event=oauth_transaction_consumed transaction_id=%s",
            trx.id,
        )
        return trx, None

    # Consumption failed: perform diagnostic lookup to identify exact security reason
    check_stmt = select(OAuthTransaction).where(OAuthTransaction.lookup_hash == lookup_hash)
    check_res = await db.execute(check_stmt)
    existing = check_res.scalars().first()

    if existing is None:
        security_logger.warning("security_event=oauth_transaction_not_found")
        return None, "transaction_not_found"

    if existing.consumed_at is not None:
        security_logger.warning(
            "security_event=oauth_replay_detected transaction_id=%s",
            existing.id,
        )
        return None, "replay_detected"

    exp = existing.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)
    if exp <= now:
        security_logger.warning(
            "security_event=oauth_transaction_expired transaction_id=%s",
            existing.id,
        )
        return None, "expired"

    if existing.state_hash != state_hash:
        security_logger.warning(
            "security_event=oauth_state_mismatch transaction_id=%s",
            existing.id,
        )
        return None, "state_mismatch"

    return None, "invalid_transaction"


def generate_google_auth_url(state: str, nonce: str, code_challenge: str) -> str:
    """Construct Google OAuth 2.0 OpenID Connect authorization URL."""
    base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "select_account",
    }
    encoded_params = httpx.QueryParams(params)
    return f"{base_url}?{encoded_params}"


async def exchange_google_code(code: str, code_verifier: str) -> dict[str, Any]:
    """Exchange authorization code and PKCE verifier for Google tokens."""
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(token_url, data=data)
        if response.status_code != 200:
            security_logger.error(
                "security_event=google_token_exchange_failed status_code=%s",
                response.status_code,
            )
            raise ValueError("Failed to exchange authorization code with identity provider")
        payload_data: dict[str, Any] = response.json()
        return payload_data


async def verify_google_id_token(
    id_token: str,
    expected_nonce: str | None = None,
    jwks_url: str = "https://www.googleapis.com/oauth2/v3/certs",
) -> dict[str, Any]:
    """
    Validate Google ID Token against Google JWKS and audience/issuer/nonce.
    Returns decoded claims dictionary.
    """
    try:
        jwks_client = jwt.PyJWKClient(jwks_url)
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.GOOGLE_CLIENT_ID,
            issuer=["https://accounts.google.com", "accounts.google.com"],
        )
    except Exception as exc:
        security_logger.warning("security_event=id_token_verification_failed error=%s", str(exc))
        raise ValueError("Invalid Google ID token signature or claims") from exc

    if expected_nonce and claims.get("nonce") != expected_nonce:
        security_logger.warning("security_event=oauth_nonce_mismatch")
        raise ValueError("OAuth nonce mismatch")

    if not claims.get("email_verified", False):
        security_logger.warning("security_event=unverified_email_rejected")
        raise ValueError("Google account email is not verified")

    return claims


# -----------------------------------------------------------------------------
# CSRF Protection Helpers (Double-Submit HMAC-Signed Token)
# -----------------------------------------------------------------------------


def generate_csrf_token() -> str:
    """Generate an HMAC-SHA256 signed CSRF token bound to the server secret."""
    raw = secrets.token_urlsafe(32)
    secret_bytes = settings.SESSION_SECRET_KEY.encode("utf-8")
    signature = hmac.new(secret_bytes, raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{raw}.{signature}"


def verify_csrf_token(token: str) -> bool:
    """Verify that a CSRF token has a valid HMAC-SHA256 signature."""
    if not token or "." not in token:
        return False
    raw, sig = token.split(".", 1)
    secret_bytes = settings.SESSION_SECRET_KEY.encode("utf-8")
    expected_sig = hmac.new(secret_bytes, raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected_sig)


def validate_csrf_request(request: Request) -> None:
    """
    Validate CSRF for state-changing browser requests (POST, PUT, PATCH, DELETE).
    Only applies if the request is authenticated via the session cookie.
    Validates Origin/Referer and double-submitted CSRF token.
    """
    # 1. Skip safe HTTP methods
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    # 2. Skip if request uses Authorization Bearer (programmatic API/CLI clients)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return

    # 3. Only enforce CSRF if session cookie is present (browser cookie session)
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        return

    # 4. Validate Origin / Referer against allowed frontend origins
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")

    allowed = settings.allowed_origins

    if origin:
        normalized_origin = origin.rstrip("/")
        if normalized_origin not in allowed:
            security_logger.warning(
                "security_event=csrf_origin_mismatch origin=%s allowed=%s path=%s",
                origin,
                allowed,
                request.url.path,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF validation failed: Origin not permitted",
            )
    elif referer:
        parsed_ref = urlparse(referer)
        ref_origin = f"{parsed_ref.scheme}://{parsed_ref.netloc}"
        if ref_origin not in allowed:
            security_logger.warning(
                "security_event=csrf_referer_mismatch referer=%s path=%s",
                referer,
                request.url.path,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF validation failed: Referer not permitted",
            )
    else:
        # Browser sent cookie without Origin or Referer on a state-changing method
        security_logger.warning(
            "security_event=csrf_missing_origin_and_referer path=%s",
            request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed: Missing origin/referer header",
        )

    # 5. Validate Double-Submitted CSRF Token
    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    csrf_header = request.headers.get(CSRF_HEADER_NAME)

    if not csrf_cookie or not csrf_header:
        security_logger.warning(
            "security_event=csrf_token_missing cookie_present=%s header_present=%s path=%s",
            bool(csrf_cookie),
            bool(csrf_header),
            request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed: Missing CSRF token or cookie",
        )

    if not hmac.compare_digest(csrf_cookie, csrf_header):
        security_logger.warning("security_event=csrf_token_mismatch path=%s", request.url.path)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed: Token mismatch",
        )

    if not verify_csrf_token(csrf_header):
        security_logger.warning(
            "security_event=csrf_token_signature_invalid path=%s", request.url.path
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed: Invalid token signature",
        )


# -----------------------------------------------------------------------------
# User & Workspace Provisioning (Account-Linking Integrity & Race Protection)
# -----------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Create a URL-safe slug from arbitrary text."""
    slug = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[-\s]+", "-", slug)


async def provision_or_get_google_user(
    db: AsyncSession,
    sub: str,
    email: str,
    email_verified: bool,
    full_name: str | None = None,
    avatar_url: str | None = None,
) -> tuple[User, Workspace, WorkspaceMembership]:
    """
    Find or provision user from validated Google OpenID Connect claims.
    Security & Integrity Guarantees:
    - Never link accounts based on unverified emails.
    - Prevents one user from being associated with conflicting Google identities (raises 409).
    - Prevents one Google sub from being associated with multiple users (unique constraint).
    - Checks account active status (inactive accounts rejected with 403).
    - Handles concurrent first-time logins and account-linking collisions via retry & read-after-rollback.
    - Preserves existing workspace memberships and roles without duplicating personal workspaces.
    - Never grants elevated workspace roles as part of OAuth login.
    """
    if not email_verified:
        raise ValueError("Cannot provision user with unverified email")

    normalized_email = email.strip().lower()

    # Attempt lookup or provisioning, retrying up to 2 times on concurrent insertion collisions
    for attempt in range(2):
        try:
            # 1. Search by stable google_sub
            stmt = (
                select(User)
                .options(selectinload(User.memberships).selectinload(WorkspaceMembership.workspace))
                .where(User.google_sub == sub)
            )
            result = await db.execute(stmt)
            user = result.scalars().first()

            if user is None:
                # 2. Search by verified email
                stmt = (
                    select(User)
                    .options(
                        selectinload(User.memberships).selectinload(WorkspaceMembership.workspace)
                    )
                    .where(User.email == normalized_email)
                )
                result = await db.execute(stmt)
                user = result.scalars().first()

            if user is not None:
                # Account active check
                if not user.is_active:
                    security_logger.warning(
                        "security_event=inactive_account_rejected user_id=%s email=%s",
                        user.id,
                        normalized_email,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Account is deactivated. Contact an administrator.",
                    )

                # Conflicting Google identity check:
                # If account was previously linked to a different google_sub, reject with conflict!
                if user.google_sub and user.google_sub != sub:
                    security_logger.warning(
                        "security_event=account_linking_conflict user_id=%s email=%s existing_sub=%s attempted_sub=%s",
                        user.id,
                        normalized_email,
                        user.google_sub,
                        sub,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Account is already linked to a different Google identity.",
                    )

                # Link google_sub if not yet linked
                if user.google_sub is None:
                    user.google_sub = sub

                user.email_verified = True
                if full_name:
                    user.full_name = full_name
                if avatar_url:
                    user.avatar_url = avatar_url
                user.updated_at = utc_now()

                # Preserve existing workspace memberships. Only create default workspace if user has zero memberships.
                if user.memberships:
                    membership = user.memberships[0]
                    workspace = membership.workspace
                else:
                    slug_base = _slugify(user.full_name or normalized_email.split("@")[0])
                    slug = f"workspace-{slug_base}-{uuid.uuid4().hex[:6]}"
                    workspace = Workspace(
                        id=uuid.uuid4(),
                        name=f"{user.full_name or 'Personal'}'s Workspace",
                        slug=slug,
                    )
                    db.add(workspace)
                    await db.flush()

                    membership = WorkspaceMembership(
                        id=uuid.uuid4(),
                        user_id=user.id,
                        workspace_id=workspace.id,
                        role=WorkspaceRole.OWNER,
                    )
                    db.add(membership)

                await db.commit()
                await db.refresh(user)
                await db.refresh(workspace)
                await db.refresh(membership)
                return user, workspace, membership

            # 3. First-time user provisioning
            new_user = User(
                id=uuid.uuid4(),
                email=normalized_email,
                google_sub=sub,
                email_verified=True,
                full_name=full_name,
                avatar_url=avatar_url,
                is_active=True,
            )
            db.add(new_user)
            await db.flush()

            slug_base = _slugify(full_name or normalized_email.split("@")[0])
            slug = f"workspace-{slug_base}-{uuid.uuid4().hex[:6]}"
            workspace = Workspace(
                id=uuid.uuid4(),
                name=f"{full_name or 'Personal'}'s Workspace",
                slug=slug,
            )
            db.add(workspace)
            await db.flush()

            membership = WorkspaceMembership(
                id=uuid.uuid4(),
                user_id=new_user.id,
                workspace_id=workspace.id,
                role=WorkspaceRole.OWNER,
            )
            db.add(membership)
            await db.commit()
            await db.refresh(new_user)
            await db.refresh(workspace)
            await db.refresh(membership)

            security_logger.info(
                "security_event=user_provisioned user_id=%s email=%s",
                new_user.id,
                normalized_email,
            )
            return new_user, workspace, membership

        except IntegrityError as exc:
            # Handle concurrent registration collision cleanly
            await db.rollback()
            if attempt == 1:
                security_logger.error(
                    "security_event=user_provisioning_integrity_failure email=%s sub=%s",
                    normalized_email,
                    sub,
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Registration collision detected. Please try logging in again.",
                ) from exc

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to provision user.",
    )


async def get_user_with_workspaces(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> tuple[User, list[tuple[Workspace, WorkspaceRole]]] | None:
    """Retrieve user along with all associated workspaces and corresponding roles."""
    stmt = (
        select(User)
        .options(selectinload(User.memberships).selectinload(WorkspaceMembership.workspace))
        .where(User.id == user_id, User.is_active.is_(True))
    )
    result = await db.execute(stmt)
    user = result.scalars().first()
    if user is None:
        return None

    workspace_list: list[tuple[Workspace, WorkspaceRole]] = []
    for m in user.memberships:
        if m.workspace:
            workspace_list.append((m.workspace, m.role))

    return user, workspace_list


# -----------------------------------------------------------------------------
# Workspace Tenant & Role Authorization
# -----------------------------------------------------------------------------


async def verify_workspace_membership(
    db: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    min_role: WorkspaceRole = WorkspaceRole.VIEWER,
) -> WorkspaceMembership:
    """
    Verify that the user is an active member of the given workspace and meets
    the required minimum role (VIEWER <= MEMBER <= ADMIN <= OWNER).
    Raises 403 Forbidden on failure.
    """
    stmt = select(WorkspaceMembership).where(
        WorkspaceMembership.user_id == user_id,
        WorkspaceMembership.workspace_id == workspace_id,
    )
    result = await db.execute(stmt)
    membership = result.scalars().first()

    if membership is None:
        security_logger.warning(
            "security_event=workspace_access_denied_not_member user_id=%s workspace_id=%s",
            user_id,
            workspace_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You are not a member of this workspace",
        )

    user_rank = ROLE_RANK.get(membership.role, 0)
    required_rank = ROLE_RANK.get(min_role, 0)

    if user_rank < required_rank:
        security_logger.warning(
            "security_event=workspace_insufficient_role user_id=%s workspace_id=%s current_role=%s required_role=%s",
            user_id,
            workspace_id,
            membership.role,
            min_role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Requires at least {min_role.value} permission in this workspace",
        )

    return membership
