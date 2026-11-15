from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    enforce_csrf_protection,
    get_current_user,
)
from app.api.v1.permissions import (
    require_workspace_admin,
    require_workspace_member,
    require_workspace_viewer,
)
from app.api.v1.schemas_agents import (
    RemediationTaskResponse,
    ScannerAvailabilityResponse,
    ScannerStatusItem,
    SecureFlowFindingListResponse,
    SecureFlowFindingResponse,
    SecureFlowScanEventListResponse,
    SecureFlowScanEventResponse,
    SecureFlowScanListResponse,
    SecureFlowScanResponse,
    SecureFlowStartScanRequest,
    SecureFlowUpdateFindingStatusRequest,
)
from app.db.models.devpilot import DevPilotTask
from app.db.models.membership import WorkspaceMembership
from app.db.models.repository import Repository
from app.db.models.secureflow import (
    SecureFlowFinding,
    SecureFlowScan,
    SecureFlowScanEvent,
)
from app.db.models.user import User
from app.db.session import get_db_session
from app.services.devpilot.workspace_manager import TaskWorkspaceManager
from app.services.secureflow.exceptions import SecureFlowError
from app.services.secureflow.redaction import redact_secrets
from app.services.secureflow.service import SecureFlowService

secureflow_router = APIRouter(prefix="/repositories", tags=["secureflow"])
logger = logging.getLogger("orchestrix.api.secureflow")

_secureflow_service: SecureFlowService | None = None


def get_secureflow_service() -> SecureFlowService:
    global _secureflow_service
    if _secureflow_service is None:
        _secureflow_service = SecureFlowService()
    return _secureflow_service


def _format_scan_response(scan: SecureFlowScan) -> SecureFlowScanResponse:
    return SecureFlowScanResponse(
        id=scan.id,
        workspace_id=scan.workspace_id,
        repository_id=scan.repository_id,
        snapshot_id=scan.snapshot_id,
        scan_type=scan.scan_type,
        status=scan.status,
        scanners_used=scan.scanners_used or [],
        total_findings=scan.total_findings,
        critical_count=scan.critical_count,
        high_count=scan.high_count,
        medium_count=scan.medium_count,
        low_count=scan.low_count,
        started_at=scan.started_at,
        completed_at=scan.completed_at,
        created_at=scan.created_at,
    )


def _format_finding_response(finding: SecureFlowFinding) -> SecureFlowFindingResponse:
    return SecureFlowFindingResponse(
        id=finding.id,
        workspace_id=finding.workspace_id,
        repository_id=finding.repository_id,
        scan_id=finding.scan_id,
        scanner=finding.scanner,
        category=finding.category,
        severity=finding.severity,
        confidence=finding.confidence,
        rule_id=finding.rule_id,
        title=redact_secrets(finding.title),
        description=redact_secrets(finding.description),
        redacted_evidence=finding.redacted_evidence,
        file_path=finding.file_path,
        line_start=finding.line_start,
        line_end=finding.line_end,
        remediation_recommendation=finding.remediation_recommendation,
        remediation_code_snippet=finding.remediation_code_snippet,
        external_advisory_url=finding.external_advisory_url,
        fingerprint=finding.fingerprint,
        status=finding.status,
        created_at=finding.created_at,
        updated_at=finding.updated_at,
    )


# -----------------------------------------------------------------------------
# 1. Start Security Scan (MEMBER)
# -----------------------------------------------------------------------------


@secureflow_router.post(
    "/{repository_id}/secureflow/scans",
    response_model=SecureFlowScanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger an automated security scan (Secret, Dependency, and SAST)",
)
async def start_security_scan(
    repository_id: uuid.UUID,
    payload: SecureFlowStartScanRequest | None = None,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_member),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
    service: SecureFlowService = Depends(get_secureflow_service),
) -> SecureFlowScanResponse:
    repo, workspace_id, _membership = auth_ctx
    wm = TaskWorkspaceManager()
    target_dir = wm.get_task_workspace_dir(repo.id)
    scan_type = payload.scan_type if payload else "FULL"
    snapshot_id = payload.snapshot_id if payload else None

    if payload and payload.subpath:
        clean_sub = payload.subpath.replace("\\", "/").strip().lstrip("/")
        if ".." in clean_sub.split("/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Path traversal detected in subpath",
            )
        target_dir = os.path.join(target_dir, clean_sub)

    os.makedirs(target_dir, exist_ok=True)

    try:
        summary = await service.run_scan(
            db=db,
            workspace_id=workspace_id,
            repository_id=repo.id,
            target_dir=target_dir,
            scan_type=scan_type,
            snapshot_id=snapshot_id,
        )
        stmt = select(SecureFlowScan).where(SecureFlowScan.id == summary.scan_id)
        scan = (await db.execute(stmt)).scalar_one()
        return _format_scan_response(scan)
    except SecureFlowError as e:
        logger.warning(f"SecureFlow scan error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.exception(f"Unexpected error running security scan: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Security scan encountered an internal error",
        ) from e


