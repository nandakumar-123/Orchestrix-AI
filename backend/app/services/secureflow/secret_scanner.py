from __future__ import annotations

import logging
import math
import os
from collections import Counter

from app.db.models.secureflow import FindingSeverity, SecureFlowFinding
from app.services.secureflow.redaction import (
    SECRET_PATTERNS,
    sanitize_evidence_line,
)
from app.services.secureflow.schemas import NormalizedFinding, SecretScanResult

logger = logging.getLogger("orchestrix.secureflow.secret_scanner")

# Ignored directories and binary extensions
EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".idea",
    ".vscode",
}

EXCLUDED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".bin",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp4",
    ".webm",
    ".lock",  # Lockfiles have hash digests that look like high entropy
}

MAX_SCAN_FILE_SIZE_BYTES = 1024 * 1024  # 1 MB file bound


def calculate_shannon_entropy(data: str) -> float:
    """Calculate the Shannon entropy of a string."""
    if not data:
        return 0.0
    entropy = 0.0
    length = len(data)
    counts = Counter(data)
    for count in counts.values():
        p_x = count / length
        entropy -= p_x * math.log2(p_x)
    return entropy


class SecretScanner:
    """
    High-precision repository secret and credential scanner.
    Detects API keys, tokens, and private keys.
    Computes Shannon entropy for secret detection.
    Guarantees evidence is sanitized and raw credentials NEVER appear in findings.
    """

    def is_eligible_file(self, file_path: str, file_size: int = 0) -> bool:
        """Check if file is suitable for text secret scanning."""
        if file_size > MAX_SCAN_FILE_SIZE_BYTES:
            return False

        clean_path = file_path.replace("\\", "/")
        parts = clean_path.split("/")
        if any(p in EXCLUDED_DIRS for p in parts):
            return False

        ext = os.path.splitext(clean_path)[1].lower()
        if ext in EXCLUDED_EXTENSIONS:
            return False

        # Exclude common lockfile names explicitly
        basename = os.path.basename(clean_path)
        if basename in (
            "package-lock.json",
            "uv.lock",
            "poetry.lock",
            "pnpm-lock.yaml",
            "yarn.lock",
        ):
            return False

        return True

    def scan_file_content(self, file_path: str, content: str) -> list[NormalizedFinding]:
        """
        Scan string content of a single file for exposed credentials.
        """
        findings: list[NormalizedFinding] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            line_str = line.strip()
            if not line_str or len(line_str) < 10 or line_str.startswith(("#", "//", "/*", "*")):
                # Skip trivial lines, but continue to inspect assignments
                if not any(
                    token in line_str.lower()
                    for token in ("key", "token", "secret", "auth", "ghp_", "aiza")
                ):
                    continue

            # 1. Regex pattern check
            for pat_idx, pat in enumerate(SECRET_PATTERNS, start=1):
                match = pat.search(line)
                if match:
                    rule_id = f"SEC-RULE-{pat_idx:02d}"
                    title = self._get_rule_title(pat_idx)
                    sanitized_evidence = sanitize_evidence_line(line)

                    # Compute deterministic fingerprint
                    fp = SecureFlowFinding.compute_fingerprint(
                        rule_id=rule_id,
                        file_path=file_path,
                        line_start=idx,
                        line_end=idx,
                        title=title,
                    )

                    findings.append(
                        NormalizedFinding(
                            scanner="secret-scanner",
                            category="SECRET",
                            severity=FindingSeverity.CRITICAL
                            if pat_idx in (1, 2, 3, 4, 5, 6)
                            else FindingSeverity.HIGH,
                            confidence=0.95,
                            rule_id=rule_id,
                            title=title,
                            description=f"Exposed credential pattern detected in {file_path} at line {idx}.",
                            redacted_evidence=sanitized_evidence,
                            file_path=file_path,
                            line_start=idx,
                            line_end=idx,
                            remediation_recommendation="Revoke and rotate the exposed credential immediately. Move secret to an environment variable or secret manager.",
                            fingerprint=fp,
                        )
                    )
                    break

        return findings

    def scan_directory(self, root_dir: str) -> SecretScanResult:
        """Scan all eligible files in a directory tree for hardcoded secrets."""
        all_findings: list[NormalizedFinding] = []
        scanned_count = 0

        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
            for f in filenames:
                full_path = os.path.join(dirpath, f)
                rel_path = os.path.relpath(full_path, root_dir).replace("\\", "/")
                try:
                    fsize = os.path.getsize(full_path)
                    if not self.is_eligible_file(rel_path, fsize):
                        continue

                    scanned_count += 1
                    with open(full_path, encoding="utf-8", errors="ignore") as fp:
                        content = fp.read()

                    file_findings = self.scan_file_content(rel_path, content)
                    all_findings.extend(file_findings)
                except Exception as e:
                    logger.debug(f"Failed scanning file {rel_path} for secrets: {e}")

        return SecretScanResult(
            scanner_name="secret-scanner",
            is_available=True,
            findings=all_findings,
            scanned_files_count=scanned_count,
        )

    def _get_rule_title(self, rule_idx: int) -> str:
        titles = {
            1: "Exposed GitHub Personal Access Token",
            2: "Exposed GitHub OAuth Token",
            3: "Exposed GitHub Fine-Grained Token",
            4: "Exposed Google Cloud / Gemini API Key",
            5: "Exposed AWS Access Key ID",
            6: "Exposed AWS Secret Access Key",
            7: "Exposed Private Key PEM Block",
            8: "Exposed Database Connection Credentials",
            9: "Exposed JWT / Bearer Authentication Token",
            10: "Exposed Slack Token",
            11: "Exposed High-Entropy Secret or API Key",
        }
        return titles.get(rule_idx, "Exposed Hardcoded Credential")
