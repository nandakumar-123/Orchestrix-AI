import base64
import hashlib
import hmac
import logging
import secrets
import time
import uuid
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import WorkspaceRole
from app.db.models.audit_log import AuditLog
from app.db.models.github_account import GitHubAccount
from app.db.models.github_installation import GitHubInstallation
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository

github_logger = logging.getLogger("orchestrix.github")
security_logger = logging.getLogger("orchestrix.security")


# -----------------------------------------------------------------------------
# Cryptographic Token Encryption (AES-128-CBC + HMAC via Fernet)
# -----------------------------------------------------------------------------


def _get_fernet_cipher() -> Fernet:
    """Derive deterministic 32-byte url-safe base64 key from SESSION_SECRET_KEY."""
    raw_secret = settings.SESSION_SECRET_KEY.encode("utf-8")
    derived_key = base64.urlsafe_b64encode(hashlib.sha256(raw_secret).digest())
    return Fernet(derived_key)


def encrypt_token(plain_token: str) -> str:
    """Encrypt plain-text access token before persisting to database."""
    if not plain_token:
        raise ValueError("Cannot encrypt an empty token")
    cipher = _get_fernet_cipher()
    return cipher.encrypt(plain_token.encode("utf-8")).decode("utf-8")


def decrypt_token(cipher_text: str) -> str:
    """Decrypt cipher-text token retrieved from database."""
    if not cipher_text:
        raise ValueError("Cannot decrypt an empty token")
    cipher = _get_fernet_cipher()
    try:
        return cipher.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        security_logger.error("security_event=github_token_decryption_failed")
        raise ValueError("Failed to decrypt GitHub access token") from exc


# -----------------------------------------------------------------------------
# OAuth State Signing & Verification (Double-Submit / Replay Protection)
# -----------------------------------------------------------------------------


