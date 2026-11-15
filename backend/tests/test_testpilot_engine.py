from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.github_installation import GitHubInstallation
from app.db.models.repository import Repository
from app.db.models.testpilot import (
    TestPilotCase,
    TestPilotExecution,
    TestPilotSuite,
    TestPilotTestType,
    TestResultOutcome,
    TestSuiteStatus,
)
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.services.devpilot.llm_provider import (
    BaseLLMProvider,
    LLMCompletionResponse,
    LLMProviderManager,
)
from app.services.impactmind.test_runner import (
    ALLOWED_TEST_EXECUTABLES,
    ControlledTestRunner,
    TestExecutionResult,
)
from app.services.testpilot.coverage import CoverageAnalyzer
from app.services.testpilot.detector import FrameworkDetector
from app.services.testpilot.diagnoser import FailureDiagnoser
from app.services.testpilot.exceptions import (
    TestApprovalRequiredError,
    TestExecutionSecurityError,
)
from app.services.testpilot.generator import TestGenerator
from app.services.testpilot.impact_selector import ImpactTestSelector
from app.services.testpilot.runner import TestPilotRunner


class MockLLM(BaseLLMProvider):
    """Deterministic mock LLM provider for TestPilot testing."""

    def __init__(self, response_text: str | None = None) -> None:
        self.response_text = (
            response_text
            or '{"cases": [{"name": "test_add", "description": "test add", "test_type": "unit", "target_symbol": "add", "code": "def test_add():\\n    assert add(1, 2) == 3\\n", "is_edge_case": false, "relevance_explanation": "Validates arithmetic"}]}'
        )
        self.last_prompt = ""

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def default_model(self) -> str:
        return "mock-deterministic"

    def is_available(self) -> bool:
        return True

    async def generate_completion(
        self,
        prompt: str,
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout_seconds: float = 45.0,
    ) -> LLMCompletionResponse:
        self.last_prompt = prompt
        return LLMCompletionResponse(
            content=self.response_text,
            provider_name="mock",
            model_name="mock-model",
            prompt_tokens=10,
            completion_tokens=20,
            duration_ms=5,
        )


@pytest.fixture
async def test_session() -> AsyncGenerator[AsyncSession, None]:
    """Isolated SQLite in-memory async database session with PRAGMA foreign_keys = ON."""
    from sqlalchemy import event

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def seed_data(test_session: AsyncSession) -> dict[str, Any]:
    """Seed base user, workspace, and repository."""
    user = User(email="tester@orchestrix.ai", full_name="Test Pilot Engineer")
    ws = Workspace(name="TestPilot Workspace", slug="testpilot-ws")
    test_session.add_all([user, ws])
    await test_session.commit()

    installation = GitHubInstallation(
        workspace_id=ws.id,
        installation_id=987654321,
        account_login="orchestrix",
        account_type="Organization",
        account_id=12345,
    )
    test_session.add(installation)
    await test_session.commit()

    repo = Repository(
        workspace_id=ws.id,
        installation_id=installation.id,
        name="test-repo",
        full_name="orchestrix/test-repo",
        owner_login="orchestrix",
        html_url="https://github.com/orchestrix/test-repo",
        github_repository_id=9901,
        default_branch="main",
    )
    test_session.add(repo)
    await test_session.commit()

    return {"user": user, "workspace": ws, "installation": installation, "repository": repo}


# ==============================================================================
# 1. FRAMEWORK AND CONVENTION DETECTOR TESTS
# ==============================================================================


def test_detect_python_pytest_framework() -> None:
    detector = FrameworkDetector()
    files = ["pyproject.toml", "src/calculator.py", "tests/test_calculator.py"]
    contents = {"pyproject.toml": "[tool.pytest.ini_options]\nminversion = '8.0'"}
    info = detector.detect_from_files(files, file_contents=contents)

    assert info.language == "python"
    assert info.framework == "pytest"
    assert info.config_file == "pyproject.toml"
    assert info.test_directory == "tests"
    assert info.naming_convention == "test_*.py"
    assert info.confidence >= 0.85


def test_detect_javascript_vitest_framework() -> None:
    detector = FrameworkDetector()
    files = ["package.json", "vitest.config.ts", "src/auth.ts", "src/__tests__/auth.test.ts"]
    contents = {"package.json": '{"name": "demo", "scripts": {"test": "vitest"}}'}
    info = detector.detect_from_files(files, file_contents=contents)

    assert info.language == "typescript"
    assert info.framework == "vitest"
    assert "vitest.config.ts" in (info.config_file or "")
    assert info.test_directory == "src/__tests__"
    assert info.naming_convention == "*.test.ts"
    assert info.confidence >= 0.90


