import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db_session
from app.main import app
from app.services.auth import generate_csrf_token
from app.services.code_intelligence import ExtractedImport, ExtractedSymbol
from app.services.context_assembly import ContextAssemblyEngine
from app.services.embedding_service import (
    MockEmbeddingProvider,
    get_embedding_provider,
    set_cached_embedding_provider,
)
from app.services.semantic_chunking import (
    ASTSemanticChunker,
    compute_content_hash,
    redact_secrets,
)
from app.services.semantic_indexing_service import SemanticIndexingService
from app.services.semantic_retrieval import SemanticRetrievalEngine

# -----------------------------------------------------------------------------
# Unit Tests: Semantic Chunking & Secret Redaction
# -----------------------------------------------------------------------------


def test_secret_redaction() -> None:
    text_with_secrets = """
    const API_KEY = "sk-1234567890abcdef1234567890abcdef";
    const GITHUB_TOKEN = "ghp_123456789012345678901234567890123456";
    const AUTH = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature";
    const NORMAL_VAR = "hello_world";
    """
    cleaned = redact_secrets(text_with_secrets)
    assert "sk-1234567890abcdef1234567890abcdef" not in cleaned
    assert "ghp_123456789012345678901234567890123456" not in cleaned
    assert "doNotLeakThisSignature" not in cleaned
    assert "[REDACTED_SECRET]" in cleaned
    assert "hello_world" in cleaned


def test_ast_semantic_chunker_basic() -> None:
    chunker = ASTSemanticChunker(max_chunk_lines=50, min_chunk_lines=2)
    py_code = b"""import os
from app.db import session

class AuthEngine:
    def __init__(self, key: str):
        self.key = key

    def verify_token(self, token: str) -> bool:
        return token == self.key

def handle_login(req) -> dict:
    return {"status": "ok"}
"""
    symbols = [
        ExtractedSymbol("AuthEngine", "class", 4, 9, 0, 0, "class AuthEngine:"),
        ExtractedSymbol(
            "__init__", "method", 5, 6, 4, 0, "def __init__(self, key: str):", "AuthEngine"
        ),
        ExtractedSymbol(
            "verify_token",
            "method",
            8,
            9,
            4,
            0,
            "def verify_token(self, token: str) -> bool:",
            "AuthEngine",
        ),
        ExtractedSymbol("handle_login", "function", 11, 12, 0, 0, "def handle_login(req) -> dict:"),
    ]
    imports = [
        ExtractedImport("os", True),
        ExtractedImport("app.db.session", False),
    ]

    chunks = chunker.chunk_file(
        file_path="app/auth.py",
        content_bytes=py_code,
        language="Python",
        symbols=symbols,
        imports=imports,
    )

    assert len(chunks) >= 4  # overview + class + methods / functions
    # Overview chunk
    overview = chunks[0]
    assert overview.symbol_type == "file_summary"
    assert "Imports: os, app.db.session" in overview.embeddable_text

    # Verify symbol chunks
    chunk_names = [c.symbol_name for c in chunks]
    assert "AuthEngine" in chunk_names
    assert "verify_token" in chunk_names
    assert "handle_login" in chunk_names

    for c in chunks:
        assert c.content_hash == compute_content_hash(c.content)
        assert c.start_line <= c.end_line
        assert c.file_path == "app/auth.py"
        assert c.language == "Python"


def test_ast_semantic_chunker_large_function_sliding_window() -> None:
    chunker = ASTSemanticChunker(max_chunk_lines=20, overlap_lines=5)
    # Generate 45-line function
    lines = ["def process_stream():"] + [f"    step_{i} = do_work({i})" for i in range(1, 44)]
    code_bytes = "\n".join(lines).encode("utf-8")
    symbols = [ExtractedSymbol("process_stream", "function", 1, 44, 0, 0, "def process_stream():")]

    chunks = chunker.chunk_file(
        file_path="app/pipeline.py",
        content_bytes=code_bytes,
        language="Python",
        symbols=symbols,
        imports=[],
    )

    part_chunks = [c for c in chunks if "process_stream (part" in (c.symbol_name or "")]
    assert len(part_chunks) >= 2
    assert part_chunks[0].start_line < part_chunks[1].start_line