def generate_github_oauth_state(user_id: uuid.UUID) -> str:
    """
    Generate an HMAC-signed, tamper-proof state parameter.
    Format: base64url(user_id:timestamp:nonce).signature
    """
    timestamp = int(time.time())
    nonce = secrets.token_urlsafe(16)
    payload_str = f"{user_id}:{timestamp}:{nonce}"
    payload_b64 = base64.urlsafe_b64encode(payload_str.encode("utf-8")).decode("utf-8").rstrip("=")

    secret_key = settings.SESSION_SECRET_KEY.encode("utf-8")
    signature = hmac.new(secret_key, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_github_oauth_state(
    state: str,
    expected_user_id: uuid.UUID | None = None,
    max_age_seconds: int = 600,
) -> uuid.UUID | None:
    """
    Validate HMAC signature, timestamp, and optional user ID of OAuth state.
    Returns the user_id if valid, or None if invalid/expired/tampered.
    """
    if not state or "." not in state:
        security_logger.warning("security_event=github_oauth_state_malformed")
        return None

    payload_b64, signature = state.split(".", 1)
    secret_key = settings.SESSION_SECRET_KEY.encode("utf-8")
    expected_sig = hmac.new(secret_key, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        security_logger.warning("security_event=github_oauth_state_tampered")
        return None

    try:
        # Restore base64 padding
        padded_b64 = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload_str = base64.urlsafe_b64decode(padded_b64.encode("utf-8")).decode("utf-8")
        parts = payload_str.split(":", 2)
        if len(parts) != 3:
            return None

        user_id_str, timestamp_str, _ = parts
        state_user_id = uuid.UUID(user_id_str)
        created_at = int(timestamp_str)
        now = int(time.time())

        # Verify time-to-live (default 10 minutes)
        if (now - created_at) > max_age_seconds or created_at > (now + 60):
            security_logger.warning("security_event=github_oauth_state_expired")
            return None

        # Verify user_id matches currently authenticated user if provided
        if expected_user_id and state_user_id != expected_user_id:
            security_logger.warning(
                "security_event=github_oauth_user_mismatch state_user=%s expected_user=%s",
                state_user_id,
                expected_user_id,
            )
            return None

        return state_user_id
    except Exception as exc:
        security_logger.warning(
            "security_event=github_oauth_state_verification_error error=%s", str(exc)
        )
        return None


# -----------------------------------------------------------------------------
# GitHub Authorization & Code Exchange
# -----------------------------------------------------------------------------


def generate_github_auth_url(
    user_id: uuid.UUID,
    redirect_uri: str | None = None,
    scopes: str | None = None,
) -> tuple[str, str]:
    """
    Construct GitHub OAuth authorization URL with signed state.
    Returns (auth_url, state).
    """
    effective_client_id = (settings.GITHUB_CLIENT_ID or "").strip()
    if not effective_client_id:
        security_logger.error("security_event=github_oauth_missing_client_id")
        raise ValueError("GitHub OAuth GITHUB_CLIENT_ID is not configured on the server")

    effective_redirect_uri = (redirect_uri or settings.GITHUB_REDIRECT_URI or "").strip()
    effective_scopes = (scopes or settings.GITHUB_SCOPES or "repo,read:user").strip()

    state = generate_github_oauth_state(user_id)
    base_url = "https://github.com/login/oauth/authorize"
    params = {
        "client_id": effective_client_id,
        "redirect_uri": effective_redirect_uri,
        "scope": effective_scopes,
        "state": state,
    }
    encoded_params = httpx.QueryParams(params)
    auth_url = f"{base_url}?{encoded_params}"
    return auth_url, state


async def exchange_github_code(
    code: str,
    redirect_uri: str | None = None,
) -> dict[str, Any]:
    """Exchange authorization code for GitHub access token."""
    client_id = (settings.GITHUB_CLIENT_ID or "").strip()
    client_secret = (settings.GITHUB_CLIENT_SECRET or "").strip()
    effective_redirect_uri = (redirect_uri or settings.GITHUB_REDIRECT_URI or "").strip()

    if not client_id or not client_secret:
        security_logger.error("security_event=github_oauth_unconfigured_credentials")
        raise ValueError("GitHub OAuth credentials are not configured on the server")

    token_url = "https://github.com/login/oauth/access_token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": effective_redirect_uri,
    }
    headers = {"Accept": "application/json"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(token_url, json=payload, headers=headers)
        if response.status_code != 200:
            security_logger.error(
                "security_event=github_token_exchange_http_error status=%s", response.status_code
            )
            raise ValueError("Failed to communicate with GitHub token endpoint")

        data: dict[str, Any] = response.json()
        if "error" in data:
            error_msg = data.get("error_description") or data.get("error")
            security_logger.warning(
                "security_event=github_token_exchange_rejected error=%s", error_msg
            )
            raise ValueError(f"GitHub authorization failed: {error_msg}")

        if "access_token" not in data:
            raise ValueError("No access_token returned by GitHub")

        return data


# -----------------------------------------------------------------------------
# GitHub API Client Operations
# -----------------------------------------------------------------------------


async def fetch_github_user_profile(access_token: str) -> dict[str, Any]:
    """Fetch profile of authenticated GitHub user."""
    url = "https://api.github.com/user"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orchestrix-AI",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=headers)
        if response.status_code == 401:
            security_logger.warning("security_event=github_credentials_revoked")
            raise PermissionError("GitHub access token is invalid or has been revoked")
        if response.status_code == 403 and "rate limit" in response.text.lower():
            security_logger.warning("security_event=github_rate_limited")
            raise RuntimeError("GitHub API rate limit exceeded")
        if response.status_code != 200:
            raise RuntimeError(f"GitHub API error: status {response.status_code}")

        data: dict[str, Any] = response.json()
        return data


async def list_accessible_repositories(
    access_token: str,
    page: int = 1,
    per_page: int = 30,
) -> list[dict[str, Any]]:
    """
    Fetch repositories accessible to the authenticated GitHub account with pagination.
    Supports both public and private repositories.
    """
    url = "https://api.github.com/user/repos"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orchestrix-AI",
    }
    params: dict[str, str | int] = {
        "sort": "updated",
        "direction": "desc",
        "per_page": min(max(per_page, 1), 100),
        "page": max(page, 1),
        "affiliation": "owner,collaborator,organization_member",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers=headers, params=params)
        if response.status_code == 401:
            security_logger.warning("security_event=github_credentials_revoked")
            raise PermissionError("GitHub access token is invalid or has been revoked")
        if response.status_code == 403 and "rate limit" in response.text.lower():
            security_logger.warning("security_event=github_rate_limited")
            raise RuntimeError("GitHub API rate limit exceeded")
        if response.status_code != 200:
            raise RuntimeError(f"GitHub API error: status {response.status_code}")

        repos_raw: list[dict[str, Any]] = response.json()
        sanitized: list[dict[str, Any]] = []

        for r in repos_raw:
            owner = r.get("owner", {})
            sanitized.append(
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "full_name": r.get("full_name"),
                    "owner_login": owner.get("login", ""),
                    "owner_avatar_url": owner.get("avatar_url"),
                    "description": r.get("description"),
                    "default_branch": r.get("default_branch", "main"),
                    "html_url": r.get("html_url", ""),
                    "visibility": "private" if r.get("private") else "public",
                    "language": r.get("language"),
                    "updated_at": r.get("updated_at"),
                    "stargazers_count": r.get("stargazers_count", 0),
                    "forks_count": r.get("forks_count", 0),
                    "open_issues_count": r.get("open_issues_count", 0),
                }
            )

        return sanitized