# -----------------------------------------------------------------------------
# 2. List Security Scans (VIEWER)
# -----------------------------------------------------------------------------


@secureflow_router.get(
    "/{repository_id}/secureflow/scans",
    response_model=SecureFlowScanListResponse,
    status_code=status.HTTP_200_OK,
    summary="List security scans for a repository",
)
async def list_security_scans(
    repository_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    db: AsyncSession = Depends(get_db_session),
) -> SecureFlowScanListResponse:
    repo, workspace_id, _membership = auth_ctx
    stmt = select(SecureFlowScan).where(
        SecureFlowScan.workspace_id == workspace_id,
        SecureFlowScan.repository_id == repo.id,
    )
    if status_filter:
        stmt = stmt.where(SecureFlowScan.status == status_filter)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(desc(SecureFlowScan.created_at)).offset(offset).limit(limit)
    res = await db.execute(stmt)
    scans = res.scalars().all()

    return SecureFlowScanListResponse(
        items=[_format_scan_response(s) for s in scans],
        total=total,
        limit=limit,
        offset=offset,
    )


# -----------------------------------------------------------------------------
# 3. Retrieve Scan Details (VIEWER)
# -----------------------------------------------------------------------------


@secureflow_router.get(
    "/{repository_id}/secureflow/scans/{scan_id}",
    response_model=SecureFlowScanResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve details of a security scan session",
)
async def get_security_scan(
    repository_id: uuid.UUID,
    scan_id: uuid.UUID,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    db: AsyncSession = Depends(get_db_session),
) -> SecureFlowScanResponse:
    repo, workspace_id, _membership = auth_ctx
    stmt = select(SecureFlowScan).where(
        SecureFlowScan.id == scan_id,
        SecureFlowScan.workspace_id == workspace_id,
        SecureFlowScan.repository_id == repo.id,
    )
    scan = (await db.execute(stmt)).scalar_one_or_none()
    if not scan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Security scan {scan_id} not found",
        )
    return _format_scan_response(scan)


# -----------------------------------------------------------------------------
# 4. Scanner Availability & Status (VIEWER)
# -----------------------------------------------------------------------------


@secureflow_router.get(
    "/{repository_id}/secureflow/scanners",
    response_model=ScannerAvailabilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve real-time availability and binary paths of integrated scanners",
)
async def get_scanner_availability(
    repository_id: uuid.UUID,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    service: SecureFlowService = Depends(get_secureflow_service),
) -> ScannerAvailabilityResponse:
    # 1. Secret Scanner (internal native engine, always available)
    secret_item = ScannerStatusItem(
        scanner="secret-scanner",
        category="SECRET",
        is_available=True,
        details="Native regex and Shannon entropy scanner with zero credential leakage",
    )

    # 2. Dependency Scanners (pip-audit, npm-audit, osv-scanner)
    pip_avail = service.dependency_scanner.is_pip_audit_available()
    pip_item = ScannerStatusItem(
        scanner="pip-audit",
        category="DEPENDENCY",
        is_available=pip_avail,
        details="Python package vulnerability audit",
    )

    npm_avail = service.dependency_scanner.is_npm_audit_available()
    npm_item = ScannerStatusItem(
        scanner="npm-audit",
        category="DEPENDENCY",
        is_available=npm_avail,
        details="Node.js npm audit dependency scanner",
    )

    osv_item = ScannerStatusItem(
        scanner="osv-scanner",
        category="DEPENDENCY",
        is_available=True,
        details="Open Source Vulnerabilities (OSV) universal HTTP client",
    )

    # 3. SAST Scanner (Semgrep)
    semgrep_avail = service.sast_scanner.is_available()
    semgrep_item = ScannerStatusItem(
        scanner="semgrep",
        category="SAST",
        is_available=semgrep_avail,
        binary_path=service.sast_scanner.semgrep_bin if semgrep_avail else None,
        details="Static application security testing for OWASP Top 10 vulnerabilities",
    )

    all_items = [secret_item, pip_item, npm_item, osv_item, semgrep_item]
    all_avail = all(it.is_available for it in all_items)

    return ScannerAvailabilityResponse(
        scanners=all_items,
        all_available=all_avail,
    )


# -----------------------------------------------------------------------------
# 5. List Security Findings (VIEWER)
# -----------------------------------------------------------------------------


