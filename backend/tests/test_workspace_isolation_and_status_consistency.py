import asyncio
import os
import tempfile
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.secureflow import FindingStatus, SecureFlowFinding, SecureFlowScan
from app.services.devpilot.workspace_manager import TaskWorkspaceManager
from app.services.impactmind.test_runner import ControlledTestRunner
from app.services.secureflow.finding_manager import FindingManager

# =============================================================================
# 1. TestPilot & DevPilot Workspace Isolation Tests
# =============================================================================


def test_workspace_directory_structure_and_path_validation():
    """Verify workspace_root / repository_id / task_id directory structure."""
    with tempfile.TemporaryDirectory() as temp_root:
        mgr = TaskWorkspaceManager(base_workspaces_dir=temp_root)
        repo_id = uuid.uuid4()
        task_id = uuid.uuid4()

        ws_dir = mgr.get_task_workspace_dir(task_id, repository_id=repo_id)
        expected_dir = os.path.abspath(os.path.join(temp_root, str(repo_id), str(task_id)))
        assert ws_dir == expected_dir

        # Created directory matches expected structure
        created_path = mgr.create_task_workspace(task_id, repository_id=repo_id)
        assert created_path == expected_dir
        assert os.path.isdir(created_path)


def test_two_tasks_receive_different_workspace_paths():
    """1. Two tasks receive different workspace paths under the same repository."""
    with tempfile.TemporaryDirectory() as temp_root:
        mgr = TaskWorkspaceManager(base_workspaces_dir=temp_root)
        repo_id = uuid.uuid4()
        task_a = uuid.uuid4()
        task_b = uuid.uuid4()

        path_a = mgr.create_task_workspace(task_a, repository_id=repo_id)
        path_b = mgr.create_task_workspace(task_b, repository_id=repo_id)

        assert path_a != path_b
        assert os.path.isdir(path_a)
        assert os.path.isdir(path_b)
        assert os.path.dirname(path_a) == os.path.dirname(path_b)


def test_concurrent_tasks_cannot_access_each_others_workspace():
    """2. Concurrent tasks cannot access each other's workspace files."""
    with tempfile.TemporaryDirectory() as temp_root:
        mgr = TaskWorkspaceManager(base_workspaces_dir=temp_root)
        repo_id = uuid.uuid4()
        task_a = uuid.uuid4()
        task_b = uuid.uuid4()

        mgr.create_task_workspace(task_a, repository_id=repo_id)
        mgr.create_task_workspace(task_b, repository_id=repo_id)

        # Write private file into Task A
        mgr.write_isolated_file(task_a, "secrets.txt", "task_a_secret", repository_id=repo_id)

        # Task B reading relative path "secrets.txt" inside Task B's workspace returns None
        assert mgr.read_isolated_file(task_b, "secrets.txt", repository_id=repo_id) is None

        # Task B cannot traverse to Task A using ../<task_a>/secrets.txt
        relative_escape = f"../{task_a}/secrets.txt"
        with pytest.raises(PermissionError, match="Path traversal"):
            mgr.resolve_safe_path(task_b, relative_escape, repository_id=repo_id)


def test_cleanup_of_task_a_does_not_delete_task_b_files():
    """4. Cleanup of Task A does not delete Task B's files."""
    with tempfile.TemporaryDirectory() as temp_root:
        mgr = TaskWorkspaceManager(base_workspaces_dir=temp_root)
        repo_id = uuid.uuid4()
        task_a = uuid.uuid4()
        task_b = uuid.uuid4()

        mgr.create_task_workspace(task_a, repository_id=repo_id)
        mgr.create_task_workspace(task_b, repository_id=repo_id)

        mgr.write_isolated_file(task_a, "data_a.txt", "content_a", repository_id=repo_id)
        mgr.write_isolated_file(task_b, "data_b.txt", "content_b", repository_id=repo_id)

        # Cleanup Task A
        cleaned = mgr.cleanup_workspace(task_a, repository_id=repo_id)
        assert cleaned is True

        # Verify Task A directory is gone
        assert not os.path.exists(mgr.get_task_workspace_dir(task_a, repository_id=repo_id))

        # Verify Task B directory and files remain completely intact
        assert os.path.exists(mgr.get_task_workspace_dir(task_b, repository_id=repo_id))
        assert mgr.read_isolated_file(task_b, "data_b.txt", repository_id=repo_id) == "content_b"


