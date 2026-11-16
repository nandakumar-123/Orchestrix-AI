from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_user
from app.db.base import Base, WorkspaceRole
from app.db.models.github_installation import GitHubInstallation
from app.db.models.impactmind import ChangeClassification, ImpactAssessment, ImpactedEntity
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db_session
from app.main import app


@pytest_asyncio.fixture
async def test_db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def api_client(test_db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield test_db_session

    app.dependency_overrides[get_db_session] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def setup_risk_fixtures(test_db_session: AsyncSession) -> dict[str, Any]:
    # Workspaces
    ws1 = Workspace(id=uuid.uuid4(), name="Alpha Team", slug="alpha-team")
    ws2 = Workspace(id=uuid.uuid4(), name="Beta Team", slug="beta-team")
    test_db_session.add_all([ws1, ws2])

    # Users
    u1 = User(id=uuid.uuid4(), email="dev@alpha.com", full_name="Alpha Dev", is_active=True)
    u_outsider = User(id=uuid.uuid4(), email="dev@beta.com", full_name="Beta Dev", is_active=True)
    test_db_session.add_all([u1, u_outsider])

    # Memberships
    m1 = WorkspaceMembership(id=uuid.uuid4(), workspace_id=ws1.id, user_id=u1.id, role=WorkspaceRole.MEMBER)
    m2 = WorkspaceMembership(id=uuid.uuid4(), workspace_id=ws2.id, user_id=u_outsider.id, role=WorkspaceRole.MEMBER)
    test_db_session.add_all([m1, m2])

    # Installations
    inst1 = GitHubInstallation(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        installation_id=3001,
        account_login="alpha-org",
        account_type="Organization",
        account_id=6001,
        is_active=True,
    )
    test_db_session.add(inst1)

    # Repositories
    repo1 = Repository(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        installation_id=inst1.id,
        github_repository_id=30101,
        name="backend-service",
        full_name="alpha-org/backend-service",
        owner_login="alpha-org",
        html_url="https://github.com/alpha-org/backend-service",
        default_branch="main",
        is_active=True,
    )
    test_db_session.add(repo1)
    await test_db_session.flush()

    # Assessments in ws1
    asst1 = ImpactAssessment(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        repository_id=repo1.id,
        comparison_mode="commit_range",
        base_commit_sha="a" * 40,
        target_commit_sha="b" * 40,
        status="completed",
        structural_exposure_score=78.5,
        exposure_tier="HIGH",
    )
    test_db_session.add(asst1)
    await test_db_session.flush()

    c1 = ChangeClassification(
        id=uuid.uuid4(),
        assessment_id=asst1.id,
        file_path="src/worker/pool.py",
        category="interface_change",
        is_breaking=True,
        breaking_reason="Removed deprecated timeout callback",
        confidence=0.95,
    )
    c2 = ChangeClassification(
        id=uuid.uuid4(),
        assessment_id=asst1.id,
        file_path="src/worker/pool.py",
        category="logic_change",
        is_breaking=False,
        confidence=0.90,
    )
    e1 = ImpactedEntity(
        id=uuid.uuid4(),
        assessment_id=asst1.id,
        entity_id="src/worker/pool.py:WorkerPool",
        name="WorkerPool",
        label="Class",
        file_path="src/worker/pool.py",
        impact_type="direct_dependent",
        depth=1,
    )
    test_db_session.add_all([c1, c2, e1])
    await test_db_session.commit()

    return {
        "ws1": ws1,
        "ws2": ws2,
        "u1": u1,
        "u_outsider": u_outsider,
        "repo1": repo1,
        "asst1": asst1,
    }


@pytest.mark.asyncio
async def test_risk_overview_aggregation(
    api_client: AsyncClient,
    setup_risk_fixtures: dict[str, Any],
) -> None:
    data = setup_risk_fixtures
    ws1 = data["ws1"]
    u1 = data["u1"]
    repo1 = data["repo1"]

    app.dependency_overrides[get_current_user] = lambda: u1

    # 1. Query risk overview for ws1
    resp = await api_client.get(f"/api/v1/risk/overview?workspace_id={ws1.id}")
    assert resp.status_code == 200
    res_data = resp.json()

    assert res_data["workspace_id"] == str(ws1.id)
    assert res_data["has_assessment_data"] is True
    assert res_data["total_assessments"] == 1
    assert res_data["latest_risk_score"] == 78.5
    assert res_data["latest_risk_tier"] == "HIGH"
    assert res_data["tier_distribution"]["HIGH"] == 1
    assert res_data["tier_distribution"]["CRITICAL"] == 0
    assert res_data["breaking_changes_total"] == 1
    assert len(res_data["recent_assessments"]) == 1
    assert res_data["recent_assessments"][0]["repository_name"] == "backend-service"
    assert res_data["recent_assessments"][0]["breaking_changes_count"] == 1
    assert len(res_data["top_exposed_files"]) == 1
    assert res_data["top_exposed_files"][0]["file_path"] == "src/worker/pool.py"

    # 2. Query with repository filter
    resp_repo = await api_client.get(
        f"/api/v1/risk/overview?workspace_id={ws1.id}&repository_id={repo1.id}"
    )
    assert resp_repo.status_code == 200
    assert resp_repo.json()["total_assessments"] == 1


@pytest.mark.asyncio
async def test_risk_overview_empty_and_tenant_isolation(
    api_client: AsyncClient,
    setup_risk_fixtures: dict[str, Any],
) -> None:
    data = setup_risk_fixtures
    ws1 = data["ws1"]
    ws2 = data["ws2"]
    u_outsider = data["u_outsider"]

    # 1. Outsider cannot access ws1
    app.dependency_overrides[get_current_user] = lambda: u_outsider
    resp_forbidden = await api_client.get(f"/api/v1/risk/overview?workspace_id={ws1.id}")
    assert resp_forbidden.status_code == 403

    # 2. ws2 has no repositories/assessments -> returns empty cleanly
    resp_empty = await api_client.get(f"/api/v1/risk/overview?workspace_id={ws2.id}")
    assert resp_empty.status_code == 200
    empty_data = resp_empty.json()
    assert empty_data["workspace_id"] == str(ws2.id)
    assert empty_data["has_assessment_data"] is False
    assert empty_data["total_assessments"] == 0
    assert empty_data["latest_risk_score"] is None
    assert empty_data["latest_risk_tier"] is None
    assert empty_data["breaking_changes_total"] == 0
    assert len(empty_data["recent_assessments"]) == 0
    assert len(empty_data["top_exposed_files"]) == 0
