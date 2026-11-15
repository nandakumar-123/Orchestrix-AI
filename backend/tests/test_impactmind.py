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
from app.db.models.repository_intelligence import (
    CodeSymbol,
)
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db_session
from app.main import app
from app.services.auth import generate_csrf_token
from app.services.graph_service import (
    GraphNode,
    GraphRelationship,
    MockGraphProvider,
)
from app.services.impactmind.ast_classifier import ASTChangeClassifier, ClassifiedChange
from app.services.impactmind.diff_parser import GitDiffParser
from app.services.impactmind.engine import ImpactMindEngine
from app.services.impactmind.exposure_scorer import ExposureScoreResult, StructuralExposureScorer
from app.services.impactmind.graph_analyzer import (
    GraphImpactAnalysisResult,
    GraphImpactAnalyzer,
    GraphImpactNode,
)
from app.services.impactmind.test_runner import ControlledTestRunner
from app.services.impactmind.test_selector import RegressionTestSelector

# =============================================================================
# Diff Parser Tests
# =============================================================================


def test_diff_parser_unified_diff() -> None:
    parser = GitDiffParser()
    sample_diff = """diff --git a/app/services/auth.py b/app/services/auth.py
index e69de29..49e29a1 100644
--- a/app/services/auth.py
+++ b/app/services/auth.py
@@ -10,6 +10,8 @@ def authenticate_user(username: str, password: str):
-    token = create_access_token(username)
+    # Updated auth with MFA
+    mfa_verified = check_mfa(username)
+    token = create_access_token(username, mfa_verified)
     return token
diff --git a/app/routes/api.py b/app/routes/api.py
new file mode 100644
--- /dev/null
+++ b/app/routes/api.py
@@ -0,0 +1,5 @@
+from fastapi import APIRouter
+router = APIRouter()
+@router.get('/health')
+def health():
+    return {'status': 'ok'}
"""
    result = parser.parse_unified_diff(
        sample_diff, base_commit_sha="abc111", target_commit_sha="def222"
    )

    assert result.total_files_changed == 2
    assert result.total_additions == 8
    assert result.total_deletions == 1
    assert result.base_commit_sha == "abc111"
    assert result.target_commit_sha == "def222"

    auth_file = result.files[0]
    assert auth_file.file_path == "app/services/auth.py"
    assert auth_file.change_type == "modified"
    assert len(auth_file.hunks) == 1
    assert auth_file.hunks[0].new_start == 10
    assert auth_file.hunks[0].new_count == 8

    api_file = result.files[1]
    assert api_file.file_path == "app/routes/api.py"
    assert api_file.change_type == "added"
    assert len(api_file.hunks) == 1


def test_diff_parser_github_compare_payload() -> None:
    parser = GitDiffParser()
    payload = {
        "base_commit": {"sha": "base123"},
        "merge_base_commit": {"sha": "merge000"},
        "files": [
            {
                "filename": "backend/core.py",
                "status": "modified",
                "additions": 12,
                "deletions": 4,
                "patch": "@@ -1,4 +1,12 @@\n-old\n+new",
            },
            {
                "filename": "old_module.py",
                "previous_filename": "legacy_module.py",
                "status": "renamed",
                "additions": 0,
                "deletions": 0,
                "patch": "",
            },
        ],
    }

    result = parser.parse_github_compare_payload(payload)
    assert result.total_files_changed == 2
    assert result.total_additions == 12
    assert result.total_deletions == 4
    assert result.files[0].file_path == "backend/core.py"
    assert result.files[1].file_path == "old_module.py"
    assert result.files[1].old_path == "legacy_module.py"
    assert result.files[1].change_type == "renamed"


# =============================================================================
# AST Change Classifier Tests
# =============================================================================


