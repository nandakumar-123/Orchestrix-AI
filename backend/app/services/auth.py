import base64
import hashlib
import re
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.base import WorkspaceRole, utc_now
from app.db.models.auth_session import AuthSession
from app.db.models.membership import WorkspaceMembership
from app.db.models.user import User
from app.db.models.workspace import Workspace

# Cookie Names
SESSION_COOKIE_NAME = "orchestrix_session"
OAUTH_TRANSIT_COOKIE_NAME = "orchestrix_oauth_transit"

# Workspace role hierarchy for authorization
ROLE_RANK: dict[WorkspaceRole, int] = {
    WorkspaceRole.VIEWER: 1,
    WorkspaceRole.MEMBER: 2,
    WorkspaceRole.ADMIN: 3,
    WorkspaceRole.OWNER: 4,
}

# -----------------------------------------------------------------------------
# Session Management
# -----------------------------------------------------------------------------


def hash_session_token(raw_token: str) -> str:
    """Compute SHA-256 hex digest of the raw session token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


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
    token_hash = hash_session_token(raw_token)
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
    Updates last_accessed_at on successful validation.
    """
    if not raw_token or len(raw_token.strip()) == 0:
        return None

    token_hash = hash_session_token(raw_token)
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

    # Update last_accessed_at
    session_record.last_accessed_at = now
    await db.commit()

    return session_record, user


async def revoke_session_token(db: AsyncSession, raw_token: str) -> bool:
    """Revoke a session by token hash."""
    if not raw_token:
        return False

    token_hash = hash_session_token(raw_token)
    stmt = update(AuthSession).where(AuthSession.token_hash == token_hash).values(is_revoked=True)
    result = await db.execute(stmt)
    await db.commit()
    count = getattr(result, "rowcount", 0)
    return bool(count and count > 0)


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
    return int(count)


# -----------------------------------------------------------------------------
# Google OAuth 2.0 PKCE & State Helpers
# -----------------------------------------------------------------------------


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return code_verifier, code_challenge


def encode_transit_token(state: str, nonce: str, code_verifier: str) -> str:
    """
    Sign OAuth transit state, nonce, and PKCE verifier into a tamper-proof short-lived JWT.
    Used in a secure transit cookie to eliminate the need for centralized transient storage.
    """
    payload = {
        "state": state,
        "nonce": nonce,
        "code_verifier": code_verifier,
        "exp": int(time.time()) + 600,  # 10 minutes lifetime
    }
    return jwt.encode(payload, settings.SESSION_SECRET_KEY, algorithm="HS256")


def decode_transit_token(token: str) -> dict[str, Any] | None:
    """Decode and verify the OAuth transit JWT cookie."""
    try:
        payload = jwt.decode(token, settings.SESSION_SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.PyJWTError:
        return None


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
            raise ValueError(f"Failed to exchange code with Google: {response.text}")
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
        raise ValueError(f"Invalid Google ID token signature or claims: {exc}") from exc

    if expected_nonce and claims.get("nonce") != expected_nonce:
        raise ValueError("OAuth nonce mismatch")

    if not claims.get("email_verified", False):
        raise ValueError("Google account email is not verified")

    return claims


# -----------------------------------------------------------------------------
# User & Workspace Provisioning
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
    - If user exists by google_sub, updates profile fields.
    - If user exists by email, safely links google_sub if email is verified.
    - If new user, creates user and provisions an isolated personal default workspace
      with OWNER membership.
    """
    if not email_verified:
        raise ValueError("Cannot provision user with unverified email")

    normalized_email = email.strip().lower()

    # 1. Search by google_sub
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
            .options(selectinload(User.memberships).selectinload(WorkspaceMembership.workspace))
            .where(User.email == normalized_email)
        )
        result = await db.execute(stmt)
        user = result.scalars().first()

    if user is not None:
        # Existing user: update attributes and link google_sub if not yet set
        user.google_sub = sub
        user.email_verified = True
        if full_name:
            user.full_name = full_name
        if avatar_url:
            user.avatar_url = avatar_url
        user.updated_at = utc_now()

        # Find existing active workspace membership or create if none exists
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

    return new_user, workspace, membership


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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You are not a member of this workspace",
        )

    user_rank = ROLE_RANK.get(membership.role, 0)
    required_rank = ROLE_RANK.get(min_role, 0)

    if user_rank < required_rank:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Requires at least {min_role.value} permission in this workspace",
        )

    return membership