def test_path_traversal_attempts_are_rejected():
    """5. Path traversal and escape attempts are strictly rejected."""
    with tempfile.TemporaryDirectory() as temp_root:
        mgr = TaskWorkspaceManager(base_workspaces_dir=temp_root)
        repo_id = uuid.uuid4()
        task_id = uuid.uuid4()

        mgr.create_task_workspace(task_id, repository_id=repo_id)

        # Traversal in file paths
        with pytest.raises(PermissionError, match="Path traversal"):
            mgr.resolve_safe_path(task_id, "../../etc/passwd", repository_id=repo_id)

        with pytest.raises(PermissionError, match="Path traversal"):
            mgr.resolve_safe_path(task_id, "..\\..\\windows\\system32", repository_id=repo_id)

        with pytest.raises(PermissionError, match="Null byte"):
            mgr.resolve_safe_path(task_id, "safe_file.txt\x00malicious", repository_id=repo_id)

        # Traversal in repository_id or task_id
        with pytest.raises(PermissionError, match="Path traversal or illegal separator"):
            mgr.get_task_workspace_dir("task_123", repository_id="../escaped_repo")

        with pytest.raises(PermissionError, match="Path traversal or illegal separator"):
            mgr.get_task_workspace_dir("../escaped_task", repository_id=repo_id)

        with pytest.raises(ValueError, match="Invalid characters"):
            mgr.get_task_workspace_dir("task_with_spaces and $special", repository_id=repo_id)


@pytest.mark.asyncio
async def test_cancelling_task_a_does_not_affect_task_b():
    """3. Cancelling Task A does not affect Task B."""
    task_a_id = str(uuid.uuid4())
    task_b_id = str(uuid.uuid4())

    # Create two async sleep tasks simulating executions
    async def simulated_execution(exec_id: str, duration: float):
        try:
            await asyncio.sleep(duration)
            return "COMPLETED"
        except asyncio.CancelledError:
            return "CANCELLED"

    loop = asyncio.get_running_loop()
    task_a = loop.create_task(simulated_execution(task_a_id, 5.0))
    task_b = loop.create_task(simulated_execution(task_b_id, 0.1))

    # Register in active execution tasks
    from app.services.impactmind.test_runner import _ACTIVE_TEST_TASKS

    _ACTIVE_TEST_TASKS[task_a_id] = task_a
    _ACTIVE_TEST_TASKS[task_b_id] = task_b

    try:
        # Cancel Task A only
        cancelled = ControlledTestRunner.cancel_execution(task_a_id)
        assert cancelled is True

        with pytest.raises(asyncio.CancelledError):
            await task_a

        res_b = await task_b
        assert res_b == "COMPLETED"
    finally:
        _ACTIVE_TEST_TASKS.pop(task_a_id, None)
        _ACTIVE_TEST_TASKS.pop(task_b_id, None)


def test_original_repository_remains_unchanged_after_execution():
    """6. The host repository files remain unchanged by isolated execution."""
    with tempfile.TemporaryDirectory() as host_repo_dir:
        # Create dummy repository files
        src_file = os.path.join(host_repo_dir, "main.py")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write("def add(a, b): return a + b\n")

        with open(src_file, "rb") as f:
            original_bytes = f.read()

        # Run task execution in isolated workspace
        with tempfile.TemporaryDirectory() as ws_root:
            mgr = TaskWorkspaceManager(base_workspaces_dir=ws_root)
            repo_id = uuid.uuid4()
            task_id = uuid.uuid4()

            mgr.create_task_workspace(task_id, repository_id=repo_id)

            # Write code and tests inside isolated workspace
            mgr.write_isolated_file(
                task_id, "main.py", "def add(a, b): return a + b + 999\n", repository_id=repo_id
            )
            mgr.write_isolated_file(
                task_id,
                "tests/test_main.py",
                "def test_add(): assert True\n",
                repository_id=repo_id,
            )

            # Verify isolated workspace has modified file
            assert (
                mgr.read_isolated_file(task_id, "main.py", repository_id=repo_id)
                != original_bytes.decode()
            )

            # Clean up task workspace
            mgr.cleanup_workspace(task_id, repository_id=repo_id)

        # Host repository file must be 100% identical and untouched
        with open(src_file, "rb") as f:
            current_bytes = f.read()

        assert current_bytes == original_bytes


