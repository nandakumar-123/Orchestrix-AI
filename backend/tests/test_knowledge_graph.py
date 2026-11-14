from __future__ import annotations

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
    FileDependency,
    RepositoryFile,
    RepositorySnapshot,
)
from app.db.models.semantic_intelligence import SemanticCodeChunk
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db_session
from app.main import app
from app.services.auth import generate_csrf_token
from app.services.embedding_service import MockEmbeddingProvider, set_cached_embedding_provider
from app.services.graph_query_engine import GraphQueryEngine
from app.services.graph_service import (
    GraphNode,
    GraphRelationship,
    MockGraphProvider,
    set_cached_graph_provider,
)
from app.services.impact_analysis import ImpactAnalysisEngine
from app.services.relationship_extraction import MultiLanguageRelationshipExtractor
from app.services.symbol_resolution import SymbolResolutionEngine

# -----------------------------------------------------------------------------
# Unit Tests: MockGraphProvider Core Functionality
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_graph_provider_crud() -> None:
    provider = MockGraphProvider()
    assert provider.provider_name == "mock"
    assert await provider.health_check() is True

    snap_id = str(uuid.uuid4())
    n1 = GraphNode(
        id=f"file:{snap_id}:app/main.py",
        label="File",
        properties={"snapshot_id": snap_id, "file_path": "app/main.py"},
    )
    n2 = GraphNode(
        id=f"sym:{snap_id}:app/main.py:function:handle_req",
        label="Function",
        properties={"snapshot_id": snap_id, "name": "handle_req"},
    )

    # Upsert nodes
    count = await provider.upsert_nodes([n1, n2])
    assert count == 2
    assert len(provider.nodes) == 2

    # Upsert relationship
    r1 = GraphRelationship(
        source_id=n1.id, target_id=n2.id, type="CONTAINS", properties={"snapshot_id": snap_id}
    )
    rel_count = await provider.upsert_relationships([r1])
    assert rel_count == 1
    assert len(provider.relationships) == 1

    # Subgraph retrieval
    sub = await provider.get_subgraph(snapshot_id=snap_id)
    assert sub["total_nodes"] == 2
    assert sub["total_edges"] == 1

    # Filter subgraph by label
    sub_func = await provider.get_subgraph(snapshot_id=snap_id, labels=["Function"])
    assert sub_func["total_nodes"] == 1
    assert sub_func["nodes"][0]["label"] == "Function"

    # Delete snapshot graph
    deleted = await provider.delete_snapshot_graph(snapshot_id=snap_id)
    assert deleted == 2
    assert len(provider.nodes) == 0
    assert len(provider.relationships) == 0


# -----------------------------------------------------------------------------
# Unit Tests: SymbolResolutionEngine
# -----------------------------------------------------------------------------


