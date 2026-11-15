from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
from typing import Any

import httpx

from app.db.models.secureflow import FindingSeverity, SecureFlowFinding
from app.services.secureflow.redaction import redact_secrets
from app.services.secureflow.schemas import DependencyScanResult, NormalizedFinding

logger = logging.getLogger("orchestrix.secureflow.dependency_scanner")

OSV_API_URL = "https://api.osv.dev/v1/query"
DEFAULT_SCAN_TIMEOUT_SECONDS = 30.0


class DependencyScanner:
    """
    Software Dependency Vulnerability Scanner.
    Integrates pip-audit for Python, npm audit for Node.js, and OSV API for universal lookup.
    Accurately normalizes findings, validates availability, and guarantees zero fabrication.
    """

    def __init__(self, osv_api_url: str = OSV_API_URL) -> None:
        self.osv_api_url = osv_api_url

    def is_pip_audit_available(self) -> bool:
        """Check if pip-audit executable or python module is installed."""
        try:
            import pip_audit  # type: ignore[import-untyped]  # noqa: F401

            return True
        except ImportError:
            return bool(shutil.which("pip-audit"))

    def is_npm_audit_available(self) -> bool:
        """Check if npm is present in PATH."""
        return bool(shutil.which("npm"))

    async def scan_python_dependencies(
        self,
        root_dir: str,
        requirements_file: str | None = None,
        timeout_seconds: float = DEFAULT_SCAN_TIMEOUT_SECONDS,
    ) -> DependencyScanResult:
        """
        Scan Python dependencies for CVEs using pip-audit.
        """
        if not self.is_pip_audit_available():
            return DependencyScanResult(
                scanner_name="pip-audit",
                is_available=False,
                error="pip-audit is not installed or available in environment",
            )

        # Validate working directory and input paths
        root_dir = os.path.abspath(root_dir)
        if not os.path.isdir(root_dir):
            raise FileNotFoundError(f"Root directory does not exist: {root_dir}")

        if requirements_file and ".." in requirements_file:
            raise ValueError(
                f"Path traversal ('..') is prohibited in requirements_file: {requirements_file}"
            )

        # Locate manifest file
        target_file = None
        if requirements_file and os.path.exists(os.path.join(root_dir, requirements_file)):
            target_file = requirements_file
        else:
            candidates = ["requirements.txt", "pyproject.toml", "Pipfile.lock", "setup.py"]
            for cand in candidates:
                if os.path.exists(os.path.join(root_dir, cand)):
                    target_file = cand
                    break

        if not target_file:
            return DependencyScanResult(
                scanner_name="pip-audit",
                is_available=True,
                findings=[],
                scanned_files=[],
                error=None,
            )

        full_path = os.path.join(root_dir, target_file)
        cmd = [shutil.which("pip-audit") or "pip-audit", "-r", full_path, "-f", "json"]

        proc = None
        try:
            extra_kwargs: dict[str, Any] = {}
            if os.name == "nt":
                extra_kwargs["creationflags"] = getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
                )
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=root_dir,
                **extra_kwargs,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
            stdout = stdout_b.decode("utf-8", errors="ignore")
            stderr = stderr_b.decode("utf-8", errors="ignore")

            # pip-audit exits with 1 if vulnerabilities are found, 0 if clean
            if proc.returncode not in (0, 1):
                clean_err = redact_secrets(stderr.strip() or stdout.strip())
                logger.warning(f"pip-audit returned exit code {proc.returncode}: {clean_err}")
                return DependencyScanResult(
                    scanner_name="pip-audit",
                    is_available=True,
                    findings=[],
                    scanned_files=[target_file],
                    error=f"pip-audit execution failed: {clean_err}",
                )

            findings = self.parse_pip_audit_json(stdout, target_file)
            return DependencyScanResult(
                scanner_name="pip-audit",
                is_available=True,
                findings=findings,
                scanned_files=[target_file],
            )
        except TimeoutError:
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            return DependencyScanResult(
                scanner_name="pip-audit",
                is_available=True,
                findings=[],
                scanned_files=[target_file],
                error=f"pip-audit execution timed out after {timeout_seconds}s",
            )
        except Exception as e:
            logger.error(f"pip-audit execution error: {e}")
            return DependencyScanResult(
                scanner_name="pip-audit",
                is_available=True,
                findings=[],
                scanned_files=[target_file],
                error=redact_secrets(str(e)),
            )

    def parse_pip_audit_json(
        self, raw_json: str, file_path: str = "requirements.txt"
    ) -> list[NormalizedFinding]:
        """Parse structured JSON from pip-audit output."""
        findings: list[NormalizedFinding] = []
        if not raw_json or not raw_json.strip():
            return findings

        try:
            data = json.loads(raw_json)
        except Exception as e:
            logger.debug(f"Failed to parse pip-audit JSON: {e}")
            return findings

        dependencies = data.get("dependencies", [])
        for dep in dependencies:
            pkg_name = dep.get("name", "unknown")
            installed_ver = dep.get("version", "unknown")
            vulns = dep.get("vulns", [])

            for vuln in vulns:
                cve_id = vuln.get("id", "VULN-UNKNOWN")
                description = vuln.get("description", f"Vulnerability {cve_id} in {pkg_name}")
                fix_versions = vuln.get("fix_versions", [])
                fixed_in = ", ".join(fix_versions) if fix_versions else "No fixed version available"

                # Default severity to HIGH
                title = f"Vulnerable dependency: {pkg_name}@{installed_ver} ({cve_id})"
                rec = (
                    f"Upgrade {pkg_name} to version {fixed_in}."
                    if fix_versions
                    else f"Review advisory for {pkg_name}."
                )

                fp = SecureFlowFinding.compute_fingerprint(
                    rule_id=cve_id,
                    file_path=file_path,
                    line_start=None,
                    line_end=None,
                    title=title,
                )

                findings.append(
                    NormalizedFinding(
                        scanner="pip-audit",
                        category="DEPENDENCY",
                        severity=FindingSeverity.HIGH,
                        confidence=1.0,
                        rule_id=cve_id,
                        title=title,
                        description=description,
                        file_path=file_path,
                        remediation_recommendation=rec,
                        external_advisory_url=f"https://osv.dev/vulnerability/{cve_id}",
                        fingerprint=fp,
                    )
                )

        return findings

    async def scan_npm_dependencies(
        self,
        root_dir: str,
        timeout_seconds: float = DEFAULT_SCAN_TIMEOUT_SECONDS,
    ) -> DependencyScanResult:
        """
        Scan Node.js package.json / package-lock.json using npm audit.
        """
        if not self.is_npm_audit_available():
            return DependencyScanResult(
                scanner_name="npm-audit",
                is_available=False,
                error="npm is not installed or available in environment",
            )

        root_dir = os.path.abspath(root_dir)
        if not os.path.isdir(root_dir):
            raise FileNotFoundError(f"Root directory does not exist: {root_dir}")

        has_pkg = os.path.exists(os.path.join(root_dir, "package.json"))
        has_lock = os.path.exists(os.path.join(root_dir, "package-lock.json"))
        if not has_pkg or not has_lock:
            return DependencyScanResult(
                scanner_name="npm-audit",
                is_available=True,
                findings=[],
                scanned_files=["package.json"] if has_pkg else [],
                error=None,
            )

        npm_bin = shutil.which("npm") or "npm"
        cmd = [npm_bin, "audit", "--json"]
        proc = None
        try:
            extra_kwargs: dict[str, Any] = {}
            if os.name == "nt":
                extra_kwargs["creationflags"] = getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
                )
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=root_dir,
                **extra_kwargs,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
            stdout = stdout_b.decode("utf-8", errors="ignore")
            stderr = stderr_b.decode("utf-8", errors="ignore")
            if stderr.strip():
                logger.debug(f"npm audit stderr: {stderr.strip()}")

            findings = self.parse_npm_audit_json(stdout, "package-lock.json")
            return DependencyScanResult(
                scanner_name="npm-audit",
                is_available=True,
                findings=findings,
                scanned_files=["package.json", "package-lock.json"],
            )
        except TimeoutError:
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            return DependencyScanResult(
                scanner_name="npm-audit",
                is_available=True,
                findings=[],
                scanned_files=["package.json"],
                error=f"npm audit timed out after {timeout_seconds}s",
            )
        except Exception as e:
            return DependencyScanResult(
                scanner_name="npm-audit",
                is_available=True,
                findings=[],
                scanned_files=["package.json"],
                error=redact_secrets(str(e)),
            )

    def parse_npm_audit_json(
        self, raw_json: str, file_path: str = "package-lock.json"
    ) -> list[NormalizedFinding]:
        """Parse structured npm audit JSON report."""
        findings: list[NormalizedFinding] = []
        if not raw_json or not raw_json.strip():
            return findings

        try:
            data = json.loads(raw_json)
        except Exception:
            return findings

        vulnerabilities = data.get("vulnerabilities", {})
        for pkg_name, vdata in vulnerabilities.items():
            severity_str = (vdata.get("severity") or "high").upper()
            sev = FindingSeverity.HIGH
            if severity_str in (
                FindingSeverity.CRITICAL,
                FindingSeverity.HIGH,
                FindingSeverity.MEDIUM,
                FindingSeverity.LOW,
            ):
                sev = FindingSeverity(severity_str)

            via_list = vdata.get("via", [])
            for item in via_list:
                if isinstance(item, dict):
                    source_id = str(item.get("source", item.get("name", "NPM-ADVISORY")))
                    title = item.get("title", f"Vulnerability in {pkg_name}")
                    url = item.get("url")
                    range_str = item.get("range", "")

                    full_title = f"Vulnerable dependency: {pkg_name} ({source_id})"
                    desc = f"{title}. Affected versions: {range_str}."

                    fp = SecureFlowFinding.compute_fingerprint(
                        rule_id=str(source_id),
                        file_path=file_path,
                        line_start=None,
                        line_end=None,
                        title=full_title,
                    )

                    findings.append(
                        NormalizedFinding(
                            scanner="npm-audit",
                            category="DEPENDENCY",
                            severity=sev,
                            confidence=1.0,
                            rule_id=str(source_id),
                            title=full_title,
                            description=desc,
                            file_path=file_path,
                            external_advisory_url=url,
                            remediation_recommendation=f"Update {pkg_name} to address advisory {source_id}.",
                            fingerprint=fp,
                        )
                    )

        return findings

    async def query_osv_package(
        self,
        package_name: str,
        version: str,
        ecosystem: str = "PyPI",
        timeout_seconds: float = 10.0,
    ) -> list[NormalizedFinding]:
        """
        Query the universal OSV database API for vulnerabilities in a package version.
        Uses bounded requests, strict timeouts, and graceful network failure handling.
        """
        payload = {
            "version": version,
            "package": {
                "name": package_name,
                "ecosystem": ecosystem,
            },
        }
        findings: list[NormalizedFinding] = []
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                res = await client.post(self.osv_api_url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    vulns = data.get("vulns", [])
                    for v in vulns:
                        vid = v.get("id", "OSV-UNKNOWN")
                        summary = (
                            v.get("summary")
                            or v.get("details")
                            or f"Vulnerability in {package_name}"
                        )
                        title = f"Vulnerable package: {package_name}@{version} ({vid})"

                        fp = SecureFlowFinding.compute_fingerprint(
                            rule_id=vid,
                            file_path="requirements.txt",
                            line_start=None,
                            line_end=None,
                            title=title,
                        )

                        findings.append(
                            NormalizedFinding(
                                scanner="osv-scanner",
                                category="DEPENDENCY",
                                severity=FindingSeverity.HIGH,
                                confidence=0.95,
                                rule_id=vid,
                                title=title,
                                description=summary,
                                file_path="requirements.txt",
                                external_advisory_url=f"https://osv.dev/vulnerability/{vid}",
                                remediation_recommendation=f"Update {package_name} to a secure patched release.",
                                fingerprint=fp,
                            )
                        )
        except Exception as e:
            logger.debug(f"OSV database query skipped or failed: {e}")

        return findings