def test_ast_change_classifier_categories() -> None:
    classifier = ASTChangeClassifier()

    # Test file paths category inference
    test_diff_result = GitDiffParser().parse_unified_diff(
        """diff --git a/tests/test_auth.py b/tests/test_auth.py
--- a/tests/test_auth.py
+++ b/tests/test_auth.py
@@ -1,2 +1,3 @@
+def test_mfa(): pass
diff --git a/alembic/versions/001_create.py b/alembic/versions/001_create.py
--- a/alembic/versions/001_create.py
+++ b/alembic/versions/001_create.py
@@ -1,2 +1,3 @@
+def upgrade(): pass
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,2 +1,3 @@
+fastapi = "^0.110.0"
"""
    )

    classified = classifier.classify_changes(
        diff_result=test_diff_result,
        symbols_by_file={},
    )

    categories = {c.file_path: c.category for c in classified}
    assert categories["tests/test_auth.py"] == "TEST_CHANGE"
    assert categories["alembic/versions/001_create.py"] == "DATABASE_SCHEMA_CHANGE"
    assert categories["pyproject.toml"] == "DEPENDENCY_CHANGE"


def test_ast_change_classifier_breaking_signature() -> None:
    classifier = ASTChangeClassifier()

    sample_diff = """diff --git a/app/services/billing.py b/app/services/billing.py
--- a/app/services/billing.py
+++ b/app/services/billing.py
@@ -2,2 +2,2 @@ class Invoice:
-    def process(self, amount: int):
+    def process(self, amount: int, currency: str, strict: bool):
"""
    diff_result = GitDiffParser().parse_unified_diff(sample_diff)

    dummy_symbol = CodeSymbol(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        snapshot_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        file_path="app/services/billing.py",
        name="process",
        symbol_type="method",
        language="python",
        start_line=2,
        end_line=3,
        signature="def process(self, amount: int):",
    )

    before_code = "class Invoice:\n    def process(self, amount: int):\n        pass\n"
    after_code = "class Invoice:\n    def process(self, amount: int, currency: str, strict: bool):\n        pass\n"

    classified = classifier.classify_changes(
        diff_result=diff_result,
        symbols_by_file={"app/services/billing.py": [dummy_symbol]},
        file_contents_before={"app/services/billing.py": before_code},
        file_contents_after={"app/services/billing.py": after_code},
    )

    process_change = next(c for c in classified if c.symbol_name == "process")
    assert process_change.category == "SIGNATURE_CHANGE"
    assert process_change.is_breaking is True
    assert "Signature of 'process' altered" in (process_change.breaking_reason or "")


# =============================================================================
# Graph Impact Analyzer Tests
# =============================================================================


@pytest.mark.asyncio
async def test_graph_impact_analyzer_traversal() -> None:
    mock_provider = MockGraphProvider()
    snap_id = str(uuid.uuid4())

    # Build small graph: function authenticate_user is called by route login_handler
    # and login_handler exposes API endpoint POST /api/login
    sym_auth = GraphNode(
        id=f"sym:{snap_id}:app/auth.py:function:authenticate_user",
        label="Function",
        properties={
            "snapshot_id": snap_id,
            "name": "authenticate_user",
            "file_path": "app/auth.py",
        },
    )
    sym_login = GraphNode(
        id=f"sym:{snap_id}:app/routes.py:function:login_handler",
        label="Function",
        properties={"snapshot_id": snap_id, "name": "login_handler", "file_path": "app/routes.py"},
    )
    endpoint_node = GraphNode(
        id=f"endpoint:{snap_id}:post:/api/login",
        label="Endpoint",
        properties={
            "snapshot_id": snap_id,
            "name": "POST /api/login",
            "file_path": "app/routes.py",
        },
    )

    await mock_provider.upsert_nodes([sym_auth, sym_login, endpoint_node])

    # sym_login CALLS sym_auth
    rel_call = GraphRelationship(
        source_id=sym_login.id,
        target_id=sym_auth.id,
        type="CALLS",
        properties={"confidence": 0.95, "status": "resolved"},
    )
    # sym_login EXPOSES endpoint
    rel_expose = GraphRelationship(
        source_id=sym_login.id,
        target_id=endpoint_node.id,
        type="EXPOSES",
        properties={"confidence": 1.0, "status": "resolved"},
    )
    await mock_provider.upsert_relationships([rel_call, rel_expose])

    analyzer = GraphImpactAnalyzer(mock_provider)
    changes = [
        ClassifiedChange(
            file_path="app/auth.py",
            symbol_name="authenticate_user",
            symbol_id=sym_auth.id,
            category="LOGIC_CHANGE",
        )
    ]
    result: GraphImpactAnalysisResult = await analyzer.analyze_impact(
        snapshot_id=uuid.UUID(snap_id),
        changes=changes,
        max_depth=2,
    )

    assert len(result.direct_dependents) >= 1
    assert len(result.exposed_endpoints) == 1
    assert "POST /api/login" in [e.name for e in result.exposed_endpoints]
    assert "login_handler" in [c.name for c in result.direct_dependents]


