import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.db.session import check_database_connection
from app.main import app


@pytest.mark.asyncio
async def test_database_connection_ping() -> None:
    """Test the low-level database ping function."""
    is_connected = await check_database_connection(timeout_seconds=5.0)
    # When DATABASE_URL is configured, connection should succeed
    if settings.DATABASE_URL:
        assert is_connected is True


@pytest.mark.asyncio
async def test_database_health_endpoint() -> None:
    """Test GET /api/v1/health/database endpoint returns structured status without leaking credentials."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health/database")

    # Should return either 200 (healthy) or 503 (unavailable)
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert "database" in data
    assert "connected" in data

    # Verify no credential leaks in response
    serialized = str(data).lower()
    assert "password" not in serialized
    assert "secret" not in serialized
    assert "@" not in serialized
