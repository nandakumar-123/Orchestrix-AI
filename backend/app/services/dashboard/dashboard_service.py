from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import IndexingJobStatus
from app.db.models.devmemory import EngineeringMemory, MemoryVerificationStatus
from app.db.models.devpilot import DevPilotTask
from app.db.models.engineering_task import EngineeringTask
from app.db.models.flowforge import (
    WorkflowApproval,
    WorkflowApprovalStatus,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionStatus,
    WorkflowStatus,
)
from app.db.models.impactmind import ImpactAssessment
from app.db.models.repository import Repository
from app.db.models.repository_intelligence import IndexingJob
from app.db.models.secureflow import (
    FindingSeverity,
    FindingStatus,
    SecureFlowFinding,
    SecureFlowScan,
    SecureFlowScanStatus,
)
from app.db.models.testpilot import (
    TestExecutionStatus,
    TestPilotExecution,
)
from app.services.dashboard.schemas import (
    ActivityEventItem,
    AgentStatusSummary,
    DashboardMetrics,
    DashboardOverviewResponse,
    ImpactSummary,
    MemorySummary,
    RepositorySummary,
    SecuritySummary,
    TaskSummaryItem,
    WorkflowSummary,
)

logger = logging.getLogger("orchestrix.services.dashboard")


