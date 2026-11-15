from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from app.services.impactmind.test_selector import SelectedRegressionTest

logger = logging.getLogger("orchestrix.impactmind.test_runner")

# Strict allowlist of recognized test binaries/prefixes
ALLOWED_TEST_EXECUTABLES = {
    "pytest",
    "python -m pytest",
    "python3 -m pytest",
    "uv run pytest",
    "python -m unittest",
    "python3 -m unittest",
    "npx vitest",
    "vitest",
    "npx jest",
    "jest",
    "npx mocha",
    "mocha",
    "npm test",
    "npm run test",
    "go test",
}

# Dangerous flags that must be rejected to prevent arbitrary code execution
FORBIDDEN_FLAG_PATTERNS = {
    # Pytest code execution / config override vectors
    "-o",
    "--override-ini",
    "-c",
    "--config",
    "-p",
    "--plugin",
    "--import-mode",
    "--assert",
    "--basetemp",
    "--rootdir",
    # Vitest / Jest execution hooks & arbitrary module loading
    "--exec",
    "--eval",
    "-e",
    "--setupFiles",
    "--setupFilesAfterEnv",
    "--transform",
    "--globalSetup",
    "--globalTeardown",
    "--runner",
    "--testResultsProcessor",
    # Mocha execution hooks
    "-r",
    "--require",
    "--ui",
    "--file",
    "--package",
    # Node / Python code execution
    "--inspect",
    "--inspect-brk",
    # Go test execution hooks
    "-exec",
    "-toolexec",
}

# Regex for redacting tokens and secrets from output logs
SECRET_REDACTION_PATTERN = re.compile(
    r"""(?i)(?:bearer|token|secret|password|api[_-]?key|jwt)\s*[:=]\s*["']?([a-zA-Z0-9_\-\.]{8,})["']?"""
)

# Active execution tasks registry for cancellation
_ACTIVE_TEST_TASKS: dict[str, asyncio.Task[Any]] = {}


@dataclass
class TestExecutionResult:
    __test__ = False
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