def test_symbol_resolution_same_file_and_imports() -> None:
    snap_id = str(uuid.uuid4())
    f1 = RepositoryFile(
        id=uuid.uuid4(),
        snapshot_id=uuid.UUID(snap_id),
        path="src/auth.ts",
        file_name="auth.ts",
        line_count=50,
        size_bytes=1000,
        sha="abc",
    )
    f2 = RepositoryFile(
        id=uuid.uuid4(),
        snapshot_id=uuid.UUID(snap_id),
        path="src/user.ts",
        file_name="user.ts",
        line_count=80,
        size_bytes=1500,
        sha="def",
    )

    s1 = CodeSymbol(
        id=uuid.uuid4(),
        snapshot_id=uuid.UUID(snap_id),
        file_id=f1.id,
        file_path="src/auth.ts",
        name="login",
        symbol_type="function",
        language="TypeScript",
        start_line=1,
        end_line=10,
    )
    s2 = CodeSymbol(
        id=uuid.uuid4(),
        snapshot_id=uuid.UUID(snap_id),
        file_id=f1.id,
        file_path="src/auth.ts",
        name="AuthToken",
        symbol_type="class",
        language="TypeScript",
        start_line=15,
        end_line=30,
    )
    s3 = CodeSymbol(
        id=uuid.uuid4(),
        snapshot_id=uuid.UUID(snap_id),
        file_id=f2.id,
        file_path="src/user.ts",
        name="UserProfile",
        symbol_type="class",
        language="TypeScript",
        start_line=1,
        end_line=25,
    )

    dep1 = FileDependency(
        id=uuid.uuid4(),
        snapshot_id=uuid.UUID(snap_id),
        source_file_path="src/user.ts",
        name="./auth",
        dependency_type="import",
    )

    engine = SymbolResolutionEngine(
        snapshot_id=snap_id,
        files=[f1, f2],
        symbols=[s1, s2, s3],
        dependencies=[dep1],
    )

    # 1. Same-file resolution
    res_same = engine.resolve_symbol("src/auth.ts", "AuthToken")
    assert res_same.status == "resolved"
    assert res_same.resolution_type == "same_file"
    assert res_same.confidence == 1.0

    # 2. Cross-file import resolution
    res_import = engine.resolve_symbol("src/user.ts", "login")
    assert res_import.status == "resolved"
    assert res_import.resolution_type == "import_match"
    assert res_import.confidence >= 0.9

    # 3. Global unique match (without direct import)
    res_global = engine.resolve_symbol("src/other.ts", "UserProfile")
    assert res_global.status == "resolved"
    assert res_global.resolution_type == "unique_global_match"

    # 4. Unresolved symbol
    res_unresolved = engine.resolve_symbol("src/user.ts", "NonExistentHelper")
    assert res_unresolved.status == "unresolved"
    assert res_unresolved.confidence == 0.0


# -----------------------------------------------------------------------------
# Unit Tests: Relationship Extraction
# -----------------------------------------------------------------------------


def test_relationship_extraction_multi_language() -> None:
    snap_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    snap = RepositorySnapshot(
        id=snap_id,
        workspace_id=ws_id,
        repository_id=repo_id,
        commit_sha="abcd1234efgh5678",
        branch="main",
    )

    f1 = RepositoryFile(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo_id,
        snapshot_id=snap_id,
        path="app/api.py",
        file_name="api.py",
        language="Python",
        line_count=40,
        size_bytes=800,
        sha="sha1",
    )
    f2 = RepositoryFile(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo_id,
        snapshot_id=snap_id,
        path="app/models.py",
        file_name="models.py",
        language="Python",
        line_count=30,
        size_bytes=600,
        sha="sha2",
    )
    f3 = RepositoryFile(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo_id,
        snapshot_id=snap_id,
        path="tests/test_api.py",
        file_name="test_api.py",
        language="Python",
        line_count=20,
        size_bytes=400,
        sha="sha3",
    )

    s1 = CodeSymbol(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo_id,
        snapshot_id=snap_id,
        file_id=f1.id,
        file_path="app/api.py",
        name="get_user",
        symbol_type="function",
        language="Python",
        start_line=5,
        end_line=12,
        signature="def get_user():",
    )
    s2 = CodeSymbol(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo_id,
        snapshot_id=snap_id,
        file_id=f2.id,
        file_path="app/models.py",
        name="UserAccount",
        symbol_type="class",
        language="Python",
        start_line=3,
        end_line=15,
        signature="class UserAccount(Base):",
    )
    s3 = CodeSymbol(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo_id,
        snapshot_id=snap_id,
        file_id=f3.id,
        file_path="tests/test_api.py",
        name="test_get_user",
        symbol_type="function",
        language="Python",
        start_line=4,
        end_line=10,
        signature="def test_get_user():",
    )

    dep1 = FileDependency(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        repository_id=repo_id,
        snapshot_id=snap_id,
        source_file_path="app/api.py",
        name="app.models",
        dependency_type="import",
    )

    file_contents = {
        "app/api.py": """
from app.models import UserAccount

@router.get("/users/me")
def get_user():
    user = query_db()
    return user
""",
        "app/models.py": """
class UserAccount(Base):
    __tablename__ = "user_accounts"
    id = Column(Integer)
""",
        "tests/test_api.py": """
def test_get_user():
    res = get_user()
    assert res is not None
""",
    }

    extractor = MultiLanguageRelationshipExtractor(
        snapshot=snap,
        files=[f1, f2, f3],
        symbols=[s1, s2, s3],
        dependencies=[dep1],
        file_contents=file_contents,
    )

    nodes, rels = extractor.extract_all()

    # Check node labels
    node_labels = {n.label for n in nodes}
    assert "Repository" in node_labels
    assert "RepositorySnapshot" in node_labels
    assert "File" in node_labels
    assert "Function" in node_labels
    assert "Class" in node_labels
    assert "APIEndpoint" in node_labels
    assert "DatabaseTable" in node_labels
    assert "TestCase" in node_labels

    # Check relationship types
    rel_types = {r.type for r in rels}
    assert "CONTAINS" in rel_types
    assert "EXPOSES" in rel_types
    assert "DEFINES" in rel_types
    assert "TESTS" in rel_types


