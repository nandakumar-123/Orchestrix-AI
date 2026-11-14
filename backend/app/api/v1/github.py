import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    enforce_csrf_protection,
    get_current_user,
    get_current_user_optional,
    require_workspace_membership,
)
from app.api.v1.schemas import (
    ConnectRepositoryPayload,
    GitHubConnectUrlResponse,
    GitHubDisconnectResponse,
    GitHubRepositoryItem,
    GitHubRepositoryListResponse,
    GitHubStatusResponse,
    RepositoryResponse,
)
from app.core.config import settings
from app.db.base import WorkspaceRole
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.github import (
    connect_workspace_repository,
    consume_github_oauth_transaction,
    create_github_oauth_transaction,
    decrypt_token,
    disconnect_github_account,
    disconnect_workspace_repository,
    exchange_github_code,
    fetch_github_user_profile,
    get_user_github_account,
    list_accessible_repositories,
    refresh_workspace_repository,
    upsert_github_account,
    verify_github_oauth_state,
)

github_router = APIRouter(prefix="/github", tags=["github"])
security_logger = logging.getLogger("orchestrix.security")


# -----------------------------------------------------------------------------
# GitHub Account OAuth Connection
# -----------------------------------------------------------------------------


@github_router.get(
    "/connect",
    summary="Initiate GitHub account connection",
    response_model=GitHubConnectUrlResponse,
    responses={
        status.HTTP_307_TEMPORARY_REDIRECT: {
            "description": "Redirects directly to GitHub OAuth authorize screen"
        },
        status.HTTP_200_OK: {"description": "Returns authorization URL for client-side navigation"},
    },
)
async def github_connect(
    request: Request,
    response: Response,
    redirect: bool = Query(
        default=True, description="Whether to redirect directly or return JSON URL"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """
    Initiate GitHub OAuth connection for the authenticated user.
    Generates a server-side transaction, binds it to an HttpOnly cookie and current_user.id.
    """
    try:
        ip_addr = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        _trx, browser_secret, state, auth_url = await create_github_oauth_transaction(
            db=db,
            user_id=current_user.id,
            ip_address=ip_addr,
            user_agent=user_agent,
        )
    except ValueError as exc:
        security_logger.error("security_event=github_connect_unconfigured error=%s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if redirect:
        redirect_res = RedirectResponse(
            url=auth_url,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )
        redirect_res.set_cookie(
            key=settings.GITHUB_OAUTH_TRX_COOKIE_NAME,
            value=browser_secret,
            max_age=600,
            httponly=True,
            samesite="lax",
            secure=settings.APP_ENV != "development",
            path="/",
        )
        return redirect_res

    response.set_cookie(
        key=settings.GITHUB_OAUTH_TRX_COOKIE_NAME,
        value=browser_secret,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.APP_ENV != "development",
        path="/",
    )
    return GitHubConnectUrlResponse(auth_url=auth_url, state=state)


@github_router.get(
    "/callback",
    summary="GitHub OAuth Callback",
    responses={
        status.HTTP_302_FOUND: {"description": "Redirects user back to frontend repositories page"}
    },
)
async def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """
    Handle GitHub OAuth callback:
    - Enforces browser-session binding via GITHUB_OAUTH_TRX_COOKIE_NAME.
    - Requires active authenticated user in browser session (SEC-01).
    - Validates HMAC signature, expiration, and user authenticity of state.
    - Atomically consumes one-time server transaction to prevent replay attacks (SEC-04).
    - Exchanges code for access token.
    - Stores encrypted token in github_accounts table.
    - Clears transaction cookie and redirects user back to frontend with status.
    """
    frontend_url = settings.GITHUB_FRONTEND_URL

    def _redirect_with_param(param_str: str) -> RedirectResponse:
        delimiter = "&" if "?" in frontend_url else "?"
        res = RedirectResponse(
            url=f"{frontend_url}{delimiter}{param_str}",
            status_code=status.HTTP_302_FOUND,
        )
        # Always clean up one-time transaction cookie
        res.delete_cookie(key=settings.GITHUB_OAUTH_TRX_COOKIE_NAME, path="/")
        return res

    # 1. Check for provider error
    if error:
        security_logger.warning(
            "security_event=github_callback_error error=%s description=%s", error, error_description
        )
        return _redirect_with_param(f"github_error={error}")

    browser_secret = request.cookies.get(settings.GITHUB_OAUTH_TRX_COOKIE_NAME)
    if not code or not state or not browser_secret:
        security_logger.warning("security_event=github_callback_missing_params")
        return _redirect_with_param("github_error=missing_oauth_params")

    # 2. Enforce active authenticated Orchestrix session
    if current_user is None:
        security_logger.warning("security_event=github_callback_unauthenticated")
        return _redirect_with_param("github_error=unauthenticated")

    # 3. Verify state signature and strictly bind to current_user.id
    state_user_id = verify_github_oauth_state(state, expected_user_id=current_user.id)
    if not state_user_id:
        security_logger.warning("security_event=github_callback_user_mismatch_or_invalid_state")
        return _redirect_with_param("github_error=user_mismatch")

    # 4. Atomically consume server-side transaction with replay protection
    trx, trx_error = await consume_github_oauth_transaction(
        db=db,
        browser_secret=browser_secret,
        state=state,
        expected_user_id=current_user.id,
    )
    if trx_error or trx is None:
        security_logger.warning(
            "security_event=github_callback_transaction_failed error=%s", trx_error
        )
        return _redirect_with_param(f"github_error={trx_error or 'invalid_transaction'}")

    # 5. Exchange code for access token
    try:
        token_data = await exchange_github_code(code)
        access_token = token_data["access_token"]
        token_type = token_data.get("token_type", "bearer")
        scope = token_data.get("scope")

        # 6. Fetch GitHub user profile
        profile = await fetch_github_user_profile(access_token)

        # 7. Persist encrypted credentials to database
        await upsert_github_account(
            db=db,
            user_id=trx.user_id,
            profile=profile,
            access_token=access_token,
            token_type=token_type,
            scope=scope,
        )
    except Exception as exc:
        security_logger.error("security_event=github_callback_failure error=%s", str(exc))
        return _redirect_with_param("github_error=connection_failed")

    login = profile.get("login", "")
    return _redirect_with_param(f"github=connected&login={login}")


@github_router.get(
    "/status",
    response_model=GitHubStatusResponse,
    summary="Get connected GitHub account status",
)
async def get_github_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> GitHubStatusResponse:
    """Return whether the authenticated user has connected their GitHub account."""
    account = await get_user_github_account(db, current_user.id)
    if not account:
        return GitHubStatusResponse(connected=False)

    return GitHubStatusResponse(
        connected=True,
        github_login=account.github_login,
        name=account.name,
        avatar_url=account.avatar_url,
        html_url=account.html_url,
        scope=account.scope,
        connected_at=account.updated_at or account.created_at,
    )


@github_router.delete(
    "/disconnect",
    response_model=GitHubDisconnectResponse,
    summary="Disconnect GitHub account",
)
async def disconnect_github(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(enforce_csrf_protection),
) -> GitHubDisconnectResponse:
    """Disconnect user's GitHub account and remove all stored encrypted credentials."""
    disconnected = await disconnect_github_account(db, current_user.id)
    if not disconnected:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No connected GitHub account found",
        )

    return GitHubDisconnectResponse(
        status="ok",
        message="GitHub account successfully disconnected",
    )


# -----------------------------------------------------------------------------
# GitHub Repository Discovery
# -----------------------------------------------------------------------------


@github_router.get(
    "/repositories",
    response_model=GitHubRepositoryListResponse,
    summary="List repositories accessible to connected GitHub account",
)
async def list_github_repositories(
    workspace_id: uuid.UUID = Query(..., description="Active workspace context"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    _membership: WorkspaceMembership = Depends(require_workspace_membership(WorkspaceRole.VIEWER)),
    db: AsyncSession = Depends(get_db_session),
) -> GitHubRepositoryListResponse:
    """
    Retrieve repositories accessible to the user's connected GitHub account.
    Cross-references with the workspace's existing repositories to mark is_connected.
    """
    account = await get_user_github_account(db, current_user.id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub account is not connected. Please connect your GitHub account first.",
        )

    try:
        access_token = decrypt_token(account.encrypted_access_token)
        repos = await list_accessible_repositories(
            access_token=access_token,
            page=page,
            per_page=per_page,
        )
    except PermissionError as perm_err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GitHub credentials have expired or been revoked. Please reconnect your account.",
        ) from perm_err
    except RuntimeError as run_err:
        if "rate limit" in str(run_err).lower():
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="GitHub API rate limit exceeded. Please wait a few moments.",
            ) from run_err
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch repositories from GitHub: {run_err}",
        ) from run_err

    # Query currently active repositories in workspace to flag already-connected repos
    repo_ids = [r["id"] for r in repos if r.get("id")]
    connected_ids: set[int] = set()

    if repo_ids:
        connected_stmt = select(Repository.github_repository_id).where(
            Repository.workspace_id == workspace_id,
            Repository.github_repository_id.in_(repo_ids),
            Repository.is_active.is_(True),
        )
        connected_res = await db.execute(connected_stmt)
        connected_ids = set(connected_res.scalars().all())

    items = [
        GitHubRepositoryItem(
            id=r["id"],
            name=r["name"],
            full_name=r["full_name"],
            owner_login=r["owner_login"],
            owner_avatar_url=r.get("owner_avatar_url"),
            description=r.get("description"),
            default_branch=r.get("default_branch", "main"),
            html_url=r["html_url"],
            visibility=r.get("visibility", "public"),
            language=r.get("language"),
            updated_at=r.get("updated_at"),
            stargazers_count=r.get("stargazers_count", 0),
            forks_count=r.get("forks_count", 0),
            open_issues_count=r.get("open_issues_count", 0),
            is_connected=(r["id"] in connected_ids),
        )
        for r in repos
    ]

    return GitHubRepositoryListResponse(
        items=items,
        page=page,
        per_page=per_page,
    )


