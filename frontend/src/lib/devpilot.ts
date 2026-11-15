import { fetchWithAuth } from "./auth";

export type DevPilotTaskStatus =
  | "CREATED"
  | "ANALYZING"
  | "PLANNING"
  | "AWAITING_APPROVAL"
  | "GENERATING"
  | "REVIEWING"
  | "AWAITING_MODIFICATION_APPROVAL"
  | "APPLYING"
  | "VALIDATING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "BLOCKED"
  | "NEEDS_CLARIFICATION";

export type DevPilotTaskType =
  | "FEATURE"
  | "BUG_FIX"
  | "REFACTOR"
  | "TESTING"
  | "API_DEVELOPMENT"
  | "PERFORMANCE_OPTIMIZATION";

export type DevPilotExecutionMode = "STANDARD" | "CAREFUL" | "DIAGNOSTIC_ONLY";

export interface DevPilotPlanStep {
  id: string;
  plan_id?: string;
  step_number: number;
  title: string;
  description: string;
  target_files: string[];
  affected_symbols: string[];
  action_type: string;
  reason: string;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | string;
  status: string;
}

export interface DevPilotEngineeringPlan {
  id: string;
  task_id: string;
  workspace_id: string;
  version: number;
  status: "PENDING" | "APPROVED" | "REJECTED";
  summary: string;
  task_understanding: string;
  architectural_context: string;
  existing_implementation_analysis: string;
  proposed_changes_description: string;
  blast_radius_summary: string;
  rollback_strategy: string;
  testing_strategy: string;
  security_implications: string;
  exposure_score: number;
  exposure_tier: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  score_type: string;
  approval_comment?: string | null;
  created_at: string;
  approved_at?: string | null;
  steps: DevPilotPlanStep[];
}

export interface DevPilotCodeChange {
  id: string;
  file_path: string;
  change_type: "CREATE" | "MODIFY" | "DELETE" | "RENAME" | string;
  old_content?: string | null;
  new_content?: string | null;
  diff_hunk?: string | null;
}

export interface DevPilotDiffResponse {
  task_id: string;
  total_files_changed: number;
  additions: number;
  deletions: number;
  unified_diff: string;
  changes: DevPilotCodeChange[];
}

export interface DevPilotReviewFinding {
  id: string;
  task_id: string;
  category: string;
  severity: "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  file_path: string;
  line_start?: number | null;
  line_end?: number | null;
  symbol_name?: string | null;
  title: string;
  description: string;
  suggested_fix?: string | null;
  is_resolved: boolean;
}

export interface DevPilotReviewResponse {
  task_id: string;
  total_findings: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  info_count: number;
  findings: DevPilotReviewFinding[];
}

export interface DevPilotValidationStage {
  id: string;
  stage_name: string;
  status: "PENDING" | "RUNNING" | "PASSED" | "FAILED" | "SKIPPED";
  details: Record<string, unknown>;
  execution_time_ms?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface DevPilotValidationResponse {
  task_id: string;
  overall_status: "PENDING" | "RUNNING" | "PASSED" | "FAILED" | "WARNING";
  stages: DevPilotValidationStage[];
}

export interface DevPilotTaskDetail {
  id: string;
  workspace_id: string;
  repository_id: string;
  task_type: DevPilotTaskType;
  status: DevPilotTaskStatus;
  title: string;
  description: string;
  execution_mode: DevPilotExecutionMode;
  error_message?: string | null;
  clarification_prompt?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  latest_plan?: DevPilotEngineeringPlan | null;
  latest_diff?: DevPilotDiffResponse | null;
  review_findings_count: number;
  plan_status?: string | null;
  is_modification_approved: boolean;
}

export interface DevPilotTaskCreateRequest {
  task_type: DevPilotTaskType;
  title: string;
  description: string;
  context_query?: string | null;
  files_of_interest?: string[];
  execution_mode?: DevPilotExecutionMode;
  auto_validate_tests?: boolean;
}

export interface DevPilotTaskListResponse {
  tasks: DevPilotTaskDetail[];
  total: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export async function createDevPilotTask(
  repositoryId: string,
  data: DevPilotTaskCreateRequest
): Promise<DevPilotTaskDetail> {
  const res = await fetchWithAuth(`${API_BASE}/repositories/${repositoryId}/devpilot/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to create task (${res.status})`);
  }
  return res.json();
}

export async function listDevPilotTasks(
  repositoryId: string,
  params?: { status?: string; task_type?: string; limit?: number; offset?: number }
): Promise<DevPilotTaskListResponse> {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.task_type) q.set("task_type", params.task_type);
  if (params?.limit) q.set("limit", params.limit.toString());
  if (params?.offset) q.set("offset", params.offset.toString());