def _create_windows_job_object() -> int | None:
    """Create a Windows Job Object configured to kill all processes on handle close."""
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.windll.kernel32

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryLimit", ctypes.c_size_t),
                ("PeakJobMemoryLimit", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        h_job = kernel32.CreateJobObjectW(None, None)
        if not h_job:
            return None

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(
            h_job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        return int(h_job) if h_job else None
    except Exception as e:
        logger.warning(f"Failed to create Windows Job Object: {e}")
        return None


def _assign_process_to_job(h_job: int | None, pid: int) -> bool:
    """Assign process PID to a Windows Job Object."""
    if os.name != "nt" or not h_job:
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        PROCESS_ALL_ACCESS = 0x1F0FFF
        h_process = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not h_process:
            return False
        try:
            res = kernel32.AssignProcessToJobObject(h_job, h_process)
            return bool(res)
        finally:
            kernel32.CloseHandle(h_process)
    except Exception as e:
        logger.warning(f"Failed to assign process {pid} to Job Object: {e}")
        return False


async def _terminate_process_tree(
    proc: asyncio.subprocess.Process, h_job: int | None = None
) -> None:
    """
    Terminates the entire process tree on Windows and POSIX to avoid orphan processes.
    """
    if os.name == "nt":
        # 1. Terminate Job Object (instantly kills all processes assigned to it)
        if h_job:
            try:
                ctypes.windll.kernel32.TerminateJobObject(h_job, 1)
                ctypes.windll.kernel32.CloseHandle(h_job)
            except Exception:
                pass

        # 2. Forceful tree kill via Windows taskkill
        try:
            tree_killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                str(proc.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await tree_killer.wait()
        except Exception:
            pass

        # 3. Fallback kill on process handle
        try:
            proc.kill()
        except Exception:
            pass
    else:
        # POSIX process group termination
        try:
            killpg_name = "killpg"
            getpgid_name = "getpgid"
            if hasattr(os, killpg_name) and hasattr(os, getpgid_name):
                getattr(os, killpg_name)(
                    getattr(os, getpgid_name)(proc.pid), getattr(signal, "SIGKILL", 9)
                )
            else:
                proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


class ControlledTestRunner:
    """
    Controlled regression test execution service.
    Enforces user approval, strict command allowlisting, argument validation,
    working-directory jail, environment secret scrubbing, process isolation
    (Windows Job Objects / POSIX process groups), and bounded execution.
    """

    MAX_OUTPUT_BYTES = 50 * 1024  # 50 KB output limit

    @classmethod
    def sanitize_command(cls, raw_command: str) -> list[str]:
        """
        Validate command against strict allowlist and argument safety rules.
        Rejects shell metacharacters, unauthorized binaries, and code-execution flags.
        """
        cleaned = raw_command.strip()
        if not cleaned:
            raise ValueError("Test command cannot be empty")

        # Disallow shell metacharacters and control characters
        disallowed_chars = [
            ";",
            "&&",
            "||",
            "|",
            "`",
            "$",
            ">",
            "<",
            "\n",
            "\r",
            "\0",
            "^",
            "%",
        ]
        for char in disallowed_chars:
            if char in cleaned:
                raise ValueError(f"Disallowed shell character '{char}' in test command")

        # Must start with an allowed executable prefix
        is_allowed = any(cleaned.startswith(exe) for exe in ALLOWED_TEST_EXECUTABLES)
        if not is_allowed:
            raise ValueError(
                f"Command '{cleaned}' is not in the approved test runner allowlist: {sorted(ALLOWED_TEST_EXECUTABLES)}"
            )

        tokens = shlex.split(cleaned, posix=os.name != "nt")
        if not tokens:
            raise ValueError("Command split yielded no tokens")

        # Deep argument safety validation: inspect every single token
        for token in tokens:
            # Check for forbidden execution/config flags
            for forbidden in FORBIDDEN_FLAG_PATTERNS:
                if token == forbidden or token.startswith(f"{forbidden}="):
                    raise ValueError(
                        f"Disallowed command flag '{token}' detected. Arbitrary configuration flags are blocked for security."
                    )

            # Block path traversal attempts in file arguments
            if ".." in token:
                raise ValueError(
                    f"Path traversal ('..') is not permitted in test arguments: '{token}'"
                )

        # Resolve binary path on Windows / system
        base_binary = tokens[0]
        resolved = shutil.which(base_binary)
        if not resolved:
            raise FileNotFoundError(
                f"Test executable '{base_binary}' could not be resolved in system PATH"
            )
        tokens[0] = resolved

        return tokens

    @classmethod
    def validate_working_directory(cls, working_dir: str) -> str:
        """
        Ensure working directory exists, is absolute, and is not a prohibited system root.
        """
        if not working_dir:
            raise ValueError("Working directory must not be empty")

        resolved = os.path.abspath(working_dir)
        if not os.path.isdir(resolved):
            raise FileNotFoundError(f"Working directory does not exist: {resolved}")

        # Prohibit system root paths
        prohibited_roots = {
            "C:\\",
            "C:\\Windows",
            "C:\\Windows\\System32",
            "C:\\Program Files",
            "C:\\Program Files (x86)",
            "/",
            "/bin",
            "/etc",
            "/usr",
            "/var",
            "/root",
        }
        for prohibited in prohibited_roots:
            if resolved.upper() == prohibited.upper() or (
                len(resolved) > len(prohibited)
                and resolved.upper().startswith(prohibited.upper())
                and prohibited in ("C:\\Windows", "C:\\Windows\\System32", "/etc")
            ):
                raise PermissionError(
                    f"Execution in protected system directory is prohibited: {resolved}"
                )

        return resolved

    @classmethod
    def build_isolated_environment(cls) -> dict[str, str]:
        """
        Construct a sanitized environment for test execution.
        Strips all sensitive credentials, database URLs, API keys, and JWT secrets.
        """
        safe_keys = {
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "SYSTEMDRIVE",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "HOMEDRIVE",
            "HOMEPATH",
            "LANG",
            "LC_ALL",
            "VIRTUAL_ENV",
            "PYTHONPATH",
            "NODE_PATH",
            "CI",
            "TERM",
        }
        isolated_env = {}
        for k, v in os.environ.items():
            k_upper = k.upper()
            if k in safe_keys:
                isolated_env[k] = v
            # Explicit blacklist of any secret/credential patterns
            if any(
                bad in k_upper
                for bad in (
                    "SECRET",
                    "KEY",
                    "TOKEN",
                    "PASSWORD",
                    "DATABASE",
                    "NEO4J",
                    "CREDENTIAL",
                    "PRIVATE",
                    "AUTH",
                    "JWT",
                    "API",
                )
            ):
                isolated_env.pop(k, None)
        return isolated_env

    @classmethod
    def redact_secrets(cls, text: str) -> str:
        """Mask sensitive tokens, passwords, and API keys from test output logs."""
        if not text:
            return ""
        from app.services.secureflow.redaction import redact_secrets as sf_redact_secrets

        return sf_redact_secrets(SECRET_REDACTION_PATTERN.sub(r"[REDACTED_SECRET]", text))

    @classmethod
    def validate_npm_script(cls, working_dir: str, script_name: str = "test") -> None:
        """
        Validate that package.json defines an approved, safe test script.
        Prevents arbitrary command execution via npm test.
        """
        pkg_json_path = os.path.join(working_dir, "package.json")
        if not os.path.isfile(pkg_json_path):
            raise ValueError(
                f"Cannot execute 'npm {script_name}': package.json not found in workspace"
            )

        try:
            with open(pkg_json_path, encoding="utf-8") as f:
                pkg_data = json.load(f)
        except Exception as e:
            raise ValueError(f"Invalid package.json in workspace: {e}") from e

        scripts = pkg_data.get("scripts", {})
        if not isinstance(scripts, dict) or script_name not in scripts:
            raise ValueError(
                f"No '{script_name}' script defined in package.json. Arbitrary execution blocked."
            )

        raw_script = str(scripts[script_name]).strip()
        if not raw_script:
            raise ValueError(f"Empty '{script_name}' script in package.json")

        # Disallow shell operators in package.json test script
        disallowed_shell_chars = [";", "&&", "||", "|", "`", "$", ">", "<", "\n", "\r", "\0"]
        for ch in disallowed_shell_chars:
            if ch in raw_script:
                raise ValueError(
                    f"Unsafe npm {script_name} script '{raw_script}': shell operator '{ch}' is prohibited"
                )

        # Parse script tokens
        tokens = shlex.split(raw_script, posix=os.name != "nt")
        if not tokens:
            raise ValueError(f"Invalid npm {script_name} script")

        # Approved test runners allowed inside package.json "test" script
        approved_runners = {
            "vitest",
            "jest",
            "mocha",
            "pytest",
            "python",
            "python3",
            "ava",
            "tape",
            "c8",
            "nyc",
            "node",
            "npx",
        }

        base_cmd = tokens[0].lower().replace(".exe", "").replace(".cmd", "")
        if base_cmd not in approved_runners:
            raise ValueError(
                f"Unsafe npm test script invokes unauthorized runner '{tokens[0]}'. "
                f"Approved runners: {sorted(approved_runners)}"
            )

        # If runner is node, require that it runs node --test
        if base_cmd == "node" and (len(tokens) < 2 or tokens[1] != "--test"):
            raise ValueError(
                "npm test scripts invoking 'node' must use the native test runner ('node --test')"
            )

        # If runner is npx, check the runner being invoked
        if base_cmd == "npx" and len(tokens) >= 2:
            npx_runner = tokens[1].lower()
            if npx_runner not in {"vitest", "jest", "mocha", "ava", "tape"}:
                raise ValueError(
                    f"npx in npm test script invokes unauthorized runner '{tokens[1]}'"
                )

        # Check for forbidden flags in the package.json script tokens
        for token in tokens:
            for forbidden in FORBIDDEN_FLAG_PATTERNS:
                if token == forbidden or token.startswith(f"{forbidden}="):
                    raise ValueError(
                        f"Disallowed flag '{token}' in package.json '{script_name}' script"
                    )
            if ".." in token:
                raise ValueError(
                    f"Path traversal ('..') is prohibited in package.json '{script_name}' script"
                )

    @classmethod
    def build_test_command(
        cls,
        tests: list[SelectedRegressionTest],
        framework: str | None = None,
    ) -> str:
        """Build an optimized command targeting the selected test files."""
        if not tests:
            return "pytest"

        target_fw = framework or tests[0].test_framework
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
        Execute approved regression tests asynchronously in a controlled, sandboxed subprocess.
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
        safe_working_dir = self.validate_working_directory(working_dir)
        isolated_env = self.build_isolated_environment()

        # If running npm test or npm run test, validate package.json test script
        if any(command.strip().startswith(npm_cmd) for npm_cmd in ("npm test", "npm run test")):
            self.validate_npm_script(safe_working_dir, "test")

        # Clamp timeout
        timeout_seconds = max(1.0, min(300.0, timeout_seconds))

        start_time = time.monotonic()
        task = asyncio.current_task()
        if task:
            _ACTIVE_TEST_TASKS[execution_id] = task

        proc = None
        h_job: int | None = None
        status = "RUNNING"
        stdout_text = ""
        stderr_text = ""
        exit_code = None

        try:
            # Create Windows Job Object before spawning
            if os.name == "nt":
                h_job = _create_windows_job_object()

            extra_kwargs: dict[str, Any] = {}
            if os.name == "nt":
                # Create in new process group on Windows
                extra_kwargs["creationflags"] = getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
                )
            else:
                extra_kwargs["start_new_session"] = True

            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                cwd=safe_working_dir,
                env=isolated_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **extra_kwargs,
            )

            # Assign to Windows Job Object immediately
            if os.name == "nt" and h_job and proc.pid:
                _assign_process_to_job(h_job, proc.pid)

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )
            exit_code = proc.returncode

            stdout_text = self.redact_secrets(
                stdout_bytes[: self.MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            )
            if len(stdout_bytes) > self.MAX_OUTPUT_BYTES:
                stdout_text += "\n[... Output Truncated at 50KB limit ...]"

            stderr_text = self.redact_secrets(
                stderr_bytes[: self.MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            )
            if len(stderr_bytes) > self.MAX_OUTPUT_BYTES:
                stderr_text += "\n[... Stderr Truncated at 50KB limit ...]"

            status = "PASSED" if exit_code == 0 else "FAILED"

        except TimeoutError:
            status = "TIMED_OUT"
            if proc:
                await _terminate_process_tree(proc, h_job)
            stderr_text = f"Execution timed out after {timeout_seconds}s"
        except asyncio.CancelledError:
            status = "CANCELLED"
            if proc:
                await _terminate_process_tree(proc, h_job)
            stderr_text = "Execution was cancelled by user"
        except Exception as e:
            status = "FAILED"
            if proc:
                await _terminate_process_tree(proc, h_job)
            stderr_text = f"Subprocess launch error: {e}"
        finally:
            # Clean up Job Object handle
            if os.name == "nt" and h_job:
                try:
                    ctypes.windll.kernel32.CloseHandle(h_job)
                except Exception:
                    pass
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