@secureflow_router.get(
    "/{repository_id}/secureflow/findings",
    response_model=SecureFlowFindingListResponse,
    status_code=status.HTTP_200_OK,
    summary="List normalized security findings with filtering and pagination",
)
async def list_security_findings(
    repository_id: uuid.UUID,
    severity: str | None = Query(
        default=None, description="Filter by severity (CRITICAL, HIGH, MEDIUM, LOW)"
    ),
    finding_status: str | None = Query(
        default=None, alias="status", description="Filter by status (OPEN, CONFIRMED, etc.)"
    ),
    category: str | None = Query(
        default=None, description="Filter by category (SECRET, DEPENDENCY, SAST)"
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    db: AsyncSession = Depends(get_db_session),
) -> SecureFlowFindingListResponse:
    repo, workspace_id, _membership = auth_ctx
    stmt = select(SecureFlowFinding).where(
        SecureFlowFinding.workspace_id == workspace_id,
        SecureFlowFinding.repository_id == repo.id,
    )
    if severity:
        stmt = stmt.where(SecureFlowFinding.severity == severity.upper())
    if finding_status:
        stmt = stmt.where(SecureFlowFinding.status == finding_status.upper())
    if category:
        stmt = stmt.where(SecureFlowFinding.category == category.upper())

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(desc(SecureFlowFinding.created_at)).offset(offset).limit(limit)
    res = await db.execute(stmt)
    findings = res.scalars().all()

    return SecureFlowFindingListResponse(
        items=[_format_finding_response(f) for f in findings],
        total=total,
        limit=limit,
        offset=offset,
    )


# -----------------------------------------------------------------------------
# 6. Retrieve Individual Finding (VIEWER)
# -----------------------------------------------------------------------------


@secureflow_router.get(
    "/{repository_id}/secureflow/findings/{finding_id}",
    response_model=SecureFlowFindingResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve details of an individual security finding",
)
async def get_security_finding(
    repository_id: uuid.UUID,
    finding_id: uuid.UUID,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    db: AsyncSession = Depends(get_db_session),
) -> SecureFlowFindingResponse:
    repo, workspace_id, _membership = auth_ctx
    stmt = select(SecureFlowFinding).where(
        SecureFlowFinding.id == finding_id,
        SecureFlowFinding.workspace_id == workspace_id,
        SecureFlowFinding.repository_id == repo.id,
    )
    finding = (await db.execute(stmt)).scalar_one_or_none()
    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Security finding {finding_id} not found",
        )
    return _format_finding_response(finding)


# -----------------------------------------------------------------------------
# 7. Update Finding Status (MEMBER)
# -----------------------------------------------------------------------------


@secureflow_router.patch(
    "/{repository_id}/secureflow/findings/{finding_id}/status",
    response_model=SecureFlowFindingResponse,
    status_code=status.HTTP_200_OK,
    summary="Update finding lifecycle triage status",
)
async def update_finding_status(
    repository_id: uuid.UUID,
    finding_id: uuid.UUID,
    payload: SecureFlowUpdateFindingStatusRequest,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_member),
    _csrf: None = Depends(enforce_csrf_protection),
    db: AsyncSession = Depends(get_db_session),
    service: SecureFlowService = Depends(get_secureflow_service),
) -> SecureFlowFindingResponse:
    repo, workspace_id, _membership = auth_ctx
    stmt = select(SecureFlowFinding).where(
        SecureFlowFinding.id == finding_id,
        SecureFlowFinding.workspace_id == workspace_id,
        SecureFlowFinding.repository_id == repo.id,
    )
    finding = (await db.execute(stmt)).scalar_one_or_none()
    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Security finding {finding_id} not found",
        )

    updated = await service.finding_manager.update_finding_status(
        db=db,
        finding_id=finding_id,
        new_status=payload.status.value,
        note=payload.note,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Security finding {finding_id} could not be updated",
        )
    return _format_finding_response(updated)


# -----------------------------------------------------------------------------
# 8. Retrieve Scan Audit Events (VIEWER)
# -----------------------------------------------------------------------------