# -----------------------------------------------------------------------------
# Unit Tests: GraphQueryEngine & Circular Dependency Detection
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_query_engine_and_cycle_detection() -> None:
    provider = MockGraphProvider()
    engine = GraphQueryEngine(provider)
    sid = str(uuid.uuid4())

    # Build circular import: A -> B -> C -> A
    fA = GraphNode(
        id=f"file:{sid}:A.py", label="File", properties={"snapshot_id": sid, "file_path": "A.py"}
    )
    fB = GraphNode(
        id=f"file:{sid}:B.py", label="File", properties={"snapshot_id": sid, "file_path": "B.py"}
    )
    fC = GraphNode(
        id=f"file:{sid}:C.py", label="File", properties={"snapshot_id": sid, "file_path": "C.py"}
    )
    await provider.upsert_nodes([fA, fB, fC])

    rAB = GraphRelationship(
        source_id=fA.id, target_id=fB.id, type="IMPORTS", properties={"snapshot_id": sid}
    )
    rBC = GraphRelationship(
        source_id=fB.id, target_id=fC.id, type="IMPORTS", properties={"snapshot_id": sid}
    )
    rCA = GraphRelationship(
        source_id=fC.id, target_id=fA.id, type="IMPORTS", properties={"snapshot_id": sid}
    )
    await provider.upsert_relationships([rAB, rBC, rCA])

    cycles = await engine.find_circular_dependencies(sid)
    assert len(cycles) > 0
    cycle_flattened = cycles[0]
    assert "A.py" in cycle_flattened
    assert "B.py" in cycle_flattened
    assert "C.py" in cycle_flattened

    # Shortest path test
    path = await engine.trace_path(fA.id, fC.id)
    assert path is not None
    assert len(path) == 2