def test_detect_javascript_jest_framework() -> None:
    detector = FrameworkDetector()
    files = ["package.json", "jest.config.js", "tests/app.spec.js"]
    contents = {"package.json": '{"name": "demo", "devDependencies": {"jest": "^29.0"}}'}
    info = detector.detect_from_files(files, file_contents=contents)

    assert info.language == "javascript"
    assert info.framework == "jest"
    assert info.config_file == "jest.config.js"
    assert info.confidence >= 0.90


def test_detect_unsupported_framework_handling() -> None:
    detector = FrameworkDetector()
    files = ["main.c", "Makefile", "README.md"]
    info = detector.detect_from_files(files)

    assert info.framework == "unsupported"
    assert info.is_available is False
    assert info.confidence == 0.0
    assert len(info.missing_requirements) > 0


# ==============================================================================
# 2. TEST GENERATION AND QUALITY VALIDATION TESTS
# ==============================================================================


def test_reject_tautological_and_placeholder_tests() -> None:
    gen = TestGenerator()

    # Reject assert True
    is_valid, reason = gen.validate_test_code_quality("def test_dummy():\n    assert True\n")
    assert not is_valid
    assert "Tautological" in (reason or "")

    # Reject assert 1 == 1
    is_valid, reason = gen.validate_test_code_quality("def test_dummy():\n    assert 1 == 1\n")
    assert not is_valid
    assert "Tautological" in (reason or "")

    # Reject expect(true).toBe(true)
    is_valid, reason = gen.validate_test_code_quality(
        "it('works', () => {\n  expect(true).toBe(true);\n});"
    )
    assert not is_valid
    assert "Tautological" in (reason or "")

    # Reject TODO placeholder
    is_valid, reason = gen.validate_test_code_quality(
        "def test_incomplete():\n    # TODO implement this\n"
    )
    assert not is_valid

    # Accept meaningful assertion
    is_valid, reason = gen.validate_test_code_quality(
        "def test_valid():\n    assert calculate(2, 3) == 5\n"
    )
    assert is_valid
    assert reason is None


@pytest.mark.asyncio
async def test_generate_suite_with_approval_boundary(
    test_session: AsyncSession, seed_data: dict[str, Any]
) -> None:
    ws = seed_data["workspace"]
    repo = seed_data["repository"]

    mock_llm = MockLLM()
    mgr = LLMProviderManager(force_mock=True)
    mgr.providers["mock"] = mock_llm
    generator = TestGenerator(llm_manager=mgr)

    suite_dto = await generator.generate_suite(
        framework="pytest",
        target_files=["app/calculator.py"],
        source_context="def add(a: int, b: int) -> int:\n    return a + b\n",
        test_type=TestPilotTestType.UNIT,
    )

    assert suite_dto.framework == "pytest"
    assert suite_dto.requires_approval is True
    assert len(suite_dto.cases) >= 1
    assert "assert add" in suite_dto.cases[0].code

    # Persist suite to DB
    persisted_suite = await generator.persist_suite(
        db=test_session,
        workspace_id=ws.id,
        repository_id=repo.id,
        suite_dto=suite_dto,
    )

    assert persisted_suite.status == TestSuiteStatus.GENERATED
    assert persisted_suite.approved_at is None
    assert persisted_suite.approved_by is None
    assert len(persisted_suite.cases) >= 1


# ==============================================================================
# 3. CONTROLLED EXECUTION & APPROVAL ENFORCEMENT TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_unapproved_suite_execution_rejected(
    test_session: AsyncSession, seed_data: dict[str, Any]
) -> None:
    ws = seed_data["workspace"]
    repo = seed_data["repository"]

    suite = TestPilotSuite(
        workspace_id=ws.id,
        repository_id=repo.id,
        framework="pytest",
        test_type=TestPilotTestType.UNIT,
        status=TestSuiteStatus.GENERATED,  # UNAPPROVED!
    )
    test_session.add(suite)
    await test_session.commit()

    runner = TestPilotRunner()
    with pytest.raises(TestApprovalRequiredError) as exc_info:
        await runner.execute_suite(
            db=test_session,
            workspace_id=ws.id,
            repository_id=repo.id,
            suite_id=suite.id,
        )
    assert "Explicit human approval is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_command_allowlist_and_injection_prevention(
    test_session: AsyncSession, seed_data: dict[str, Any]
) -> None:
    ws = seed_data["workspace"]
    repo = seed_data["repository"]

    suite = TestPilotSuite(
        workspace_id=ws.id,
        repository_id=repo.id,
        framework="pytest",
        status=TestSuiteStatus.APPROVED,  # Approved
    )
    test_session.add(suite)
    await test_session.commit()

    runner = TestPilotRunner()

    # Reject dangerous shell chaining
    with pytest.raises(TestExecutionSecurityError):
        await runner.execute_suite(
            db=test_session,
            workspace_id=ws.id,
            repository_id=repo.id,
            suite_id=suite.id,
            custom_command="pytest; rm -rf /",
        )

    # Reject unauthorized binary
    with pytest.raises(TestExecutionSecurityError):
        await runner.execute_suite(
            db=test_session,
            workspace_id=ws.id,
            repository_id=repo.id,
            suite_id=suite.id,
            custom_command="bash malicious.sh",
        )

    # Reject dangerous config override flags
    with pytest.raises(TestExecutionSecurityError):
        await runner.execute_suite(
            db=test_session,
            workspace_id=ws.id,
            repository_id=repo.id,
            suite_id=suite.id,
            custom_command="pytest -o rootdir=/tmp",
        )


