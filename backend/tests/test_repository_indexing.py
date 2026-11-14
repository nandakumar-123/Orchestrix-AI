import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base, IndexingJobStatus, WorkspaceRole
from app.db.models.github_account import GitHubAccount
from app.db.models.github_installation import GitHubInstallation
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.repository_intelligence import (
    IndexingJob,
)
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.session import get_db_session
from app.main import app
from app.services.auth import generate_csrf_token
from app.services.code_intelligence import analyze_code_content
from app.services.dependency_intelligence import (
    parse_cargo_toml,
    parse_go_mod,
    parse_package_json,
    parse_pyproject_toml,
    parse_requirements_txt,
)
from app.services.github import encrypt_token
from app.services.indexing_service import (
    _execute_indexing_job_background,
    cancel_indexing_job,
    create_indexing_job,
    get_latest_repository_snapshot,
    list_repository_dependencies,
    list_repository_files,
    list_repository_symbols,
)
from app.services.repository_ingestion import (
    detect_language,
    is_manifest_file,
    is_path_safe,
    is_secret_file,
    should_skip_file,
)

# -----------------------------------------------------------------------------
# Unit Tests: File Discovery, Language & Secret Filtering
# -----------------------------------------------------------------------------


def test_file_filtering_and_security_exclusions() -> None:
    # 1. Safe paths
    assert is_path_safe("app/main.py") is True
    assert is_path_safe("src/components/ui/button.tsx") is True
    assert is_path_safe("../etc/passwd") is False
    assert is_path_safe("app/../../secrets") is False

    # 2. Secret file detection
    assert is_secret_file(".env") is True
    assert is_secret_file(".env.production") is True
    assert is_secret_file("id_rsa") is True
    assert is_secret_file("client_secret_xyz.json") is True
    assert is_secret_file("server.key") is True
    assert is_secret_file("normal_file.py") is False

    # 3. Directory and binary skipping
    skip, reason = should_skip_file("node_modules/react/index.js")
    assert skip is True
    assert "excluded_directory" in reason

    skip, reason = should_skip_file(".git/config")
    assert skip is True

    skip, reason = should_skip_file("venv/lib/site-packages/os.py")
    assert skip is True

    skip, reason = should_skip_file(".env")
    assert skip is True
    assert reason == "secret_file_excluded"

    skip, reason = should_skip_file("assets/logo.png")
    assert skip is True
    assert reason == "binary_file_skipped"

    skip, reason = should_skip_file("large_data.json", size=600 * 1024)
    assert skip is True
    assert "file_size_exceeded" in reason

    skip, reason = should_skip_file("app/main.py", size=10 * 1024)
    assert skip is False
    assert reason == "ok"


def test_language_detection() -> None:
    assert detect_language("backend/main.py") == "Python"
    assert detect_language("frontend/src/index.ts") == "TypeScript"
    assert detect_language("frontend/src/App.tsx") == "TSX"
    assert detect_language("script.js") == "JavaScript"
    assert detect_language("App.java") == "Java"
    assert detect_language("engine.c") == "C"
    assert detect_language("core.cpp") == "C++"
    assert detect_language("main.go") == "Go"
    assert detect_language("lib.rs") == "Rust"
    assert detect_language("unknown.xyz") is None


def test_manifest_file_detection() -> None:
    assert is_manifest_file("package.json") is True
    assert is_manifest_file("frontend/package.json") is True
    assert is_manifest_file("pyproject.toml") is True
    assert is_manifest_file("requirements.txt") is True
    assert is_manifest_file("Cargo.toml") is True
    assert is_manifest_file("go.mod") is True
    assert is_manifest_file("README.md") is False


# -----------------------------------------------------------------------------
# Unit Tests: Tree-sitter Code Intelligence
# -----------------------------------------------------------------------------


