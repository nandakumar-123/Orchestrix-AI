from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.api.v1.schemas import DatabaseHealthResponse, HealthResponse
from app.core.config import settings
from app.db.session import check_database_connection

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service Health Check")
async def get_health() -> HealthResponse:
    """Return application operational status."""
    return HealthResponse(
        status="ok",
        app=settings.APP_NAME,
        environment=settings.APP_ENV,
        version="0.1.0",
    )


@router.get(
    "/health/database",
    response_model=DatabaseHealthResponse,
    summary="Database Connectivity Health Check",
    responses={
        status.HTTP_200_OK: {"description": "Database is reachable and healthy"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Database connection failed"},
    },
)
async def get_database_health() -> JSONResponse:
    """Check connectivity to PostgreSQL database safely without exposing credentials."""
    is_connected = await check_database_connection(timeout_seconds=3.0)

    db_type = "postgresql" if "postgresql" in settings.async_database_url else "database"

    payload = DatabaseHealthResponse(
        status="healthy" if is_connected else "unavailable",
        database=db_type,
        connected=is_connected,
    )

    status_code = status.HTTP_200_OK if is_connected else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=payload.model_dump())