@pytest.mark.asyncio
async def test_controlled_execution_success(
    test_session: AsyncSession, seed_data: dict[str, Any]
) -> None:
    ws = seed_data["workspace"]
    repo = seed_data["repository"]

    suite = TestPilotSuite(
        workspace_id=ws.id,
        repository_id=repo.id,
        framework="pytest",
        status=TestSuiteStatus.APPROVED,
    )
    test_session.add(suite)
    await test_session.commit()

    case = TestPilotCase(
        suite_id=suite.id,
        name="test_math",
        description="Verifies math",
        test_type="unit",
        code="def test_math():\n    assert 2 + 2 == 4\n",
    )
    test_session.add(case)
    await test_session.commit()

    # Mock ControlledTestRunner execution to return structured PASSED
    class MockControlledRunner(ControlledTestRunner):
        async def execute_approved_tests(
            self,
            execution_id: str,
            command: str,
            working_dir: str,
            run_approved: bool,
            timeout_seconds: float = 60.0,
        ) -> TestExecutionResult:
            return TestExecutionResult(
                execution_id=execution_id,
                command=command,
                status="PASSED",
                exit_code=0,
                stdout="tests/test_test_math.py::test_math PASSED\n1 passed in 0.05s",
                stderr="",
                passed_count=1,
                failed_count=0,
                skipped_count=0,
                duration_ms=50,
            )

    runner = TestPilotRunner(test_runner=MockControlledRunner())
    summary = await runner.execute_suite(
        db=test_session,
        workspace_id=ws.id,
        repository_id=repo.id,
        suite_id=suite.id,
    )

    assert summary.status == "PASSED"
    assert summary.passed_count == 1
    assert summary.failed_count == 0
    assert len(summary.results) == 1
    assert summary.results[0].status == "PASSED"

    # Verify execution persisted in DB
    exec_row = await test_session.get(TestPilotExecution, summary.execution_id)
    assert exec_row is not None
    assert exec_row.suite_id == suite.id
    assert exec_row.passed_count == 1


# ==============================================================================
# 4. FAILURE DIAGNOSIS & SECRET SCRUBBING TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_failure_diagnosis_and_pre_llm_redaction() -> None:
    mock_llm = MockLLM(
        response_text='{"root_cause": "IndexError: array index out of range in fetch_record", "suggestions": ["Check length before index access", "Use .get() with default value"], "confidence": 0.95}'
    )
    mgr = LLMProviderManager(force_mock=True)
    mgr.providers["mock"] = mock_llm
    diagnoser = FailureDiagnoser(llm_manager=mgr)

    token_leak = "gh" + "p_111122223333444455556666777788889999"
    api_key_leak = "AI" + "zaSyDummySecret123456789012345678"

    synthetic_traceback = f"""
Traceback (most recent call last):
  File "app/service.py", line 42, in fetch_record
    auth_header = "Bearer {token_leak}"
    return records[5]
IndexError: list index out of range
"""

    report = await diagnoser.diagnose(
        failing_test_name="tests.test_service::test_fetch",
        stdout="",
        stderr=synthetic_traceback,
        source_context=f"api_key = '{api_key_leak}'\ndef fetch_record(): pass",
    )

    assert report.failing_test == "tests.test_service::test_fetch"
    assert "IndexError" in report.error_message
    assert len(report.fix_suggestions) == 2
    assert report.confidence == 0.95

    # PROVE SECRET REDACTION: The prompt sent to LLM MUST NEVER contain raw token or API key!
    assert token_leak not in mock_llm.last_prompt
    assert api_key_leak not in mock_llm.last_prompt
    assert "[REDACTED_SECRET]" in mock_llm.last_prompt


