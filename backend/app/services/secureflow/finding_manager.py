from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models.secureflow import (
    FindingSeverity,
    FindingStatus,
    ScanEventType,
    SecureFlowFinding,
    SecureFlowScan,
    SecureFlowScanEvent,
)
from app.services.secureflow.redaction import redact_secrets, sanitize_evidence_line
from app.services.secureflow.schemas import NormalizedFinding

logger = logging.getLogger("orchestrix.secureflow.finding_manager")


class FindingManager:
    """
    SecureFlow Finding Lifecycle and Deduplication Manager.
    Enforces repository-scoped deduplication using deterministic SHA-256 fingerprints.
    Guarantees evidence sanitization, reconciles repeated scans, records audit events,
    and updates scan aggregate counts.
    """

    async def persist_and_reconcile_findings(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID,
        scan_id: uuid.UUID,
        new_findings: list[NormalizedFinding],
    ) -> list[SecureFlowFinding]:
        """
        Reconcile and persist findings for a scan execution.
        Deduplicates against existing findings for the repository.
        """
        persisted_findings: list[SecureFlowFinding] = []

        # 1. Fetch existing findings for this repository
        stmt = select(SecureFlowFinding).where(
            SecureFlowFinding.repository_id == repository_id,
            SecureFlowFinding.workspace_id == workspace_id,
        )
        existing_res = await db.execute(stmt)
        existing_by_fp: dict[str, SecureFlowFinding] = {
            f.fingerprint: f for f in existing_res.scalars().all()
        }

        # 2. Process findings
        for nf in new_findings:
            # Guarantee fingerprint is present
            fp = nf.fingerprint or SecureFlowFinding.compute_fingerprint(
                rule_id=nf.rule_id,
                file_path=nf.file_path,
                line_start=nf.line_start,
                line_end=nf.line_end,
                title=nf.title,
            )

            # Mandatory Evidence Redaction Guardrail
            clean_evidence = (
                sanitize_evidence_line(nf.redacted_evidence or "") if nf.redacted_evidence else None
            )
            clean_title = redact_secrets(nf.title)
            clean_desc = redact_secrets(nf.description)
            clean_rec = (
                redact_secrets(nf.remediation_recommendation or "")
                if nf.remediation_recommendation
                else None
            )
            clean_snippet = (
                redact_secrets(nf.remediation_code_snippet or "")
                if nf.remediation_code_snippet
                else None
            )

            if fp in existing_by_fp:
                # Reconcile existing finding: update scan_id and timestamps without duplicating
                existing = existing_by_fp[fp]
                existing.scan_id = scan_id
                existing.updated_at = utc_now()
                # If it was resolved earlier but rediscovered, reopen it
                if existing.status == FindingStatus.RESOLVED:
                    existing.status = FindingStatus.OPEN
                persisted_findings.append(existing)
            else:
                # Create brand new finding
                finding = SecureFlowFinding(
                    workspace_id=workspace_id,
                    repository_id=repository_id,
                    scan_id=scan_id,
                    scanner=nf.scanner,
                    category=nf.category,
                    severity=nf.severity,
                    confidence=max(0.0, min(1.0, nf.confidence)),
                    file_path=nf.file_path,
                    line_start=nf.line_start,
                    line_end=nf.line_end,
                    rule_id=nf.rule_id,
                    title=clean_title,
                    description=clean_desc,
                    redacted_evidence=clean_evidence,
                    remediation_recommendation=clean_rec,
                    remediation_code_snippet=clean_snippet,
                    external_advisory_url=nf.external_advisory_url,
                    status=FindingStatus.OPEN,
                    fingerprint=fp,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
                db.add(finding)
                existing_by_fp[fp] = finding
                persisted_findings.append(finding)

        # 3. Update scan statistics
        scan = await db.get(SecureFlowScan, scan_id)
        if scan:
            crit = sum(1 for f in persisted_findings if f.severity == FindingSeverity.CRITICAL)
            high = sum(1 for f in persisted_findings if f.severity == FindingSeverity.HIGH)
            med = sum(1 for f in persisted_findings if f.severity == FindingSeverity.MEDIUM)
            low = sum(1 for f in persisted_findings if f.severity == FindingSeverity.LOW)

            scan.total_findings = len(persisted_findings)
            scan.critical_count = crit
            scan.high_count = high
            scan.medium_count = med
            scan.low_count = low

            # 4. Record audit event
            event = SecureFlowScanEvent(
                scan_id=scan_id,
                event_type=ScanEventType.FINDINGS_RECORDED,
                message=f"Recorded {len(persisted_findings)} security findings across scanners.",
                details={
                    "total": len(persisted_findings),
                    "critical": crit,
                    "high": high,
                    "medium": med,
                    "low": low,
                },
                created_at=utc_now(),
            )
            db.add(event)

        await db.commit()
        return persisted_findings

    async def update_finding_status(
        self,
        db: AsyncSession,
        finding_id: uuid.UUID,
        new_status: str,
        note: str | None = None,
    ) -> SecureFlowFinding | None:
        """
        Transition a finding status (e.g. to FALSE_POSITIVE, ACCEPTED_RISK, RESOLVED).
        """
        finding = await db.get(SecureFlowFinding, finding_id)
        if not finding:
            return None

        finding.status = new_status
        finding.updated_at = utc_now()
        await db.commit()
        await db.refresh(finding)
        return finding
