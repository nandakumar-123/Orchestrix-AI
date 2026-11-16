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
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db_session
from app.main import app
from app.services.auth import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token


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
async def setup_ticket_fixtures(test_db_session: AsyncSession) -> dict[str, Any]:
    # Workspaces
    ws1 = Workspace(id=uuid.uuid4(), name="Engineering Team Alpha", slug="eng-alpha")
    ws2 = Workspace(id=uuid.uuid4(), name="Engineering Team Beta", slug="eng-beta")
    test_db_session.add_all([ws1, ws2])

    # Users
    u_owner = User(id=uuid.uuid4(), email="owner@alpha.com", full_name="Alpha Owner", is_active=True)
    u_member = User(id=uuid.uuid4(), email="member@alpha.com", full_name="Alpha Member", is_active=True)
    u_viewer = User(id=uuid.uuid4(), email="viewer@alpha.com", full_name="Alpha Viewer", is_active=True)
    u_outsider = User(id=uuid.uuid4(), email="outsider@beta.com", full_name="Beta Outsider", is_active=True)
    test_db_session.add_all([u_owner, u_member, u_viewer, u_outsider])

    # Memberships
    m_owner = WorkspaceMembership(id=uuid.uuid4(), workspace_id=ws1.id, user_id=u_owner.id, role=WorkspaceRole.OWNER)
    m_member = WorkspaceMembership(id=uuid.uuid4(), workspace_id=ws1.id, user_id=u_member.id, role=WorkspaceRole.MEMBER)
    m_viewer = WorkspaceMembership(id=uuid.uuid4(), workspace_id=ws1.id, user_id=u_viewer.id, role=WorkspaceRole.VIEWER)
    m_outsider = WorkspaceMembership(id=uuid.uuid4(), workspace_id=ws2.id, user_id=u_outsider.id, role=WorkspaceRole.MEMBER)
    test_db_session.add_all([m_owner, m_member, m_viewer, m_outsider])

    # GitHub Installations
    inst1 = GitHubInstallation(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        installation_id=1001,
        account_login="org-alpha",
        account_type="Organization",
        account_id=5001,
        is_active=True,
    )
    inst2 = GitHubInstallation(
        id=uuid.uuid4(),
        workspace_id=ws2.id,
        installation_id=1002,
        account_login="org-beta",
        account_type="Organization",
        account_id=5002,
        is_active=True,
    )
    test_db_session.add_all([inst1, inst2])

    # Repositories
    repo_ws1 = Repository(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        installation_id=inst1.id,
        github_repository_id=10101,
        name="alpha-core",
        full_name="org/alpha-core",
        owner_login="org",
        html_url="https://github.com/org/alpha-core",
        default_branch="main",
        is_active=True,
    )
    repo_ws2 = Repository(
        id=uuid.uuid4(),
        workspace_id=ws2.id,
        installation_id=inst2.id,
        github_repository_id=20202,
        name="beta-core",
        full_name="org/beta-core",
        owner_login="org",
        html_url="https://github.com/org/beta-core",
        default_branch="main",
        is_active=True,
    )
    test_db_session.add_all([repo_ws1, repo_ws2])
    await test_db_session.commit()

    return {
        "ws1": ws1,
        "ws2": ws2,
        "u_owner": u_owner,
        "u_member": u_member,
        "u_viewer": u_viewer,
        "u_outsider": u_outsider,
        "repo_ws1": repo_ws1,
        "repo_ws2": repo_ws2,
    }


def _auth_headers() -> dict[str, str]:
    csrf = generate_csrf_token()
    return {
        "Origin": "http://localhost:3000",
        CSRF_HEADER_NAME: csrf,
    }