@github_router.post(
    "/repositories/connect",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect an accessible GitHub repository to workspace",
)
async def connect_repository(
    payload: ConnectRepositoryPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(enforce_csrf_protection),
) -> RepositoryResponse:
    """
    Connect an accessible GitHub repository to the target workspace.
    Requires workspace ADMIN or OWNER role.
    """
    try:
        repo = await connect_workspace_repository(
            db=db,
            user_id=current_user.id,
            workspace_id=payload.workspace_id,
            repo_data=payload.model_dump(),
        )
        return RepositoryResponse.model_validate(repo)
    except PermissionError as perm_err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(perm_err),
        ) from perm_err
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        ) from val_err
    except Exception as exc:
        security_logger.error("security_event=repo_connection_failed error=%s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect repository: {exc}",
        ) from exc


# -----------------------------------------------------------------------------
# Workspace Repository Disconnect & Refresh
# -----------------------------------------------------------------------------


@github_router.post(
    "/repositories/{repository_id}/refresh",
    response_model=RepositoryResponse,
    summary="Refresh connected repository metadata from GitHub",
)
async def refresh_repository(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Active workspace context"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(enforce_csrf_protection),
) -> RepositoryResponse:
    """Fetch latest metadata from GitHub and refresh the repository record."""
    try:
        refreshed = await refresh_workspace_repository(
            db=db,
            user_id=current_user.id,
            workspace_id=workspace_id,
            repository_id=repository_id,
        )
        return RepositoryResponse.model_validate(refreshed)
    except PermissionError as perm_err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(perm_err),
        ) from perm_err
    except LookupError as look_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(look_err),
        ) from look_err
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        ) from val_err
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh repository metadata: {exc}",
        ) from exc


@github_router.delete(
    "/repositories/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect repository from workspace",
)
async def disconnect_repository(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Active workspace context"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(enforce_csrf_protection),
) -> Response:
    """Disconnect a repository from the workspace."""
    try:
        success = await disconnect_workspace_repository(
            db=db,
            user_id=current_user.id,
            workspace_id=workspace_id,
            repository_id=repository_id,
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Repository not found in workspace",
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except PermissionError as perm_err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(perm_err),
        ) from perm_err
