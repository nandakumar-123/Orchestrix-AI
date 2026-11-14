from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.api.v1.auth import google_oauth_router
from app.core.config import settings
from app.db.session import close_database_connection, get_async_engine


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown events cleanly."""
    # Ensure database connection pool initializes
    get_async_engine()
    yield
    # Dispose connection pool cleanly on shutdown
    await close_database_connection()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    application = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router, prefix=settings.API_V1_STR)
    application.include_router(google_oauth_router)

    @application.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        return {
            "name": settings.APP_NAME,
            "status": "running",
            "docs": "/docs",
            "health": f"{settings.API_V1_STR}/health",
            "database_health": f"{settings.API_V1_STR}/health/database",
        }

    return application


app = create_app()