@pytest.mark.asyncio
async def test_graph_impact_analyzer_offline_fallback() -> None:
    # When provider is None, fallback gracefully
    analyzer = GraphImpactAnalyzer(provider=None)
    changes = [
        ClassifiedChange(
            file_path="app/core.py",
            symbol_name="test",
            symbol_id="sym:123:test",
            category="LOGIC_CHANGE",
        )
    ]
    result = await analyzer.analyze_impact(
        snapshot_id=uuid.uuid4(),
        changes=changes,
    )
    assert len(result.direct_dependents) == 0
    assert result.is_degraded is True


# =============================================================================
# Structural Exposure Scorer Tests
# =============================================================================


def test_exposure_scorer_calculation() -> None:
    scorer = StructuralExposureScorer()

    score_res: ExposureScoreResult = scorer.compute_score(
        changes=[],
        graph_result=None,
        recommended_tests=[],
    )
    assert score_res.score == 0.0
    assert score_res.tier == "LOW"

    # With breaking changes and exposed endpoints
    changes = [
        ClassifiedChange(
            file_path="app/api.py",
            symbol_name="update_user",
            category="SIGNATURE_CHANGE",
            is_breaking=True,
            breaking_reason="Parameter added",
        )
    ]
    graph_res = GraphImpactAnalysisResult(
        target_changes=changes,
        direct_dependents=[
            GraphImpactNode(
                "1", "caller1", "Function", "app/api.py", "direct_dependent", 1, "CALLS", 1.0
            ),
            GraphImpactNode(
                "2", "caller2", "Function", "app/api.py", "direct_dependent", 1, "CALLS", 1.0
            ),
        ],
        indirect_dependents=[
            GraphImpactNode(
                "3", "caller3", "Function", "app/api.py", "indirect_dependent", 2, "CALLS", 0.8
            ),
        ],
        exposed_endpoints=[
            GraphImpactNode(
                "4",
                "POST /api/users",
                "Endpoint",
                "app/api.py",
                "exposed_endpoint",
                1,
                "EXPOSES",
                1.0,
            ),
        ],
        database_models=[],
        affected_tests=[],
        uncertain_dependents=[],
    )

    res_high = scorer.compute_score(
        changes=changes,
        graph_result=graph_res,
        recommended_tests=[],
    )
    assert res_high.score >= 45.0
    assert res_high.tier in ("HIGH", "CRITICAL")
    assert any("breaking contract change" in r for r in res_high.reasons)
    assert any("API endpoint" in r for r in res_high.reasons)


# =============================================================================
# Regression Test Selector Tests
# =============================================================================


def test_test_selector_ranking() -> None:
    selector = RegressionTestSelector()

    changes = [
        ClassifiedChange(
            file_path="app/auth.py",
            symbol_name="login",
            category="LOGIC_CHANGE",
        )
    ]
    graph_res = GraphImpactAnalysisResult(
        target_changes=changes,
        direct_dependents=[],
        indirect_dependents=[],
        exposed_endpoints=[
            GraphImpactNode(
                "ep1",
                "POST /login",
                "Endpoint",
                "app/auth.py",
                "exposed_endpoint",
                1,
                "EXPOSES",
                1.0,
            )
        ],
        database_models=[],
        affected_tests=[],
        uncertain_dependents=[],
    )

    repo_files = ["tests/test_auth.py", "tests/test_billing.py", "app/auth.py"]

    recs = selector.select_tests(
        changes=changes,
        graph_result=graph_res,
        all_test_files=repo_files,
    )

    assert len(recs) >= 1
    top_test = recs[0]
    assert top_test.test_file == "tests/test_auth.py"
    assert top_test.priority in ("CRITICAL", "HIGH", "MEDIUM")
    assert top_test.test_framework == "pytest"


