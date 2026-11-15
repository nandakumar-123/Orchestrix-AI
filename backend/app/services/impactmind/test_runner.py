from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import time
from dataclasses import dataclass
from typing import Any

from app.services.impactmind.test_selector import SelectedRegressionTest

logger = logging.getLogger("orchestrix.impactmind.test_runner")

# Strict allowlist of recognized test binaries/prefixes
ALLOWED_TEST_EXECUTABLES = {
    "pytest",
    "python -m pytest",
    "uv run pytest",
    "npm test",
    "npm run test",
    "npx vitest",
    "vitest",
    "go test",
}

# Regex for redacting tokens and secrets from output logs
SECRET_REDACTION_PATTERN = re.compile(
    r"""(?i)(?:bearer|token|secret|password|api[_-]?key|jwt)\s*[:=]\s*["']?([a-zA-Z0-9_\-\.]{8,})["']?"""
)

# Active execution tasks registry for cancellation
_ACTIVE_TEST_TASKS: dict[str, asyncio.Task[Any]] = {}


@dataclass
class TestExecutionResult:
    execution_id: str
    command: str
    status: str  # "PASSED" | "FAILED" | "TIMED_OUT" | "CANCELLED" | "SKIPPED" | "NOT_EXECUTED"
    exit_code: int | None
    stdout: str
    stderr: str
    passed_count: int
    failed_count: int
    skipped_count: int
    duration_ms: int
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "command": self.command,
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
        }


class ControlledTestRunner:
    """
    Controlled regression test execution service.
    Enforces user approval, strict command allowlisting, working-directory isolation,
    configurable execution timeouts, output truncation, and secret redaction.
    """

    MAX_OUTPUT_BYTES = 50 * 1024  # 50 KB output limit

    @classmethod
    def sanitize_command(cls, raw_command: str) -> list[str]:
        """
        Validate command against strict allowlist.
        Rejects shell metacharacters (; && || | ` $ > <).
        """
        cleaned = raw_command.strip()
        # Disallow shell injection characters
        for char in [";", "&&", "||", "|", "`", "$", ">", "<", "\n", "\r"]:
            if char in cleaned:
                raise ValueError(f"Disallowed shell character '{char}' in test command")

        # Must start with an allowed executable
        is_allowed = any(cleaned.startswith(exe) for exe in ALLOWED_TEST_EXECUTABLES)
        if not is_allowed:
            raise ValueError(
                f"Command '{cleaned}' is not in the approved test runner allowlist: {ALLOWED_TEST_EXECUTABLES}"
            )

        return shlex.split(cleaned, posix=os.name != "nt")

    @classmethod
    def redact_secrets(cls, text: str) -> str:
        """Mask sensitive tokens, passwords, and API keys from test output logs."""
        if not text:
            return ""
        return SECRET_REDACTION_PATTERN.sub(r"[REDACTED_SECRET]", text)

    @classmethod
    def build_test_command(
        cls,
        tests: list[SelectedRegressionTest],
        framework: str | None = None,
    ) -> str:
        """Build an optimized command targeting the selected test files."""
        if not tests:
            return "pytest"

        # Determine dominant framework
        target_fw = framework or tests[0].test_framework

        # Deduplicate test files
        target_files = sorted({t.test_file for t in tests if t.test_file})

        if target_fw == "pytest":
            file_args = " ".join(target_files)
            return f"pytest {file_args}"
        elif target_fw == "vitest":
            file_args = " ".join(target_files)
            return f"npx vitest run {file_args}"
        elif target_fw == "go_test":
            file_args = " ".join(target_files)
            return f"go test -v {file_args}"
        return "pytest"

    async def execute_approved_tests(
        self,
        execution_id: str,
        command: str,
        working_dir: str,
        run_approved: bool,
        timeout_seconds: float = 60.0,
    ) -> TestExecutionResult:
        """
        Execute approved regression tests asynchronously in a controlled subprocess.
        """
        if not run_approved:
            return TestExecutionResult(
                execution_id=execution_id,
                command=command,
                status="NOT_EXECUTED",
                exit_code=None,
                stdout="",
                stderr="Test execution was not approved by user.",
                passed_count=0,
                failed_count=0,
                skipped_count=0,
                duration_ms=0,
            )

        cmd_args = self.sanitize_command(command)

        if not os.path.exists(working_dir):
            raise FileNotFoundError(f"Working directory does not exist: {working_dir}")

        start_time = time.monotonic()
        task = asyncio.current_task()
        if task:
            _ACTIVE_TEST_TASKS[execution_id] = task

        proc = None
        status = "RUNNING"
        stdout_text = ""
        stderr_text = ""
        exit_code = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                cwd=working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )
            exit_code = proc.returncode

            stdout_text = self.redact_secrets(
                stdout_bytes[: self.MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            )
            stderr_text = self.redact_secrets(
                stderr_bytes[: self.MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            )

            status = "PASSED" if exit_code == 0 else "FAILED"

        except asyncio.TimeoutError:
            status = "TIMED_OUT"
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            stderr_text = f"Execution timed out after {timeout_seconds}s"
        except asyncio.CancelledError:
            status = "CANCELLED"
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            stderr_text = "Execution was cancelled by user"
        except Exception as e:
            status = "FAILED"
            stderr_text = f"Subprocess launch error: {e}"
        finally:
            _ACTIVE_TEST_TASKS.pop(execution_id, None)

        duration_ms = int((time.monotonic() - start_time) * 1000)

        # Parse test metrics from output
        passed_cnt, failed_cnt, skipped_cnt = self._parse_test_summary(stdout_text)

        return TestExecutionResult(
            execution_id=execution_id,
            command=command,
            status=status,
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            passed_count=passed_cnt,
            failed_count=failed_cnt,
            skipped_count=skipped_cnt,
            duration_ms=duration_ms,
        )

    @classmethod
    def cancel_execution(cls, execution_id: str) -> bool:
        """Cancel an ongoing test execution task."""
        task = _ACTIVE_TEST_TASKS.get(execution_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def _parse_test_summary(self, stdout: str) -> tuple[int, int, int]:
        """Parse count of passed, failed, and skipped tests from common test runners."""
        passed = 0
        failed = 0
        skipped = 0

        # Pytest pattern: 5 passed, 1 failed, 2 skipped in 1.23s
        py_match = re.search(r"(\d+)\s+passed", stdout)
        if py_match:
            passed = int(py_match.group(1))
        py_fail = re.search(r"(\d+)\s+failed", stdout)
        if py_fail:
            failed = int(py_fail.group(1))
        py_skip = re.search(r"(\d+)\s+skipped", stdout)
        if py_skip:
            skipped = int(py_skip.group(1))

        # Vitest pattern: Tests  4 passed (4)
        vit_pass = re.search(r"Tests\s+(\d+)\s+passed", stdout)
        if vit_pass:
            passed = int(vit_pass.group(1))
        vit_fail = re.search(r"Tests\s+(\d+)\s+failed", stdout)
        if vit_fail:
            failed = int(vit_fail.group(1))

        return passed, failed, skipped
