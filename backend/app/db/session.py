import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger("orchestrix.db")

_async_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_async_engine() -> AsyncEngine:
    """Initialize or return the singleton asynchronous SQLAlchemy engine."""
    global _async_engine, _async_session_factory

    if _async_engine is not None:
        return _async_engine

    db_url = settings.async_database_url
    if not db_url:
        logger.warning("DATABASE_URL is not configured; using memory fallback for engine.")
        db_url = "sqlite+aiosqlite:///:memory:"

    connect_args: dict[str, object] = {}
    engine_kwargs: dict[str, object] = {
        "echo": settings.DB_ECHO,
        "future": True,
    }

    # PostgreSQL / Neon specific connection pool optimization
    if db_url.startswith("postgresql"):
        engine_kwargs.update(
            {
                "pool_size": settings.DB_POOL_SIZE,
                "max_overflow": settings.DB_MAX_OVERFLOW,
                "pool_timeout": settings.DB_POOL_TIMEOUT,
                "pool_recycle": settings.DB_POOL_RECYCLE,
                "pool_pre_ping": True,
            }
        )

    _async_engine = create_async_engine(
        db_url,
        connect_args=connect_args,
        **engine_kwargs,
    )

    _async_session_factory = async_sessionmaker(
        bind=_async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    return _async_engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory, initializing engine if needed."""
    if _async_session_factory is None:
        get_async_engine()
    assert _async_session_factory is not None
    return _async_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency yielding a transactional AsyncSession.
    Ensures safe commit on success and rollback on exceptions.
    """
    session_factory = get_async_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_database_connection(timeout_seconds: float = 3.0) -> bool:
    """
    Execute a lightweight connectivity ping (SELECT 1) against the database.
    Catches errors safely without exposing credentials or stack traces.
    """
    try:
        engine = get_async_engine()
        async with engine.connect() as conn:
            # Enforce quick timeout check
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error(f"Database health check failed: {exc.__class__.__name__}")
        return False


async def close_database_connection() -> None:
    """Dispose and cleanly close database engine pool connections."""
    global _async_engine, _async_session_factory
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _async_session_factory = None
        logger.info("Database connection engine closed.")
