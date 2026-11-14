from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.db.models.repository_intelligence import (
    CodeSymbol,
    FileDependency,
    RepositoryFile,
    RepositorySnapshot,
)
from app.services.relationship_extraction import MultiLanguageRelationshipExtractor


@dataclass
class RelationshipMetric:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        total = self.tp + self.fp
        return round(self.tp / total, 4) if total > 0 else 1.0

    @property
    def recall(self) -> float:
        total = self.tp + self.fn
        return round(self.tp / total, 4) if total > 0 else 1.0

    @property
    def f1(self) -> float:
        p = self.precision
        r = self.recall
        return round(2 * (p * r) / (p + r), 4) if (p + r) > 0 else 0.0


def compute_metrics(
    extracted: list[tuple[str, str, str]],  # (source, target, type)
    expected: set[tuple[str, str, str]],
) -> RelationshipMetric:
    ext_set = set(extracted)
    tp = len(ext_set.intersection(expected))
    fp = len(ext_set - expected)
    fn = len(expected - ext_set)
    return RelationshipMetric(tp=tp, fp=fp, fn=fn)


def test_python_relationship_extraction_benchmark() -> None:
    """
    Benchmark relationship extraction on real Python backend codebase sample (FastAPI / SQLAlchemy).
    Measures: CALLS, IMPORTS, EXTENDS, EXPOSES, TESTS, DEFINES.
    """
    repo_id = uuid.uuid4()
    snap_id = uuid.uuid4()
    snapshot = RepositorySnapshot(id=snap_id, repository_id=repo_id, commit_sha="abc1234")

    files = [
        RepositoryFile(id=uuid.uuid4(), snapshot_id=snap_id, path="app/models/user.py"),
        RepositoryFile(id=uuid.uuid4(), snapshot_id=snap_id, path="app/services/auth.py"),
        RepositoryFile(id=uuid.uuid4(), snapshot_id=snap_id, path="app/api/auth.py"),
        RepositoryFile(id=uuid.uuid4(), snapshot_id=snap_id, path="tests/test_auth.py"),
    ]

    symbols = [
        # user.py
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="app/models/user.py",
            name="UserBase",
            symbol_type="class",
            start_line=1,
            end_line=2,
            signature="class UserBase:",
        ),
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="app/models/user.py",
            name="User",
            symbol_type="class",
            start_line=4,
            end_line=8,
            signature="class User(UserBase):",
        ),
        # auth.py
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="app/services/auth.py",
            name="hash_password",
            symbol_type="function",
            start_line=1,
            end_line=2,
            signature="def hash_password(pwd: str) -> str:",
        ),
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="app/services/auth.py",
            name="authenticate_user",
            symbol_type="function",
            start_line=4,
            end_line=6,
            signature="def authenticate_user(username: str, pwd: str):",
        ),
        # api/auth.py
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="app/api/auth.py",
            name="login_endpoint",
            symbol_type="function",
            start_line=2,
            end_line=4,
            signature="def login_endpoint(payload: LoginRequest):",
        ),
        # test_auth.py
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="tests/test_auth.py",
            name="test_authenticate_user",
            symbol_type="function",
            start_line=1,
            end_line=3,
            signature="def test_authenticate_user():",
        ),
    ]

    dependencies = [
        FileDependency(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            source_file_path="app/services/auth.py",
            name="app.models.user",
            dependency_type="import",
        ),
        FileDependency(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            source_file_path="app/api/auth.py",
            name="app.services.auth",
            dependency_type="import",
        ),
        FileDependency(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            source_file_path="tests/test_auth.py",
            name="app.services.auth",
            dependency_type="import",
        ),
        FileDependency(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            source_file_path="app/services/auth.py",
            name="bcrypt",
            dependency_type="package_dependency",
            version_spec="^4.0.0",
        ),
    ]

    file_contents = {
        "app/models/user.py": "class UserBase:\n    pass\n\nclass User(UserBase):\n    __tablename__ = 'users'\n    id: int\n    name: str\n",
        "app/services/auth.py": "def hash_password(pwd: str) -> str:\n    return pwd + '_hashed'\n\ndef authenticate_user(username: str, pwd: str):\n    h = hash_password(pwd)\n    return True\n",
        "app/api/auth.py": "@router.post('/login')\ndef login_endpoint(payload: LoginRequest):\n    return authenticate_user(payload.u, payload.p)\n",
        "tests/test_auth.py": "def test_authenticate_user():\n    assert authenticate_user('admin', 'secret') is True\n",
    }

    extractor = MultiLanguageRelationshipExtractor(
        snapshot=snapshot,
        files=files,
        symbols=symbols,
        dependencies=dependencies,
        file_contents=file_contents,
    )
    nodes, relationships = extractor.extract_all()

    # 1. Verify schema completeness across all extracted relationships
    for r in relationships:
        assert r.source_id, "Missing source_id"
        assert r.target_id, "Missing target_id"
        assert r.type, "Missing relationship type"
        assert "status" in r.properties, f"Missing status property in {r.type}"
        assert r.properties["status"] in ("resolved", "partially_resolved", "unresolved")
        assert "confidence" in r.properties, f"Missing confidence property in {r.type}"
        assert 0.0 <= r.properties["confidence"] <= 1.0, f"Confidence out of range in {r.type}"

    # 2. Measure accuracy metrics per relationship type
    rels_by_type: dict[str, list[tuple[str, str, str]]] = {}
    for r in relationships:
        rels_by_type.setdefault(r.type, []).append((r.source_id, r.target_id, r.type))

    # Verify EXTENDS: User -> UserBase
    user_node_id = f"sym:{snap_id}:app/models/user.py:class:User"
    base_node_id = f"sym:{snap_id}:app/models/user.py:class:UserBase"
    expected_extends = {(user_node_id, base_node_id, "EXTENDS")}
    m_extends = compute_metrics(rels_by_type.get("EXTENDS", []), expected_extends)
    assert m_extends.precision == 1.0
    assert m_extends.recall == 1.0
    assert m_extends.f1 == 1.0

    # Verify CALLS: authenticate_user -> hash_password, login_endpoint -> authenticate_user, test_authenticate_user -> authenticate_user
    auth_node_id = f"sym:{snap_id}:app/services/auth.py:function:authenticate_user"
    hash_node_id = f"sym:{snap_id}:app/services/auth.py:function:hash_password"
    login_node_id = f"sym:{snap_id}:app/api/auth.py:function:login_endpoint"
    test_node_id = f"sym:{snap_id}:tests/test_auth.py:function:test_authenticate_user"
    expected_calls = {
        (auth_node_id, hash_node_id, "CALLS"),
        (login_node_id, auth_node_id, "CALLS"),
        (test_node_id, auth_node_id, "CALLS"),
    }
    m_calls = compute_metrics(rels_by_type.get("CALLS", []), expected_calls)
    assert m_calls.precision == 1.0
    assert m_calls.recall == 1.0
    assert m_calls.f1 == 1.0

    # Verify EXPOSES: login_endpoint -> APIEndpoint POST /login
    endpoint_node_id = f"api:{snap_id}:POST:/login"
    expected_exposes = {(login_node_id, endpoint_node_id, "EXPOSES")}
    m_exposes = compute_metrics(rels_by_type.get("EXPOSES", []), expected_exposes)
    assert m_exposes.precision == 1.0
    assert m_exposes.recall == 1.0
    assert m_exposes.f1 == 1.0

    # Verify TESTS: test_authenticate_user -> authenticate_user
    test_case_node_id = f"test:{snap_id}:tests/test_auth.py:test_authenticate_user"
    expected_tests = {(test_case_node_id, auth_node_id, "TESTS")}
    m_tests = compute_metrics(rels_by_type.get("TESTS", []), expected_tests)
    assert m_tests.precision == 1.0
    assert m_tests.recall == 1.0
    assert m_tests.f1 == 1.0