# =============================================================================
# 2. SecureFlow Canonical Status Consistency & Transition Tests
# =============================================================================


def test_canonical_status_vocabulary():
    """Verify all 5 canonical statuses exist in model and schemas without NEW or IGNORED."""
    canonical = {"OPEN", "CONFIRMED", "FALSE_POSITIVE", "ACCEPTED_RISK", "RESOLVED"}
    model_statuses = {s.value for s in FindingStatus}
    assert model_statuses == canonical
    assert "NEW" not in model_statuses
    assert "IGNORED" not in model_statuses


@pytest.mark.asyncio
async def test_valid_and_invalid_status_transitions():
    """Verify permitted status transitions succeed and invalid transitions are rejected."""
    mgr = FindingManager()

    # Create mock session and finding
    finding_id = uuid.uuid4()
    scan_id = uuid.uuid4()

    finding = SecureFlowFinding(
        id=finding_id,
        workspace_id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        scan_id=scan_id,
        scanner="secret-scanner",
        category="secrets",
        severity="HIGH",
        rule_id="AWS-KEY",
        title="AWS Access Key Exposed",
        description="Found AWS credential",
        status=FindingStatus.OPEN,
        fingerprint="dummy_fp_" + str(uuid.uuid4())[:8],
    )

    class MockSession:
        def __init__(self, finding_obj):
            self.finding = finding_obj
            self.events = []

        async def get(self, entity_cls, ident):
            if ident == self.finding.id:
                return self.finding
            return None

        def add(self, obj):
            self.events.append(obj)

        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    session = MockSession(finding)

    # 1. Valid transition: OPEN -> CONFIRMED
    updated = await mgr.update_finding_status(
        db=session,
        finding_id=finding_id,
        new_status="CONFIRMED",
        note="Verified genuine API key",
    )
    assert updated is not None
    assert updated.status == "CONFIRMED"
    assert len(session.events) == 1
    assert session.events[0].details["previous_status"] == "OPEN"
    assert session.events[0].details["new_status"] == "CONFIRMED"

    # 2. Valid transition: CONFIRMED -> RESOLVED
    updated = await mgr.update_finding_status(
        db=session,
        finding_id=finding_id,
        new_status=FindingStatus.RESOLVED,
        note="Key rotated and invalidated",
    )
    assert updated.status == "RESOLVED"

    # 3. Invalid transition: RESOLVED -> FALSE_POSITIVE directly (must go through OPEN or CONFIRMED)
    with pytest.raises(ValueError, match="Invalid finding status transition"):
        await mgr.update_finding_status(
            db=session,
            finding_id=finding_id,
            new_status="FALSE_POSITIVE",
        )

    # 4. Unknown/unrecognized status (like NEW or IGNORED) rejected immediately
    with pytest.raises(ValueError, match="Invalid finding status 'NEW'"):
        await mgr.update_finding_status(
            db=session,
            finding_id=finding_id,
            new_status="NEW",
        )

    with pytest.raises(ValueError, match="Invalid finding status 'IGNORED'"):
        await mgr.update_finding_status(
            db=session,
            finding_id=finding_id,
            new_status="IGNORED",
        )