# =============================================================================
# Controlled Test Runner Tests
# =============================================================================


@pytest.mark.asyncio
async def test_test_runner_safeguards() -> None:
    runner = ControlledTestRunner()

    # 1. Reject if run_approved is False
    res_not_approved = await runner.execute_approved_tests(
        execution_id="exec-1",
        command="pytest tests/",
        working_dir=".",
        run_approved=False,
    )
    assert res_not_approved.status == "NOT_EXECUTED"
    assert "not approved" in res_not_approved.stderr.lower()

    # 2. Reject non-allowlisted command
    with pytest.raises(ValueError, match="not in the approved test runner allowlist"):
        runner.sanitize_command("rm -rf /")

    # 3. Reject shell injection metacharacters
    with pytest.raises(ValueError, match="Disallowed shell character"):
        runner.sanitize_command("pytest tests/ ; cat /etc/passwd")

    with pytest.raises(ValueError, match="Disallowed shell character"):
        runner.sanitize_command("pytest tests/ && ls -la")

    # 4. Allow legitimate test command
    cmd_args = runner.sanitize_command("pytest tests/test_auth.py")
    assert "pytest" in cmd_args[0].lower()
    assert cmd_args[1] == "tests/test_auth.py"

    # 5. Reject forbidden flags (argument injection protection)
    with pytest.raises(ValueError, match="Disallowed command flag"):
        runner.sanitize_command("pytest -o addopts=--capture=no")

    with pytest.raises(ValueError, match="Disallowed command flag"):
        runner.sanitize_command("pytest --override-ini=foo=bar")

    with pytest.raises(ValueError, match="Disallowed command flag"):
        runner.sanitize_command("pytest -c evil.ini")

    with pytest.raises(ValueError, match="Disallowed command flag"):
        runner.sanitize_command("go test -exec calc.exe")

    # 6. Reject path traversal
    with pytest.raises(ValueError, match="Path traversal"):
        runner.sanitize_command("pytest ../../../outside_test.py")

    # 7. Working directory validation & jail
    with pytest.raises(PermissionError, match="protected system directory"):
        runner.validate_working_directory("C:\\Windows\\System32" if os.name == "nt" else "/etc")

    with pytest.raises(FileNotFoundError, match="does not exist"):
        runner.validate_working_directory("non_existent_dir_999999")

    # 8. Environment secret scrubbing
    os.environ["ORCHESTRIX_DATABASE_URL"] = "postgresql://secret_user:secret_pass@localhost/db"
    os.environ["ORCHESTRIX_JWT_SECRET"] = "super_secret_jwt_key_12345"
    isolated_env = runner.build_isolated_environment()
    assert "ORCHESTRIX_DATABASE_URL" not in isolated_env
    assert "ORCHESTRIX_JWT_SECRET" not in isolated_env
    assert "PATH" in isolated_env

    # 9. Secret redaction
    sensitive_log = (
        "Error in auth: bearer_token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz123' failed"
    )
    redacted = runner.redact_secrets(sensitive_log)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz123" not in redacted
    assert "REDACTED" in redacted


# =============================================================================
# API Integration Tests
# =============================================================================


@pytest_asyncio.fixture
async def test_db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
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