# -----------------------------------------------------------------------------
# Unit Tests: Embedding Providers
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_embedding_provider() -> None:
    provider = MockEmbeddingProvider(dimension=384)
    assert provider.provider_name == "mock"
    assert provider.dimension == 384

    # Determinism check
    vec1 = await provider.embed_query("user authentication flow")
    vec2 = await provider.embed_query("user authentication flow")
    assert len(vec1) == 384
    assert vec1 == vec2

    # Different text yields different vector
    vec3 = await provider.embed_query("database migration setup")
    assert vec1 != vec3

    # Batch test
    batch_vecs = await provider.embed_texts(["hello", "world"])
    assert len(batch_vecs) == 2
    assert len(batch_vecs[0]) == 384


def test_embedding_provider_factory_and_cache() -> None:
    mock_p = MockEmbeddingProvider()
    set_cached_embedding_provider(mock_p)
    p = get_embedding_provider()
    assert p.provider_name == "mock"
    set_cached_embedding_provider(None)


# -----------------------------------------------------------------------------
# Integration Tests: Setup, Retrieval, Indexing, and Context Assembly
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def semantic_test_setup() -> AsyncGenerator[
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

    # Use MockEmbeddingProvider for deterministic offline unit/integration test runs
    set_cached_embedding_provider(MockEmbeddingProvider(dimension=384))

    async with session_factory() as db:
        # 1. User
        user = User(
            email=f"tester-{uuid.uuid4().hex[:6]}@orchestrix.ai",
            full_name="Semantic Tester",
            email_verified=True,
        )
        db.add(user)
        await db.flush()

        # 2. Workspace
        ws = Workspace(name="Intelligence WS", slug=f"intel-ws-{uuid.uuid4().hex[:6]}")
        db.add(ws)
        await db.flush()

        # 3. Membership
        mem = WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER)
        db.add(mem)

        # 4. Installation & Repo
        inst = GitHubInstallation(
            workspace_id=ws.id,
            installation_id=1234567,
            account_login="intel-org",
            account_id=999888,
            account_type="Organization",
        )
        db.add(inst)
        await db.flush()

        repo = Repository(
            workspace_id=ws.id,
            installation_id=inst.id,
            github_repository_id=111222,
            name="orchestrix-backend",
            full_name="intel-org/orchestrix-backend",
            owner_login="intel-org",
            default_branch="main",
            html_url="https://github.com/intel-org/orchestrix-backend",
        )
        db.add(repo)
        await db.flush()

        # 5. Snapshot
        snap = RepositorySnapshot(
            workspace_id=ws.id,
            repository_id=repo.id,
            commit_sha="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
            branch="main",
            total_files=2,
            total_lines=150,
            total_bytes=4096,
            total_symbols=3,
            total_dependencies=2,
        )
        db.add(snap)
        await db.flush()

        # 6. Repository Files
        file_auth = RepositoryFile(
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
            path="backend/app/api/v1/auth.py",
            file_name="auth.py",
            extension=".py",
            language="Python",
            size_bytes=2048,
            line_count=80,
            sha="sha_auth_123",
            is_binary=False,
            is_manifest=False,
        )
        file_db = RepositoryFile(
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
            path="backend/app/db/session.py",
            file_name="session.py",
            extension=".py",
            language="Python",
            size_bytes=1024,
            line_count=50,
            sha="sha_db_456",
            is_binary=False,
            is_manifest=False,
        )
        db.add(file_auth)
        db.add(file_db)
        await db.flush()

        # 7. Code Symbols
        sym_oauth = CodeSymbol(
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
            file_id=file_auth.id,
            file_path="backend/app/api/v1/auth.py",
            name="google_oauth_callback",
            symbol_type="function",
            language="Python",
            start_line=25,
            end_line=55,
            signature="async def google_oauth_callback(code: str):",
        )
        sym_session = CodeSymbol(
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
            file_id=file_db.id,
            file_path="backend/app/db/session.py",
            name="get_db_session",
            symbol_type="function",
            language="Python",
            start_line=10,
            end_line=30,
            signature="async def get_db_session():",
        )
        db.add(sym_oauth)
        db.add(sym_session)
        await db.flush()

        # 8. File Dependencies
        dep = FileDependency(
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
            file_id=file_auth.id,
            source_file_path="backend/app/api/v1/auth.py",
            name="authlib",
            dependency_type="import",
            is_external=True,
        )
        db.add(dep)
        await db.commit()

    yield db, session_factory, user, ws, repo, snap