@pytest.mark.asyncio
async def test_ticket_crud_and_activity_lifecycle(
    api_client: AsyncClient,
    setup_ticket_fixtures: dict[str, Any],
) -> None:
    data = setup_ticket_fixtures
    ws1 = data["ws1"]
    u_member = data["u_member"]
    repo_ws1 = data["repo_ws1"]

    app.dependency_overrides[get_current_user] = lambda: u_member
    csrf = generate_csrf_token()
    api_client.cookies.set(CSRF_COOKIE_NAME, csrf)

    # 1. Create a ticket
    create_payload = {
        "workspace_id": str(ws1.id),
        "title": "Fix memory leak in background worker pool",
        "description": "Worker threads fail to release database connection on timeout.",
        "priority": "HIGH",
        "repository_id": str(repo_ws1.id),
        "assignee_id": str(u_member.id),
        "tags": ["performance", "backend"],
    }
    resp_create = await api_client.post(
        "/api/v1/tickets",
        json=create_payload,
        headers={"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf},
    )
    assert resp_create.status_code == 201
    ticket_data = resp_create.json()
    ticket_id = ticket_data["id"]

    assert ticket_data["title"] == "Fix memory leak in background worker pool"
    assert ticket_data["status"] == "OPEN"
    assert ticket_data["priority"] == "HIGH"
    assert ticket_data["repository_name"] == "alpha-core"
    assert ticket_data["assignee_name"] == "Alpha Member"
    assert len(ticket_data["activities"]) == 1
    assert ticket_data["activities"][0]["activity_type"] == "CREATED"

    # 2. Get ticket by ID
    resp_get = await api_client.get(f"/api/v1/tickets/{ticket_id}?workspace_id={ws1.id}")
    assert resp_get.status_code == 200
    assert resp_get.json()["id"] == ticket_id

    # 3. Update ticket metadata (priority, description)
    update_payload = {
        "priority": "CRITICAL",
        "description": "Urgent: production workers timing out under load.",
    }
    resp_patch = await api_client.patch(
        f"/api/v1/tickets/{ticket_id}?workspace_id={ws1.id}",
        json=update_payload,
        headers={"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf},
    )
    assert resp_patch.status_code == 200
    patched_data = resp_patch.json()
    assert patched_data["priority"] == "CRITICAL"
    assert any(a["activity_type"] == "PRIORITY_CHANGED" for a in patched_data["activities"])

    # 4. Status transition: OPEN -> IN_PROGRESS
    status_payload = {"status": "IN_PROGRESS", "comment": "Started investigating connection pool"}
    resp_status = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/status?workspace_id={ws1.id}",
        json=status_payload,
        headers={"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf},
    )
    assert resp_status.status_code == 200
    assert resp_status.json()["status"] == "IN_PROGRESS"
    assert resp_status.json()["resolved_at"] is None

    # 5. Add comment
    comment_payload = {"comment": "Found unclosed session in worker task loop."}
    resp_comment = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/comments?workspace_id={ws1.id}",
        json=comment_payload,
        headers={"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf},
    )
    assert resp_comment.status_code == 201
    assert resp_comment.json()["comment"] == "Found unclosed session in worker task loop."

    # 6. Status transition: IN_PROGRESS -> RESOLVED
    resolve_payload = {"status": "RESOLVED", "comment": "Fixed session lifecycle in PR #42"}
    resp_resolve = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/status?workspace_id={ws1.id}",
        json=resolve_payload,
        headers={"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf},
    )
    assert resp_resolve.status_code == 200
    assert resp_resolve.json()["status"] == "RESOLVED"
    assert resp_resolve.json()["resolved_at"] is not None

    # 7. List tickets with filters
    resp_list = await api_client.get(
        f"/api/v1/tickets?workspace_id={ws1.id}&status=RESOLVED&search=memory"
    )
    assert resp_list.status_code == 200
    list_data = resp_list.json()
    assert list_data["total"] == 1
    assert list_data["items"][0]["id"] == ticket_id


@pytest.mark.asyncio
async def test_ticket_security_and_tenant_isolation(
    api_client: AsyncClient,
    setup_ticket_fixtures: dict[str, Any],
) -> None:
    data = setup_ticket_fixtures
    ws1 = data["ws1"]
    u_member = data["u_member"]
    u_viewer = data["u_viewer"]
    u_outsider = data["u_outsider"]
    repo_ws2 = data["repo_ws2"]

    csrf = generate_csrf_token()
    api_client.cookies.set(CSRF_COOKIE_NAME, csrf)

    # 1. Create a ticket in ws1 as member
    app.dependency_overrides[get_current_user] = lambda: u_member
    resp_create = await api_client.post(
        "/api/v1/tickets",
        json={"workspace_id": str(ws1.id), "title": "Secure ticket in ws1"},
        headers={"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf},
    )
    assert resp_create.status_code == 201
    ticket_id = resp_create.json()["id"]

    # 2. Cannot link foreign repo belonging to ws2
    resp_bad_repo = await api_client.post(
        "/api/v1/tickets",
        json={"workspace_id": str(ws1.id), "title": "Bad repo", "repository_id": str(repo_ws2.id)},
        headers={"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf},
    )
    assert resp_bad_repo.status_code == 400

    # 3. Cannot assign to foreign user (u_outsider)
    resp_bad_assign = await api_client.post(
        "/api/v1/tickets",
        json={"workspace_id": str(ws1.id), "title": "Bad user", "assignee_id": str(u_outsider.id)},
        headers={"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf},
    )
    assert resp_bad_assign.status_code == 400

    # 4. Outsider from ws2 cannot access ws1 tickets -> 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: u_outsider
    resp_cross = await api_client.get(f"/api/v1/tickets/{ticket_id}?workspace_id={ws1.id}")
    assert resp_cross.status_code == 403

    # 5. Viewer can read ticket in ws1
    app.dependency_overrides[get_current_user] = lambda: u_viewer
    resp_viewer_read = await api_client.get(f"/api/v1/tickets/{ticket_id}?workspace_id={ws1.id}")
    assert resp_viewer_read.status_code == 200

    # 6. Viewer cannot mutate ticket (requires MEMBER role) -> 403 Forbidden
    resp_viewer_mutate = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/status?workspace_id={ws1.id}",
        json={"status": "CLOSED"},
        headers={"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf},
    )
    assert resp_viewer_mutate.status_code == 403

    # 7. Viewer cannot create ticket -> 403 Forbidden
    resp_viewer_create = await api_client.post(
        "/api/v1/tickets",
        json={"workspace_id": str(ws1.id), "title": "Viewer creating ticket"},
        headers={"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf},
    )
    assert resp_viewer_create.status_code == 403

    # 8. Viewer cannot update ticket -> 403 Forbidden
    resp_viewer_patch = await api_client.patch(
        f"/api/v1/tickets/{ticket_id}?workspace_id={ws1.id}",
        json={"title": "Viewer updating title"},
        headers={"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf},
    )
    assert resp_viewer_patch.status_code == 403

    # 9. Viewer cannot assign ticket -> 403 Forbidden
    resp_viewer_assign = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/assign?workspace_id={ws1.id}",
        json={"assignee_id": str(u_member.id)},
        headers={"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf},
    )
    assert resp_viewer_assign.status_code == 403

    # 10. Viewer cannot add comment -> 403 Forbidden
    resp_viewer_comment = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/comments?workspace_id={ws1.id}",
        json={"comment": "Viewer commentary"},
        headers={"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf},
    )
    assert resp_viewer_comment.status_code == 403


@pytest.mark.asyncio
async def test_ticket_lifecycle_state_machine_and_validation(
    api_client: AsyncClient,
    setup_ticket_fixtures: dict[str, Any],
) -> None:
    data = setup_ticket_fixtures
    ws1 = data["ws1"]
    u_member = data["u_member"]
    repo_ws2 = data["repo_ws2"]
    u_outsider = data["u_outsider"]

    app.dependency_overrides[get_current_user] = lambda: u_member
    csrf = generate_csrf_token()
    api_client.cookies.set(CSRF_COOKIE_NAME, csrf)
    headers = {"Origin": "http://localhost:3000", CSRF_HEADER_NAME: csrf}

    # Create initial ticket (OPEN)
    create_resp = await api_client.post(
        "/api/v1/tickets",
        json={"workspace_id": str(ws1.id), "title": "Lifecycle test ticket"},
        headers=headers,
    )
    assert create_resp.status_code == 201
    ticket_id = create_resp.json()["id"]

    # 1. Self-transition is rejected (OPEN -> OPEN)
    resp_same = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/status?workspace_id={ws1.id}",
        json={"status": "OPEN"},
        headers=headers,
    )
    assert resp_same.status_code == 400
    assert "already in 'OPEN' status" in resp_same.json()["detail"]

    # 2. Valid transition: OPEN -> IN_PROGRESS
    resp_in_prog = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/status?workspace_id={ws1.id}",
        json={"status": "IN_PROGRESS"},
        headers=headers,
    )
    assert resp_in_prog.status_code == 200
    assert resp_in_prog.json()["status"] == "IN_PROGRESS"

    # 3. Valid transition: IN_PROGRESS -> UNDER_REVIEW
    resp_review = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/status?workspace_id={ws1.id}",
        json={"status": "UNDER_REVIEW"},
        headers=headers,
    )
    assert resp_review.status_code == 200
    assert resp_review.json()["status"] == "UNDER_REVIEW"

    # 4. Valid transition: UNDER_REVIEW -> RESOLVED
    resp_resolve = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/status?workspace_id={ws1.id}",
        json={"status": "RESOLVED"},
        headers=headers,
    )
    assert resp_resolve.status_code == 200
    assert resp_resolve.json()["status"] == "RESOLVED"
    assert resp_resolve.json()["resolved_at"] is not None

    # 5. Invalid transition: RESOLVED cannot go to UNDER_REVIEW
    resp_bad_trans = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/status?workspace_id={ws1.id}",
        json={"status": "UNDER_REVIEW"},
        headers=headers,
    )
    assert resp_bad_trans.status_code == 400
    assert "Invalid status transition" in resp_bad_trans.json()["detail"]

    # 6. Valid transition: RESOLVED -> CLOSED
    resp_close = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/status?workspace_id={ws1.id}",
        json={"status": "CLOSED"},
        headers=headers,
    )
    assert resp_close.status_code == 200
    assert resp_close.json()["status"] == "CLOSED"

    # 7. Invalid transition: CLOSED cannot jump directly to UNDER_REVIEW or RESOLVED (must be reopened first)
    resp_closed_bad = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/status?workspace_id={ws1.id}",
        json={"status": "RESOLVED"},
        headers=headers,
    )
    assert resp_closed_bad.status_code == 400
    assert "Invalid status transition" in resp_closed_bad.json()["detail"]

    # 8. Reopening: CLOSED -> OPEN
    resp_reopen = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/status?workspace_id={ws1.id}",
        json={"status": "OPEN", "comment": "Issue re-occurred in staging"},
        headers=headers,
    )
    assert resp_reopen.status_code == 200
    assert resp_reopen.json()["status"] == "OPEN"
    assert resp_reopen.json()["resolved_at"] is None

    # 9. Update with foreign repository is rejected
    resp_patch_bad_repo = await api_client.patch(
        f"/api/v1/tickets/{ticket_id}?workspace_id={ws1.id}",
        json={"repository_id": str(repo_ws2.id)},
        headers=headers,
    )
    assert resp_patch_bad_repo.status_code == 400

    # 10. Assign to non-member user is rejected
    resp_assign_outsider = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/assign?workspace_id={ws1.id}",
        json={"assignee_id": str(u_outsider.id)},
        headers=headers,
    )
    assert resp_assign_outsider.status_code == 400

    # 11. Unassign ticket succeeds
    resp_unassign = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/assign?workspace_id={ws1.id}",
        json={"assignee_id": None},
        headers=headers,
    )
    assert resp_unassign.status_code == 200
    assert resp_unassign.json()["assignee_id"] is None

    # 12. Empty comment rejected
    resp_empty_comment = await api_client.post(
        f"/api/v1/tickets/{ticket_id}/comments?workspace_id={ws1.id}",
        json={"comment": "   "},
        headers=headers,
    )
    assert resp_empty_comment.status_code == 400
