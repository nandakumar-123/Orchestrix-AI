from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from typing import Any

from app.db.models.secureflow import FindingSeverity, SecureFlowFinding
from app.services.secureflow.redaction import redact_secrets, sanitize_evidence_line
from app.services.secureflow.schemas import NormalizedFinding, SASTScanResult

logger = logging.getLogger("orchestrix.secureflow.sast_scanner")

SEMGREP_SEVERITY_MAP = {
    "ERROR": FindingSeverity.HIGH,
    "WARNING": FindingSeverity.MEDIUM,
    "INFO": FindingSeverity.LOW,
}

OWASP_CATEGORY_RULES = {
    "sql-injection": "A03:2021-Injection",
    "xss": "A03:2021-Injection",
    "command-injection": "A03:2021-Injection",
    "path-traversal": "A01:2021-Broken Access Control",
    "deserialization": "A08:2021-Software and Data Integrity Failures",
    "crypto": "A02:2021-Cryptographic Failures",
    "hardcoded-secret": "A07:2021-Identification and Authentication Failures",
}


class SASTScanner:
    """
    Static Application Security Testing (SAST) Scanner.
    Integrates Semgrep when installed in the environment.
    Covers OWASP Top 10 vulnerabilities (SQLi, XSS, Command Injection, Path Traversal).
    Guarantees that an unavailable scanner is never reported as clean.
    """

    def __init__(self, semgrep_bin: str | None = None) -> None:
        self.semgrep_bin = semgrep_bin or shutil.which("semgrep")

    def is_available(self) -> bool:
        """Return True if Semgrep CLI binary is found on system."""
        return bool(
            self.semgrep_bin and os.path.exists(self.semgrep_bin) or shutil.which("semgrep")
        )

    async def scan_directory(
        self,
        root_dir: str,
        timeout_seconds: float = 45.0,
        custom_config: str = "auto",
    ) -> SASTScanResult:
        """
        Execute Semgrep SAST scan over repository directory.
        """
        # Validate custom_config to prevent command injection and path traversal
        if (
            not custom_config
            or not re.match(r"^[a-zA-Z0-9_\-\./]+$", custom_config)
            or ".." in custom_config
        ):
            raise ValueError(f"Invalid or unsafe Semgrep config: '{custom_config}'")

        root_dir = os.path.abspath(root_dir)
        if not os.path.isdir(root_dir):
            raise FileNotFoundError(f"Root directory does not exist: {root_dir}")

        if not self.is_available():
            return SASTScanResult(
                scanner_name="semgrep",
                is_available=False,
                error="Semgrep is not installed or available on this host. Install via 'pip install semgrep' or install Semgrep CLI binary.",
            )

        cmd_bin = self.semgrep_bin or shutil.which("semgrep") or "semgrep"
        cmd = [
            cmd_bin,
            "scan",
            "--config",
            custom_config,
            "--json",
            "--quiet",
            "--no-git-ignore",  # Respect our own file boundaries
            root_dir,
        ]

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

            # Semgrep exits with 0 (clean or findings) or 1 (findings present in some versions)
            if proc.returncode not in (0, 1):
                clean_err = redact_secrets(stderr.strip() or stdout.strip())
                return SASTScanResult(
                    scanner_name="semgrep",
                    is_available=True,
                    findings=[],
                    error=f"Semgrep execution error (exit code {proc.returncode}): {clean_err}",
                )

            findings = self.parse_semgrep_json(stdout, root_dir)
            return SASTScanResult(
                scanner_name="semgrep",
                is_available=True,
                findings=findings,
                rules_run_count=len(findings),
            )
        except TimeoutError:
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            return SASTScanResult(
                scanner_name="semgrep",
                is_available=True,
                findings=[],
                error=f"Semgrep scan timed out after {timeout_seconds}s",
            )
        except Exception as e:
            return SASTScanResult(
                scanner_name="semgrep",
                is_available=True,
                findings=[],
                error=redact_secrets(str(e)),
            )

    def parse_semgrep_json(self, raw_json: str, root_dir: str = "") -> list[NormalizedFinding]:
        """Parse structured Semgrep JSON findings."""
        findings: list[NormalizedFinding] = []
        if not raw_json or not raw_json.strip():
            return findings

        try:
            data = json.loads(raw_json)
        except Exception as e:
            logger.debug(f"Failed to parse Semgrep JSON output: {e}")
            return findings

        results = data.get("results", [])
        for r in results:
            check_id = r.get("check_id", "semgrep.security.rule")
            path = r.get("path", "").replace("\\", "/")
            if root_dir and (os.path.isabs(path) or path.startswith(root_dir)):
                try:
                    path = os.path.relpath(path, root_dir).replace("\\", "/")
                except Exception:
                    pass

            start_line = r.get("start", {}).get("line")
            end_line = r.get("end", {}).get("line")
            extra = r.get("extra", {})
            message = extra.get("message", "Security vulnerability detected by Semgrep.")
            raw_sev = extra.get("severity", "WARNING").upper()
            sev = SEMGREP_SEVERITY_MAP.get(raw_sev, FindingSeverity.MEDIUM)

            metadata = extra.get("metadata", {})
            cwe = metadata.get("cwe", [])
            owasp = metadata.get("owasp", [])
            raw_title = f"{check_id.split('.')[-1].replace('-', ' ').title()} in {path}"

            cwe_suffix = f" ({cwe[0]})" if cwe else ""
            desc = f"{message}{cwe_suffix}"

            fp = SecureFlowFinding.compute_fingerprint(
                rule_id=check_id,
                file_path=path,
                line_start=start_line,
                line_end=end_line,
                title=raw_title,
            )

            raw_lines = extra.get("lines")
            clean_evidence = sanitize_evidence_line(raw_lines) if raw_lines else None

            rec = f"Review and remediate according to {owasp[0] if owasp else 'OWASP guidelines'}."
            findings.append(
                NormalizedFinding(
                    scanner="semgrep",
                    category="SAST",
                    severity=sev,
                    confidence=0.90,
                    rule_id=check_id,
                    title=redact_secrets(raw_title),
                    description=redact_secrets(desc),
                    redacted_evidence=clean_evidence,
                    file_path=path,
                    line_start=start_line,
                    line_end=end_line,
                    remediation_recommendation=rec,
                    external_advisory_url=f"https://semgrep.dev/r/{check_id}",
                    fingerprint=fp,
                )
            )

        return findings
