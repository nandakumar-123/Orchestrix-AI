from __future__ import annotations

import enum
import hashlib
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, utc_now

if TYPE_CHECKING:
    from app.db.models.devpilot import DevPilotTask
    from app.db.models.repository import Repository
    from app.db.models.repository_intelligence import RepositorySnapshot
    from app.db.models.workspace import Workspace

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class SecureFlowScanStatus(enum.StrEnum):
    """Lifecycle statuses for SecureFlow security scans."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"


class FindingSeverity(enum.StrEnum):
    """Standardized finding severity ratings."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class FindingStatus(enum.StrEnum):
    """Triage and lifecycle status of a detected security finding."""

    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    ACCEPTED_RISK = "ACCEPTED_RISK"
    RESOLVED = "RESOLVED"


class ScanEventType(enum.StrEnum):
    """Audit event categories logged during a security scan lifecycle."""

    SCAN_STARTED = "SCAN_STARTED"
    SCANNER_STARTED = "SCANNER_STARTED"
    SCANNER_COMPLETED = "SCANNER_COMPLETED"
    SCANNER_FAILED = "SCANNER_FAILED"
    FINDINGS_RECORDED = "FINDINGS_RECORDED"
    SCAN_COMPLETED = "SCAN_COMPLETED"
    SCAN_FAILED = "SCAN_FAILED"
    SCAN_CANCELLED = "SCAN_CANCELLED"


class SecureFlowScan(Base):
    """
    Security analysis scan session execution against a repository.
    Enforces tenant isolation by workspace_id and repository_id,
    with detailed scanner status, counts, and timing.
    """

    __tablename__ = "secureflow_scans"

    __table_args__ = (
        ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_secureflow_scans_repo_workspace",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'PARTIALLY_COMPLETED')",
            name="ck_secureflow_scans_status",
        ),
        CheckConstraint(
            "total_findings >= 0",
            name="ck_secureflow_scans_total_findings_nonnegative",
        ),
        CheckConstraint(
            "critical_count >= 0",
            name="ck_secureflow_scans_critical_count_nonnegative",
        ),
        CheckConstraint(
            "high_count >= 0",
            name="ck_secureflow_scans_high_count_nonnegative",
        ),
        CheckConstraint(
            "medium_count >= 0",
            name="ck_secureflow_scans_medium_count_nonnegative",
        ),
        CheckConstraint(
            "low_count >= 0",
            name="ck_secureflow_scans_low_count_nonnegative",
        ),
        Index("ix_secureflow_scans_workspace_id", "workspace_id"),
        Index("ix_secureflow_scans_repository_id", "repository_id"),
        Index("ix_secureflow_scans_snapshot_id", "snapshot_id"),
        Index("ix_secureflow_scans_status", "status"),
        Index("ix_secureflow_scans_scan_type", "scan_type"),
        Index("ix_secureflow_scans_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repository_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    scan_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=SecureFlowScanStatus.PENDING,
        nullable=False,
    )
    scanners_used: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_TYPE,
        default=list,
        nullable=False,
    )
    total_findings: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    critical_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    high_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    medium_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    low_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    workspace: Mapped[Workspace] = relationship(
        "Workspace", foreign_keys=[workspace_id], lazy="selectin"
    )
    repository: Mapped[Repository] = relationship(
        "Repository", foreign_keys=[repository_id], lazy="selectin"
    )
    snapshot: Mapped[RepositorySnapshot | None] = relationship(
        "RepositorySnapshot", lazy="selectin"
    )

    findings: Mapped[list[SecureFlowFinding]] = relationship(
        "SecureFlowFinding",
        back_populates="scan",
        cascade="all, delete-orphan",
        order_by="SecureFlowFinding.created_at.desc()",
        lazy="selectin",
    )
    events: Mapped[list[SecureFlowScanEvent]] = relationship(
        "SecureFlowScanEvent",
        back_populates="scan",
        cascade="all, delete-orphan",
        order_by="SecureFlowScanEvent.created_at.asc()",
        lazy="selectin",
    )