@pytest.mark.asyncio
async def test_semantic_indexing_and_incremental_reuse(
    semantic_test_setup: tuple[
        AsyncSession,
        async_sessionmaker[AsyncSession],
        User,
        Workspace,
        Repository,
        RepositorySnapshot,
    ],
) -> None:
    db, session_factory, user, ws, repo, snap = semantic_test_setup

    service = SemanticIndexingService(provider=MockEmbeddingProvider())

    async with session_factory() as session:
        meta = await service.index_snapshot(
            db=session,
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
        )
        assert meta.status == "completed"
        assert meta.total_chunks > 0

        # Verify chunks exist in DB
        retrieval = SemanticRetrievalEngine(provider=MockEmbeddingProvider())
        results = await retrieval.search(
            db=session,
            workspace_id=ws.id,
            repository_id=repo.id,
            query="google oauth authentication callback",
        )
        assert len(results) > 0
        top = results[0]
        assert top.similarity_score > 0.0
        assert top.repository_name == "orchestrix-backend"


@pytest.mark.asyncio
async def test_semantic_retrieval_filters_and_hybrid_scoring(
    semantic_test_setup: tuple[
        AsyncSession,
        async_sessionmaker[AsyncSession],
        User,
        Workspace,
        Repository,
        RepositorySnapshot,
    ],
) -> None:
    db, session_factory, user, ws, repo, snap = semantic_test_setup

    async with session_factory() as session:
        service = SemanticIndexingService(provider=MockEmbeddingProvider())
        await service.index_snapshot(
            db=session,
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
        )

        retrieval = SemanticRetrievalEngine(provider=MockEmbeddingProvider())

        # Test language filter
        py_results = await retrieval.search(
            db=session,
            workspace_id=ws.id,
            repository_id=repo.id,
            query="database session",
            language="Python",
        )
        assert len(py_results) > 0
        assert all(r.language == "Python" for r in py_results)

        # Non-matching language filter
        ts_results = await retrieval.search(
            db=session,
            workspace_id=ws.id,
            repository_id=repo.id,
            query="database session",
            language="TypeScript",
        )
        assert len(ts_results) == 0

        # Path prefix filter
        auth_results = await retrieval.search(
            db=session,
            workspace_id=ws.id,
            repository_id=repo.id,
            query="oauth",
            file_path_prefix="backend/app/api",
        )
        assert len(auth_results) > 0
        assert all(r.file_path.startswith("backend/app/api") for r in auth_results)


@pytest.mark.asyncio
async def test_context_assembly_engine(
    semantic_test_setup: tuple[
        AsyncSession,
        async_sessionmaker[AsyncSession],
        User,
        Workspace,
        Repository,
        RepositorySnapshot,
    ],
) -> None:
    db, session_factory, user, ws, repo, snap = semantic_test_setup

    async with session_factory() as session:
        service = SemanticIndexingService(provider=MockEmbeddingProvider())
        await service.index_snapshot(
            db=session,
            workspace_id=ws.id,
            repository_id=repo.id,
            snapshot_id=snap.id,
        )

        retrieval = SemanticRetrievalEngine(provider=MockEmbeddingProvider())
        chunks = await retrieval.search(
            db=session,
            workspace_id=ws.id,
            repository_id=repo.id,
            query="user authentication handling",
        )

        assembler = ContextAssemblyEngine(max_context_chars=10000)
        ctx = assembler.assemble(
            repository_id=repo.id,
            repository_name=repo.name,
            query="user authentication handling",
            retrieved_chunks=chunks,
        )

        assert ctx.total_blocks_included > 0
        assert ctx.total_characters > 0
        assert ctx.estimated_tokens > 0
        assert "Repository Context: orchestrix-backend" in ctx.formatted_context_markdown
        assert "File:" in ctx.formatted_context_markdown


