from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# TestPilot Schemas
# =============================================================================


class TestPilotFrameworkEnum(enum.StrEnum):
    PYTEST = "pytest"
    UNITTEST = "unittest"
    VITEST = "vitest"
    JEST = "jest"
    MOCHA = "mocha"
    CUSTOM = "custom"


class TestPilotTestTypeEnum(enum.StrEnum):
    UNIT = "unit"
    INTEGRATION = "integration"
    REGRESSION = "regression"
    EDGE_CASE = "edge_case"
    NEGATIVE = "negative"


class TestSuiteStatusEnum(enum.StrEnum):
    GENERATED = "GENERATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TestExecutionStatusEnum(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class TestResultOutcomeEnum(enum.StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"


# Request Schemas


class TestPilotDetectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subpath: str | None = Field(default=None, description="Optional repository subpath to analyze")


class TestPilotGenerateSuiteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    framework: TestPilotFrameworkEnum = Field(..., description="Testing framework to target")
    target_files: list[str] = Field(
        ..., min_length=1, description="Source files to generate tests for"
    )
    source_context: str = Field(
        ..., min_length=1, max_length=100000, description="Code context or snippet"
    )
    test_type: TestPilotTestTypeEnum = Field(
        default=TestPilotTestTypeEnum.UNIT, description="Category of tests"
    )
    snapshot_id: uuid.UUID | None = Field(default=None, description="Repository snapshot ID")
    symbols_info: list[dict[str, Any]] | None = Field(
        default=None, description="Target symbol definitions"
    )


class TestPilotRejectSuiteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=1000, description="Reason for rejection")


class TestPilotExecuteSuiteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    custom_command: str | None = Field(
        default=None, max_length=500, description="Optional custom runner command"
    )
    timeout_seconds: int = Field(
        default=120, ge=5, le=600, description="Execution timeout in seconds"
    )


class TestPilotDiagnoseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_context: str | None = Field(
        default=None, max_length=100000, description="Optional extra source context"
    )


class TestPilotImpactSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diff_text: str = Field(
        ..., min_length=1, max_length=500000, description="Unified git diff to analyze"
    )
    all_test_files: list[str] | None = Field(
        default=None, description="All discovered test files in repository"
    )


# Response Schemas


class DetectedFrameworkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    language: str
    framework: str
    config_file: str | None
    test_directory: str
    naming_convention: str
    runner_command: str
    is_available: bool
    confidence: float
    missing_requirements: list[str] = Field(default_factory=list)


class TestCaseItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID | None = None
    name: str
    description: str
    test_type: str
    target_symbol: str | None = None
    code: str
    is_edge_case: bool = False
    relevance_explanation: str = ""


class TestPilotSuiteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    workspace_id: uuid.UUID
    repository_id: uuid.UUID
    snapshot_id: uuid.UUID | None = None
    framework: str
    target_files: list[str]
    test_type: str
    test_cases: list[TestCaseItem]
    status: str
    created_at: datetime
    approved_at: datetime | None = None
    approved_by: uuid.UUID | None = None


class TestPilotSuiteListResponse(BaseModel):
    items: list[TestPilotSuiteResponse]
    total: int
    limit: int
    offset: int


class IndividualTestResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    execution_id: uuid.UUID
    test_name: str
    status: str
    duration_ms: int
    failure_message: str | None = None
    traceback: str | None = None


class TestExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    suite_id: uuid.UUID | None = None
    workspace_id: uuid.UUID
    repository_id: uuid.UUID
    command: str
    status: str
    exit_code: int | None = None
    duration_ms: int
    passed_count: int
    failed_count: int
    skipped_count: int
    error_message: str | None = None
    stdout: str
    stderr: str
    executed_at: datetime | None = None
    created_at: datetime


class TestExecutionListResponse(BaseModel):
    items: list[TestExecutionResponse]
    total: int
    limit: int
    offset: int


class CoverageReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    workspace_id: uuid.UUID
    repository_id: uuid.UUID
    execution_id: uuid.UUID | None = None
    line_coverage_pct: float | None = None
    branch_coverage_pct: float | None = None
    uncovered_files: list[str] = Field(default_factory=list)
    uncovered_functions: list[dict[str, Any]] = Field(default_factory=list)
    raw_report: dict[str, Any] | None = None
    created_at: datetime


