from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class NormalizedFinding:
    """Standardized representation of a detected security vulnerability or secret."""

    scanner: str  # "secret-scanner" | "pip-audit" | "npm-audit" | "osv-scanner" | "semgrep"
    category: str  # "SECRET" | "DEPENDENCY" | "SAST"
    severity: str  # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN"
    confidence: float  # 0.0 to 1.0
    rule_id: str
    title: str
    description: str
    redacted_evidence: str | None = None  # MUST NEVER contain raw secrets
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    remediation_recommendation: str | None = None
    remediation_code_snippet: str | None = None
    external_advisory_url: str | None = None
    fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanner": self.scanner,
            "category": self.category,
            "severity": self.severity,
            "confidence": round(self.confidence, 2),
            "rule_id": self.rule_id,
            "title": self.title,
            "description": self.description,
            "redacted_evidence": self.redacted_evidence,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "remediation_recommendation": self.remediation_recommendation,
            "remediation_code_snippet": self.remediation_code_snippet,
            "external_advisory_url": self.external_advisory_url,
            "fingerprint": self.fingerprint,
        }


@dataclass
class DependencyScanResult:
    """Result of software dependency vulnerability analysis."""

    scanner_name: str
    is_available: bool
    findings: list[NormalizedFinding] = field(default_factory=list)
    scanned_files: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanner_name": self.scanner_name,
            "is_available": self.is_available,
            "scanned_files": self.scanned_files,
            "findings_count": len(self.findings),
            "error": self.error,
        }


@dataclass
class SecretScanResult:
    """Result of repository secret and credential scanning."""

    scanner_name: str = "secret-scanner"
    is_available: bool = True
    findings: list[NormalizedFinding] = field(default_factory=list)
    scanned_files_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanner_name": self.scanner_name,
            "is_available": self.is_available,
            "scanned_files_count": self.scanned_files_count,
            "findings_count": len(self.findings),
            "error": self.error,
        }


@dataclass
class SASTScanResult:
    """Result of Static Application Security Testing analysis."""

    scanner_name: str = "semgrep"
    is_available: bool = False
    findings: list[NormalizedFinding] = field(default_factory=list)
    rules_run_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanner_name": self.scanner_name,
            "is_available": self.is_available,
            "rules_run_count": self.rules_run_count,
            "findings_count": len(self.findings),
            "error": self.error,
        }


@dataclass
class ScanExecutionSummary:
    """Consolidated summary of a multi-scanner SecureFlow analysis execution."""

    scan_id: uuid.UUID
    workspace_id: uuid.UUID
    repository_id: uuid.UUID
    status: str  # "COMPLETED" | "PARTIALLY_COMPLETED" | "FAILED" | "CANCELLED"
    scanners_used: list[dict[str, Any]]
    total_findings: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    started_at: datetime | None
    completed_at: datetime | None
    findings: list[NormalizedFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_id": str(self.scan_id),
            "workspace_id": str(self.workspace_id),
            "repository_id": str(self.repository_id),
            "status": self.status,
            "scanners_used": self.scanners_used,
            "total_findings": self.total_findings,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class RemediationTaskResult:
    """Result of converting a security finding into a DevPilot remediation task."""

    finding_id: uuid.UUID
    devpilot_task_id: uuid.UUID
    task_title: str
    task_status: str
    requires_plan_approval: bool = True
    requires_code_approval: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": str(self.finding_id),
            "devpilot_task_id": str(self.devpilot_task_id),
            "task_title": self.task_title,
            "task_status": self.task_status,
            "requires_plan_approval": self.requires_plan_approval,
            "requires_code_approval": self.requires_code_approval,
        }
