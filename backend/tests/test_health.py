import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_root_endpoint() -> None:
    """Test root endpoint returns running status and metadata."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Orchestrix AI"
    assert data["status"] == "running"
    assert "/health" in data["health"]


@pytest.mark.asyncio
async def test_health_check_endpoint() -> None:
    """Test health check returns status ok and correct version."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "Orchestrix AI"
    assert data["version"] == "0.1.0"
