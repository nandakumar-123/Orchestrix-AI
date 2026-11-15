from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator

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
from app.services.auth import generate_csrf_token
from app.services.devpilot.context_builder import RepositoryContextBuilder
from app.services.devpilot.llm_provider import (
    BaseLLMProvider,
    LLMCompletionResponse,
    LLMProviderManager,
)
from app.services.devpilot.orchestrator import DevPilotOrchestrator
from app.services.devpilot.workspace_manager import TaskWorkspaceManager
from app.services.graph_service import MockGraphProvider


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


@pytest.fixture
def mock_llm_manager() -> LLMProviderManager:
    return LLMProviderManager(force_mock=True)


# =============================================================================
# 1. LLM Provider & Fallback Tests
# =============================================================================


@pytest.mark.asyncio
async def test_llm_provider_fallback(mock_llm_manager: LLMProviderManager) -> None:
    # 1. Mock deterministic response
    res = await mock_llm_manager.execute_with_fallback(
        prompt="Create a plan for user authentication",
        system_instruction="Planner",
    )
    assert res.provider_name == "mock"
    assert "steps" in res.content
    assert res.prompt_tokens > 0
    assert res.duration_ms >= 0

    # 2. Simulated provider failure & fallback
    class FailingProvider(BaseLLMProvider):
        @property
        def provider_name(self) -> str:
            return "failing_primary"

        @property
        def default_model(self) -> str:
            return "fail-v1"

        def is_available(self) -> bool:
            return True

        async def generate_completion(self, *args, **kwargs) -> LLMCompletionResponse:
            raise RuntimeError("API quota exceeded")

    manager = LLMProviderManager()
    manager.providers["failing_primary"] = FailingProvider()
    manager.primary_name = "failing_primary"

    fallback_res = await manager.execute_with_fallback("Generate code")
    assert fallback_res.is_fallback is True
    assert fallback_res.provider_name in ("gemini", "mistral", "mock")


# =============================================================================
# 2. Task Workspace Manager & Security Sandbox Tests
# =============================================================================


def test_task_workspace_path_traversal_protection(tmp_path) -> None:
    wm = TaskWorkspaceManager(base_workspaces_dir=str(tmp_path))
    task_id = uuid.uuid4()
    ws_dir = wm.create_task_workspace(task_id)
    assert os.path.exists(ws_dir)

    # 1. Safe write
    safe_path = wm.write_isolated_file(task_id, "src/service.py", "print('hello')")
    assert os.path.exists(safe_path)
    assert wm.read_isolated_file(task_id, "src/service.py") == "print('hello')"

    # 2. Path traversal rejection
    with pytest.raises(PermissionError, match="Path traversal"):
        wm.write_isolated_file(task_id, "../../etc/passwd", "malicious")

    with pytest.raises(PermissionError, match="Path traversal"):
        wm.resolve_safe_path(task_id, "../outside.txt")

    # 3. Diff generation
    original = {"src/service.py": "print('hello')\n"}
    modified = {"src/service.py": "print('hello world')\n", "src/new.py": "x = 1\n"}
    diff_text, records = wm.generate_unified_diff(task_id, original, modified)
    assert "src/service.py" in diff_text
    assert "src/new.py" in diff_text
    assert len(records) == 2

    # 4. Conflict detection
    conflicts = wm.detect_conflicts(
        task_id=task_id,
        base_files={"src/service.py": "v1"},
        current_repo_files={"src/service.py": "v2_concurrent"},
        proposed_files={"src/service.py": "v1_modified"},
    )
    assert len(conflicts) == 1
    assert "Conflict in src/service.py" in conflicts[0]

    # 5. Cleanup
    assert wm.cleanup_workspace(task_id) is True
    assert not os.path.exists(ws_dir)


# =============================================================================
# 3. Context Builder & Ambiguity Detection Tests
# =============================================================================