async def fetch_single_repository(
    access_token: str,
    owner: str,
    repo: str,
) -> dict[str, Any]:
    """Fetch single repository metadata for refresh."""
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orchestrix-AI",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=headers)
        if response.status_code == 401:
            raise PermissionError("GitHub access token is invalid or has been revoked")
        if response.status_code == 403 and "rate limit" in response.text.lower():
            raise RuntimeError("GitHub API rate limit exceeded")
        if response.status_code == 404:
            raise LookupError(f"Repository {owner}/{repo} not found on GitHub or access revoked")
        if response.status_code != 200:
            raise RuntimeError(f"GitHub API error: status {response.status_code}")

        data: dict[str, Any] = response.json()
        owner_data = data.get("owner", {})
        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "full_name": data.get("full_name"),
            "owner_login": owner_data.get("login", ""),
            "description": data.get("description"),
            "default_branch": data.get("default_branch", "main"),
            "html_url": data.get("html_url", ""),
            "visibility": "private" if data.get("private") else "public",
            "language": data.get("language"),
            "updated_at": data.get("updated_at"),
        }


# -----------------------------------------------------------------------------
# Database Account & Repository Management
# -----------------------------------------------------------------------------


async def upsert_github_account(
    db: AsyncSession,
    user_id: uuid.UUID,
    profile: dict[str, Any],
    access_token: str,
    token_type: str = "bearer",
    scope: str | None = None,
) -> GitHubAccount:
    """Save or update user's connected GitHub account with encrypted token."""
    stmt = select(GitHubAccount).where(GitHubAccount.user_id == user_id)
    res = await db.execute(stmt)
    account = res.scalars().first()

    encrypted_token = encrypt_token(access_token)
    github_user_id = profile.get("id")
    if not github_user_id:
        raise ValueError("GitHub profile does not contain a valid user id")

    github_login = profile.get("login", "")

    if account is None:
        account = GitHubAccount(
            user_id=user_id,
            github_user_id=int(github_user_id),
            github_login=github_login,
            name=profile.get("name"),
            email=profile.get("email"),
            avatar_url=profile.get("avatar_url"),
            html_url=profile.get("html_url"),
            encrypted_access_token=encrypted_token,
            token_type=token_type,
            scope=scope,
        )
        db.add(account)
    else:
        account.github_user_id = int(github_user_id)
        account.github_login = github_login
        account.name = profile.get("name")
        account.email = profile.get("email")
        account.avatar_url = profile.get("avatar_url")
        account.html_url = profile.get("html_url")
        account.encrypted_access_token = encrypted_token
        account.token_type = token_type
        account.scope = scope

    await db.commit()
    await db.refresh(account)
    security_logger.info(
        "security_event=github_account_connected user_id=%s github_login=%s",
        user_id,
        github_login,
    )
    return account