def test_tree_sitter_python_analysis() -> None:
    code = b"""
import os
from typing import List

class ArchitectureEngine:
    def __init__(self, name: str):
        self.name = name

    def compute_metric(self, factor: int) -> float:
        return factor * 2.5

def standalone_pipeline(items: List[str]) -> bool:
    return len(items) > 0
"""
    intel = analyze_code_content(code, "Python")
    assert intel.parse_error is None
    assert intel.language == "Python"
    assert intel.line_count > 10

    sym_names = [s.name for s in intel.symbols]
    assert "ArchitectureEngine" in sym_names
    assert "__init__" in sym_names
    assert "compute_metric" in sym_names
    assert "standalone_pipeline" in sym_names

    # Check method parent-child relationship
    method = next(s for s in intel.symbols if s.name == "compute_metric")
    assert method.symbol_type == "method"
    assert method.parent_symbol_name == "ArchitectureEngine"
    assert method.start_line > 0

    func = next(s for s in intel.symbols if s.name == "standalone_pipeline")
    assert func.symbol_type == "function"
    assert func.parent_symbol_name is None

    # Check imports
    imp_names = [i.module_name for i in intel.imports]
    assert "os" in imp_names
    assert "typing" in imp_names


def test_tree_sitter_typescript_analysis() -> None:
    code = b"""
import React, { useState } from 'react';
import { Button } from './ui/button';

export interface AgentConfig {
    id: string;
    model: string;
}

export class TaskRunner {
    runTask(taskId: string): void {
        console.log(taskId);
    }
}

export function initializeMesh(): boolean {
    return true;
}
"""
    intel = analyze_code_content(code, "TypeScript")
    assert intel.parse_error is None
    assert intel.language == "TypeScript"

    sym_names = [s.name for s in intel.symbols]
    assert "AgentConfig" in sym_names
    assert "TaskRunner" in sym_names
    assert "runTask" in sym_names
    assert "initializeMesh" in sym_names

    interface_sym = next(s for s in intel.symbols if s.name == "AgentConfig")
    assert interface_sym.symbol_type == "interface"

    # Check external vs internal imports
    ext_imports = [i for i in intel.imports if i.is_external]
    int_imports = [i for i in intel.imports if not i.is_external]
    assert any(i.module_name == "react" for i in ext_imports)
    assert any("./ui/button" in i.module_name for i in int_imports)


def test_tree_sitter_java_and_cpp_analysis() -> None:
    java_code = b"""
package com.orchestrix;
import java.util.concurrent.ExecutorService;

public class ExecutionEngine {
    public void executeJob(String jobId) {
        System.out.println(jobId);
    }
}
"""
    java_intel = analyze_code_content(java_code, "Java")
    assert java_intel.parse_error is None
    assert any(s.name == "ExecutionEngine" for s in java_intel.symbols)
    assert any(s.name == "executeJob" for s in java_intel.symbols)
    assert any("java.util.concurrent.ExecutorService" in i.module_name for i in java_intel.imports)

    cpp_code = b"""
#include <vector>
#include "header.h"

class Optimizer {
public:
    int optimize(int x) { return x + 1; }
};
"""
    cpp_intel = analyze_code_content(cpp_code, "C++")
    assert cpp_intel.parse_error is None
    assert any(s.name == "Optimizer" for s in cpp_intel.symbols)
    assert any(s.name == "optimize" for s in cpp_intel.symbols)
    assert any(i.module_name == "vector" for i in cpp_intel.imports)


def test_tree_sitter_malformed_syntax_graceful_handling() -> None:
    # Unterminated block and garbage syntax should not raise an exception
    bad_code = b"def broken_function( incomplete syntax {{{(((\n"
    intel = analyze_code_content(bad_code, "Python")
    assert intel.language == "Python"
    # Parser should produce an AST with error nodes without throwing Python exceptions
    assert isinstance(intel.symbols, list)


# -----------------------------------------------------------------------------
# Unit Tests: Dependency Manifest Intelligence
# -----------------------------------------------------------------------------


def test_package_json_parsing() -> None:
    content = """{
        "name": "orchestrix-frontend",
        "dependencies": {
            "react": "^19.0.0",
            "next": "16.4.6"
        },
        "devDependencies": {
            "typescript": "^5.0.0",
            "vitest": "^3.0.0"
        }
    }"""
    deps = parse_package_json(content)
    assert len(deps) == 4
    react_dep = next(d for d in deps if d.name == "react")
    assert react_dep.version_spec == "^19.0.0"
    assert react_dep.dependency_type == "package_dependency"
    assert react_dep.package_manager == "npm"

    ts_dep = next(d for d in deps if d.name == "typescript")
    assert ts_dep.dependency_type == "dev_dependency"