class CoverageReportListResponse(BaseModel):
    items: list[CoverageReportResponse]
    total: int
    limit: int
    offset: int


class DiagnosisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    failing_test: str
    error_message: str
    traceback_parsed: dict[str, Any] = Field(default_factory=dict)
    root_cause_analysis: str
    fix_suggestions: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    confidence: float
    target_symbol: str | None = None


class ImpactTestSelectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    selected_tests: list[dict[str, Any]]
    impacted_symbols: list[str]
    risk_exposure_score: float
    change_summary: str
    rationale: list[str]


# =============================================================================
# SecureFlow Schemas
# =============================================================================


class ScanStatusEnum(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"


class FindingSeverityEnum(enum.StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class FindingStatusEnum(enum.StrEnum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    ACCEPTED_RISK = "ACCEPTED_RISK"
    RESOLVED = "RESOLVED"


class ScanEventTypeEnum(enum.StrEnum):
    SCAN_STARTED = "SCAN_STARTED"
    SCANNER_STARTED = "SCANNER_STARTED"
    SCANNER_COMPLETED = "SCANNER_COMPLETED"
    SCANNER_FAILED = "SCANNER_FAILED"
    FINDINGS_RECORDED = "FINDINGS_RECORDED"
    SCAN_COMPLETED = "SCAN_COMPLETED"
    SCAN_FAILED = "SCAN_FAILED"
    SCAN_CANCELLED = "SCAN_CANCELLED"


# Request Schemas


class SecureFlowStartScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scan_type: str = Field(
        default="FULL", pattern=r"^(FULL|SECRETS|DEPENDENCIES|SAST)$", description="Scan mode"
    )
    snapshot_id: uuid.UUID | None = Field(default=None, description="Repository snapshot ID")
    subpath: str | None = Field(default=None, description="Optional subdirectory to restrict scan")


class SecureFlowUpdateFindingStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: FindingStatusEnum = Field(..., description="Target lifecycle status")
    note: str | None = Field(
        default=None, max_length=2000, description="Optional explanation or audit note"
    )


# Response Schemas


class ScannerStatusItem(BaseModel):
    scanner: str
    category: str
    is_available: bool
    version: str | None = None
    binary_path: str | None = None
    details: str | None = None


class ScannerAvailabilityResponse(BaseModel):
    scanners: list[ScannerStatusItem]
    all_available: bool


class SecureFlowFindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    workspace_id: uuid.UUID
    repository_id: uuid.UUID
    scan_id: uuid.UUID
    scanner: str
    category: str
    severity: str
    confidence: float
    rule_id: str
    title: str
    description: str
    redacted_evidence: str | None = None
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    remediation_recommendation: str | None = None
    remediation_code_snippet: str | None = None
    external_advisory_url: str | None = None
    fingerprint: str
    status: str
    created_at: datetime
    updated_at: datetime


class SecureFlowFindingListResponse(BaseModel):
    items: list[SecureFlowFindingResponse]
    total: int
    limit: int
    offset: int


class SecureFlowScanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    workspace_id: uuid.UUID
    repository_id: uuid.UUID
    snapshot_id: uuid.UUID | None = None
    scan_type: str
    status: str
    scanners_used: list[dict[str, Any]]
    total_findings: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class SecureFlowScanListResponse(BaseModel):
    items: list[SecureFlowScanResponse]
    total: int
    limit: int
    offset: int


class SecureFlowScanEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    scan_id: uuid.UUID
    event_type: str
    message: str
    details: dict[str, Any] | None = None
    created_at: datetime


class SecureFlowScanEventListResponse(BaseModel):
    items: list[SecureFlowScanEventResponse]
    total: int
    limit: int
    offset: int


class RemediationTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    finding_id: uuid.UUID
    devpilot_task_id: uuid.UUID
    task_title: str
    task_status: str
    requires_plan_approval: bool = True
    requires_code_approval: bool = True