# ==============================================================================
# 5. COVERAGE INTELLIGENCE TESTS
# ==============================================================================


def test_coverage_analyzer_preserves_null_branch_metrics() -> None:
    analyzer = CoverageAnalyzer()

    # coverage.py JSON report without branches
    raw_coverage = {
        "totals": {
            "percent_covered": 88.5,
            "num_branches": 0,  # No branch coverage enabled
        },
        "files": {
            "app/service.py": {"summary": {"missing_lines": 3}},
            "app/utils.py": {"summary": {"missing_lines": 0}},
        },
    }

    summary = analyzer.parse_coverage_json(raw_coverage, provider="coverage.py")
    assert summary.is_available is True
    assert summary.line_coverage_pct == 88.5
    # Critical requirement: Missing branch coverage must remain None, NOT 0.0!
    assert summary.branch_coverage_pct is None
    assert summary.uncovered_files == ["app/service.py"]


def test_coverage_analyzer_with_valid_branch_metrics() -> None:
    analyzer = CoverageAnalyzer()

    raw_coverage = {
        "totals": {
            "percent_covered": 92.0,
            "num_branches": 10,
            "covered_branches": 8,
        },
        "files": {},
    }

    summary = analyzer.parse_coverage_json(raw_coverage, provider="coverage.py")
    assert summary.line_coverage_pct == 92.0
    assert summary.branch_coverage_pct == 80.0


# ==============================================================================
# 6. IMPACTMIND TEST SELECTION TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_impact_test_selector_diff_analysis() -> None:
    selector = ImpactTestSelector()

    synthetic_diff = """diff --git a/app/calculator.py b/app/calculator.py
index e69de29..b1b2b3b 100644
--- a/app/calculator.py
+++ b/app/calculator.py
@@ -1,4 +1,4 @@
 def add(a: int, b: int) -> int:
-    return a + b
+    return a + b + 1
"""

    result = await selector.select_regression_tests(
        diff_text=synthetic_diff,
        all_test_files=["tests/test_calculator.py", "tests/test_unrelated.py"],
    )

    assert result.risk_exposure_score >= 0.0
    assert "calculator.py" in result.change_summary
    assert isinstance(result.selected_tests, list)


# ==============================================================================
# 7. MULTI-FRAMEWORK EXECUTION & SECURITY HARDENING TESTS
# ==============================================================================


def test_supported_frameworks_default_command_resolution() -> None:
    """Verify that all 5 supported frameworks resolve to safe, valid commands."""
    runner = TestPilotRunner()

    expected = {
        "pytest": "pytest -v",
        "unittest": "python -m unittest discover -s tests -v",
        "vitest": "npx vitest run",
        "jest": "npx jest --colors=false",
        "mocha": "npx mocha --no-colors",
    }

    for fw, expected_cmd in expected.items():
        resolved = runner._resolve_default_command(fw)
        assert resolved == expected_cmd
        # Verify that the command prefix is allowed by ControlledTestRunner
        is_allowed = any(resolved.startswith(exe) for exe in ALLOWED_TEST_EXECUTABLES)
        assert is_allowed


def test_parse_individual_results_across_all_frameworks() -> None:
    """Verify that stdout output parsing works accurately for all 5 frameworks."""
    runner = TestPilotRunner()

    # 1. Pytest
    pytest_out = """
tests/test_math.py::test_addition PASSED
tests/test_math.py::test_subtraction FAILED
tests/test_math.py::test_division SKIPPED
"""
    r_pytest = runner._parse_individual_results(pytest_out, "")
    assert len(r_pytest) == 3
    assert r_pytest[0].status == TestResultOutcome.PASSED
    assert r_pytest[1].status == TestResultOutcome.FAILED
    assert r_pytest[2].status == TestResultOutcome.SKIPPED

    # 2. Python unittest
    unittest_out = """
test_add (tests.test_math.TestMath) ... ok
test_sub (tests.test_math.TestMath) ... FAIL
test_div (tests.test_math.TestMath) ... ERROR
test_skip (tests.test_math.TestMath) ... skipped 'not supported'
"""
    r_unittest = runner._parse_individual_results(unittest_out, "")
    assert len(r_unittest) == 4
    assert r_unittest[0].test_name == "tests.test_math.TestMath.test_add"
    assert r_unittest[0].status == TestResultOutcome.PASSED
    assert r_unittest[1].status == TestResultOutcome.FAILED
    assert r_unittest[2].status == TestResultOutcome.FAILED
    assert r_unittest[3].status == TestResultOutcome.SKIPPED

    # 3. Jest
    jest_out = """
PASS src/math.test.js
  ✓ adds numbers (5 ms)
  ✕ fails on negative (2 ms)
  ○ skipped edge case
"""
    r_jest = runner._parse_individual_results(jest_out, "")
    assert len(r_jest) == 3
    assert r_jest[0].test_name == "adds numbers"
    assert r_jest[0].status == TestResultOutcome.PASSED
    assert r_jest[1].test_name == "fails on negative"
    assert r_jest[1].status == TestResultOutcome.FAILED
    assert r_jest[2].test_name == "skipped edge case"
    assert r_jest[2].status == TestResultOutcome.SKIPPED

    # 4. Mocha
    mocha_out = """
  Math Operations
    ✓ should return 42 (10ms)
    1) should throw on invalid input:
"""
    r_mocha = runner._parse_individual_results(mocha_out, "")
    assert len(r_mocha) == 2
    assert r_mocha[0].status == TestResultOutcome.PASSED
    assert r_mocha[1].status == TestResultOutcome.FAILED

    # 5. Vitest
    vitest_out = """
 ✓ tests/unit.test.ts > fast add
 ✗ tests/unit.test.ts > failed case
"""
    r_vitest = runner._parse_individual_results(vitest_out, "")
    assert len(r_vitest) == 2
    assert r_vitest[0].status == TestResultOutcome.PASSED
    assert r_vitest[1].status == TestResultOutcome.FAILED