def _normalize_dt(dt: datetime | None) -> datetime:
    """Normalize datetime to timezone-aware UTC for robust sorting across drivers."""
    if dt is None:
        return datetime.min.replace(tzinfo=UTC)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class DashboardService:
    """Aggregates authentic workspace and repository metrics for dashboard consumption."""

    def __init__(self, db: AsyncSession | None = None) -> None:
        self.db = db

    async def get_overview(
        self,
        workspace_id: uuid.UUID,
        repository_id: uuid.UUID | None = None,
        db: AsyncSession | None = None,
        activity_limit: int = 15,
    ) -> DashboardOverviewResponse:
        session = db or self.db
        if session is None:
            raise ValueError("AsyncSession must be provided to DashboardService or get_overview")
        now = datetime.now(UTC)

        # ---------------------------------------------------------------------
        # 1. Repositories (Only active repositories)
        # ---------------------------------------------------------------------
        repo_stmt = select(Repository).where(
            Repository.workspace_id == workspace_id,
            Repository.is_active.is_(True),
        )
        if repository_id:
            repo_stmt = repo_stmt.where(Repository.id == repository_id)
        repo_result = await session.execute(repo_stmt)
        repos = list(repo_result.scalars().all())

        repo_summaries: list[RepositorySummary] = []
        indexed_repo_count = 0

        # Map all workspace repos (including historical) to name for task/activity display
        all_repo_stmt = select(Repository.id, Repository.name).where(Repository.workspace_id == workspace_id)
        all_repo_res = await session.execute(all_repo_stmt)
        repo_name_map: dict[uuid.UUID, str] = {row[0]: row[1] for row in all_repo_res.all()}

        for r in repos:
            # Latest indexing job for this repository
            idx_stmt = (
                select(IndexingJob)
                .where(
                    IndexingJob.repository_id == r.id,
                    IndexingJob.workspace_id == workspace_id,
                )
                .order_by(desc(IndexingJob.created_at))
                .limit(1)
            )
            idx_res = await session.execute(idx_stmt)
            latest_idx = idx_res.scalar_one_or_none()

            idx_status = "NOT_STARTED"
            last_indexed = None
            if latest_idx:
                idx_status = latest_idx.status.value if hasattr(latest_idx.status, "value") else str(latest_idx.status)
                last_indexed = latest_idx.completed_at or latest_idx.created_at
                if idx_status == IndexingJobStatus.COMPLETED:
                    indexed_repo_count += 1

            repo_summaries.append(
                RepositorySummary(
                    id=r.id,
                    name=r.name,
                    owner=r.owner_login,
                    default_branch=r.default_branch,
                    primary_language=r.language,
                    indexing_status=idx_status,
                    last_indexed_at=last_indexed,
                    is_private=(r.visibility == "private"),
                )
            )

        # ---------------------------------------------------------------------
        # 2. FlowForge Workflows & Executions
        # ---------------------------------------------------------------------
        wf_stmt = select(WorkflowDefinition).where(WorkflowDefinition.workspace_id == workspace_id)
        wf_res = await session.execute(wf_stmt)
        workflows = list(wf_res.scalars().all())

        total_wf = len(workflows)
        active_wf = sum(1 for w in workflows if w.status == WorkflowStatus.ACTIVE)
        paused_wf = sum(1 for w in workflows if w.status == WorkflowStatus.PAUSED)
        draft_wf = sum(1 for w in workflows if w.status == WorkflowStatus.DRAFT)

        # Executions
        exec_stmt = select(WorkflowExecution).where(WorkflowExecution.workspace_id == workspace_id)
        exec_res = await session.execute(exec_stmt)
        executions = list(exec_res.scalars().all())

        running_execs = sum(1 for e in executions if e.status == WorkflowExecutionStatus.RUNNING)
        failed_execs = sum(1 for e in executions if e.status in (WorkflowExecutionStatus.FAILED, WorkflowExecutionStatus.TIMED_OUT))

        # Workflow Approvals
        wf_appr_stmt = select(func.count(WorkflowApproval.id)).where(
            WorkflowApproval.workspace_id == workspace_id,
            WorkflowApproval.status == WorkflowApprovalStatus.PENDING,
        )
        wf_appr_res = await session.execute(wf_appr_stmt)
        wf_pending_approvals = wf_appr_res.scalar() or 0

        workflow_summary = WorkflowSummary(
            total_workflows=total_wf,
            active_workflows=active_wf,
            paused_workflows=paused_wf,
            draft_workflows=draft_wf,
            recent_executions=len(executions),
            running_executions=running_execs,
            failed_executions=failed_execs,
            pending_approvals=wf_pending_approvals,
        )

        # ---------------------------------------------------------------------
        # 3. DevMemory Statistics
        # ---------------------------------------------------------------------
        mem_stmt = select(EngineeringMemory).where(EngineeringMemory.workspace_id == workspace_id)
        if repository_id:
            mem_stmt = mem_stmt.where(EngineeringMemory.repository_id == repository_id)
        mem_res = await session.execute(mem_stmt)
        memories = list(mem_res.scalars().all())

        total_mems = len(memories)
        verified_mems = sum(1 for m in memories if m.verification_status == MemoryVerificationStatus.VERIFIED)
        unverified_mems = sum(1 for m in memories if m.verification_status == MemoryVerificationStatus.UNVERIFIED)
        outdated_mems = sum(1 for m in memories if m.verification_status == MemoryVerificationStatus.OUTDATED)
        archived_mems = sum(1 for m in memories if m.verification_status == MemoryVerificationStatus.ARCHIVED)

        memory_summary = MemorySummary(
            total_count=total_mems,
            verified_count=verified_mems,
            unverified_count=unverified_mems,
            outdated_count=outdated_mems,
            archived_count=archived_mems,
        )

        # ---------------------------------------------------------------------
        # 4. SecureFlow Security Statistics
        # ---------------------------------------------------------------------
        sec_find_stmt = select(SecureFlowFinding).where(SecureFlowFinding.workspace_id == workspace_id)
        if repository_id:
            sec_find_stmt = sec_find_stmt.where(SecureFlowFinding.repository_id == repository_id)
        sec_find_res = await session.execute(sec_find_stmt)
        findings = list(sec_find_res.scalars().all())

        open_findings = sum(1 for f in findings if f.status == FindingStatus.OPEN)
        confirmed_findings = sum(1 for f in findings if f.status == FindingStatus.CONFIRMED)
        accepted_risks = sum(1 for f in findings if f.status == FindingStatus.ACCEPTED_RISK)
        resolved_findings = sum(1 for f in findings if f.status == FindingStatus.RESOLVED)

        severity_counts = {
            FindingSeverity.CRITICAL.value: 0,
            FindingSeverity.HIGH.value: 0,
            FindingSeverity.MEDIUM.value: 0,
            FindingSeverity.LOW.value: 0,
            FindingSeverity.UNKNOWN.value: 0,
        }
        for f in findings:
            if f.status in (FindingStatus.OPEN, FindingStatus.CONFIRMED):
                sev_key = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
                severity_counts[sev_key] = severity_counts.get(sev_key, 0) + 1

        # Latest scan info
        scan_stmt = (
            select(SecureFlowScan)
            .where(SecureFlowScan.workspace_id == workspace_id)
            .order_by(desc(SecureFlowScan.created_at))
            .limit(1)
        )
        if repository_id:
            scan_stmt = scan_stmt.where(SecureFlowScan.repository_id == repository_id)
        scan_res = await session.execute(scan_stmt)
        latest_scan = scan_res.scalar_one_or_none()

        total_scans_stmt = select(func.count(SecureFlowScan.id)).where(SecureFlowScan.workspace_id == workspace_id)
        if repository_id:
            total_scans_stmt = total_scans_stmt.where(SecureFlowScan.repository_id == repository_id)
        total_scans_res = await session.execute(total_scans_stmt)
        total_scans = total_scans_res.scalar() or 0

        security_summary = SecuritySummary(
            open_findings=open_findings + confirmed_findings,
            confirmed_findings=confirmed_findings,
            accepted_risks=accepted_risks,
            resolved_findings=resolved_findings,
            severity_distribution=severity_counts,
            scans_count=total_scans,
            last_scan_at=latest_scan.completed_at if latest_scan else None,
            last_scan_status=latest_scan.status.value if (latest_scan and hasattr(latest_scan.status, "value")) else None,
        )

        # ---------------------------------------------------------------------
        # 5. ImpactMind Change Intelligence
        # ---------------------------------------------------------------------
        impact_stmt = (
            select(ImpactAssessment)
            .where(ImpactAssessment.workspace_id == workspace_id)
            .order_by(desc(ImpactAssessment.created_at))
        )
        if repository_id:
            impact_stmt = impact_stmt.where(ImpactAssessment.repository_id == repository_id)
        impact_res = await session.execute(impact_stmt)
        assessments = list(impact_res.scalars().all())

        latest_assessment = assessments[0] if assessments else None
        impact_summary = ImpactSummary(
            total_assessments=len(assessments),
            latest_risk_score=latest_assessment.structural_exposure_score if latest_assessment else None,
            latest_risk_tier=latest_assessment.exposure_tier if latest_assessment else None,
            latest_assessment_at=latest_assessment.completed_at or latest_assessment.created_at if latest_assessment else None,
            latest_changed_files_count=len(latest_assessment.change_summary.get("files", [])) if (latest_assessment and isinstance(latest_assessment.change_summary, dict)) else 0,
            latest_status=latest_assessment.status if latest_assessment else None,
        )

        # ---------------------------------------------------------------------
        # 6. Tasks (DevPilot + EngineeringTask)
        # ---------------------------------------------------------------------
        devpilot_task_stmt = select(DevPilotTask).where(DevPilotTask.workspace_id == workspace_id)
        if repository_id:
            devpilot_task_stmt = devpilot_task_stmt.where(DevPilotTask.repository_id == repository_id)
        devpilot_task_res = await session.execute(devpilot_task_stmt)
        dp_tasks = list(devpilot_task_res.scalars().all())

        eng_task_stmt = select(EngineeringTask).where(EngineeringTask.workspace_id == workspace_id)
        if repository_id:
            eng_task_stmt = eng_task_stmt.where(EngineeringTask.repository_id == repository_id)
        eng_task_res = await session.execute(eng_task_stmt)
        eng_tasks = list(eng_task_res.scalars().all())

        task_items: list[TaskSummaryItem] = []
        running_tasks_count = 0

        for t in dp_tasks:
            t_status = t.status.value if hasattr(t.status, "value") else str(t.status)
            if t_status in ("PLANNING", "GENERATING", "VALIDATING", "IN_PROGRESS", "ANALYZING", "REVIEWING", "APPLYING"):
                running_tasks_count += 1
            task_items.append(
                TaskSummaryItem(
                    id=t.id,
                    task_type="devpilot",
                    title=t.title,
                    status=t_status,
                    repository_id=t.repository_id,
                    repository_name=repo_name_map.get(t.repository_id),
                    assigned_agent="DevPilot",
                    updated_at=t.updated_at,
                )
            )

        for et in eng_tasks:
            et_status = et.status.value if hasattr(et.status, "value") else str(et.status)
            if et_status == "IN_PROGRESS":
                running_tasks_count += 1
            task_items.append(
                TaskSummaryItem(
                    id=et.id,
                    task_type="engineering_task",
                    title=et.title,
                    status=et_status,
                    repository_id=et.repository_id,
                    repository_name=repo_name_map.get(et.repository_id) if et.repository_id else None,
                    assigned_agent=et.assigned_agent or "Coordinator",
                    updated_at=et.updated_at or et.created_at,
                )
            )

        # Sort combined tasks by updated_at descending and keep top 8
        task_items.sort(key=lambda item: _normalize_dt(item.updated_at), reverse=True)
        recent_task_slice = task_items[:8]

        # ---------------------------------------------------------------------
        # 7. AI Agent Execution Status
        # ---------------------------------------------------------------------
        # DevPilot
        dp_active = sum(1 for t in dp_tasks if (t.status.value if hasattr(t.status, "value") else str(t.status)) in ("PLANNING", "GENERATING", "VALIDATING", "IN_PROGRESS", "ANALYZING", "REVIEWING", "APPLYING"))
        dp_completed = sum(1 for t in dp_tasks if (t.status.value if hasattr(t.status, "value") else str(t.status)) == "COMPLETED")
        dp_failed = sum(1 for t in dp_tasks if (t.status.value if hasattr(t.status, "value") else str(t.status)) == "FAILED")
        dp_latest = max((t.updated_at for t in dp_tasks), default=None)
        dp_current = next((t.title for t in dp_tasks if (t.status.value if hasattr(t.status, "value") else str(t.status)) in ("PLANNING", "GENERATING", "VALIDATING", "IN_PROGRESS", "ANALYZING", "REVIEWING", "APPLYING")), None)

        devpilot_status = "RUNNING" if dp_active > 0 else ("AVAILABLE" if len(dp_tasks) > 0 else "IDLE")

        # ImpactMind
        im_active = sum(1 for a in assessments if a.status == "ANALYZING")
        im_completed = sum(1 for a in assessments if a.status == "COMPLETED")
        im_failed = sum(1 for a in assessments if a.status == "FAILED")
        im_latest = max((a.created_at for a in assessments), default=None)
        impactmind_status = "RUNNING" if im_active > 0 else ("AVAILABLE" if len(assessments) > 0 else "IDLE")

        # TestPilot
        test_exec_stmt = select(TestPilotExecution).where(TestPilotExecution.workspace_id == workspace_id)
        if repository_id:
            test_exec_stmt = test_exec_stmt.where(TestPilotExecution.repository_id == repository_id)
        test_exec_res = await session.execute(test_exec_stmt)
        test_execs = list(test_exec_res.scalars().all())

        tp_active = sum(1 for te in test_execs if te.status == TestExecutionStatus.RUNNING)
        tp_completed = sum(1 for te in test_execs if te.status in (TestExecutionStatus.PASSED, TestExecutionStatus.FAILED))
        tp_failed = sum(1 for te in test_execs if te.status in (TestExecutionStatus.FAILED, TestExecutionStatus.ERROR))
        tp_latest = max((te.created_at for te in test_execs), default=None)
        testpilot_status = "RUNNING" if tp_active > 0 else ("AVAILABLE" if len(test_execs) > 0 else "IDLE")

        # SecureFlow
        sf_scans_stmt = select(SecureFlowScan).where(SecureFlowScan.workspace_id == workspace_id)
        if repository_id:
            sf_scans_stmt = sf_scans_stmt.where(SecureFlowScan.repository_id == repository_id)
        sf_scans_res = await session.execute(sf_scans_stmt)
        sf_scans = list(sf_scans_res.scalars().all())

        sf_active = sum(1 for s in sf_scans if s.status == SecureFlowScanStatus.RUNNING)
        sf_completed = sum(1 for s in sf_scans if s.status == SecureFlowScanStatus.COMPLETED)
        sf_failed = sum(1 for s in sf_scans if s.status == SecureFlowScanStatus.FAILED)
        sf_latest = max((s.created_at for s in sf_scans), default=None)
        secureflow_status = "RUNNING" if sf_active > 0 else ("AVAILABLE" if len(sf_scans) > 0 else "IDLE")

        # FlowForge
        ff_active = running_execs
        ff_completed = sum(1 for e in executions if e.status == WorkflowExecutionStatus.COMPLETED)
        ff_failed = failed_execs
        ff_latest = max((e.created_at for e in executions), default=None)
        flowforge_status = "RUNNING" if ff_active > 0 else ("AVAILABLE" if len(executions) > 0 else "IDLE")

        # DevMemory
        dm_completed = total_mems
        dm_latest = max((m.updated_at for m in memories), default=None)
        devmemory_status = "AVAILABLE" if total_mems > 0 else "IDLE"

        agent_summaries = [
            AgentStatusSummary(
                agent_id="devpilot",
                name="DevPilot",
                role="AI Software Engineer",
                status=devpilot_status,
                active_executions=dp_active,
                completed_executions=dp_completed,
                failed_executions=dp_failed,
                last_execution_time=dp_latest,
                current_task=dp_current,
            ),
            AgentStatusSummary(
                agent_id="impactmind",
                name="ImpactMind",
                role="Change Blast Radius Analyst",
                status=impactmind_status,
                active_executions=im_active,
                completed_executions=im_completed,
                failed_executions=im_failed,
                last_execution_time=im_latest,
                current_task=f"Analyzed risk: {latest_assessment.exposure_tier}" if latest_assessment else None,
            ),
            AgentStatusSummary(
                agent_id="testpilot",
                name="TestPilot",
                role="Autonomous Quality Assurance",
                status=testpilot_status,
                active_executions=tp_active,
                completed_executions=tp_completed,
                failed_executions=tp_failed,
                last_execution_time=tp_latest,
            ),
            AgentStatusSummary(
                agent_id="secureflow",
                name="SecureFlow",
                role="Application Security Auditor",
                status=secureflow_status,
                active_executions=sf_active,
                completed_executions=sf_completed,
                failed_executions=sf_failed,
                last_execution_time=sf_latest,
            ),
            AgentStatusSummary(
                agent_id="flowforge",
                name="FlowForge",
                role="Workflow Engine Coordinator",
                status=flowforge_status,
                active_executions=ff_active,
                completed_executions=ff_completed,
                failed_executions=ff_failed,
                last_execution_time=ff_latest,
            ),
            AgentStatusSummary(
                agent_id="devmemory",
                name="DevMemory",
                role="Engineering Knowledge Graph",
                status=devmemory_status,
                active_executions=0,
                completed_executions=dm_completed,
                failed_executions=0,
                last_execution_time=dm_latest,
                current_task=f"{verified_mems} verified conventions" if verified_mems > 0 else None,
            ),
        ]

        # ---------------------------------------------------------------------
        # 8. Activity Stream (aggregated from real events)
        # ---------------------------------------------------------------------
        activities: list[ActivityEventItem] = []

        # From DevPilot tasks
        for t in dp_tasks[:10]:
            t_status = t.status.value if hasattr(t.status, "value") else str(t.status)
            activities.append(
                ActivityEventItem(
                    id=f"dp-{t.id}",
                    event_type="devpilot_task",
                    title=f"DevPilot: {t.title}",
                    description=f"Status: {t_status}",
                    status=t_status.lower(),
                    agent="DevPilot",
                    repository_id=t.repository_id,
                    repository_name=repo_name_map.get(t.repository_id),
                    created_at=t.updated_at,
                )
            )

        # From Workflow executions
        for e in executions[:10]:
            e_status = e.status.value if hasattr(e.status, "value") else str(e.status)
            activities.append(
                ActivityEventItem(
                    id=f"wf-{e.id}",
                    event_type="workflow_execution",
                    title=f"Workflow Run #{str(e.id)[:8]}",
                    description=f"Execution status: {e_status}",
                    status=e_status.lower(),
                    agent="FlowForge",
                    repository_id=None,
                    repository_name=None,
                    created_at=e.completed_at or e.started_at or e.created_at,
                )
            )

        # From Security scans
        for s in sf_scans[:5]:
            s_status = s.status.value if hasattr(s.status, "value") else str(s.status)
            activities.append(
                ActivityEventItem(
                    id=f"sf-{s.id}",
                    event_type="security_scan",
                    title=f"Security Scan ({s.scan_type})",
                    description=f"Status: {s_status}",
                    status=s_status.lower(),
                    agent="SecureFlow",
                    repository_id=s.repository_id,
                    repository_name=repo_name_map.get(s.repository_id),
                    created_at=s.completed_at or s.created_at,
                )
            )

        # From Indexing jobs
        for r in repos:
            idx_stmt = (
                select(IndexingJob)
                .where(
                    IndexingJob.repository_id == r.id,
                    IndexingJob.workspace_id == workspace_id,
                )
                .order_by(desc(IndexingJob.created_at))
                .limit(2)
            )
            idx_res = await session.execute(idx_stmt)
            for ij in idx_res.scalars().all():
                ij_status = ij.status.value if hasattr(ij.status, "value") else str(ij.status)
                activities.append(
                    ActivityEventItem(
                        id=f"idx-{ij.id}",
                        event_type="repo_index",
                        title=f"Repository Indexing: {r.name}",
                        description=f"Indexed branch: {ij.commit_sha[:8] if ij.commit_sha else 'HEAD'}",
                        status=ij_status.lower(),
                        agent="Repository Intelligence",
                        repository_id=r.id,
                        repository_name=r.name,
                        created_at=ij.completed_at or ij.created_at,
                    )
                )

        # Sort activities descending by created_at and paginate to activity_limit
        activities.sort(key=lambda a: _normalize_dt(a.created_at), reverse=True)
        paginated_activities = activities[:activity_limit]

        # ---------------------------------------------------------------------
        # 9. Top-Level Metrics
        # ---------------------------------------------------------------------
        metrics = DashboardMetrics(
            connected_repositories=len(repos),
            indexed_repositories=indexed_repo_count,
            active_workflows=active_wf,
            workflow_executions=len(executions),
            pending_approvals=wf_pending_approvals,
            total_memories=total_mems,
            verified_memories=verified_mems,
            open_security_findings=open_findings + confirmed_findings,
            running_tasks=running_tasks_count,
            total_tasks=len(task_items),
            impact_assessments=len(assessments),
        )

        return DashboardOverviewResponse(
            workspace_id=workspace_id,
            repository_filter_id=repository_id,
            generated_at=now,
            metrics=metrics,
            repositories=repo_summaries,
            agents=agent_summaries,
            tasks=recent_task_slice,
            security=security_summary,
            impact=impact_summary,
            memory=memory_summary,
            workflows=workflow_summary,
            activities=paginated_activities,
        )