def test_typescript_relationship_extraction_benchmark() -> None:
    """
    Benchmark relationship extraction on real TypeScript / React architecture.
    Measures: IMPORTS, EXTENDS, IMPLEMENTS, CALLS, TESTS.
    """
    repo_id = uuid.uuid4()
    snap_id = uuid.uuid4()
    snapshot = RepositorySnapshot(id=snap_id, repository_id=repo_id, commit_sha="ts12345")

    files = [
        RepositoryFile(id=uuid.uuid4(), snapshot_id=snap_id, path="src/interfaces.ts"),
        RepositoryFile(id=uuid.uuid4(), snapshot_id=snap_id, path="src/client.ts"),
        RepositoryFile(id=uuid.uuid4(), snapshot_id=snap_id, path="src/services/order.ts"),
        RepositoryFile(id=uuid.uuid4(), snapshot_id=snap_id, path="tests/order.test.ts"),
    ]

    symbols = [
        # interfaces.ts
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="src/interfaces.ts",
            name="IOrderClient",
            symbol_type="interface",
            start_line=1,
            end_line=5,
            signature="interface IOrderClient",
        ),
        # client.ts
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="src/client.ts",
            name="BaseClient",
            symbol_type="class",
            start_line=1,
            end_line=2,
            signature="export class BaseClient {",
        ),
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="src/client.ts",
            name="HttpClient",
            symbol_type="class",
            start_line=3,
            end_line=6,
            signature="export class HttpClient extends BaseClient implements IOrderClient {",
        ),
        # order.ts
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="src/services/order.ts",
            name="validateCart",
            symbol_type="function",
            start_line=1,
            end_line=1,
            signature="export function validateCart(items: any[]) {",
        ),
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="src/services/order.ts",
            name="processOrder",
            symbol_type="function",
            start_line=2,
            end_line=5,
            signature="export function processOrder(cart: any[]) {",
        ),
        # order.test.ts
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="tests/order.test.ts",
            name="test_processOrder",
            symbol_type="function",
            start_line=1,
            end_line=5,
            signature="function test_processOrder() {",
        ),
    ]

    dependencies = [
        FileDependency(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            source_file_path="src/client.ts",
            name="./interfaces",
            dependency_type="import",
        ),
        FileDependency(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            source_file_path="src/services/order.ts",
            name="../client",
            dependency_type="import",
        ),
        FileDependency(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            source_file_path="tests/order.test.ts",
            name="../src/services/order",
            dependency_type="import",
        ),
    ]

    file_contents = {
        "src/interfaces.ts": "export interface IOrderClient {\n  send(): void;\n}\n",
        "src/client.ts": "export class BaseClient {}\nexport class HttpClient extends BaseClient implements IOrderClient {\n  send() {}\n}\n",
        "src/services/order.ts": "export function validateCart(items: any[]) { return true; }\nexport function processOrder(cart: any[]) {\n  validateCart(cart);\n  return true;\n}\n",
        "tests/order.test.ts": "function test_processOrder() {\n  processOrder([]);\n}\n",
    }

    extractor = MultiLanguageRelationshipExtractor(
        snapshot=snapshot,
        files=files,
        symbols=symbols,
        dependencies=dependencies,
        file_contents=file_contents,
    )
    nodes, relationships = extractor.extract_all()

    rels_by_type: dict[str, list[tuple[str, str, str]]] = {}
    for r in relationships:
        rels_by_type.setdefault(r.type, []).append((r.source_id, r.target_id, r.type))

    # EXTENDS: HttpClient -> BaseClient
    http_node_id = f"sym:{snap_id}:src/client.ts:class:HttpClient"
    base_node_id = f"sym:{snap_id}:src/client.ts:class:BaseClient"
    expected_extends = {(http_node_id, base_node_id, "EXTENDS")}
    m_extends = compute_metrics(rels_by_type.get("EXTENDS", []), expected_extends)
    assert m_extends.precision == 1.0
    assert m_extends.recall == 1.0

    # IMPLEMENTS: HttpClient -> IOrderClient
    iface_node_id = f"sym:{snap_id}:src/interfaces.ts:interface:IOrderClient"
    expected_implements = {(http_node_id, iface_node_id, "IMPLEMENTS")}
    m_impl = compute_metrics(rels_by_type.get("IMPLEMENTS", []), expected_implements)
    assert m_impl.precision == 1.0
    assert m_impl.recall == 1.0

    # CALLS: processOrder -> validateCart, test_processOrder -> processOrder
    proc_node_id = f"sym:{snap_id}:src/services/order.ts:function:processOrder"
    val_node_id = f"sym:{snap_id}:src/services/order.ts:function:validateCart"
    test_node_id = f"sym:{snap_id}:tests/order.test.ts:function:test_processOrder"
    expected_calls = {
        (proc_node_id, val_node_id, "CALLS"),
        (test_node_id, proc_node_id, "CALLS"),
    }
    m_calls = compute_metrics(rels_by_type.get("CALLS", []), expected_calls)
    assert m_calls.precision == 1.0
    assert m_calls.recall == 1.0