def test_pyproject_toml_parsing() -> None:
    content = """
    [project]
    name = "backend"
    dependencies = [
        "fastapi>=0.115.0",
        "pydantic~=2.10.0",
    ]

    [dependency-groups]
    dev = [
        "pytest>=8.0.0",
    ]
    """
    deps = parse_pyproject_toml(content)
    assert len(deps) == 3
    fastapi_dep = next(d for d in deps if d.name == "fastapi")
    assert fastapi_dep.version_spec == ">=0.115.0"
    assert fastapi_dep.package_manager == "pip"

    pytest_dep = next(d for d in deps if d.name == "pytest")
    assert pytest_dep.dependency_type == "dev_dependency"


def test_requirements_and_cargo_and_go_parsing() -> None:
    reqs = "httpx>=0.28.0\n# comment\nsqlalchemy==2.0.36\n"
    deps = parse_requirements_txt(reqs)
    assert len(deps) == 2
    assert deps[0].name == "httpx"
    assert deps[1].name == "sqlalchemy"

    cargo = '[dependencies]\ntokio = "1.0"\nserde = { version = "1.0" }\n'
    c_deps = parse_cargo_toml(cargo)
    assert len(c_deps) == 2
    assert any(d.name == "tokio" for d in c_deps)

    go_mod = "module example.com/app\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n)\n"
    g_deps = parse_go_mod(go_mod)
    assert len(g_deps) == 1
    assert g_deps[0].name == "github.com/gin-gonic/gin"
    assert g_deps[0].version_spec == "v1.9.1"


