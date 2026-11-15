from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import WorkspaceRole
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.auth import verify_workspace_membership

logger = logging.getLogger("orchestrix.api.permissions")


async def resolve_repository_workspace(
    repository_id: uuid.UUID,
    workspace_id: uuid.UUID | None = Query(default=None, description="Workspace tenant identifier"),
    db: AsyncSession = Depends(get_db_session),
) -> tuple[Repository, uuid.UUID]:
    """
    Resolve the repository and its workspace ID.
    Validates that if workspace_id query parameter is supplied, it matches the repository's workspace_id.
    Prevents cross-workspace IDOR.
    """
    repo = await db.get(Repository, repository_id)
    if not repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found",
        )
    if workspace_id is not None and repo.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repository_id} not found in workspace",
        )
    return repo, repo.workspace_id


def require_repository_workspace_role(
    min_role: WorkspaceRole = WorkspaceRole.VIEWER,
) -> Callable[..., Any]:
    """
    Dependency factory to authenticate user, resolve repository & workspace,
    and enforce workspace membership meets or exceeds the required minimum role.
    Role hierarchy: VIEWER (1) < MEMBER (2) < ADMIN (3) < OWNER (4).
    """

    async def _workspace_role_dependency(
        repo_and_ws: tuple[Repository, uuid.UUID] = Depends(resolve_repository_workspace),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db_session),
    ) -> tuple[Repository, uuid.UUID, WorkspaceMembership]:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Cookie"},
            )
        repo, workspace_id = repo_and_ws
        membership = await verify_workspace_membership(
            db=db,
            user_id=current_user.id,
            workspace_id=workspace_id,
            min_role=min_role,
        )
        return repo, workspace_id, membership

    return _workspace_role_dependency


# Pre-configured role dependencies for clean endpoint declarations
require_workspace_viewer = require_repository_workspace_role(WorkspaceRole.VIEWER)
require_workspace_member = require_repository_workspace_role(WorkspaceRole.MEMBER)
require_workspace_admin = require_repository_workspace_role(WorkspaceRole.ADMIN)
require_workspace_owner = require_repository_workspace_role(WorkspaceRole.OWNER)
