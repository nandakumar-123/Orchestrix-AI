from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any

from app.services.testpilot.schemas import DetectedFrameworkInfo

logger = logging.getLogger("orchestrix.testpilot.detector")


class FrameworkDetector:
    """
    Automatic software test framework and convention detector.
    Analyzes project manifests, test directories, naming conventions,
    and runtime environment executables for Python and JavaScript/TypeScript.
    """

    SUPPORTED_FRAMEWORKS = ["pytest", "unittest", "vitest", "jest", "mocha"]

    @classmethod
    def is_runner_available(cls, framework: str) -> bool:
        """Check whether the required CLI runner executable is present in the environment."""
        if framework in ("pytest", "unittest"):
            # Check for pytest executable or python interpreter
            if framework == "pytest":
                return bool(
                    shutil.which("pytest") or shutil.which("python") or shutil.which("python3")
                )
            return bool(shutil.which("python") or shutil.which("python3"))
        elif framework in ("vitest", "jest", "mocha"):
            # Check for npx or npm
            return bool(shutil.which("npx") or shutil.which("npm"))
        return False

    def detect_from_directory(self, root_dir: str) -> DetectedFrameworkInfo:
        """
        Scan a local filesystem directory to detect test frameworks and conventions.
        """
        if not os.path.exists(root_dir) or not os.path.isdir(root_dir):
            return self._unknown_fallback("Directory does not exist", root_dir)

        # Collect relative file paths
        all_files: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Prune noisy directories
            dirnames[:] = [
                d
                for d in dirnames
                if d not in (".git", "node_modules", ".venv", "__pycache__", "dist", "build")
            ]
            for f in filenames:
                rel = os.path.relpath(os.path.join(dirpath, f), root_dir).replace("\\", "/")
                all_files.append(rel)

        return self.detect_from_files(all_files, root_dir=root_dir)

    def detect_from_files(
        self,
        file_paths: list[str],
        file_contents: dict[str, str] | None = None,
        root_dir: str | None = None,
    ) -> DetectedFrameworkInfo:
        """
        Detect test framework from file list and optional content snippets.
        Works seamlessly on real directories or synthetic in-memory manifests.
        """
        paths_set = {p.replace("\\", "/") for p in file_paths}
        basenames = {os.path.basename(p): p for p in file_paths}
        file_contents = file_contents or {}

        # ---------------------------------------------------------
        # 1. PYTHON DETECTION: pytest vs unittest
        # ---------------------------------------------------------
        py_files = [p for p in paths_set if p.endswith(".py")]
        test_py_files = [
            p
            for p in py_files
            if os.path.basename(p).startswith("test_") or os.path.basename(p).endswith("_test.py")
        ]

        # Check Python manifest configurations
        has_pytest_ini = "pytest.ini" in basenames
        has_setup_cfg = "setup.cfg" in basenames
        has_pyproject = "pyproject.toml" in basenames

        pytest_declared = has_pytest_ini
        if has_pyproject and not pytest_declared:
            content = self._get_file_content("pyproject.toml", basenames, file_contents, root_dir)
            if content and ("tool.pytest" in content or "pytest" in content):
                pytest_declared = True

        if has_setup_cfg and not pytest_declared:
            content = self._get_file_content("setup.cfg", basenames, file_contents, root_dir)
            if content and "tool:pytest" in content:
                pytest_declared = True

        if pytest_declared or (test_py_files and not self._is_js_repo(paths_set)):
            # Check test directory
            test_dir = self._find_test_dir(paths_set, default="tests")
            naming = self._detect_naming_convention(test_py_files, default="test_*.py")
            is_avail = self.is_runner_available("pytest")
            missing = [] if is_avail else ["pytest executable or python runner not found in PATH"]

            confidence = (
                0.95 if pytest_declared and test_py_files else (0.85 if pytest_declared else 0.70)
            )
            return DetectedFrameworkInfo(
                language="python",
                framework="pytest",
                config_file="pytest.ini"
                if has_pytest_ini
                else ("pyproject.toml" if has_pyproject else None),
                test_directory=test_dir,
                naming_convention=naming,
                runner_command="pytest",
                is_available=is_avail,
                confidence=confidence,
                missing_requirements=missing,
            )

        # ---------------------------------------------------------
        # 2. JAVASCRIPT / TYPESCRIPT DETECTION: vitest, jest, mocha
        # ---------------------------------------------------------
        has_package_json = "package.json" in basenames
        pkg_json_content: dict[str, Any] = {}
        if has_package_json:
            raw_pkg = self._get_file_content("package.json", basenames, file_contents, root_dir)
            if raw_pkg:
                try:
                    pkg_json_content = json.loads(raw_pkg)
                except Exception:
                    pkg_json_content = {}

        deps = {
            **pkg_json_content.get("dependencies", {}),
            **pkg_json_content.get("devDependencies", {}),
        }
        scripts = pkg_json_content.get("scripts", {})
        test_script = scripts.get("test", "")

        js_ts_test_files = [
            p
            for p in paths_set
            if any(
                p.endswith(ext)
                for ext in (
                    ".test.ts",
                    ".spec.ts",
                    ".test.tsx",
                    ".spec.tsx",
                    ".test.js",
                    ".spec.js",
                )
            )
        ]
        test_dir = self._find_test_dir(paths_set, default="__tests__")
        is_ts = any(p.endswith((".ts", ".tsx")) for p in paths_set)
        lang = "typescript" if is_ts else "javascript"

        # Vitest check
        has_vitest_config = any(
            b.startswith("vitest.config") or b.startswith("vite.config") for b in basenames
        )
        if has_vitest_config or "vitest" in deps or "vitest" in test_script:
            is_avail = self.is_runner_available("vitest")
            missing = [] if is_avail else ["Node.js/npx not found in PATH for vitest"]
            naming = self._detect_naming_convention(
                js_ts_test_files, default="*.test.ts" if is_ts else "*.test.js"
            )
            config_file = next(
                (
                    b
                    for b in basenames
                    if b.startswith("vitest.config") or b.startswith("vite.config")
                ),
                "package.json",
            )
            return DetectedFrameworkInfo(
                language=lang,
                framework="vitest",
                config_file=config_file,
                test_directory=test_dir,
                naming_convention=naming,
                runner_command="npx vitest run",
                is_available=is_avail,
                confidence=0.95 if has_vitest_config else 0.85,
                missing_requirements=missing,
            )

        # Jest check
        has_jest_config = any(b.startswith("jest.config") for b in basenames)
        if has_jest_config or "jest" in deps or "jest" in test_script:
            is_avail = self.is_runner_available("jest")
            missing = [] if is_avail else ["Node.js/npx not found in PATH for jest"]
            naming = self._detect_naming_convention(
                js_ts_test_files, default="*.test.ts" if is_ts else "*.test.js"
            )
            config_file = next(
                (b for b in basenames if b.startswith("jest.config")), "package.json"
            )
            return DetectedFrameworkInfo(
                language=lang,
                framework="jest",
                config_file=config_file,
                test_directory=test_dir,
                naming_convention=naming,
                runner_command="npx jest",
                is_available=is_avail,
                confidence=0.95 if has_jest_config else 0.85,
                missing_requirements=missing,
            )

        # Mocha check
        has_mocha_config = any(b.startswith(".mocharc") for b in basenames)
        if has_mocha_config or "mocha" in deps or "mocha" in test_script:
            is_avail = self.is_runner_available("mocha")
            missing = [] if is_avail else ["Node.js/npx not found in PATH for mocha"]
            naming = self._detect_naming_convention(js_ts_test_files, default="*.spec.js")
            config_file = next((b for b in basenames if b.startswith(".mocharc")), "package.json")
            return DetectedFrameworkInfo(
                language=lang,
                framework="mocha",
                config_file=config_file,
                test_directory=test_dir,
                naming_convention=naming,
                runner_command="npx mocha",
                is_available=is_avail,
                confidence=0.90 if has_mocha_config else 0.80,
                missing_requirements=missing,
            )

        # Fallback / unsupported framework
        return self._unknown_fallback(
            "No recognized test framework configuration or tests found", root_dir or ""
        )

    def _get_file_content(
        self,
        target_name: str,
        basenames: dict[str, str],
        file_contents: dict[str, str],
        root_dir: str | None,
    ) -> str | None:
        if target_name in file_contents:
            return file_contents[target_name]
        if target_name in basenames:
            rel_path = basenames[target_name]
            if rel_path in file_contents:
                return file_contents[rel_path]
            if root_dir:
                full_path = os.path.join(root_dir, rel_path)
                if os.path.exists(full_path):
                    try:
                        with open(full_path, encoding="utf-8", errors="ignore") as f:
                            return f.read()
                    except Exception:
                        return None
        return None

    def _is_js_repo(self, paths: set[str]) -> bool:
        return any(p.endswith((".ts", ".tsx", ".js", ".jsx", "package.json")) for p in paths)

    def _find_test_dir(self, paths: set[str], default: str) -> str:
        candidates = ["tests", "test", "__tests__", "spec", "src/test", "src/__tests__"]
        for cand in candidates:
            if any(p == cand or p.startswith(f"{cand}/") for p in paths):
                return cand
        return default

    def _detect_naming_convention(self, test_files: list[str], default: str) -> str:
        if not test_files:
            return default
        # Inspect patterns
        names = [os.path.basename(p) for p in test_files]
        if any(n.startswith("test_") for n in names):
            return "test_*.py"
        if any(n.endswith("_test.py") for n in names):
            return "*_test.py"
        if any(n.endswith(".test.ts") for n in names):
            return "*.test.ts"
        if any(n.endswith(".spec.ts") for n in names):
            return "*.spec.ts"
        if any(n.endswith(".test.js") for n in names):
            return "*.test.js"
        if any(n.endswith(".spec.js") for n in names):
            return "*.spec.js"
        return default

    def _unknown_fallback(self, reason: str, root_dir: str) -> DetectedFrameworkInfo:
        return DetectedFrameworkInfo(
            language="unknown",
            framework="unsupported",
            config_file=None,
            test_directory="tests",
            naming_convention="test_*.*",
            runner_command="",
            is_available=False,
            confidence=0.0,
            missing_requirements=[reason],
        )