@secureflow_router.get(
    "/{repository_id}/secureflow/scans/{scan_id}/events",
    response_model=SecureFlowScanEventListResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve audit and lifecycle events for a security scan session",
)
async def get_scan_events(
    repository_id: uuid.UUID,
    scan_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    db: AsyncSession = Depends(get_db_session),
) -> SecureFlowScanEventListResponse:
    repo, workspace_id, _membership = auth_ctx
    scan_stmt = select(SecureFlowScan).where(
        SecureFlowScan.id == scan_id,
        SecureFlowScan.workspace_id == workspace_id,
        SecureFlowScan.repository_id == repo.id,
    )
    scan = (await db.execute(scan_stmt)).scalar_one_or_none()
    if not scan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Security scan {scan_id} not found",
        )

    stmt = select(SecureFlowScanEvent).where(SecureFlowScanEvent.scan_id == scan_id)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(SecureFlowScanEvent.created_at.asc()).offset(offset).limit(limit)
    res = await db.execute(stmt)
    events = res.scalars().all()

    return SecureFlowScanEventListResponse(
        items=[
            SecureFlowScanEventResponse(
                id=e.id,
                scan_id=e.scan_id,
                event_type=e.event_type,
                message=redact_secrets(e.message),
                details=e.details,
                created_at=e.created_at,
            )
            for e in events
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# -----------------------------------------------------------------------------
# 9. Request DevPilot Remediation (MEMBER)
# -----------------------------------------------------------------------------


@secureflow_router.post(
    "/{repository_id}/secureflow/findings/{finding_id}/remediate",
    response_model=RemediationTaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Create a DevPilot remediation task for a vulnerability (enforces human approval gates)",
)
async def create_remediation_task(
    repository_id: uuid.UUID,
    finding_id: uuid.UUID,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_member),
    _csrf: None = Depends(enforce_csrf_protection),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    service: SecureFlowService = Depends(get_secureflow_service),
) -> RemediationTaskResponse:
    repo, workspace_id, _membership = auth_ctx
    stmt = select(SecureFlowFinding).where(
        SecureFlowFinding.id == finding_id,
        SecureFlowFinding.workspace_id == workspace_id,
        SecureFlowFinding.repository_id == repo.id,
    )
    finding = (await db.execute(stmt)).scalar_one_or_none()
    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Security finding {finding_id} not found",
        )

    try:
        rem_res = await service.create_remediation_task(
            db=db,
            finding_id=finding_id,
            user_id=current_user.id,
        )
        return RemediationTaskResponse(
            finding_id=rem_res.finding_id,
            devpilot_task_id=rem_res.devpilot_task_id,
            task_title=rem_res.task_title,
            task_status=rem_res.task_status,
            requires_plan_approval=rem_res.requires_plan_approval,
            requires_code_approval=rem_res.requires_code_approval,
        )
    except SecureFlowError as e:
        logger.warning(f"Error initiating remediation task: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.exception(f"Unexpected error initiating remediation task: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create remediation task",
        ) from e


# -----------------------------------------------------------------------------
# 10. Retrieve Associated Remediation Task (VIEWER)
# -----------------------------------------------------------------------------


@secureflow_router.get(
    "/{repository_id}/secureflow/findings/{finding_id}/remediation",
    response_model=RemediationTaskResponse | None,
    status_code=status.HTTP_200_OK,
    summary="Retrieve the associated DevPilot remediation task for a finding, if one exists",
)
async def get_remediation_task(
    repository_id: uuid.UUID,
    finding_id: uuid.UUID,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_viewer),
    db: AsyncSession = Depends(get_db_session),
) -> RemediationTaskResponse | None:
    repo, workspace_id, _membership = auth_ctx
    stmt = select(SecureFlowFinding).where(
        SecureFlowFinding.id == finding_id,
        SecureFlowFinding.workspace_id == workspace_id,
        SecureFlowFinding.repository_id == repo.id,
    )
    finding = (await db.execute(stmt)).scalar_one_or_none()
    if not finding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Security finding {finding_id} not found",
        )

    if not finding.devpilot_task_id:
        return None

    task = await db.get(DevPilotTask, finding.devpilot_task_id)
    if not task:
        return None

    return RemediationTaskResponse(
        finding_id=finding.id,
        devpilot_task_id=task.id,
        task_title=task.title,
        task_status=task.status,
        requires_plan_approval=True,
        requires_code_approval=True,
    )


# -----------------------------------------------------------------------------
# 11. Security Administration Policy Inspection (ADMIN / OWNER)
# -----------------------------------------------------------------------------


@secureflow_router.get(
    "/{repository_id}/secureflow/admin/policy",
    status_code=status.HTTP_200_OK,
    summary="Retrieve workspace-level security administrative policy configuration (Admin/Owner only)",
)
async def get_security_policy(
    repository_id: uuid.UUID,
    auth_ctx: tuple[Repository, uuid.UUID, WorkspaceMembership] = Depends(require_workspace_admin),
) -> dict[str, Any]:
    repo, workspace_id, membership = auth_ctx
    return {
        "workspace_id": str(workspace_id),
        "repository_id": str(repo.id),
        "effective_role": membership.role.value,
        "enforce_remediation_approval_gates": True,
        "allowed_scanners": ["secret-scanner", "pip-audit", "npm-audit", "osv-scanner", "semgrep"],
        "secret_scrubbing_mandatory": True,
        "auto_push_blocked": True,
    }