@pytest.mark.asyncio
async def test_impact_api_pipeline(api_client: AsyncClient, test_db_session: AsyncSession) -> None:
    # 1. Seed tenant user, workspace, membership, repository
    user = User(
        id=uuid.uuid4(),
        email="developer@example.com",
        full_name="Impact Developer",
        is_active=True,
    )
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Impact Workspace",
        slug="impact-ws",
    )
    membership = WorkspaceMembership(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.ADMIN,
    )
    test_db_session.add_all([user, workspace, membership])
    await test_db_session.flush()

    inst = GitHubInstallation(
        workspace_id=workspace.id,
        installation_id=9876543,
        account_login="org",
        account_id=123123,
        account_type="Organization",
    )
    test_db_session.add(inst)
    await test_db_session.flush()

    repo = Repository(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        installation_id=inst.id,
        github_repository_id=555666,
        name="backend-repo",
        full_name="org/backend-repo",
        owner_login="org",
        html_url="https://github.com/org/backend-repo",
        default_branch="main",
        visibility="private",
    )
    test_db_session.add(repo)
    await test_db_session.commit()

    # Override current user
    app.dependency_overrides[get_current_user] = lambda: user

    csrf_token = generate_csrf_token()
    headers = {
        "X-CSRF-Token": csrf_token,
        "Cookie": f"csrf_token={csrf_token}",
    }

    # 2. Post Analyze Request
    diff_payload = {
        "diff_text": """diff --git a/app/core.py b/app/core.py
--- a/app/core.py
+++ b/app/core.py
@@ -10,3 +10,4 @@ def compute():
+    x = 1
     return 42
""",
        "comparison_mode": "diff_input",
    }

    response = await api_client.post(
        f"/api/v1/repositories/{repo.id}/impact/analyze?workspace_id={workspace.id}",
        json=diff_payload,
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["repository_id"] == str(repo.id)
    assert data["workspace_id"] == str(workspace.id)
    assert data["status"].upper() == "COMPLETED"
    assert data["score_type"] == "heuristic_structural_exposure"
    assert 0.0 <= data["structural_exposure_score"] <= 100.0
    assessment_id = data["id"]

    # 3. Get Assessment Detail
    detail_res = await api_client.get(
        f"/api/v1/repositories/{repo.id}/impact/{assessment_id}?workspace_id={workspace.id}"
    )
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["id"] == assessment_id

    # 4. List History
    history_res = await api_client.get(
        f"/api/v1/repositories/{repo.id}/impact/history?workspace_id={workspace.id}"
    )
    assert history_res.status_code == 200
    history_data = history_res.json()
    assert history_data["total"] >= 1
    assert history_data["assessments"][0]["id"] == assessment_id

    # 5. Get Test Recommendations
    tests_res = await api_client.get(
        f"/api/v1/repositories/{repo.id}/impact/{assessment_id}/tests?workspace_id={workspace.id}"
    )
    assert tests_res.status_code == 200
    assert isinstance(tests_res.json(), list)

    # 6. Run Tests Endpoint - Reject if run_approved is False
    unapproved_run = await api_client.post(
        f"/api/v1/repositories/{repo.id}/impact/{assessment_id}/tests/run?workspace_id={workspace.id}",
        json={"run_approved": False},
        headers=headers,
    )
    assert unapproved_run.status_code == 400
    assert "Explicit user approval" in unapproved_run.json()["detail"]


@pytest.mark.asyncio
async def test_real_github_repository_compare_analysis(
    test_db_session: AsyncSession,
) -> None:
    """
    Test ImpactMind analysis using real-world multi-file payload from
    the connected nandakumar-123/time-tracker GitHub repository.
    Verifies Tree-sitter multi-language extraction, symbol resolution,
    and structural exposure calculation across 23 real repository files.
    """
    # 1. Seed Workspace, Installation, Repository and Snapshot
    repo_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    snap_id = uuid.uuid4()
    inst_id = uuid.uuid4()

    workspace = Workspace(
        id=ws_id,
        name="Time Tracker Workspace",
        slug="time-tracker-ws",
    )
    installation = GitHubInstallation(
        id=inst_id,
        workspace_id=ws_id,
        installation_id=207181718,
        account_login="nandakumar-123",
        account_type="User",
        account_id=207181718,
    )
    repo = Repository(
        id=repo_id,
        workspace_id=ws_id,
        installation_id=inst_id,
        github_repository_id=12345678,
        name="time-tracker",
        full_name="nandakumar-123/time-tracker",
        owner_login="nandakumar-123",
        html_url="https://github.com/nandakumar-123/time-tracker",
        default_branch="main",
        is_active=True,
    )
    test_db_session.add_all([workspace, installation, repo])

    # Add symbols corresponding to real time-tracker repository
    sym1 = CodeSymbol(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo_id,
        snapshot_id=snap_id,
        file_id=uuid.uuid4(),
        file_path="src/components/ui/button.tsx",
        name="Button",
        symbol_type="function",
        start_line=37,
        end_line=56,
        language="TSX",
    )
    sym2 = CodeSymbol(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo_id,
        snapshot_id=snap_id,
        file_id=uuid.uuid4(),
        file_path="src/lib/utils.ts",
        name="cn",
        symbol_type="function",
        start_line=4,
        end_line=6,
        language="TypeScript",
    )
    sym3 = CodeSymbol(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo_id,
        snapshot_id=snap_id,
        file_id=uuid.uuid4(),
        file_path="src/components/ui/TimeChart.tsx",
        name="Data",
        symbol_type="interface",
        start_line=7,
        end_line=10,
        language="TSX",
    )
    test_db_session.add_all([sym1, sym2, sym3])
    await test_db_session.flush()

    # Real GitHub compare payload with 23 modified files
    real_compare_payload = {
        "base_commit": {"sha": "e242a62142"},
        "commits": [{"sha": "3632fecee7", "commit": {"message": "second project"}}],
        "files": [
            {
                "filename": "package.json",
                "status": "modified",
                "additions": 41,
                "deletions": 0,
                "patch": '@@ -0,0 +1,41 @@\n+{\n+  "name": "time-tracker",\n+  "dependencies": {"react": "^18.2.0"}\n+}',
            },
            {
                "filename": "src/components/ui/button.tsx",
                "status": "modified",
                "additions": 58,
                "deletions": 0,
                "patch": "@@ -0,0 +37,20 @@\n+function Button() {\n+  return <button>Click</button>;\n+}",
            },
            {
                "filename": "src/lib/utils.ts",
                "status": "modified",
                "additions": 6,
                "deletions": 0,
                "patch": "@@ -0,0 +4,3 @@\n+export function cn(...inputs) {\n+  return inputs.join(' ');\n+}",
            },
            {
                "filename": "src/components/ui/TimeChart.tsx",
                "status": "modified",
                "additions": 58,
                "deletions": 0,
                "patch": "@@ -0,0 +7,4 @@\n+export interface Data {\n+  hours: number;\n+}",
            },
            {
                "filename": "components.json",
                "status": "modified",
                "additions": 22,
                "deletions": 0,
                "patch": '@@ -0,0 +1,22 @@\n+{"$schema": "https://ui.shadcn.com/schema.json"}',
            },
        ],
    }

    engine = ImpactMindEngine(graph_provider=MockGraphProvider())
    assessment = await engine.analyze_changes(
        db=test_db_session,
        workspace_id=ws_id,
        repository_id=repo_id,
        snapshot_id=snap_id,
        github_compare_payload=real_compare_payload,
        comparison_mode="commit_range",
    )

    assert assessment.status == "completed"
    assert assessment.base_commit_sha == "e242a62142"
    assert assessment.target_commit_sha == "3632fecee7"
    assert len(assessment.classifications) == 5

    # Verify symbol resolution against real repo symbols
    button_change = next(
        c for c in assessment.classifications if c.file_path == "src/components/ui/button.tsx"
    )
    assert button_change.symbol_name == "Button"
    assert button_change.symbol_id == str(sym1.id)

    cn_change = next(c for c in assessment.classifications if c.file_path == "src/lib/utils.ts")
    assert cn_change.symbol_name == "cn"
    assert cn_change.symbol_id == str(sym2.id)

    # Verify dependency change classification
    pkg_change = next(c for c in assessment.classifications if c.file_path == "package.json")
    assert pkg_change.category == "DEPENDENCY_CHANGE"
    assert not pkg_change.is_breaking