# -----------------------------------------------------------------------------
# Integration Tests: Indexing Engine & API Lifecycle
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def indexing_setup() -> AsyncGenerator[
    tuple[
        AsyncSession, async_sessionmaker[AsyncSession], User, Workspace, Repository, GitHubAccount
    ],
    None,
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db_session:
        # 1. Create User
        user = User(
            email=f"arch-{uuid.uuid4().hex[:6]}@orchestrix.ai",
            full_name="Lead Architect",
            email_verified=True,
        )
        db_session.add(user)
        await db_session.flush()

        # 2. Create Workspace
        ws = Workspace(
            name="Architecture Workspace",
            slug=f"arch-ws-{uuid.uuid4().hex[:6]}",
        )
        db_session.add(ws)
        await db_session.flush()

        # 3. Create WorkspaceMembership (OWNER)
        member = WorkspaceMembership(
            workspace_id=ws.id,
            user_id=user.id,
            role=WorkspaceRole.OWNER,
        )
        db_session.add(member)

        # 4. Create GitHubInstallation
        inst = GitHubInstallation(
            workspace_id=ws.id,
            installation_id=int(uuid.uuid4().int % 10000000),
            account_login="octo-architect",
            account_id=987654,
            account_type="User",
        )
        db_session.add(inst)
        await db_session.flush()

        # 5. Create Repository
        repo = Repository(
            workspace_id=ws.id,
            installation_id=inst.id,
            github_repository_id=888999,
            name="orchestrix-core",
            full_name="octo-architect/orchestrix-core",
            owner_login="octo-architect",
            description="Core autonomous framework",
            default_branch="main",
            html_url="https://github.com/octo-architect/orchestrix-core",
            visibility="private",
            language="Python",
            is_active=True,
        )
        db_session.add(repo)

        # 6. Create GitHubAccount with encrypted token
        token = "gho_test_token_secret_123"
        enc_token = encrypt_token(token)
        gh_acc = GitHubAccount(
            user_id=user.id,
            github_user_id=987654,
            github_login="octo-architect",
            encrypted_access_token=enc_token,
            token_type="bearer",
            scope="repo,read:user",
        )
        db_session.add(gh_acc)

        await db_session.commit()
        await db_session.refresh(user)
        await db_session.refresh(ws)
        await db_session.refresh(repo)
        await db_session.refresh(gh_acc)

        yield db_session, session_factory, user, ws, repo, gh_acc


@pytest.mark.asyncio
async def test_indexing_job_creation_and_deduplication(
    indexing_setup: tuple[
        AsyncSession, async_sessionmaker[AsyncSession], User, Workspace, Repository, GitHubAccount
    ],
) -> None:
    db_session, _sf, user, ws, repo, _gh_acc = indexing_setup

    with patch(
        "app.services.indexing_service.fetch_latest_commit_sha",
        new_callable=AsyncMock,
    ) as mock_sha:
        mock_sha.return_value = "commit_sha_1234567890abcdef"

        # 1. Start initial indexing job
        job1, created1 = await create_indexing_job(
            db=db_session,
            workspace_id=ws.id,
            repository_id=repo.id,
            user_id=user.id,
        )
        assert created1 is True
        assert job1.status == IndexingJobStatus.PENDING
        assert job1.commit_sha == "commit_sha_1234567890abcdef"

        # 2. Trigger again while job1 is active -> deduplication must return job1
        job2, created2 = await create_indexing_job(
            db=db_session,
            workspace_id=ws.id,
            repository_id=repo.id,
            user_id=user.id,
        )
        assert created2 is False
        assert job2.id == job1.id


@pytest.mark.asyncio
async def test_indexing_job_cancellation(
    indexing_setup: tuple[
        AsyncSession, async_sessionmaker[AsyncSession], User, Workspace, Repository, GitHubAccount
    ],
) -> None:
    db_session, _sf, user, ws, repo, _gh_acc = indexing_setup

    with patch(
        "app.services.indexing_service.fetch_latest_commit_sha",
        new_callable=AsyncMock,
    ) as mock_sha:
        mock_sha.return_value = "commit_sha_to_cancel"

        job, _ = await create_indexing_job(
            db=db_session,
            workspace_id=ws.id,
            repository_id=repo.id,
            user_id=user.id,
        )

        cancelled_job = await cancel_indexing_job(
            db=db_session,
            job_id=job.id,
            workspace_id=ws.id,
        )
        assert cancelled_job.status == IndexingJobStatus.CANCELLED
        assert "cancelled" in (cancelled_job.error_message or "").lower()


@pytest.mark.asyncio
async def test_full_background_indexing_execution(
    indexing_setup: tuple[
        AsyncSession, async_sessionmaker[AsyncSession], User, Workspace, Repository, GitHubAccount
    ],
) -> None:
    db_session, session_factory, user, ws, repo, _gh_acc = indexing_setup
    commit_sha = "sha_full_execution_test"

    # Mock git tree with python file and package.json manifest
    mock_tree = [
        {"path": "app/main.py", "type": "blob", "sha": "blob_py_1", "size": 150},
        {"path": "package.json", "type": "blob", "sha": "blob_json_2", "size": 95},
        {"path": "node_modules/bad.js", "type": "blob", "sha": "blob_skip", "size": 500},
    ]

    py_content = b"import sys\nclass Server:\n    def start(self):\n        pass\n"
    json_content = b'{"dependencies": {"react": "^19.0.0"}}'

    async def mock_blob_fetch(access_token: str, owner: str, repo: str, blob_sha: str) -> bytes:
        if blob_sha == "blob_py_1":
            return py_content
        if blob_sha == "blob_json_2":
            return json_content
        return b""

    with (
        patch(
            "app.services.indexing_service.fetch_repository_tree", new_callable=AsyncMock
        ) as mock_tree_fetch,
        patch("app.services.indexing_service.fetch_blob_content", side_effect=mock_blob_fetch),
        patch(
            "app.services.indexing_service.get_async_session_factory", return_value=session_factory
        ),
    ):
        mock_tree_fetch.return_value = mock_tree

        # Create job
        job = IndexingJob(
            workspace_id=ws.id,
            repository_id=repo.id,
            commit_sha=commit_sha,
            branch="main",
            status=IndexingJobStatus.PENDING,
        )
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        # Execute background runner directly
        await _execute_indexing_job_background(
            job_id=job.id,
            workspace_id=ws.id,
            repository_id=repo.id,
            owner=repo.owner_login,
            repo_name=repo.name,
            default_branch=repo.default_branch,
            commit_sha=commit_sha,
            access_token="test_token",
        )

        # Verify job completed successfully
        await db_session.refresh(job)
        assert job.status == IndexingJobStatus.COMPLETED
        assert job.progress_percent == 100
        assert job.files_count == 2
        assert job.symbols_count >= 2  # Server class, start method
        assert job.dependencies_count >= 2  # sys import + react dependency

        # Verify snapshot
        snapshot = await get_latest_repository_snapshot(db_session, repo.id, ws.id)
        assert snapshot is not None
        assert snapshot.commit_sha == commit_sha
        assert snapshot.total_files == 2
        assert "Python" in (snapshot.languages_summary or {})

        # Verify files list
        files, total_f = await list_repository_files(db_session, repo.id, ws.id)
        assert total_f == 2
        file_paths = [f.path for f in files]
        assert "app/main.py" in file_paths
        assert "package.json" in file_paths

        # Verify symbols
        symbols, total_s = await list_repository_symbols(db_session, repo.id, ws.id)
        assert total_s >= 2
        sym_names = [s.name for s in symbols]
        assert "Server" in sym_names
        assert "start" in sym_names

        # Verify dependencies
        deps, total_d = await list_repository_dependencies(db_session, repo.id, ws.id)
        assert total_d >= 2
        dep_names = [d.name for d in deps]
        assert "react" in dep_names
        assert "sys" in dep_names


@pytest.mark.asyncio
async def test_indexing_api_endpoints_and_tenant_isolation(
    indexing_setup: tuple[
        AsyncSession, async_sessionmaker[AsyncSession], User, Workspace, Repository, GitHubAccount
    ],
) -> None:
    db_session, _sf, user, ws, repo, _gh_acc = indexing_setup

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    csrf_token = generate_csrf_token()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={
            "X-CSRF-Token": csrf_token,
            "Origin": "http://localhost:3000",
        },
        cookies={"orchestrix_session": "test_session", "orchestrix_csrf": csrf_token},
    ) as client:
        # Override auth dependency
        from app.api.deps import get_current_user, get_current_user_optional

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_current_user_optional] = lambda: user

        with patch(
            "app.services.indexing_service.fetch_latest_commit_sha",
            new_callable=AsyncMock,
        ) as mock_sha:
            mock_sha.return_value = "sha_api_test_999"

            # 1. Start indexing via API (POST /repositories/{id}/indexing/start)
            res_start = await client.post(
                f"/api/v1/repositories/{repo.id}/indexing/start?workspace_id={ws.id}",
            )
            assert res_start.status_code == 202
            data_start = res_start.json()
            assert data_start["repository_id"] == str(repo.id)
            assert data_start["commit_sha"] == "sha_api_test_999"
            job_id = data_start["id"]

            # 2. Get indexing job details
            res_job = await client.get(
                f"/api/v1/repositories/{repo.id}/indexing/jobs/{job_id}?workspace_id={ws.id}",
            )
            assert res_job.status_code == 200
            assert res_job.json()["id"] == job_id

            # 3. List jobs
            res_list = await client.get(
                f"/api/v1/repositories/{repo.id}/indexing/jobs?workspace_id={ws.id}",
            )
            assert res_list.status_code == 200
            assert res_list.json()["total"] >= 1

            # 4. Get intelligence overview
            res_intel = await client.get(
                f"/api/v1/repositories/{repo.id}/intelligence?workspace_id={ws.id}",
            )
            assert res_intel.status_code == 200
            assert res_intel.json()["repository_id"] == str(repo.id)

            # 5. Cross-tenant isolation check: Attempting access with unrelated workspace ID returns 403 Forbidden
            other_ws_id = uuid.uuid4()
            res_forbidden = await client.get(
                f"/api/v1/repositories/{repo.id}/intelligence?workspace_id={other_ws_id}",
            )
            assert res_forbidden.status_code == 403

    app.dependency_overrides.clear()
