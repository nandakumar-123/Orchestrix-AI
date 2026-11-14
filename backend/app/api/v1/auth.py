import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.schemas import (
    CurrentUserResponse,
    LogoutResponse,
    UserWorkspaceMembershipResponse,
)
from app.core.config import settings
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.auth import (
    OAUTH_TRANSIT_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    create_auth_session,
    decode_transit_token,
    encode_transit_token,
    exchange_google_code,
    generate_google_auth_url,
    generate_pkce_pair,
    get_user_with_workspaces,
    provision_or_get_google_user,
    revoke_session_token,
    verify_google_id_token,
)

auth_router = APIRouter(tags=["authentication"])
google_oauth_router = APIRouter(prefix="/auth/google", tags=["google-oauth"])


# -----------------------------------------------------------------------------
# Google OAuth 2.0 PKCE Flow
# -----------------------------------------------------------------------------


@google_oauth_router.get(
    "/login",
    summary="Initiate Google OAuth 2.0 PKCE Flow",
    responses={
        status.HTTP_307_TEMPORARY_REDIRECT: {
            "description": "Redirects user to Google OAuth consent page"
        }
    },
)
async def google_login(request: Request) -> Response:
    """
    Initiate Google OAuth 2.0 PKCE flow.
    Generates cryptographically random state, nonce, and PKCE (S256) verifier/challenge.
    Signs transit parameters into a short-lived transit cookie and redirects to Google.
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth is not configured on the server",
        )

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce_pair()

    transit_token = encode_transit_token(
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
    )

    auth_url = generate_google_auth_url(
        state=state,
        nonce=nonce,
        code_challenge=code_challenge,
    )

    redirect = RedirectResponse(
        url=auth_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    redirect.set_cookie(
        key=OAUTH_TRANSIT_COOKIE_NAME,
        value=transit_token,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.APP_ENV != "development",
        path="/",
    )
    return redirect


@google_oauth_router.get(
    "/callback",
    summary="Google OAuth 2.0 Callback",
    responses={
        status.HTTP_302_FOUND: {
            "description": "Sets session cookie and redirects user to dashboard or login on error"
        }
    },
)
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """
    Handle Google OAuth 2.0 callback:
    - Verifies CSRF state and PKCE verifier from transit cookie
    - Exchanges authorization code for tokens
    - Validates Google ID token signature and nonce against JWKS
    - Provisions or updates user and ensures default personal workspace
    - Issues server-side opaque session and sets HttpOnly cookie
    """
    frontend_url = settings.GOOGLE_FRONTEND_URL.rstrip("/")

    if error:
        return RedirectResponse(
            url=f"{frontend_url}/login?error={error}",
            status_code=status.HTTP_302_FOUND,
        )

    transit_cookie = request.cookies.get(OAUTH_TRANSIT_COOKIE_NAME)
    if not transit_cookie or not code or not state:
        return RedirectResponse(
            url=f"{frontend_url}/login?error=invalid_oauth_state",
            status_code=status.HTTP_302_FOUND,
        )

    transit_data = decode_transit_token(transit_cookie)
    if not transit_data or transit_data.get("state") != state:
        return RedirectResponse(
            url=f"{frontend_url}/login?error=state_mismatch",
            status_code=status.HTTP_302_FOUND,
        )

    expected_nonce = transit_data.get("nonce")
    code_verifier = transit_data.get("code_verifier")
    if not code_verifier:
        return RedirectResponse(
            url=f"{frontend_url}/login?error=missing_verifier",
            status_code=status.HTTP_302_FOUND,
        )

    try:
        token_response = await exchange_google_code(code, code_verifier)
        id_token = token_response.get("id_token")
        if not id_token:
            raise ValueError("No id_token received in Google response")

        claims = await verify_google_id_token(id_token, expected_nonce=expected_nonce)
    except Exception:
        err_response = RedirectResponse(
            url=f"{frontend_url}/login?error=token_verification_failed",
            status_code=status.HTTP_302_FOUND,
        )
        err_response.delete_cookie(OAUTH_TRANSIT_COOKIE_NAME, path="/")
        return err_response

    sub = claims.get("sub")
    email = claims.get("email")
    email_verified = claims.get("email_verified", False)
    full_name = claims.get("name")
    avatar_url = claims.get("picture")

    if not sub or not email or not email_verified:
        err_response = RedirectResponse(
            url=f"{frontend_url}/login?error=unverified_email",
            status_code=status.HTTP_302_FOUND,
        )
        err_response.delete_cookie(OAUTH_TRANSIT_COOKIE_NAME, path="/")
        return err_response

    try:
        user, _, _ = await provision_or_get_google_user(
            db=db,
            sub=sub,
            email=email,
            email_verified=email_verified,
            full_name=full_name,
            avatar_url=avatar_url,
        )
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        _, raw_session_token = await create_auth_session(
            db=db,
            user_id=user.id,
            ip_address=client_ip,
            user_agent=user_agent,
        )
    except Exception:
        err_response = RedirectResponse(
            url=f"{frontend_url}/login?error=provisioning_failed",
            status_code=status.HTTP_302_FOUND,
        )
        err_response.delete_cookie(OAUTH_TRANSIT_COOKIE_NAME, path="/")
        return err_response

    success_response = RedirectResponse(
        url=f"{frontend_url}/dashboard",
        status_code=status.HTTP_302_FOUND,
    )
    success_response.delete_cookie(OAUTH_TRANSIT_COOKIE_NAME, path="/")
    success_response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_session_token,
        max_age=settings.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.APP_ENV != "development",
        path="/",
    )
    return success_response


# -----------------------------------------------------------------------------
# User Profile & Session Management
# -----------------------------------------------------------------------------


@auth_router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="Get current user profile and workspaces",
)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CurrentUserResponse:
    """Return the profile, verified status, and workspaces for the current authenticated user."""
    result = await get_user_with_workspaces(db, current_user.id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    user, workspaces = result

    return CurrentUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        email_verified=user.email_verified,
        workspaces=[
            UserWorkspaceMembershipResponse(
                workspace_id=ws.id,
                name=ws.name,
                slug=ws.slug,
                role=role,
            )
            for ws, role in workspaces
        ],
    )


@auth_router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Revoke session and logout",
)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> LogoutResponse:
    """Revoke the current server-side session and clear the session cookie."""
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        await revoke_session_token(db, raw_token)

    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return LogoutResponse(status="ok", message="Successfully logged out")
