from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.secureflow import (
    ScanEventType,
    SecureFlowScan,
    SecureFlowScanEvent,
    SecureFlowScanStatus,
)
from app.services.secureflow.dependency_scanner import DependencyScanner
from app.services.secureflow.finding_manager import FindingManager
from app.services.secureflow.remediation_bridge import DevPilotRemediationBridge
from app.services.secureflow.sast_scanner import SASTScanner
from app.services.secureflow.schemas import (
    NormalizedFinding,
    RemediationTaskResult,
    ScanExecutionSummary,
)
from app.services.secureflow.secret_scanner import SecretScanner

logger = logging.getLogger("orchestrix.secureflow.service")


class SecureFlowService:
    """
    SecureFlow — Application Security Analysis Agent Orchestration Service.
    Coordinates dependency vulnerability scanning, secret detection, and SAST.
    Emits granular scan lifecycle audit events and calculates aggregate statistics.
    Supports partial completion when individual scanners are unavailable without false claims.
    """

    def __init__(
        self,
        secret_scanner: SecretScanner | None = None,
        dependency_scanner: DependencyScanner | None = None,
        sast_scanner: SASTScanner | None = None,
        finding_manager: FindingManager | None = None,
        remediation_bridge: DevPilotRemediationBridge | None = None,
    ) -> None:
        self.secret_scanner = secret_scanner or SecretScanner()
        self.dependency_scanner = dependency_scanner or DependencyScanner()
        self.sast_scanner = sast_scanner or SASTScanner()
        self.finding_manager = finding_manager or FindingManager()
        self.remediation_bridge = remediation_bridge or DevPilotRemediationBridge()

    async def run_scan(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        target_dir: str,
        scan_type: str = "FULL",
        snapshot_id: uuid.UUID | None = None,
    ) -> ScanExecutionSummary:
        """
        Execute an end-to-end multi-scanner security analysis against a repository directory.
        """
        # 1. Initialize SecureFlowScan record in PENDING / RUNNING status
        scan = SecureFlowScan(
            workspace_id=workspace_id,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            scan_type=scan_type,
            status=SecureFlowScanStatus.RUNNING,
            scanners_used=[],
            total_findings=0,
            critical_count=0,
            high_count=0,
            medium_count=0,
            low_count=0,
            started_at=utc_now(),
            created_at=utc_now(),
        )
        db.add(scan)
        await db.commit()
        await db.refresh(scan)

        # 2. Emit initial SCAN_STARTED audit event
        ev_start = SecureFlowScanEvent(
            scan_id=scan.id,
            event_type=ScanEventType.SCAN_STARTED,
            message=f"Initiated {scan_type} security scan session.",
            details={"scan_type": scan_type, "target_dir": target_dir},
            created_at=utc_now(),
        )
        db.add(ev_start)
        await db.commit()

        scanners_metadata: list[dict[str, Any]] = []
        all_findings: list[NormalizedFinding] = []
        has_unavailable_scanner = False

        # ----------------------------------------------------------------------
        # Scanner 1: Secret Scanner (Mandatory Credential Detection)
        # ----------------------------------------------------------------------
        await self._log_event(
            db, scan.id, ScanEventType.SCANNER_STARTED, "Started secret-scanner analysis."
        )
        secret_res = self.secret_scanner.scan_directory(target_dir)
        scanners_metadata.append(
            {
                "name": "secret-scanner",
                "available": secret_res.is_available,
                "status": "COMPLETED" if not secret_res.error else "FAILED",
                "files_scanned": secret_res.scanned_files_count,
                "findings": len(secret_res.findings),
            }
        )
        all_findings.extend(secret_res.findings)
        await self._log_event(
            db,
            scan.id,
            ScanEventType.SCANNER_COMPLETED,
            f"Completed secret-scanner analysis with {len(secret_res.findings)} findings.",
        )

        # ----------------------------------------------------------------------
        # Scanner 2: Dependency Scanner (pip-audit & npm audit)
        # ----------------------------------------------------------------------
        await self._log_event(
            db, scan.id, ScanEventType.SCANNER_STARTED, "Started dependency vulnerability analysis."
        )
        py_dep_res = await self.dependency_scanner.scan_python_dependencies(target_dir)
        if not py_dep_res.is_available:
            has_unavailable_scanner = True
        scanners_metadata.append(
            {
                "name": "pip-audit",
                "available": py_dep_res.is_available,
                "status": "COMPLETED" if py_dep_res.is_available else "UNAVAILABLE",
                "error": py_dep_res.error,
                "findings": len(py_dep_res.findings),
            }
        )
        all_findings.extend(py_dep_res.findings)

        # Also check npm dependencies if present
        npm_dep_res = await self.dependency_scanner.scan_npm_dependencies(target_dir)
        scanners_metadata.append(
            {
                "name": "npm-audit",
                "available": npm_dep_res.is_available,
                "status": "COMPLETED" if npm_dep_res.is_available else "UNAVAILABLE",
                "error": npm_dep_res.error,
                "findings": len(npm_dep_res.findings),
            }
        )
        all_findings.extend(npm_dep_res.findings)
        await self._log_event(
            db,
            scan.id,
            ScanEventType.SCANNER_COMPLETED,
            f"Completed dependency analysis. Total dependency findings: {len(py_dep_res.findings) + len(npm_dep_res.findings)}.",
        )

        # ----------------------------------------------------------------------
        # Scanner 3: Static Application Security Testing (SAST - Semgrep)
        # ----------------------------------------------------------------------
        await self._log_event(
            db, scan.id, ScanEventType.SCANNER_STARTED, "Started Semgrep SAST analysis."
        )
        sast_res = await self.sast_scanner.scan_directory(target_dir)
        if not sast_res.is_available:
            has_unavailable_scanner = True
        scanners_metadata.append(
            {
                "name": "semgrep",
                "available": sast_res.is_available,
                "status": "COMPLETED"
                if sast_res.is_available and not sast_res.error
                else ("UNAVAILABLE" if not sast_res.is_available else "FAILED"),
                "error": sast_res.error,
                "findings": len(sast_res.findings),
            }
        )
        all_findings.extend(sast_res.findings)
        await self._log_event(
            db,
            scan.id,
            ScanEventType.SCANNER_COMPLETED,
            f"Completed SAST analysis (available: {sast_res.is_available}). Findings: {len(sast_res.findings)}.",
        )

        # ----------------------------------------------------------------------
        # Reconcile, Deduplicate, and Persist Findings
        # ----------------------------------------------------------------------
        await self.finding_manager.persist_and_reconcile_findings(
            db=db,
            workspace_id=workspace_id,
            repository_id=repository_id,
            scan_id=scan.id,
            new_findings=all_findings,
        )

        # ----------------------------------------------------------------------
        # Final Scan Status: PARTIALLY_COMPLETED if any scanner was unavailable
        # ----------------------------------------------------------------------
        final_status = SecureFlowScanStatus.COMPLETED
        if has_unavailable_scanner:
            final_status = SecureFlowScanStatus.PARTIALLY_COMPLETED

        scan.status = final_status
        scan.scanners_used = scanners_metadata
        scan.completed_at = utc_now()
        await db.commit()
        await db.refresh(scan)

        # Final audit event
        await self._log_event(
            db,
            scan.id,
            ScanEventType.SCAN_COMPLETED,
            f"Security scan completed with status '{final_status}'. Total findings: {scan.total_findings}.",
        )

        return ScanExecutionSummary(
            scan_id=scan.id,
            workspace_id=scan.workspace_id,
            repository_id=scan.repository_id,
            status=scan.status,
            scanners_used=scan.scanners_used,
            total_findings=scan.total_findings,
            critical_count=scan.critical_count,
            high_count=scan.high_count,
            medium_count=scan.medium_count,
            low_count=scan.low_count,
            started_at=scan.started_at,
            completed_at=scan.completed_at,
            findings=all_findings,
        )

    async def create_remediation_task(
        self,
        db: AsyncSession,
        finding_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
    ) -> RemediationTaskResult:
        """
        Convert a finding into a DevPilot remediation task with explicit human approval gates.
        """
        return await self.remediation_bridge.create_remediation_task(
            db=db,
            finding_id=finding_id,
            user_id=user_id,
        )

    async def _log_event(
        self,
        db: AsyncSession,
        scan_id: uuid.UUID,
        event_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = SecureFlowScanEvent(
            scan_id=scan_id,
            event_type=event_type,
            message=message,
            details=details or {},
            created_at=utc_now(),
        )
        db.add(event)
        await db.commit()