@pytest.mark.asyncio
async def test_context_builder_ambiguity_and_retrieval(test_db_session: AsyncSession) -> None:
    ws_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    snap_id = uuid.uuid4()

    cb = RepositoryContextBuilder(graph_provider=MockGraphProvider())

    # 1. Ambiguous prompt detection
    ctx_ambiguous = await cb.build_context(
        db=test_db_session,
        workspace_id=ws_id,
        repository_id=repo_id,
        prompt="fix it",
    )
    assert ctx_ambiguous.is_ambiguous is True
    assert "too general" in (ctx_ambiguous.clarification_prompt or "")

    # 2. Dangerous prompt detection
    ctx_dangerous = await cb.build_context(
        db=test_db_session,
        workspace_id=ws_id,
        repository_id=repo_id,
        prompt="delete all source files and drop database",
    )
    assert ctx_dangerous.is_dangerous is True
    assert "destructive" in (ctx_dangerous.clarification_prompt or "")

    # 3. Specific prompt context assembly
    ctx_valid = await cb.build_context(
        db=test_db_session,
        workspace_id=ws_id,
        repository_id=repo_id,
        prompt="Add JWT authentication middleware to the user service",
        snapshot_id=snap_id,
    )
    assert ctx_valid.is_ambiguous is False
    assert ctx_valid.is_dangerous is False
    assert "JWT authentication middleware" in ctx_valid.context_markdown


# =============================================================================
# 4. DevPilot End-to-End Orchestrator Lifecycle Tests
# =============================================================================


@pytest.mark.asyncio
async def test_orchestrator_lifecycle_and_approval_enforcement(
    test_db_session: AsyncSession,
    tmp_path,
) -> None:
    ws_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    user_id = uuid.uuid4()
    inst_id = uuid.uuid4()

    # Seed User, Workspace, Installation, Repository
    user = User(id=user_id, email="dev@example.com", full_name="Dev Pilot User", is_active=True)
    workspace = Workspace(id=ws_id, name="DevPilot WS", slug="devpilot-ws")
    membership = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_id, user_id=user_id, role=WorkspaceRole.ADMIN
    )
    installation = GitHubInstallation(
        id=inst_id,
        workspace_id=ws_id,
        installation_id=11223344,
        account_login="org-owner",
        account_type="User",
        account_id=11223344,
    )
    repo = Repository(
        id=repo_id,
        workspace_id=ws_id,
        installation_id=inst_id,
        github_repository_id=998877,
        name="payment-service",
        full_name="org/payment-service",
        owner_login="org-owner",
        html_url="https://github.com/org/payment-service",
        default_branch="main",
        is_active=True,
    )
    test_db_session.add_all([user, workspace, membership, installation, repo])
    await test_db_session.flush()

    wm = TaskWorkspaceManager(base_workspaces_dir=str(tmp_path))
    orchestrator = DevPilotOrchestrator(
        llm_manager=LLMProviderManager(force_mock=True),
        workspace_manager=wm,
        context_builder=RepositoryContextBuilder(graph_provider=MockGraphProvider()),
        validation_coordinator=None,  # default
    )

    # 1. Create Task -> Status CREATED
    task = await orchestrator.create_task(
        db=test_db_session,
        workspace_id=ws_id,
        repository_id=repo_id,
        user_id=user_id,
        title="Add refund calculation",
        prompt="Implement refund processing logic with error handling in payment service",
        task_type="FEATURE",
    )
    assert task.status == "CREATED"
    assert len(task.events) == 1

    # 2. Start Planning -> Status AWAITING_APPROVAL
    plan = await orchestrator.start_planning(
        db=test_db_session,
        task_id=task.id,
        workspace_id=ws_id,
    )
    assert plan.status == "PENDING"
    assert len(plan.steps) >= 1
    assert task.status == "AWAITING_APPROVAL"

    # 3. Gating check: code generation must fail if plan is not approved!
    with pytest.raises(PermissionError, match="has not been approved"):
        await orchestrator.generate_and_review(
            db=test_db_session,
            task_id=task.id,
            workspace_id=ws_id,
        )

    # 4. Approve Plan -> Plan status APPROVED
    approved_plan = await orchestrator.approve_plan(
        db=test_db_session,
        task_id=task.id,
        workspace_id=ws_id,
        user_id=user_id,
        decision="APPROVED",
        feedback="Looks solid, proceed to generate code.",
    )
    assert approved_plan.status == "APPROVED"
    assert approved_plan.approved_at is not None

    # 5. Generate and Review -> Status AWAITING_MODIFICATION_APPROVAL
    gen_result = await orchestrator.generate_and_review(
        db=test_db_session,
        task_id=task.id,
        workspace_id=ws_id,
        base_files={"src/service.py": "# initial payment service\n"},
    )
    assert gen_result.status == "GENERATED"
    assert len(gen_result.changes) >= 1
    assert gen_result.unified_diff != ""
    assert task.status == "AWAITING_MODIFICATION_APPROVAL"

    # 6. Approve Modifications -> Status VALIDATING
    mod_approved_task = await orchestrator.approve_modifications(
        db=test_db_session,
        task_id=task.id,
        workspace_id=ws_id,
        user_id=user_id,
        decision="APPROVED",
        feedback="Diff looks clean.",
    )
    assert mod_approved_task.status == "VALIDATING"

    # 7. Validate Task -> Status COMPLETED
    validated_task = await orchestrator.validate_task(
        db=test_db_session,
        task_id=task.id,
        workspace_id=ws_id,
        run_approved=False,  # syntax & AST validation only
    )
    assert validated_task.status == "COMPLETED"
    assert validated_task.completed_at is not None