@pytest.mark.asyncio
async def test_workspace_isolation_and_authorization(
    semantic_test_setup: tuple[
        AsyncSession,
        async_sessionmaker[AsyncSession],
        User,
        Workspace,
        Repository,
        RepositorySnapshot,
    ],
) -> None:
    db, session_factory, user, ws, repo, snap = semantic_test_setup

    other_ws_id = uuid.uuid4()
    async with session_factory() as session:
        retrieval = SemanticRetrievalEngine(provider=MockEmbeddingProvider())
        with pytest.raises(LookupError):
            await retrieval.search(
                db=session,
                workspace_id=other_ws_id,  # Invalid workspace ID
                repository_id=repo.id,
                query="authentication",
            )


# -----------------------------------------------------------------------------
# API Endpoint Integration Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_api_endpoints(
    semantic_test_setup: tuple[
        AsyncSession,
        async_sessionmaker[AsyncSession],
        User,
        Workspace,
        Repository,
        RepositorySnapshot,
    ],
) -> None:
    db, session_factory, user, ws, repo, snap = semantic_test_setup

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield db

    app.dependency_overrides[get_db_session] = override_get_db_session

    csrf_token = generate_csrf_token()
    cookies = {
        "access_token": "mock_jwt_token",
        "csrf_token": csrf_token,
    }
    headers = {
        "X-CSRF-Token": csrf_token,
    }

    from app.api.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies=cookies,
        headers=headers,
    ) as client:
        # 1. Trigger Semantic Indexing
        idx_res = await client.post(
            f"/api/v1/repositories/{repo.id}/semantic-index?workspace_id={ws.id}",
            json={"snapshot_id": str(snap.id), "force_reembed": True},
        )
        assert idx_res.status_code == 202
        data = idx_res.json()
        assert data["status"] == "completed"
        assert data["total_chunks"] > 0

        # 2. Get Status
        status_res = await client.get(
            f"/api/v1/repositories/{repo.id}/semantic-index/status?workspace_id={ws.id}",
        )
        assert status_res.status_code == 200
        assert status_res.json()["status"] == "completed"

        # 3. Semantic Search (POST)
        search_res = await client.post(
            f"/api/v1/repositories/{repo.id}/semantic-search?workspace_id={ws.id}",
            json={"query": "oauth callback handling", "limit": 5},
        )
        assert search_res.status_code == 200
        search_data = search_res.json()
        assert search_data["total_results"] > 0
        top_item = search_data["results"][0]
        chunk_id = top_item["chunk_id"]

        # 4. Semantic Search (GET)
        get_search_res = await client.get(
            f"/api/v1/repositories/{repo.id}/semantic-search?workspace_id={ws.id}&q=oauth",
        )
        assert get_search_res.status_code == 200
        assert get_search_res.json()["total_results"] > 0

        # 5. Get Chunk Detail
        chunk_res = await client.get(
            f"/api/v1/repositories/{repo.id}/semantic-chunks/{chunk_id}?workspace_id={ws.id}",
        )
        assert chunk_res.status_code == 200
        assert chunk_res.json()["id"] == chunk_id

        # 6. Assemble Context
        context_res = await client.post(
            f"/api/v1/repositories/{repo.id}/assemble-context?workspace_id={ws.id}",
            json={"query": "where is oauth callback handled", "limit": 5, "max_characters": 8000},
        )
        assert context_res.status_code == 200
        ctx_data = context_res.json()
        assert ctx_data["total_blocks_included"] > 0
        assert "Repository Context:" in ctx_data["formatted_context_markdown"]

    app.dependency_overrides.clear()