# -----------------------------------------------------------------------------
# Unit Tests: ImpactAnalysisEngine
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_impact_analysis_engine() -> None:
    provider = MockGraphProvider()
    sid = str(uuid.uuid4())

    sym_target = GraphNode(
        id=f"sym:{sid}:core.py:function:validate_jwt",
        label="Function",
        properties={"snapshot_id": sid, "name": "validate_jwt", "file_path": "core.py"},
    )
    sym_caller = GraphNode(
        id=f"sym:{sid}:auth.py:function:login_route",
        label="Function",
        properties={"snapshot_id": sid, "name": "login_route", "file_path": "auth.py"},
    )
    api_ep = GraphNode(
        id=f"api:{sid}:POST:/auth/login",
        label="APIEndpoint",
        properties={"snapshot_id": sid, "method": "POST", "path": "/auth/login"},
    )
    test_case = GraphNode(
        id=f"test:{sid}:test_auth.py:test_login",
        label="TestCase",
        properties={"snapshot_id": sid, "name": "test_login", "file_path": "test_auth.py"},
    )

    await provider.upsert_nodes([sym_target, sym_caller, api_ep, test_case])

    rel_call = GraphRelationship(
        source_id=sym_caller.id,
        target_id=sym_target.id,
        type="CALLS",
        properties={"snapshot_id": sid},
    )
    rel_expose = GraphRelationship(
        source_id=sym_caller.id,
        target_id=api_ep.id,
        type="EXPOSES",
        properties={"snapshot_id": sid},
    )
    rel_test = GraphRelationship(
        source_id=test_case.id,
        target_id=sym_target.id,
        type="TESTS",
        properties={"snapshot_id": sid},
    )

    await provider.upsert_relationships([rel_call, rel_expose, rel_test])

    impact_engine = ImpactAnalysisEngine(provider)
    res = await impact_engine.analyze_impact(snapshot_id=sid, symbol_id=sym_target.id)

    assert res.target_name == "validate_jwt"
    assert len(res.direct_dependents) == 2
    dep_names = [d["name"] for d in res.direct_dependents]
    assert "login_route" in dep_names
    assert len(res.affected_endpoints) == 1
    assert res.affected_endpoints[0]["name"] == "/auth/login"
    assert len(res.affected_tests) == 1
    assert res.affected_tests[0]["name"] == "test_login"
    assert res.risk_level in ("MEDIUM", "HIGH", "CRITICAL")
    assert res.risk_score > 0.0


# -----------------------------------------------------------------------------
# Integration Test Fixture & Database Setup
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def graph_test_setup() -> AsyncGenerator[
    tuple[
        AsyncSession,
        async_sessionmaker[AsyncSession],
        User,
        Workspace,
        Repository,
        RepositorySnapshot,
    ],
    None,
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # Use deterministic MockGraphProvider & MockEmbeddingProvider
    set_cached_graph_provider(MockGraphProvider())
    set_cached_embedding_provider(MockEmbeddingProvider(dimension=384))

    async with session_factory() as db:
        user = User(
            email=f"tester-{uuid.uuid4().hex[:6]}@orchestrix.ai",
            full_name="Graph Tester",
            email_verified=True,
        )
        db.add(user)
        await db.flush()

        ws = Workspace(name="Graph WS", slug=f"graph-ws-{uuid.uuid4().hex[:6]}")
        db.add(ws)
        await db.flush()

        mem = WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER)
        db.add(mem)

        inst = GitHubInstallation(
            workspace_id=ws.id,
            installation_id=9876543,
            account_login="graph-org",
            account_id=123123,
            account_type="Organization",
        )
        db.add(inst)
        await db.flush()

        repo = Repository(
            workspace_id=ws.id,
            installation_id=inst.id,
            github_repository_id=555666,
            name="knowledge-repo",
            full_name="graph-org/knowledge-repo",
            owner_login="graph-org",
            html_url="https://github.com/graph-org/knowledge-repo",
            default_branch="main",
            visibility="private",
        )
        db.add(repo)
        await db.flush()

        snap = RepositorySnapshot(
            workspace_id=ws.id,
            repository_id=repo.id,
            commit_sha="aabbccdd11223344",
            branch="main",
            total_files=2,
            total_symbols=3,
            total_dependencies=1,
            structure_summary={},
        )
        db.add(snap)
        await db.flush()

        f1 = RepositoryFile(
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
            path="app/auth.py",
            file_name="auth.py",
            language="Python",
            size_bytes=1200,
            line_count=40,
            sha="sha111",
        )
        f2 = RepositoryFile(
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
            path="app/models.py",
            file_name="models.py",
            language="Python",
            size_bytes=800,
            line_count=25,
            sha="sha222",
        )
        db.add_all([f1, f2])
        await db.flush()

        s1 = CodeSymbol(
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
            file_id=f1.id,
            file_path="app/auth.py",
            name="login_handler",
            symbol_type="function",
            language="Python",
            start_line=5,
            end_line=15,
            signature="def login_handler():",
        )
        s2 = CodeSymbol(
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
            file_id=f2.id,
            file_path="app/models.py",
            name="UserAccount",
            symbol_type="class",
            language="Python",
            start_line=3,
            end_line=20,
            signature="class UserAccount(Base):",
        )
        db.add_all([s1, s2])

        dep1 = FileDependency(
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
            source_file_path="app/auth.py",
            name="app.models",
            dependency_type="import",
        )
        db.add(dep1)

        chunk1 = SemanticCodeChunk(
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
            file_id=f1.id,
            file_path="app/auth.py",
            language="Python",
            symbol_name="login_handler",
            symbol_type="function",
            start_line=5,
            end_line=15,
            chunk_index=0,
            content="def login_handler():\n    return 'auth_token'",
            content_hash="hash1",
            embedding=[0.05] * 384,
        )
        db.add(chunk1)
        await db.commit()

        yield db, session_factory, user, ws, repo, snap

    set_cached_graph_provider(None)
    set_cached_embedding_provider(None)


