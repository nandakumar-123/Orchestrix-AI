import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import GitHubInstallation, Workspace
from app.db.session import get_db_session
from app.main import app


@pytest.fixture
async def api_client() -> AsyncGenerator[AsyncClient, None]:
    """Test client with an in-memory SQLite database overriding get_db_session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_get_db_session

    # Seed workspace and installation
    async with session_factory() as sess:
        ws = Workspace(name="API Test Workspace", slug="api-test-ws")
        sess.add(ws)
        await sess.commit()
        await sess.refresh(ws)

        inst = GitHubInstallation(
            workspace_id=ws.id,
            installation_id=88888,
            account_login="api-test-ws",
            account_type="Organization",
            account_id=88888,
        )
        sess.add(inst)
        await sess.commit()
        await sess.refresh(inst)

        app.state.test_workspace_id = ws.id
        app.state.test_installation_id = inst.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_repository_api_crud_lifecycle(api_client: AsyncClient) -> None:
    """Test repository registration, listing, retrieval, update, and deactivation via API."""
    workspace_id = app.state.test_workspace_id
    installation_id = app.state.test_installation_id

    # 1. Create Repository
    create_payload = {
        "workspace_id": str(workspace_id),
        "installation_id": str(installation_id),
        "github_repository_id": 999111,
        "name": "orchestrix-core",
        "full_name": "acme/orchestrix-core",
        "owner_login": "acme",
        "html_url": "https://github.com/acme/orchestrix-core",
        "visibility": "private",
    }
    res = await api_client.post("/api/v1/repositories", json=create_payload)
    assert res.status_code == 201
    repo_data = res.json()
    repo_id = repo_data["id"]
    assert repo_data["name"] == "orchestrix-core"

    # 2. List Repositories
    list_res = await api_client.get(f"/api/v1/repositories?workspace_id={workspace_id}")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total"] == 1
    assert list_data["items"][0]["id"] == repo_id

    # 3. Get Repository By ID
    get_res = await api_client.get(f"/api/v1/repositories/{repo_id}?workspace_id={workspace_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == repo_id

    # 4. Cross-workspace not found
    other_ws_id = uuid.uuid4()
    cross_res = await api_client.get(f"/api/v1/repositories/{repo_id}?workspace_id={other_ws_id}")
    assert cross_res.status_code == 404

    # 5. Patch Repository
    patch_res = await api_client.patch(
        f"/api/v1/repositories/{repo_id}?workspace_id={workspace_id}",
        json={"description": "Updated repository description"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["description"] == "Updated repository description"

    # 6. Delete/Deactivate Repository
    del_res = await api_client.delete(f"/api/v1/repositories/{repo_id}?workspace_id={workspace_id}")
    assert del_res.status_code == 204

    # Verify deactivated repository is no longer in active listing
    list_after_del = await api_client.get(f"/api/v1/repositories?workspace_id={workspace_id}")
    assert list_after_del.json()["total"] == 0


@pytest.mark.asyncio
async def test_engineering_task_api_crud_lifecycle(api_client: AsyncClient) -> None:
    """Test engineering task creation, listing, retrieval, and status updates via API."""
    workspace_id = app.state.test_workspace_id

    # 1. Create Task
    task_payload = {
        "workspace_id": str(workspace_id),
        "title": "Synthesize regression guards",
        "task_type": "TESTING",
        "priority": "HIGH",
        "assigned_agent": "TestPilot",
    }
    create_res = await api_client.post("/api/v1/tasks", json=task_payload)
    assert create_res.status_code == 201
    task_data = create_res.json()
    task_id = task_data["id"]
    assert task_data["status"] == "BACKLOG"
    assert task_data["assigned_agent"] == "TestPilot"

    # 2. List Tasks
    list_res = await api_client.get(f"/api/v1/tasks?workspace_id={workspace_id}")
    assert list_res.status_code == 200
    assert list_res.json()["total"] == 1

    # 3. Patch Task Status
    patch_res = await api_client.patch(
        f"/api/v1/tasks/{task_id}?workspace_id={workspace_id}",
        json={"status": "RUNNING"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "RUNNING"
