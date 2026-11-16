import { fetchWithAuth } from "./auth";
import { getResponseErrorMessage } from "./api-error";

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
  id?: string;
  plan_id?: string;
  step_number: number;
  title: string;
  description: string;
  target_files: string[];
  affected_symbols: string[];
  action_type: string;
  reason?: string;
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
  provider_used?: string | null;
  model_used?: string | null;
}

export interface DevPilotReviewFinding {
  id: string;
  task_id?: string;
  category: string;
  severity: "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  file_path: string;
  line_start?: number | null;
  line_end?: number | null;
  symbol_name?: string | null;
  title: string;
  description: string;
  suggested_fix?: string | null;
  suggested_correction?: string | null;
  evidence?: string | null;
  is_resolved?: boolean;
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
  prompt?: string;
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
  description?: string;
  prompt?: string;
  context_query?: string | null;
  files_of_interest?: string[];
  execution_mode?: DevPilotExecutionMode;
  auto_validate_tests?: boolean;
  base_commit_sha?: string | null;
}

export interface DevPilotTaskListResponse {
  tasks: DevPilotTaskDetail[];
  total: number;
}

function buildQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined && val !== null && val !== "") {
      q.set(key, String(val));
    }
  }
  const str = q.toString();
  return str ? `?${str}` : "";
}

function parsePlanSteps(steps: unknown): DevPilotPlanStep[] {
  if (!Array.isArray(steps)) return [];
  return steps.map((item: unknown, idx: number) => {
    const s = typeof item === "object" && item !== null ? (item as Record<string, unknown>) : {};
    return {
      id: typeof s.id === "string" ? s.id : `step-${idx + 1}`,
      step_number: typeof s.step_number === "number" ? s.step_number : idx + 1,
      title: typeof s.title === "string" ? s.title : `Step ${idx + 1}`,
      description: typeof s.description === "string" ? s.description : "",
      target_files: Array.isArray(s.target_files) ? (s.target_files as string[]) : [],
      affected_symbols: Array.isArray(s.affected_symbols) ? (s.affected_symbols as string[]) : [],
      action_type: typeof s.action_type === "string" ? s.action_type : "MODIFY",
      reason: typeof s.reason === "string" ? s.reason : undefined,
      risk_level: typeof s.risk_level === "string" ? s.risk_level : "LOW",
      status: typeof s.status === "string" ? s.status : "PENDING",
    };
  });
}

function parsePlan(rawPlan: unknown): DevPilotEngineeringPlan | null {
  if (!rawPlan || typeof rawPlan !== "object") return null;
  const p = rawPlan as Record<string, unknown>;
  return {
    id: String(p.id || ""),
    task_id: String(p.task_id || ""),
    workspace_id: String(p.workspace_id || ""),
    version: typeof p.version === "number" ? p.version : 1,
    status: (p.status === "APPROVED" || p.status === "REJECTED" ? p.status : "PENDING") as
      | "PENDING"
      | "APPROVED"
      | "REJECTED",
    summary: typeof p.summary === "string" ? p.summary : "",
    task_understanding: typeof p.task_understanding === "string" ? p.task_understanding : "",
    architectural_context: typeof p.architectural_context === "string" ? p.architectural_context : "",
    existing_implementation_analysis:
      typeof p.existing_implementation_analysis === "string"
        ? p.existing_implementation_analysis
        : "",
    proposed_changes_description:
      typeof p.proposed_changes_description === "string" ? p.proposed_changes_description : "",
    blast_radius_summary: typeof p.blast_radius_summary === "string" ? p.blast_radius_summary : "",
    rollback_strategy: typeof p.rollback_strategy === "string" ? p.rollback_strategy : "",
    testing_strategy: typeof p.testing_strategy === "string" ? p.testing_strategy : "",
    security_implications: typeof p.security_implications === "string" ? p.security_implications : "",
    exposure_score: typeof p.exposure_score === "number" ? p.exposure_score : 0,
    exposure_tier:
      p.exposure_tier === "CRITICAL" || p.exposure_tier === "HIGH" || p.exposure_tier === "MEDIUM"
        ? p.exposure_tier
        : "LOW",
    score_type: typeof p.score_type === "string" ? p.score_type : "heuristic_structural_exposure",
    approval_comment: typeof p.approval_comment === "string" ? p.approval_comment : null,
    created_at: typeof p.created_at === "string" ? p.created_at : new Date().toISOString(),
    approved_at: typeof p.approved_at === "string" ? p.approved_at : null,
    steps: parsePlanSteps(p.steps),
  };
}