# -----------------------------------------------------------------------------
# Integration Tests: End-to-End REST APIs
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_graph_rest_apis(
    graph_test_setup: tuple[
        AsyncSession,
        async_sessionmaker[AsyncSession],
        User,
        Workspace,
        Repository,
        RepositorySnapshot,
    ],
) -> None:
    db, session_factory, user, ws, repo, snap = graph_test_setup

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield db

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user] = lambda: user

    csrf_token = generate_csrf_token()
    cookies = {
        "access_token": "mock_jwt_token",
        "csrf_token": csrf_token,
    }
    headers = {
        "X-CSRF-Token": csrf_token,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies=cookies,
        headers=headers,
    ) as client:
        # 1. Trigger Graph Indexing
        idx_res = await client.post(
            f"/api/v1/repositories/{repo.id}/graph-index?workspace_id={ws.id}",
            json={"snapshot_id": str(snap.id), "force_reindex": True},
        )
        assert idx_res.status_code == 202
        idx_data = idx_res.json()
        assert idx_data["status"] == "completed"
        assert idx_data["total_nodes"] > 0

        # 2. Get Graph Status
        status_res = await client.get(
            f"/api/v1/repositories/{repo.id}/graph-index/status?workspace_id={ws.id}&snapshot_id={snap.id}",
        )
        assert status_res.status_code == 200
        st_data = status_res.json()
        assert st_data["status"] == "completed"
        assert st_data["total_nodes"] > 0

        # 3. Get Visual Subgraph
        sub_res = await client.get(
            f"/api/v1/repositories/{repo.id}/graph?workspace_id={ws.id}&snapshot_id={snap.id}&limit=50",
        )
        assert sub_res.status_code == 200
        sub_data = sub_res.json()
        assert sub_data["total_nodes"] > 0

        # 4. Impact Preview
        impact_res = await client.post(
            f"/api/v1/repositories/{repo.id}/impact-preview?workspace_id={ws.id}",
            json={
                "snapshot_id": str(snap.id),
                "file_path": "app/auth.py",
                "symbol_name": "login_handler",
            },
        )
        assert impact_res.status_code == 200
        imp_data = impact_res.json()
        assert imp_data["target_name"] == "login_handler"
        assert "risk_level" in imp_data
        assert "risk_score" in imp_data

        # 5. Hybrid Search with Graph Enrichment
        search_res = await client.post(
            f"/api/v1/repositories/{repo.id}/intelligence/search?workspace_id={ws.id}",
            json={
                "query": "login authentication handler",
                "snapshot_id": str(snap.id),
                "include_graph_enrichment": True,
            },
        )
        assert search_res.status_code == 200
        search_data = search_res.json()
        assert search_data["total_results"] > 0
        assert "graph" in search_data["results"][0]["metadata"]

        # 6. Tenant Isolation check: Unauthorized workspace access must fail with 403 or 404
        fake_ws_id = uuid.uuid4()
        unauth_res = await client.get(
            f"/api/v1/repositories/{repo.id}/graph?workspace_id={fake_ws_id}",
        )
        assert unauth_res.status_code in (403, 404)