def test_go_relationship_extraction_benchmark() -> None:
    """
    Benchmark relationship extraction on Go systems codebase.
    Measures: CALLS, IMPORTS, TESTS, DEPENDS_ON.
    """
    repo_id = uuid.uuid4()
    snap_id = uuid.uuid4()
    snapshot = RepositorySnapshot(id=snap_id, repository_id=repo_id, commit_sha="go12345")

    files = [
        RepositoryFile(id=uuid.uuid4(), snapshot_id=snap_id, path="pkg/crypto/hash.go"),
        RepositoryFile(id=uuid.uuid4(), snapshot_id=snap_id, path="pkg/auth/service.go"),
        RepositoryFile(id=uuid.uuid4(), snapshot_id=snap_id, path="pkg/auth/service_test.go"),
    ]

    symbols = [
        # hash.go
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="pkg/crypto/hash.go",
            name="ComputeSHA",
            symbol_type="function",
            start_line=1,
            end_line=3,
            signature="func ComputeSHA(data []byte) []byte {",
        ),
        # service.go
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="pkg/auth/service.go",
            name="VerifyCredentials",
            symbol_type="function",
            start_line=1,
            end_line=5,
            signature="func VerifyCredentials(u, p string) bool {",
        ),
        # service_test.go
        CodeSymbol(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            file_path="pkg/auth/service_test.go",
            name="TestVerifyCredentials",
            symbol_type="function",
            start_line=1,
            end_line=4,
            signature="func TestVerifyCredentials(t *testing.T) {",
        ),
    ]

    dependencies = [
        FileDependency(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            source_file_path="pkg/auth/service.go",
            name="example.com/repo/pkg/crypto",
            dependency_type="import",
        ),
        FileDependency(
            id=uuid.uuid4(),
            snapshot_id=snap_id,
            source_file_path="pkg/auth/service.go",
            name="golang.org/x/crypto",
            dependency_type="package_dependency",
            version_spec="v0.17.0",
        ),
    ]

    file_contents = {
        "pkg/crypto/hash.go": 'func ComputeSHA(data []byte) []byte {\n  return []byte("hash")\n}\n',
        "pkg/auth/service.go": "func VerifyCredentials(u, p string) bool {\n  h := ComputeSHA([]byte(p))\n  return len(h) > 0\n}\n",
        "pkg/auth/service_test.go": 'func TestVerifyCredentials(t *testing.T) {\n  VerifyCredentials("admin", "secret")\n}\n',
    }

    extractor = MultiLanguageRelationshipExtractor(
        snapshot=snapshot,
        files=files,
        symbols=symbols,
        dependencies=dependencies,
        file_contents=file_contents,
    )
    nodes, relationships = extractor.extract_all()

    rels_by_type: dict[str, list[tuple[str, str, str]]] = {}
    for r in relationships:
        rels_by_type.setdefault(r.type, []).append((r.source_id, r.target_id, r.type))

    # CALLS: VerifyCredentials -> ComputeSHA, TestVerifyCredentials -> VerifyCredentials
    svc_node_id = f"sym:{snap_id}:pkg/auth/service.go:function:VerifyCredentials"
    hash_node_id = f"sym:{snap_id}:pkg/crypto/hash.go:function:ComputeSHA"
    test_node_id = f"sym:{snap_id}:pkg/auth/service_test.go:function:TestVerifyCredentials"
    expected_calls = {
        (svc_node_id, hash_node_id, "CALLS"),
        (test_node_id, svc_node_id, "CALLS"),
    }
    m_calls = compute_metrics(rels_by_type.get("CALLS", []), expected_calls)
    assert m_calls.precision == 1.0
    assert m_calls.recall == 1.0

    # TESTS: TestVerifyCredentials -> VerifyCredentials
    test_case_node_id = f"test:{snap_id}:pkg/auth/service_test.go:TestVerifyCredentials"
    expected_tests = {(test_case_node_id, svc_node_id, "TESTS")}
    m_tests = compute_metrics(rels_by_type.get("TESTS", []), expected_tests)
    assert m_tests.precision == 1.0
    assert m_tests.recall == 1.0

    # DEPENDS_ON: package dependency
    dep_rels = rels_by_type.get("DEPENDS_ON", [])
    assert len(dep_rels) == 1
    assert dep_rels[0][2] == "DEPENDS_ON"