function mapRawTaskDetail(raw: Record<string, unknown>): DevPilotTaskDetail {
  const mappedPlan = parsePlan(raw.latest_plan);
  const reviewFindings = Array.isArray(raw.review_findings) ? raw.review_findings : [];
  const statusStr = typeof raw.status === "string" ? raw.status : "CREATED";

  return {
    id: String(raw.id || ""),
    workspace_id: String(raw.workspace_id || ""),
    repository_id: String(raw.repository_id || ""),
    task_type: (raw.task_type as DevPilotTaskType) || "FEATURE",
    status: statusStr as DevPilotTaskStatus,
    title: typeof raw.title === "string" ? raw.title : "Untitled Task",
    description:
      typeof raw.description === "string"
        ? raw.description
        : typeof raw.prompt === "string"
        ? raw.prompt
        : "",
    prompt: typeof raw.prompt === "string" ? raw.prompt : undefined,
    execution_mode: (raw.execution_mode as DevPilotExecutionMode) || "STANDARD",
    error_message: typeof raw.error_message === "string" ? raw.error_message : null,
    clarification_prompt:
      typeof raw.clarification_prompt === "string" ? raw.clarification_prompt : null,
    created_at: typeof raw.created_at === "string" ? raw.created_at : new Date().toISOString(),
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : new Date().toISOString(),
    completed_at: typeof raw.completed_at === "string" ? raw.completed_at : null,
    latest_plan: mappedPlan,
    latest_diff:
      raw.latest_diff && typeof raw.latest_diff === "object"
        ? (raw.latest_diff as DevPilotDiffResponse)
        : null,
    review_findings_count:
      typeof raw.review_findings_count === "number"
        ? raw.review_findings_count
        : reviewFindings.length,
    plan_status: mappedPlan?.status || (typeof raw.plan_status === "string" ? raw.plan_status : null),
    is_modification_approved:
      typeof raw.is_modification_approved === "boolean"
        ? raw.is_modification_approved
        : statusStr === "VALIDATING" || statusStr === "COMPLETED",
  };
}

export async function createDevPilotTask(
  repositoryId: string,
  data: DevPilotTaskCreateRequest,
  workspaceId?: string
): Promise<DevPilotTaskDetail> {
  const query = buildQuery({ workspace_id: workspaceId });
  const payload = {
    title: data.title,
    prompt: data.prompt || data.description || data.title,
    task_type: data.task_type || "FEATURE",
    base_commit_sha: data.base_commit_sha,
  };

  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/devpilot/tasks${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to create task (${res.status})`);
    throw new Error(err);
  }
  const raw = (await res.json()) as Record<string, unknown>;
  return mapRawTaskDetail(raw);
}

export async function listDevPilotTasks(
  repositoryId: string,
  params?: {
    status?: string;
    task_type?: string;
    limit?: number;
    offset?: number;
    workspaceId?: string;
    workspace_id?: string;
  }
): Promise<DevPilotTaskListResponse> {
  const query = buildQuery({
    status: params?.status,
    task_type: params?.task_type,
    limit: params?.limit,
    offset: params?.offset,
    workspace_id: params?.workspaceId || params?.workspace_id,
  });

  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/devpilot/tasks${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to fetch tasks (${res.status})`);
    throw new Error(err);
  }
  const raw = (await res.json()) as { tasks?: Array<Record<string, unknown>>; total?: number };
  const rawTasks = Array.isArray(raw.tasks) ? raw.tasks : [];
  return {
    tasks: rawTasks.map(mapRawTaskDetail),
    total: typeof raw.total === "number" ? raw.total : rawTasks.length,
  };
}

