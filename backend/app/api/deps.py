import uuid
from collections.abc import Callable

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import WorkspaceRole
from app.db.models.membership import WorkspaceMembership
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.auth import (
    SESSION_COOKIE_NAME,
    validate_session_token,
    verify_workspace_membership,
)

__all__ = [
    "get_current_user",
    "get_current_user_optional",
    "require_workspace_membership",
    "verify_workspace_membership",
]


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> User | None:
    """
    Extract session token from HttpOnly cookie or Authorization Bearer header.
    Validates token in database and returns User if active and unexpired, else None.
    """
    # 1. Primary: check HttpOnly session cookie
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)

    # 2. Fallback: check Authorization Bearer header (for API test clients and SDKs)
    if not raw_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            raw_token = auth_header[7:].strip()

    if not raw_token:
        return None

    session_data = await validate_session_token(db, raw_token)
    if not session_data:
        return None

    _, user = session_data
    return user


async def get_current_user(
    current_user: User | None = Depends(get_current_user_optional),
) -> User:
    """
    Dependency that enforces authentication.
    Raises 401 Unauthorized if no valid session is present.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return current_user


def require_workspace_membership(
    min_role: WorkspaceRole = WorkspaceRole.VIEWER,
) -> Callable[..., object]:
    """
    Dependency factory to enforce workspace membership and role hierarchy.
    Extracts workspace_id from query parameter, verifies user's active membership,
    and checks if the user's role meets min_role.
    """

    async def _workspace_auth_dependency(
        workspace_id: uuid.UUID = Query(..., description="Workspace tenant identifier"),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db_session),
    ) -> WorkspaceMembership:
        return await verify_workspace_membership(
            db=db,
            user_id=current_user.id,
            workspace_id=workspace_id,
            min_role=min_role,
        )

    return _workspace_auth_dependency
