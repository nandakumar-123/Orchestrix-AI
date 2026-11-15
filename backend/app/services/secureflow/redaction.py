from __future__ import annotations

import re
from typing import Any

# ==============================================================================
# COMPILED SECRET PATTERNS FOR HIGH-PRECISION DETECTION AND REDACTION
# ==============================================================================

SECRET_PATTERNS = [
    # 1. GitHub Tokens (Fine-grained & Classic)
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"gho_[a-zA-Z0-9]{36}"),
    re.compile(r"github_pat_[a-zA-Z0-9_]{82}"),
    # 2. Google Cloud / Gemini API Keys
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    # 3. AWS Access Key IDs
    re.compile(r"\b(?:AKIA|ASIA|AROA)[A-Z0-9]{16}\b"),
    # 4. AWS Secret Access Keys
    re.compile(
        r"""(?i)(?:aws_secret_access_key|aws_secret_key)\s*[:=]\s*["']?([A-Za-z0-9/+=]{40})["']?"""
    ),
    # 5. Private Key PEM Blocks
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    # 6. Database Connection URLs with passwords
    re.compile(r"""(?i)(?:postgres(?:ql)?|mysql|mongodb|redis)://[^:\s]+:([^@\s]+)@[^\s]+"""),
    # 7. JWT / Bearer Tokens
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    # 8. Slack Bot / User Tokens
    re.compile(r"xox[baprs]-[0-9a-zA-Z]{10,48}"),
    # 9. Generic API Key & Secret Assignments
    re.compile(
        r"""(?i)(?:api[_-]?key|secret|token|password|auth[_-]?token)\s*[:=]\s*["']([^"'\s]{8,})["']"""
    ),
]

REDACTION_TOKEN = "[REDACTED_SECRET]"


def contains_secrets(text: str) -> bool:
    """Return True if any recognized secret pattern is detected."""
    if not text:
        return False
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            return True
    return False


def redact_secrets(text: str) -> str:
    """
    Scrub all detected API keys, credentials, private keys, and tokens from text.
    Replaces matched secret bytes with '[REDACTED_SECRET]'.
    """
    if not text:
        return ""

    sanitized = text
    for pat in SECRET_PATTERNS:
        # Check if regex has capture groups or full match
        if pat.groups > 0:
            # Replace only the sensitive captured group while preserving parameter name
            def _replacer(match: re.Match[str]) -> str:
                full = match.group(0)
                captured = match.group(1)
                return full.replace(captured, REDACTION_TOKEN)

            sanitized = pat.sub(_replacer, sanitized)
        else:
            sanitized = pat.sub(REDACTION_TOKEN, sanitized)

    return sanitized


def sanitize_evidence_line(line: str) -> str:
    """
    Sanitize an individual source code line containing an apparent secret.
    Guarantees no raw credential appears in finding evidence.
    """
    return redact_secrets(line).strip()


def redact_data_structure(data: Any) -> Any:
    """
    Recursively redact secrets across dictionaries, lists, and string values.
    Ensures structured payloads destined for LLMs or logging are completely safe.
    """
    if isinstance(data, str):
        return redact_secrets(data)
    elif isinstance(data, dict):
        return {k: redact_data_structure(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [redact_data_structure(item) for item in data]
    return data