export async function listWorkspaceDevPilotTasks(
  workspaceId: string,
  params?: {
    repository_id?: string;
    limit?: number;
  }
): Promise<DevPilotTaskListResponse> {
  const query = buildQuery({
    workspace_id: workspaceId,
    repository_id: params?.repository_id,
    limit: params?.limit || 50,
  });

  const res = await fetchWithAuth(`/api/v1/devpilot/tasks${query}`);
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to load workspace tasks (${res.status})`);
    throw new Error(err);
  }
  const raw = (await res.json()) as { tasks?: Array<Record<string, unknown>>; total?: number };
  const rawTasks = Array.isArray(raw.tasks) ? raw.tasks : [];
  return {
    tasks: rawTasks.map(mapRawTaskDetail),
    total: typeof raw.total === "number" ? raw.total : rawTasks.length,
  };
}


export async function getDevPilotTask(
  repositoryId: string,
  taskId: string,
  workspaceId?: string
): Promise<DevPilotTaskDetail> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/devpilot/tasks/${taskId}${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to fetch task (${res.status})`);
    throw new Error(err);
  }
  const raw = (await res.json()) as Record<string, unknown>;
  return mapRawTaskDetail(raw);
}

export async function getDevPilotPlan(
  repositoryId: string,
  taskId: string,
  workspaceId?: string
): Promise<DevPilotEngineeringPlan> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/devpilot/tasks/${taskId}/plan${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to fetch engineering plan (${res.status})`);
    throw new Error(err);
  }
  const p = await res.json();
  const parsed = parsePlan(p);
  if (!parsed) {
    throw new Error("Invalid plan data structure received from server");
  }
  return parsed;
}

export async function approveDevPilotPlan(
  repositoryId: string,
  taskId: string,
  approved: boolean,
  rejectionReason?: string,
  feedback?: string,
  workspaceId?: string
): Promise<DevPilotTaskDetail> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/devpilot/tasks/${taskId}/approve-plan${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision: approved ? "APPROVED" : "REJECTED",
        feedback: feedback || rejectionReason || undefined,
      }),
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to process plan approval (${res.status})`);
    throw new Error(err);
  }
  return getDevPilotTask(repositoryId, taskId, workspaceId);
}

export async function approveDevPilotChanges(
  repositoryId: string,
  taskId: string,
  approved: boolean,
  rejectionReason?: string,
  feedback?: string,
  workspaceId?: string
): Promise<DevPilotTaskDetail> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/devpilot/tasks/${taskId}/approve-changes${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision: approved ? "APPROVED" : "REJECTED",
        feedback: feedback || rejectionReason || undefined,
      }),
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to process modification approval (${res.status})`);
    throw new Error(err);
  }
  const raw = (await res.json()) as Record<string, unknown>;
  return mapRawTaskDetail(raw);
}

export async function getDevPilotDiff(
  repositoryId: string,
  taskId: string,
  workspaceId?: string
): Promise<DevPilotDiffResponse> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/devpilot/tasks/${taskId}/diff${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to fetch diff (${res.status})`);
    throw new Error(err);
  }
  const raw = (await res.json()) as Record<string, unknown>;
  const changes = Array.isArray(raw.changes) ? (raw.changes as DevPilotCodeChange[]) : [];
  return {
    task_id: String(raw.task_id || ""),
    total_files_changed: typeof raw.total_files_changed === "number" ? raw.total_files_changed : changes.length,
    additions: typeof raw.additions === "number" ? raw.additions : 0,
    deletions: typeof raw.deletions === "number" ? raw.deletions : 0,
    unified_diff: typeof raw.unified_diff === "string" ? raw.unified_diff : "",
    changes,
    provider_used: typeof raw.provider_used === "string" ? raw.provider_used : null,
    model_used: typeof raw.model_used === "string" ? raw.model_used : null,
  };
}