class SecureFlowFinding(Base):
    """
    Security finding detected across code, dependencies, or secrets.
    Enforces repository-scoped deduplication via stable SHA-256 fingerprint,
    preventing duplicate findings across repeated scans while preserving historical associations.
    Links optionally to a DevPilotTask for automated remediation.
    """

    __tablename__ = "secureflow_findings"

    __table_args__ = (
        ForeignKeyConstraint(
            ["repository_id", "workspace_id"],
            ["repositories.id", "repositories.workspace_id"],
            name="fk_secureflow_findings_repo_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "repository_id",
            "fingerprint",
            name="uq_secureflow_findings_repo_fingerprint",
        ),
        CheckConstraint(
            "severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN')",
            name="ck_secureflow_findings_severity",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'CONFIRMED', 'FALSE_POSITIVE', 'ACCEPTED_RISK', 'RESOLVED')",
            name="ck_secureflow_findings_status",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_secureflow_findings_confidence_range",
        ),
        CheckConstraint(
            "line_start IS NULL OR line_start > 0",
            name="ck_secureflow_findings_line_start_positive",
        ),
        CheckConstraint(
            "line_end IS NULL OR line_end > 0",
            name="ck_secureflow_findings_line_end_positive",
        ),
        CheckConstraint(
            "line_start IS NULL OR line_end IS NULL OR line_end >= line_start",
            name="ck_secureflow_findings_line_range_valid",
        ),
        Index("ix_secureflow_findings_workspace_id", "workspace_id"),
        Index("ix_secureflow_findings_repository_id", "repository_id"),
        Index("ix_secureflow_findings_scan_id", "scan_id"),
        Index("ix_secureflow_findings_severity", "severity"),
        Index("ix_secureflow_findings_status", "status"),
        Index("ix_secureflow_findings_category", "category"),
        Index("ix_secureflow_findings_fingerprint", "fingerprint"),
        Index("ix_secureflow_findings_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("secureflow_scans.id", ondelete="CASCADE"),
        nullable=False,
    )
    scanner: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        String(16),
        default=FindingSeverity.MEDIUM,
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        nullable=False,
    )
    file_path: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    line_start: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    line_end: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    rule_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    redacted_evidence: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    remediation_recommendation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    remediation_code_snippet: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    external_advisory_url: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=FindingStatus.OPEN,
        nullable=False,
    )
    devpilot_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devpilot_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    # Relationships
    workspace: Mapped[Workspace] = relationship(
        "Workspace", foreign_keys=[workspace_id], lazy="selectin"
    )
    repository: Mapped[Repository] = relationship(
        "Repository", foreign_keys=[repository_id], lazy="selectin"
    )
    scan: Mapped[SecureFlowScan] = relationship(
        "SecureFlowScan",
        back_populates="findings",
        lazy="selectin",
    )
    devpilot_task: Mapped[DevPilotTask | None] = relationship("DevPilotTask", lazy="selectin")

    @staticmethod
    def compute_fingerprint(
        rule_id: str,
        file_path: str | None,
        line_start: int | None,
        line_end: int | None,
        title: str,
    ) -> str:
        """
        Compute deterministic SHA-256 fingerprint for finding deduplication within a repository.
        Normalizes rule_id, path, line span, and title.
        """
        norm_rule = (rule_id or "").strip()
        norm_path = (file_path or "").strip().replace("\\", "/")
        norm_start = str(line_start or 0)
        norm_end = str(line_end or 0)
        norm_title = (title or "").strip()
        raw = f"{norm_rule}:{norm_path}:{norm_start}:{norm_end}:{norm_title}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SecureFlowScanEvent(Base):
    """
    Audit event record preserving the lifecycle and diagnostics of a SecureFlow scan.
    Guarantees immutable historical audit log for compliance.
    """

    __tablename__ = "secureflow_scan_events"

    __table_args__ = (
        Index("ix_secureflow_scan_events_scan_id", "scan_id"),
        Index("ix_secureflow_scan_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("secureflow_scans.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    scan: Mapped[SecureFlowScan] = relationship(
        "SecureFlowScan",
        back_populates="events",
        lazy="selectin",
    )