def test_npm_test_script_validation_security() -> None:
    """Verify ControlledTestRunner prevents arbitrary code execution via npm test scripts."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # 1. Missing package.json
        with pytest.raises(ValueError, match="package.json not found"):
            ControlledTestRunner.validate_npm_script(tmp_dir, "test")

        # 2. Missing scripts.test
        pkg_file = os.path.join(tmp_dir, "package.json")
        with open(pkg_file, "w", encoding="utf-8") as f:
            f.write('{"name": "test-pkg", "scripts": {"build": "tsc"}}')
        with pytest.raises(ValueError, match="No 'test' script defined"):
            ControlledTestRunner.validate_npm_script(tmp_dir, "test")

        # 3. Disallowed shell chaining in scripts.test
        with open(pkg_file, "w", encoding="utf-8") as f:
            f.write('{"scripts": {"test": "vitest run && rm -rf /"}}')
        with pytest.raises(ValueError, match="shell operator '&&' is prohibited"):
            ControlledTestRunner.validate_npm_script(tmp_dir, "test")

        # 4. Disallowed arbitrary runner (e.g. bash, node arbitrary.js)
        with open(pkg_file, "w", encoding="utf-8") as f:
            f.write('{"scripts": {"test": "bash run_tests.sh"}}')
        with pytest.raises(ValueError, match="unauthorized runner 'bash'"):
            ControlledTestRunner.validate_npm_script(tmp_dir, "test")

        with open(pkg_file, "w", encoding="utf-8") as f:
            f.write('{"scripts": {"test": "node evil_script.js"}}')
        with pytest.raises(ValueError, match="must use the native test runner"):
            ControlledTestRunner.validate_npm_script(tmp_dir, "test")

        # 5. Disallowed forbidden flags
        with open(pkg_file, "w", encoding="utf-8") as f:
            f.write('{"scripts": {"test": "jest --setupFiles exploit.js"}}')
        with pytest.raises(ValueError, match="Disallowed flag '--setupFiles'"):
            ControlledTestRunner.validate_npm_script(tmp_dir, "test")

        # 6. Valid safe test scripts
        valid_scripts = [
            "vitest run",
            "jest --colors=false",
            "mocha --no-colors",
            "node --test",
        ]
        for script in valid_scripts:
            with open(pkg_file, "w", encoding="utf-8") as f:
                f.write(f'{{"scripts": {{"test": "{script}"}}}}')
            ControlledTestRunner.validate_npm_script(tmp_dir, "test")  # Must not raise


def test_forbidden_flags_rejection_across_frameworks() -> None:
    """Verify that dangerous flags across pytest, vitest, jest, and mocha are blocked."""
    dangerous_commands = [
        "pytest -c evil.ini",
        "pytest --config=evil.ini",
        "pytest -o python_files=exploit.py",
        "npx jest --setupFiles exploit.js",
        "npx mocha -r exploit.js",
        "npx mocha --require exploit.js",
        "npx vitest --exec exploit.js",
        "npx vitest --eval 'process.exit(1)'",
        "pytest tests/../../etc/passwd",
    ]

    for cmd in dangerous_commands:
        with pytest.raises(ValueError):
            ControlledTestRunner.sanitize_command(cmd)