@pytest.mark.asyncio
async def test_api_status_transition_validation():
    """Verify API endpoint enforces status transition rules and canonical vocabulary."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api.deps import get_current_user
    from app.db.base import Base, WorkspaceRole
    from app.db.models.github_installation import GitHubInstallation
    from app.db.models.membership import WorkspaceMembership
    from app.db.models.repository import Repository
    from app.db.models.user import User
    from app.db.models.workspace import Workspace
    from app.db.session import get_db_session
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as db_session:
        user_id = uuid.uuid4()
        user = User(id=user_id, email="auditor@orchestrix.ai", full_name="Auditor", is_active=True)
        db_session.add(user)

        workspace_id = uuid.uuid4()
        workspace = Workspace(id=workspace_id, name="Security Workspace", slug="security-workspace")
        db_session.add(workspace)

        membership = WorkspaceMembership(
            workspace_id=workspace_id, user_id=user_id, role=WorkspaceRole.MEMBER
        )
        db_session.add(membership)

        gh_inst = GitHubInstallation(
            workspace_id=workspace_id,
            account_id="12345",
            account_login="org",
            account_type="Organization",
            installation_id=98765,
        )
        db_session.add(gh_inst)
        await db_session.flush()

        repo_id = uuid.uuid4()
        repo = Repository(
            id=repo_id,
            workspace_id=workspace_id,
            installation_id=gh_inst.id,
            github_repository_id=99999,
            name="security-repo",
            full_name="org/security-repo",
            owner_login="org",
            default_branch="main",
            html_url="https://github.com/org/security-repo",
        )
        db_session.add(repo)

        scan_id = uuid.uuid4()
        scan = SecureFlowScan(
            id=scan_id,
            workspace_id=workspace_id,
            repository_id=repo_id,
            scan_type="FULL",
            status="COMPLETED",
            total_findings=1,
            critical_count=0,
            high_count=1,
            medium_count=0,
            low_count=0,
            scanners_used=["secret-scanner"],
        )
        db_session.add(scan)

        finding_id = uuid.uuid4()
        finding = SecureFlowFinding(
            id=finding_id,
            workspace_id=workspace_id,
            repository_id=repo_id,
            scan_id=scan_id,
            scanner="secret-scanner",
            category="secrets",
            severity="HIGH",
            rule_id="AWS-SECRET",
            title="Exposed Secret",
            description="Exposed AWS secret",
            status=FindingStatus.OPEN,
            fingerprint="fp_api_test_123",
        )
        db_session.add(finding)
        await db_session.commit()

        async def override_get_current_user():
            return user

        async def override_get_db_session():
            async with session_maker() as s:
                yield s

        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_db_session] = override_get_db_session

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # 1. Valid transition: OPEN -> CONFIRMED (200 OK)
                res1 = await client.patch(
                    f"/api/v1/repositories/{repo_id}/secureflow/findings/{finding_id}/status?workspace_id={workspace_id}",
                    json={"status": "CONFIRMED", "note": "Verified by security lead"},
                )
                assert res1.status_code == 200, res1.text
                assert res1.json()["status"] == "CONFIRMED"

                # 2. Valid transition: CONFIRMED -> RESOLVED (200 OK)
                res2 = await client.patch(
                    f"/api/v1/repositories/{repo_id}/secureflow/findings/{finding_id}/status?workspace_id={workspace_id}",
                    json={"status": "RESOLVED", "note": "Secret rotated"},
                )
                assert res2.status_code == 200, res2.text
                assert res2.json()["status"] == "RESOLVED"

                # 3. Invalid transition: RESOLVED -> FALSE_POSITIVE directly (400 Bad Request)
                res3 = await client.patch(
                    f"/api/v1/repositories/{repo_id}/secureflow/findings/{finding_id}/status?workspace_id={workspace_id}",
                    json={"status": "FALSE_POSITIVE", "note": "Invalid direct jump"},
                )
                assert res3.status_code == 400
                assert "Invalid finding status transition" in res3.json()["detail"]

                # 4. Unknown/unrecognized status e.g. "NEW" (422 Unprocessable Entity by Pydantic)
                res4 = await client.patch(
                    f"/api/v1/repositories/{repo_id}/secureflow/findings/{finding_id}/status?workspace_id={workspace_id}",
                    json={"status": "NEW"},
                )
                assert res4.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db_session, None)
            await engine.dispose()