async def get_user_github_account(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> GitHubAccount | None:
    """Retrieve connected GitHub account for user."""
    stmt = select(GitHubAccount).where(GitHubAccount.user_id == user_id)
    res = await db.execute(stmt)
    return res.scalars().first()


async def disconnect_github_account(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> bool:
    """Disconnect user's GitHub account and purge stored credentials."""
    account = await get_user_github_account(db, user_id)
    if not account:
        return False

    login = account.github_login
    await db.delete(account)
    await db.commit()
    security_logger.info(
        "security_event=github_account_disconnected user_id=%s login=%s", user_id, login
    )
    return True


async def ensure_workspace_installation(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    account_login: str,
    account_id: int,
    account_type: str = "User",
) -> GitHubInstallation:
    """
    Find or create a GitHubInstallation for a workspace to satisfy the composite foreign key
    on repositories (installation_id, workspace_id).
    Ensures installation_id is globally unique across installations.
    """
    # 1. Check if installation already exists for this workspace and account
    stmt = select(GitHubInstallation).where(
        GitHubInstallation.workspace_id == workspace_id,
        GitHubInstallation.account_login == account_login,
    )
    res = await db.execute(stmt)
    inst = res.scalars().first()
    if inst:
        return inst

    # 2. Check if ANY installation exists for this workspace
    workspace_inst_stmt = select(GitHubInstallation).where(
        GitHubInstallation.workspace_id == workspace_id
    )
    workspace_inst_res = await db.execute(workspace_inst_stmt)
    existing_ws_inst = workspace_inst_res.scalars().first()
    if existing_ws_inst:
        return existing_ws_inst

    # 3. Create a new installation with a collision-free integer installation_id
    # Derive unique 63-bit integer from (workspace_id, account_id)
    hash_bytes = hashlib.sha256(f"{workspace_id}:{account_id}:{account_login}".encode()).digest()
    numeric_id = int.from_bytes(hash_bytes[:8], "big") & 0x7FFFFFFFFFFFFFFF

    # Avoid zero
    if numeric_id == 0:
        numeric_id = 1

    # In rare collision case with existing installation_id, adjust
    while True:
        check_unique_stmt = select(GitHubInstallation).where(
            GitHubInstallation.installation_id == numeric_id
        )
        colliding = (await db.execute(check_unique_stmt)).scalars().first()
        if colliding is None:
            break
        numeric_id = (numeric_id + 1) & 0x7FFFFFFFFFFFFFFF

    new_inst = GitHubInstallation(
        workspace_id=workspace_id,
        installation_id=numeric_id,
        account_login=account_login,
        account_type=account_type,
        account_id=account_id,
        is_active=True,
    )
    db.add(new_inst)
    await db.commit()
    await db.refresh(new_inst)
    return new_inst


async def connect_workspace_repository(
    db: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    repo_data: dict[str, Any],
) -> Repository:
    """
    Connect an accessible GitHub repository to the target workspace.
    Enforces workspace membership role (ADMIN or OWNER).
    Prevents duplicate connections within the workspace.
    """
    # 1. Enforce workspace membership authorization
    member_stmt = select(WorkspaceMembership).where(
        WorkspaceMembership.user_id == user_id,
        WorkspaceMembership.workspace_id == workspace_id,
    )
    member_res = await db.execute(member_stmt)
    membership = member_res.scalars().first()
    if not membership:
        raise PermissionError("User is not a member of the target workspace")

    if membership.role not in (WorkspaceRole.ADMIN, WorkspaceRole.OWNER):
        raise PermissionError("Only workspace Admins and Owners can connect repositories")

    # 2. Get user's GitHub account
    github_account = await get_user_github_account(db, user_id)
    if not github_account:
        raise ValueError(
            "GitHub account is not connected. Please connect your GitHub account first."
        )

    github_repo_id = int(repo_data["github_repository_id"])
    owner_login = repo_data.get("owner_login") or github_account.github_login

    # 3. Check for existing repository connection in workspace
    existing_stmt = select(Repository).where(
        Repository.workspace_id == workspace_id,
        Repository.github_repository_id == github_repo_id,
    )
    existing_repo = (await db.execute(existing_stmt)).scalars().first()

    if existing_repo:
        if existing_repo.is_active:
            raise ValueError(
                f"Repository '{existing_repo.full_name}' is already connected to this workspace"
            )
        # Reactivate previously disconnected repository
        existing_repo.is_active = True
        existing_repo.name = repo_data.get("name", existing_repo.name)
        existing_repo.full_name = repo_data.get("full_name", existing_repo.full_name)
        existing_repo.description = repo_data.get("description", existing_repo.description)
        existing_repo.default_branch = repo_data.get("default_branch", existing_repo.default_branch)
        existing_repo.html_url = repo_data.get("html_url", existing_repo.html_url)
        existing_repo.visibility = repo_data.get("visibility", existing_repo.visibility)
        existing_repo.language = repo_data.get("language", existing_repo.language)
        await db.commit()
        await db.refresh(existing_repo)

        # Audit log
        db.add(
            AuditLog(
                workspace_id=workspace_id,
                actor_user_id=user_id,
                action="repository.reconnected",
                resource_type="repository",
                resource_id=str(existing_repo.id),
                details={"full_name": existing_repo.full_name, "github_repo_id": github_repo_id},
            )
        )
        await db.commit()
        return existing_repo

    # 4. Ensure workspace installation exists
    installation = await ensure_workspace_installation(
        db=db,
        workspace_id=workspace_id,
        account_login=owner_login,
        account_id=github_account.github_user_id,
        account_type="User",
    )

    # 5. Create new repository record
    new_repo = Repository(
        workspace_id=workspace_id,
        installation_id=installation.id,
        github_repository_id=github_repo_id,
        name=repo_data["name"],
        full_name=repo_data["full_name"],
        owner_login=owner_login,
        description=repo_data.get("description"),
        default_branch=repo_data.get("default_branch", "main"),
        html_url=repo_data.get("html_url", f"https://github.com/{repo_data['full_name']}"),
        visibility=repo_data.get("visibility", "private"),
        language=repo_data.get("language"),
        is_active=True,
    )
    db.add(new_repo)
    await db.commit()
    await db.refresh(new_repo)

    # 6. Record audit log
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_user_id=user_id,
            action="repository.connected",
            resource_type="repository",
            resource_id=str(new_repo.id),
            details={"full_name": new_repo.full_name, "github_repo_id": github_repo_id},
        )
    )
    await db.commit()
    security_logger.info(
        "security_event=repository_connected workspace_id=%s user_id=%s repo=%s",
        workspace_id,
        user_id,
        new_repo.full_name,
    )
    return new_repo