export async function getDevPilotReview(
  repositoryId: string,
  taskId: string,
  workspaceId?: string
): Promise<DevPilotReviewResponse> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/devpilot/tasks/${taskId}/review${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to fetch review findings (${res.status})`);
    throw new Error(err);
  }
  const raw = (await res.json()) as Record<string, unknown>;
  const rawFindings = Array.isArray(raw.findings) ? (raw.findings as Array<Record<string, unknown>>) : [];

  const validSeverities: Record<string, "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"> = {
    CRITICAL: "CRITICAL",
    HIGH: "HIGH",
    MEDIUM: "MEDIUM",
    LOW: "LOW",
    INFO: "INFO",
  };

  const findings: DevPilotReviewFinding[] = rawFindings.map((f) => {
    const rawSev = typeof f.severity === "string" ? f.severity.toUpperCase() : "INFO";
    return {
      id: String(f.id || ""),
      task_id: typeof f.task_id === "string" ? f.task_id : String(raw.task_id || ""),
      category: typeof f.category === "string" ? f.category : "CODE_QUALITY",
      severity: validSeverities[rawSev] || "INFO",
      file_path: typeof f.file_path === "string" ? f.file_path : "",
      line_start: typeof f.line_start === "number" ? f.line_start : null,
      line_end: typeof f.line_end === "number" ? f.line_end : null,
      symbol_name: typeof f.symbol_name === "string" ? f.symbol_name : null,
      title: typeof f.title === "string" ? f.title : "Finding",
      description: typeof f.description === "string" ? f.description : "",
      suggested_fix: typeof f.suggested_fix === "string" ? f.suggested_fix : null,
      suggested_correction:
        typeof f.suggested_correction === "string" ? f.suggested_correction : null,
      evidence: typeof f.evidence === "string" ? f.evidence : null,
      is_resolved: Boolean(f.is_resolved),
    };
  });

  const counts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
  for (const f of findings) {
    if (f.severity === "CRITICAL") counts.critical++;
    else if (f.severity === "HIGH") counts.high++;
    else if (f.severity === "MEDIUM") counts.medium++;
    else if (f.severity === "LOW") counts.low++;
    else counts.info++;
  }

  return {
    task_id: String(raw.task_id || ""),
    total_findings: typeof raw.total_findings === "number" ? raw.total_findings : findings.length,
    critical_count: typeof raw.critical_count === "number" ? raw.critical_count : counts.critical,
    high_count: typeof raw.high_count === "number" ? raw.high_count : counts.high,
    medium_count: typeof raw.medium_count === "number" ? raw.medium_count : counts.medium,
    low_count: typeof raw.low_count === "number" ? raw.low_count : counts.low,
    info_count: typeof raw.info_count === "number" ? raw.info_count : counts.info,
    findings,
  };
}

export async function triggerDevPilotValidation(
  repositoryId: string,
  taskId: string,
  runTests: boolean = true,
  testCommand?: string,
  workspaceId?: string
): Promise<DevPilotValidationResponse> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/devpilot/tasks/${taskId}/validate${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_approved: runTests,
        test_command: testCommand,
      }),
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to trigger validation (${res.status})`);
    throw new Error(err);
  }
  const raw = (await res.json()) as Record<string, unknown>;
  const events = Array.isArray(raw.events) ? (raw.events as Array<Record<string, unknown>>) : [];
  const statusStr = typeof raw.status === "string" ? raw.status : "RUNNING";

  return {
    task_id: String(raw.id || ""),
    overall_status:
      statusStr === "COMPLETED" ? "PASSED" : statusStr === "FAILED" ? "FAILED" : "RUNNING",
    stages: events.map((e, idx) => ({
      id: typeof e.id === "string" ? e.id : `event-${idx}`,
      stage_name: typeof e.event_type === "string" ? e.event_type : "Validation Step",
      status: (statusStr === "FAILED" ? "FAILED" : "PASSED") as
        | "PENDING"
        | "RUNNING"
        | "PASSED"
        | "FAILED"
        | "SKIPPED",
      details:
        e.details && typeof e.details === "object"
          ? (e.details as Record<string, unknown>)
          : { message: typeof e.message === "string" ? e.message : "" },
      started_at: typeof e.created_at === "string" ? e.created_at : null,
      completed_at: typeof e.created_at === "string" ? e.created_at : null,
    })),
  };
}

export async function cancelDevPilotTask(
  repositoryId: string,
  taskId: string,
  reason?: string,
  workspaceId?: string
): Promise<DevPilotTaskDetail> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/devpilot/tasks/${taskId}/cancel${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to cancel task (${res.status})`);
    throw new Error(err);
  }
  const raw = (await res.json()) as Record<string, unknown>;
  return mapRawTaskDetail(raw);
}