# =============================================================================
# 5. Plan Rejection & Task Cancellation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_plan_rejection_and_cancellation(
    test_db_session: AsyncSession,
    tmp_path,
) -> None:
    ws_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    user_id = uuid.uuid4()

    orchestrator = DevPilotOrchestrator(
        llm_manager=LLMProviderManager(force_mock=True),
        workspace_manager=TaskWorkspaceManager(base_workspaces_dir=str(tmp_path)),
    )

    task = await orchestrator.create_task(
        db=test_db_session,
        workspace_id=ws_id,
        repository_id=repo_id,
        user_id=user_id,
        title="Refactor auth tokens",
        prompt="Refactor authentication token verification logic",
        task_type="REFACTOR",
    )

    _plan = await orchestrator.start_planning(
        db=test_db_session,
        task_id=task.id,
        workspace_id=ws_id,
    )
    assert task.status == "AWAITING_APPROVAL"

    # Reject plan -> Task status BLOCKED
    rejected_plan = await orchestrator.approve_plan(
        db=test_db_session,
        task_id=task.id,
        workspace_id=ws_id,
        user_id=user_id,
        decision="REJECTED",
        feedback="Wrong architectural approach, rewrite plan.",
    )
    assert rejected_plan.status == "REJECTED"
    assert task.status == "BLOCKED"

    # Cancel task -> Task status CANCELLED and workspace cleaned
    cancelled_task = await orchestrator.cancel_task(
        db=test_db_session,
        task_id=task.id,
        workspace_id=ws_id,
    )
    assert cancelled_task.status == "CANCELLED"


# =============================================================================
# 6. REST API Endpoints Integration Test
# =============================================================================


