from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import enforce_csrf_protection, get_current_user
from app.api.v1.schemas import (
    CsrfTokenResponse,
    CurrentUserResponse,
    LogoutResponse,
    UserWorkspaceMembershipResponse,
)
from app.core.config import settings
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.auth import (
    CSRF_COOKIE_NAME,
    OAUTH_TRX_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    consume_oauth_transaction,
    create_auth_session,
    create_oauth_transaction,
    exchange_google_code,
    generate_csrf_token,
    generate_google_auth_url,
    get_user_with_workspaces,
    provision_or_get_google_user,
    revoke_session_token,
    security_logger,
    verify_google_id_token,
)

auth_router = APIRouter(tags=["authentication"])
google_oauth_router = APIRouter(prefix="/auth/google", tags=["google-oauth"])


# -----------------------------------------------------------------------------
# Google OAuth 2.0 PKCE Flow (Hardened with Server-Side Transaction & Replay Protection)
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
async def google_login(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """
    Initiate Google OAuth 2.0 PKCE flow.
    Generates a server-side one-time OAuth transaction in PostgreSQL.
    Binds the transaction to the browser using an unguessable HttpOnly cookie secret.
    Zero raw PKCE code verifiers or nonces are exposed to the browser.
    """
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_REDIRECT_URI:
        security_logger.error(
            "security_event=google_oauth_unconfigured missing_client_id=%s missing_redirect_uri=%s",
            not bool(settings.GOOGLE_CLIENT_ID),
            not bool(settings.GOOGLE_REDIRECT_URI),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth is not configured on the server: missing client_id or redirect_uri",
        )

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    trx, browser_secret, state, code_challenge = await create_oauth_transaction(
        db=db,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    try:
        auth_url = generate_google_auth_url(
            state=state,
            nonce=trx.nonce,
            code_challenge=code_challenge,
            redirect_uri=settings.GOOGLE_REDIRECT_URI,
        )
    except ValueError as exc:
        security_logger.error("security_event=google_auth_url_generation_failed error=%s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate Google OAuth URL: {exc}",
        ) from exc

    redirect = RedirectResponse(
        url=auth_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    # Set short-lived browser binding cookie (10 minutes)
    redirect.set_cookie(
        key=OAUTH_TRX_COOKIE_NAME,
        value=browser_secret,
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
    Handle Google OAuth 2.0 callback with atomic one-time transaction consumption:
    - Verifies and atomically consumes server-side transaction record (replay-proof)
    - Validates state against stored transaction hash
    - Exchanges authorization code for tokens using server-stored PKCE verifier
    - Validates Google ID token against Google's JWKS and stored nonce
    - Provisions or links user account safely without race conditions or conflicting identities
    - Issues server-side opaque session and sets HttpOnly session + CSRF cookies
    """
    frontend_url = settings.GOOGLE_FRONTEND_URL.rstrip("/")

    def _error_redirect(err_code: str) -> RedirectResponse:
        res = RedirectResponse(
            url=f"{frontend_url}/login?error={err_code}",
            status_code=status.HTTP_302_FOUND,
        )
        res.delete_cookie(OAUTH_TRX_COOKIE_NAME, path="/")
        return res

    if error:
        security_logger.warning("security_event=google_oauth_callback_error error=%s", error)
        return _error_redirect(error)

    browser_secret = request.cookies.get(OAUTH_TRX_COOKIE_NAME)
    if not browser_secret or not code or not state:
        security_logger.warning("security_event=oauth_callback_missing_params")
        return _error_redirect("missing_oauth_params")

    # Atomically consume transaction from PostgreSQL
    trx, err_reason = await consume_oauth_transaction(
        db=db,
        browser_secret=browser_secret,
        state=state,
    )
    if trx is None:
        return _error_redirect(err_reason or "invalid_oauth_state")

    try:
        token_response = await exchange_google_code(
            code=code,
            code_verifier=trx.code_verifier,
            redirect_uri=settings.GOOGLE_REDIRECT_URI,
        )
        id_token = token_response.get("id_token")
        if not id_token:
            raise ValueError("No id_token received in Google response")

        claims = await verify_google_id_token(id_token, expected_nonce=trx.nonce)
    except Exception as exc:
        security_logger.error("security_event=token_verification_failed error=%s", str(exc))
        return _error_redirect("token_verification_failed")

    sub = claims.get("sub")
    email = claims.get("email")
    email_verified = claims.get("email_verified", False)
    full_name = claims.get("name")
    avatar_url = claims.get("picture")

    if not sub or not email or not email_verified:
        security_logger.warning("security_event=unverified_email_rejected")
        return _error_redirect("unverified_email")

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
    except HTTPException as http_exc:
        if http_exc.status_code == status.HTTP_409_CONFLICT:
            return _error_redirect("account_linking_conflict")
        if http_exc.status_code == status.HTTP_403_FORBIDDEN:
            return _error_redirect("account_inactive")
        return _error_redirect("provisioning_failed")
    except Exception as exc:
        security_logger.error("security_event=provisioning_unexpected_error error=%s", str(exc))
        return _error_redirect("provisioning_failed")

    success_response = RedirectResponse(
        url=f"{frontend_url}/dashboard",
        status_code=status.HTTP_302_FOUND,
    )
    # Always delete the one-time transaction cookie
    success_response.delete_cookie(OAUTH_TRX_COOKIE_NAME, path="/")

    # Issue secure HttpOnly session cookie
    success_response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_session_token,
        max_age=settings.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.APP_ENV != "development",
        path="/",
    )

    # Issue initial CSRF token cookie for frontend
    csrf_token = generate_csrf_token()
    success_response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=settings.SESSION_TTL_SECONDS,
        httponly=False,  # Accessible to frontend JS to mirror in X-CSRF-Token header
        samesite="lax",
        secure=settings.APP_ENV != "development",
        path="/",
    )

    security_logger.info("security_event=oauth_login_success user_id=%s", user.id)
    return success_response


# -----------------------------------------------------------------------------
# User Profile, CSRF & Session Management
# -----------------------------------------------------------------------------


@auth_router.get(
    "/csrf",
    response_model=CsrfTokenResponse,
    summary="Get CSRF Token",
)
async def get_csrf_token(response: Response) -> CsrfTokenResponse:
    """Generate and return an HMAC-signed CSRF token, setting the double-submit cookie."""
    token = generate_csrf_token()
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=settings.SESSION_TTL_SECONDS,
        httponly=False,
        samesite="lax",
        secure=settings.APP_ENV != "development",
        path="/",
    )
    return CsrfTokenResponse(csrf_token=token)


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
    _csrf: None = Depends(enforce_csrf_protection),
) -> LogoutResponse:
    """Revoke the current server-side session and clear cookies."""
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        await revoke_session_token(db, raw_token)

    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    response.delete_cookie(OAUTH_TRX_COOKIE_NAME, path="/")
    return LogoutResponse(status="ok", message="Successfully logged out")
