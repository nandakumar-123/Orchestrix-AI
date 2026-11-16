from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    require_workspace_membership,
)
from app.db.base import WorkspaceRole
from app.db.models.membership import WorkspaceMembership
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.dashboard.dashboard_service import DashboardService
from app.services.dashboard.schemas import DashboardOverviewResponse

logger = logging.getLogger(__name__)

dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@dashboard_router.get(
    "/overview",
    response_model=DashboardOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Get aggregated workspace dashboard overview",
)
async def get_dashboard_overview(
    workspace_id: Annotated[uuid.UUID, Query(description="Workspace ID")],
    repository_id: Annotated[uuid.UUID | None, Query(description="Optional repository filter")] = None,
    current_user: User = Depends(get_current_user),
    membership: WorkspaceMembership = Depends(
        require_workspace_membership(WorkspaceRole.VIEWER)
    ),
    db: AsyncSession = Depends(get_db_session),
) -> DashboardOverviewResponse:
    """Retrieve verified aggregated workspace metrics, agent status, recent tasks, and activity events."""
    try:
        service = DashboardService(db)
        return await service.get_overview(
            workspace_id=workspace_id,
            repository_id=repository_id,
        )
    except Exception as e:
        logger.exception("Failed to assemble dashboard overview for workspace %s: %s", workspace_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve dashboard overview data.",
        ) from e