async def disconnect_workspace_repository(
    db: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    repository_id: uuid.UUID,
) -> bool:
    """Disconnect a repository from a workspace."""
    # 1. Enforce workspace membership authorization
    member_stmt = select(WorkspaceMembership).where(
        WorkspaceMembership.user_id == user_id,
        WorkspaceMembership.workspace_id == workspace_id,
    )
    membership = (await db.execute(member_stmt)).scalars().first()
    if not membership:
        raise PermissionError("User is not a member of the target workspace")
    if membership.role not in (WorkspaceRole.ADMIN, WorkspaceRole.OWNER):
        raise PermissionError("Only workspace Admins and Owners can disconnect repositories")

    # 2. Get repository
    repo_stmt = select(Repository).where(
        Repository.id == repository_id,
        Repository.workspace_id == workspace_id,
        Repository.is_active.is_(True),
    )
    repo = (await db.execute(repo_stmt)).scalars().first()
    if not repo:
        return False

    repo.is_active = False
    await db.commit()

    # Record audit log
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_user_id=user_id,
            action="repository.disconnected",
            resource_type="repository",
            resource_id=str(repository_id),
            details={"full_name": repo.full_name, "github_repo_id": repo.github_repository_id},
        )
    )
    await db.commit()
    security_logger.info(
        "security_event=repository_disconnected workspace_id=%s user_id=%s repo_id=%s",
        workspace_id,
        user_id,
        repository_id,
    )
    return True


async def refresh_workspace_repository(
    db: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    repository_id: uuid.UUID,
) -> Repository:
    """Fetch latest metadata from GitHub and refresh repository entity."""
    # 1. Enforce workspace membership authorization
    member_stmt = select(WorkspaceMembership).where(
        WorkspaceMembership.user_id == user_id,
        WorkspaceMembership.workspace_id == workspace_id,
    )
    membership = (await db.execute(member_stmt)).scalars().first()
    if not membership:
        raise PermissionError("User is not a member of the target workspace")

    # 2. Get repository
    repo_stmt = select(Repository).where(
        Repository.id == repository_id,
        Repository.workspace_id == workspace_id,
        Repository.is_active.is_(True),
    )
    repo = (await db.execute(repo_stmt)).scalars().first()
    if not repo:
        raise LookupError("Repository not found in workspace")

    # 3. Retrieve user's decrypted GitHub token
    github_account = await get_user_github_account(db, user_id)
    if not github_account:
        raise ValueError("GitHub account is not connected. Reconnection required.")

    access_token = decrypt_token(github_account.encrypted_access_token)
    parts = repo.full_name.split("/", 1)
    if len(parts) == 2:
        owner, repo_name = parts
    else:
        owner = repo.owner_login
        repo_name = repo.name

    fresh_data = await fetch_single_repository(access_token, owner, repo_name)
    repo.name = fresh_data.get("name", repo.name)
    repo.full_name = fresh_data.get("full_name", repo.full_name)
    repo.description = fresh_data.get("description", repo.description)
    repo.default_branch = fresh_data.get("default_branch", repo.default_branch)
    repo.html_url = fresh_data.get("html_url", repo.html_url)
    repo.visibility = fresh_data.get("visibility", repo.visibility)
    repo.language = fresh_data.get("language", repo.language)

    await db.commit()
    await db.refresh(repo)

    # Record audit log
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_user_id=user_id,
            action="repository.refreshed",
            resource_type="repository",
            resource_id=str(repository_id),
            details={"full_name": repo.full_name},
        )
    )
    await db.commit()
    return repo