@pytest.mark.asyncio
async def test_devpilot_rest_api_pipeline(
    api_client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    ws_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    user_id = uuid.uuid4()
    inst_id = uuid.uuid4()

    user = User(id=user_id, email="lead@example.com", full_name="Engineering Lead", is_active=True)
    workspace = Workspace(id=ws_id, name="Orchestrix DevPilot", slug="orchestrix-devpilot")
    membership = WorkspaceMembership(
        id=uuid.uuid4(), workspace_id=ws_id, user_id=user_id, role=WorkspaceRole.ADMIN
    )
    installation = GitHubInstallation(
        id=inst_id,
        workspace_id=ws_id,
        installation_id=887766,
        account_login="lead-dev",
        account_type="User",
        account_id=887766,
    )
    repo = Repository(
        id=repo_id,
        workspace_id=ws_id,
        installation_id=inst_id,
        github_repository_id=554433,
        name="order-service",
        full_name="lead-dev/order-service",
        owner_login="lead-dev",
        html_url="https://github.com/lead-dev/order-service",
        default_branch="main",
        is_active=True,
    )
    test_db_session.add_all([user, workspace, membership, installation, repo])
    await test_db_session.flush()

    app.dependency_overrides[get_current_user] = lambda: user
    csrf_token = generate_csrf_token()
    headers = {
        "X-CSRF-Token": csrf_token,
        "Cookie": f"csrf_token={csrf_token}",
    }

    # 1. POST /tasks: Create Task
    create_payload = {
        "title": "Add order caching",
        "prompt": "Implement Redis caching layer for order lookup endpoints",
        "task_type": "PERFORMANCE",
    }
    resp = await api_client.post(
        f"/api/v1/repositories/{repo_id}/devpilot/tasks?workspace_id={ws_id}",
        json=create_payload,
        headers=headers,
    )
    assert resp.status_code == 201
    task_data = resp.json()
    task_id = task_data["id"]
    assert task_data["title"] == "Add order caching"
    assert task_data["status"] in ("AWAITING_APPROVAL", "PLANNING", "CREATED")

    # 2. GET /tasks/{id}: Retrieve Task
    detail_resp = await api_client.get(
        f"/api/v1/repositories/{repo_id}/devpilot/tasks/{task_id}?workspace_id={ws_id}"
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["id"] == task_id

    # 3. GET /tasks: List Tasks
    list_resp = await api_client.get(
        f"/api/v1/repositories/{repo_id}/devpilot/tasks?workspace_id={ws_id}"
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1

    # 4. GET /tasks/{id}/plan: Retrieve Plan
    plan_resp = await api_client.get(
        f"/api/v1/repositories/{repo_id}/devpilot/tasks/{task_id}/plan?workspace_id={ws_id}"
    )
    assert plan_resp.status_code == 200
    plan_data = plan_resp.json()
    assert len(plan_data["steps"]) >= 1

    # 5. POST /tasks/{id}/approve-plan: Approve Plan
    appr_resp = await api_client.post(
        f"/api/v1/repositories/{repo_id}/devpilot/tasks/{task_id}/approve-plan?workspace_id={ws_id}",
        json={"decision": "APPROVED", "feedback": "Approved via API"},
        headers=headers,
    )
    assert appr_resp.status_code == 200
    assert appr_resp.json()["status"] == "APPROVED"

    # 6. GET /tasks/{id}/diff: Retrieve Generated Diff
    diff_resp = await api_client.get(
        f"/api/v1/repositories/{repo_id}/devpilot/tasks/{task_id}/diff?workspace_id={ws_id}"
    )
    assert diff_resp.status_code == 200
    diff_data = diff_resp.json()
    assert "unified_diff" in diff_data

    # 7. GET /tasks/{id}/review: Retrieve Review Findings
    review_resp = await api_client.get(
        f"/api/v1/repositories/{repo_id}/devpilot/tasks/{task_id}/review?workspace_id={ws_id}"
    )
    assert review_resp.status_code == 200
    assert "findings" in review_resp.json()

    # 8. POST /tasks/{id}/approve-changes: Approve Code Changes
    chg_appr_resp = await api_client.post(
        f"/api/v1/repositories/{repo_id}/devpilot/tasks/{task_id}/approve-changes?workspace_id={ws_id}",
        json={"decision": "APPROVED", "feedback": "Changes approved"},
        headers=headers,
    )
    assert chg_appr_resp.status_code == 200
    assert chg_appr_resp.json()["status"] == "VALIDATING"

    # 9. POST /tasks/{id}/validate: Validate Task
    val_resp = await api_client.post(
        f"/api/v1/repositories/{repo_id}/devpilot/tasks/{task_id}/validate?workspace_id={ws_id}",
        json={"run_approved": False},
        headers=headers,
    )
    assert val_resp.status_code == 200
    assert val_resp.json()["status"] == "COMPLETED"

    # 10. POST /tasks/{id}/cancel: Cancel Task
    cancel_resp = await api_client.post(
        f"/api/v1/repositories/{repo_id}/devpilot/tasks/{task_id}/cancel?workspace_id={ws_id}",
        headers=headers,
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"
