// Dashboard API Client & TypeScript Interfaces
// Aligns with backend/app/services/dashboard/schemas.py and /api/v1/dashboard/overview

import { fetchWithAuth } from "./auth";
import { getResponseErrorMessage } from "./api-error";

export interface DashboardMetrics {
  connected_repositories: number;
  indexed_repositories: number;
  active_workflows: number;
  workflow_executions: number;
  pending_approvals: number;
  total_memories: number;
  verified_memories: number;
  open_security_findings: number;
  running_tasks: number;
  total_tasks: number;
  impact_assessments: number;
}

export interface RepositorySummary {
  id: string;
  name: string;
  owner: string;
  default_branch: string;
  primary_language: string | null;
  indexing_status: string; // e.g. "COMPLETED", "FAILED", "RUNNING", "NOT_STARTED"
  last_indexed_at: string | null;
  is_private: boolean;
}

export interface AgentStatusSummary {
  agent_id: string;
  name: string;
  role: string;
  status: "AVAILABLE" | "RUNNING" | "IDLE" | "FAILED" | "UNAVAILABLE" | string;
  active_executions: number;
  completed_executions: number;
  failed_executions: number;
  last_execution_time: string | null;
  current_task: string | null;
}

export interface TaskSummaryItem {
  id: string;
  task_type: string;
  title: string;
  status: string;
  repository_id: string | null;
  repository_name: string | null;
  assigned_agent: string | null;
  updated_at: string;
}

export interface SecuritySummary {
  open_findings: number;
  confirmed_findings: number;
  accepted_risks: number;
  resolved_findings: number;
  severity_distribution: Record<string, number>;
  scans_count: number;
  last_scan_at: string | null;
  last_scan_status: string | null;
}

export interface ImpactSummary {
  total_assessments: number;
  latest_risk_score: number | null;
  latest_risk_tier: string | null;
  latest_assessment_at: string | null;
  latest_changed_files_count: number;
  latest_status: string | null;
}

export interface MemorySummary {
  total_count: number;
  verified_count: number;
  unverified_count: number;
  outdated_count: number;
  archived_count: number;
}

export interface WorkflowSummary {
  total_workflows: number;
  active_workflows: number;
  paused_workflows: number;
  draft_workflows: number;
  recent_executions: number;
  running_executions: number;
  failed_executions: number;
  pending_approvals: number;
}

export interface ActivityEventItem {
  id: string;
  event_type: string;
  title: string;
  description: string | null;
  status: string;
  agent: string | null;
  repository_id: string | null;
  repository_name: string | null;
  created_at: string;
}

export interface DashboardOverviewResponse {
  workspace_id: string;
  repository_filter_id: string | null;
  generated_at: string;
  metrics: DashboardMetrics;
  repositories: RepositorySummary[];
  agents: AgentStatusSummary[];
  tasks: TaskSummaryItem[];
  security: SecuritySummary;
  impact: ImpactSummary;
  memory: MemorySummary;
  workflows: WorkflowSummary;
  activities: ActivityEventItem[];
}

/**
 * Fetch dashboard overview data for a given workspace and optional repository filter.
 */
export async function getDashboardOverview(
  workspaceId: string,
  repositoryId?: string | null
): Promise<DashboardOverviewResponse> {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  if (repositoryId) {
    params.set("repository_id", repositoryId);
  }

  const res = await fetchWithAuth(`/api/v1/dashboard/overview?${params.toString()}`);
  if (!res.ok) {
    const errorMsg = await getResponseErrorMessage(res);
    throw new Error(errorMsg || "Failed to load dashboard overview");
  }

  return res.json();
}