  const res = await fetchWithAuth(
    `${API_BASE}/repositories/${repositoryId}/devpilot/tasks?${q.toString()}`
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch tasks (${res.status})`);
  }
  return res.json();
}

export async function getDevPilotTask(
  repositoryId: string,
  taskId: string
): Promise<DevPilotTaskDetail> {
  const res = await fetchWithAuth(
    `${API_BASE}/repositories/${repositoryId}/devpilot/tasks/${taskId}`
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch task (${res.status})`);
  }
  return res.json();
}

export async function getDevPilotPlan(
  repositoryId: string,
  taskId: string
): Promise<DevPilotEngineeringPlan> {
  const res = await fetchWithAuth(
    `${API_BASE}/repositories/${repositoryId}/devpilot/tasks/${taskId}/plan`
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch engineering plan (${res.status})`);
  }
  return res.json();
}

export async function approveDevPilotPlan(
  repositoryId: string,
  taskId: string,
  approved: boolean,
  rejectionReason?: string,
  feedback?: string
): Promise<DevPilotTaskDetail> {
  const res = await fetchWithAuth(
    `${API_BASE}/repositories/${repositoryId}/devpilot/tasks/${taskId}/approve-plan`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        approved,
        rejection_reason: rejectionReason,
        feedback,
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to process plan approval (${res.status})`);
  }
  return res.json();
}

export async function approveDevPilotChanges(
  repositoryId: string,
  taskId: string,
  approved: boolean,
  rejectionReason?: string,
  feedback?: string
): Promise<DevPilotTaskDetail> {
  const res = await fetchWithAuth(
    `${API_BASE}/repositories/${repositoryId}/devpilot/tasks/${taskId}/approve-changes`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        approved,
        rejection_reason: rejectionReason,
        feedback,
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to process modification approval (${res.status})`);
  }
  return res.json();
}

export async function getDevPilotDiff(
  repositoryId: string,
  taskId: string
): Promise<DevPilotDiffResponse> {
  const res = await fetchWithAuth(
    `${API_BASE}/repositories/${repositoryId}/devpilot/tasks/${taskId}/diff`
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch diff (${res.status})`);
  }
  return res.json();
}

export async function getDevPilotReview(
  repositoryId: string,
  taskId: string
): Promise<DevPilotReviewResponse> {
  const res = await fetchWithAuth(
    `${API_BASE}/repositories/${repositoryId}/devpilot/tasks/${taskId}/review`
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch review findings (${res.status})`);
  }
  return res.json();
}

export async function triggerDevPilotValidation(
  repositoryId: string,
  taskId: string,
  runTests: boolean = true,
  testCommand?: string
): Promise<DevPilotValidationResponse> {
  const res = await fetchWithAuth(
    `${API_BASE}/repositories/${repositoryId}/devpilot/tasks/${taskId}/validate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_tests: runTests,
        test_command: testCommand,
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to trigger validation (${res.status})`);
  }
  return res.json();
}

export async function cancelDevPilotTask(
  repositoryId: string,
  taskId: string,
  reason?: string
): Promise<DevPilotTaskDetail> {
  const res = await fetchWithAuth(
    `${API_BASE}/repositories/${repositoryId}/devpilot/tasks/${taskId}/cancel`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to cancel task (${res.status})`);
  }
  return res.json();
}
