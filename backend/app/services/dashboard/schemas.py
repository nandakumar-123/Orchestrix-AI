from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DashboardMetrics(BaseModel):
    connected_repositories: int = Field(0, description="Total connected repositories in workspace")
    indexed_repositories: int = Field(0, description="Repositories with completed indexing")
    active_workflows: int = Field(0, description="Workflows in ACTIVE state")
    workflow_executions: int = Field(0, description="Total workflow executions")
    pending_approvals: int = Field(0, description="Workflow and DevPilot approvals pending action")
    total_memories: int = Field(0, description="Total engineering memories stored")
    verified_memories: int = Field(0, description="Verified engineering memories")
    open_security_findings: int = Field(0, description="Security vulnerabilities awaiting resolution")
    running_tasks: int = Field(0, description="Tasks currently in progress")
    total_tasks: int = Field(0, description="Total tasks in workspace")
    impact_assessments: int = Field(0, description="Total impact analysis assessments executed")


class RepositorySummary(BaseModel):
    id: uuid.UUID
    name: str
    owner: str
    default_branch: str
    primary_language: str | None = None
    indexing_status: str  # e.g., "COMPLETED", "FAILED", "RUNNING", "NOT_STARTED"
    last_indexed_at: datetime | None = None
    is_private: bool = False


class AgentStatusSummary(BaseModel):
    agent_id: str
    name: str
    role: str
    status: str  # "AVAILABLE", "RUNNING", "IDLE", "FAILED", "UNAVAILABLE"
    active_executions: int = 0
    completed_executions: int = 0
    failed_executions: int = 0
    last_execution_time: datetime | None = None
    current_task: str | None = None


class TaskSummaryItem(BaseModel):
    id: uuid.UUID
    task_type: str  # "devpilot" | "engineering_task"
    title: str
    status: str
    repository_id: uuid.UUID | None = None
    repository_name: str | None = None
    assigned_agent: str | None = None
    updated_at: datetime


class SecuritySummary(BaseModel):
    open_findings: int = 0
    confirmed_findings: int = 0
    accepted_risks: int = 0
    resolved_findings: int = 0
    severity_distribution: dict[str, int] = Field(default_factory=dict)
    scans_count: int = 0
    last_scan_at: datetime | None = None
    last_scan_status: str | None = None


class ImpactSummary(BaseModel):
    total_assessments: int = 0
    latest_risk_score: float | None = None
    latest_risk_tier: str | None = None
    latest_assessment_at: datetime | None = None
    latest_changed_files_count: int = 0
    latest_status: str | None = None


class MemorySummary(BaseModel):
    total_count: int = 0
    verified_count: int = 0
    unverified_count: int = 0
    outdated_count: int = 0
    archived_count: int = 0


class WorkflowSummary(BaseModel):
    total_workflows: int = 0
    active_workflows: int = 0
    paused_workflows: int = 0
    draft_workflows: int = 0
    recent_executions: int = 0
    running_executions: int = 0
    failed_executions: int = 0
    pending_approvals: int = 0


class ActivityEventItem(BaseModel):
    id: str
    event_type: str
    title: str
    description: str | None = None
    status: str
    agent: str | None = None
    repository_id: uuid.UUID | None = None
    repository_name: str | None = None
    created_at: datetime


class DashboardOverviewResponse(BaseModel):
    workspace_id: uuid.UUID
    repository_filter_id: uuid.UUID | None = None
    generated_at: datetime
    metrics: DashboardMetrics
    repositories: list[RepositorySummary]
    agents: list[AgentStatusSummary]
    tasks: list[TaskSummaryItem]
    security: SecuritySummary
    impact: ImpactSummary
    memory: MemorySummary
    workflows: WorkflowSummary
    activities: list[ActivityEventItem]
