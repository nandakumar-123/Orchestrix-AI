// FlowForge API client — types and fetch functions
// Mirrors backend schemas in backend/app/api/v1/schemas_flowforge.py
// and backend/app/services/flowforge/schemas.py

import { fetchWithAuth } from "./auth";
import { getResponseErrorMessage } from "./api-error";

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type WorkflowStatus = "DRAFT" | "ACTIVE" | "PAUSED" | "ARCHIVED";

export type WorkflowNodeType =
  | "TRIGGER"
  | "DEVPILOT"
  | "IMPACTMIND"
  | "TESTPILOT"
  | "SECUREFLOW"
  | "CONDITION"
  | "APPROVAL"
  | "PARALLEL"
  | "MERGE"
  | "NOTIFICATION"
  | "END";

export type WorkflowExecutionStatus =
  | "PENDING"
  | "RUNNING"
  | "WAITING_FOR_APPROVAL"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "TIMED_OUT";

export type WorkflowStepStatus =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "SKIPPED"
  | "CANCELLED"
  | "TIMED_OUT";

export type WorkflowApprovalStatus =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "EXPIRED"
  | "CANCELLED";

export type WorkflowValidationSeverity = "ERROR" | "WARNING";

// ---------------------------------------------------------------------------
// Graph definition types
// ---------------------------------------------------------------------------

export interface WorkflowNodeConnection {
  source_node_id: string;
  target_node_id: string;
  condition_branch?: string | null; // "true", "false", "default"
}

export interface WorkflowNodeDefinition {
  id: string;
  name?: string | null;
  node_type: WorkflowNodeType;
  config: Record<string, unknown>;
  retry_limit?: number;
  retry_delay_seconds?: number;
  timeout_seconds?: number;
}

export interface WorkflowGraphDefinition {
  nodes: WorkflowNodeDefinition[];
  connections: WorkflowNodeConnection[];
}

// ---------------------------------------------------------------------------
// API response types
// ---------------------------------------------------------------------------

export interface WorkflowVersionResponse {
  id: string;
  workflow_id: string;
  workspace_id: string;
  version_number: number;
  workflow_definition_json: WorkflowGraphDefinition;
  description?: string | null;
  created_by?: string | null;
  created_at: string;
}

export interface WorkflowResponse {
  id: string;
  workspace_id: string;
  name: string;
  description?: string | null;
  status: WorkflowStatus;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
  latest_version?: WorkflowVersionResponse | null;
}

export interface WorkflowListResponse {
  items: WorkflowResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface WorkflowStepExecutionResponse {
  id: string;
  execution_id: string;
  workflow_id: string;
  workspace_id: string;
  node_id: string;
  node_type: WorkflowNodeType;
  status: WorkflowStepStatus;
  attempt_number: number;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  input_reference?: Record<string, unknown> | null;
  output_reference?: Record<string, unknown> | null;
  created_at: string;
}

export interface WorkflowApprovalResponse {
  id: string;
  execution_id: string;
  workflow_id: string;
  workspace_id: string;
  node_id: string;
  status: WorkflowApprovalStatus;
  requested_by?: string | null;
  decided_by?: string | null;
  decision_reason?: string | null;
  requested_at: string;
  decided_at?: string | null;
  expires_at?: string | null;
}

export interface WorkflowExecutionResponse {
  id: string;
  workflow_id: string;
  workspace_id: string;
  status: WorkflowExecutionStatus;
  trigger_id?: string | null;
  workflow_version_id?: string | null;
  context_data?: Record<string, unknown> | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  steps: WorkflowStepExecutionResponse[];
  approvals: WorkflowApprovalResponse[];
}

export interface WorkflowExecutionListResponse {
  items: WorkflowExecutionResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface WorkflowEventResponse {
  id: string;
  execution_id: string;
  workflow_id: string;
  workspace_id: string;
  event_type: string;
  node_id?: string | null;
  details?: Record<string, unknown> | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Validation types
// ---------------------------------------------------------------------------

export interface WorkflowValidationIssue {
  severity: WorkflowValidationSeverity;
  code: string;
  message: string;
  node_id?: string | null;
  target_node_id?: string | null;
}

export interface WorkflowValidationResult {
  is_valid: boolean;
  issues: WorkflowValidationIssue[];
  entry_node_id?: string | null;
  node_count: number;
  connection_count: number;
}

// ---------------------------------------------------------------------------
// API error helper
// ---------------------------------------------------------------------------

class FlowForgeApiError extends Error {
  constructor(
    public statusCode: number,
    message: string
  ) {
    super(message);
    this.name = "FlowForgeApiError";
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const message = await getResponseErrorMessage(res);
    throw new FlowForgeApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Workflow CRUD
// ---------------------------------------------------------------------------

export async function listWorkflows(
  workspaceId: string,
  params?: { status?: string; limit?: number; offset?: number }
): Promise<WorkflowListResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  if (params?.status) q.set("status", params.status);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const res = await fetchWithAuth(`/api/v1/workflows?${q.toString()}`);
  return handleResponse<WorkflowListResponse>(res);
}

export async function getWorkflow(
  workflowId: string,
  workspaceId: string
): Promise<WorkflowResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/workflows/${workflowId}?${q.toString()}`
  );
  return handleResponse<WorkflowResponse>(res);
}

export async function createWorkflow(payload: {
  workspaceId: string;
  name: string;
  description?: string;
  definition?: WorkflowGraphDefinition;
}): Promise<WorkflowResponse> {
  const q = new URLSearchParams({ workspace_id: payload.workspaceId });
  const res = await fetchWithAuth(`/api/v1/workflows?${q.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: payload.name,
      description: payload.description ?? null,
      definition: payload.definition ?? null,
    }),
  });
  return handleResponse<WorkflowResponse>(res);
}

export async function updateWorkflow(
  workflowId: string,
  payload: {
    workspaceId: string;
    name?: string;
    description?: string;
    definition?: WorkflowGraphDefinition;
  }
): Promise<WorkflowResponse> {
  const q = new URLSearchParams({ workspace_id: payload.workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/workflows/${workflowId}?${q.toString()}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: payload.name,
        description: payload.description,
        definition: payload.definition,
      }),
    }
  );
  return handleResponse<WorkflowResponse>(res);
}

export async function validateWorkflow(
  workflowId: string,
  workspaceId: string,
  definition: WorkflowGraphDefinition
): Promise<WorkflowValidationResult> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/workflows/${workflowId}/validate?${q.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ definition }),
    }
  );
  return handleResponse<WorkflowValidationResult>(res);
}

export async function activateWorkflow(
  workflowId: string,
  workspaceId: string
): Promise<WorkflowResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/workflows/${workflowId}/activate?${q.toString()}`,
    { method: "POST" }
  );
  return handleResponse<WorkflowResponse>(res);
}

export async function pauseWorkflow(
  workflowId: string,
  workspaceId: string
): Promise<WorkflowResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/workflows/${workflowId}/pause?${q.toString()}`,
    { method: "POST" }
  );
  return handleResponse<WorkflowResponse>(res);
}

// ---------------------------------------------------------------------------
// Versions
// ---------------------------------------------------------------------------

export async function createVersion(
  workflowId: string,
  payload: {
    workspaceId: string;
    definition: WorkflowGraphDefinition;
    description?: string;
  }
): Promise<WorkflowVersionResponse> {
  const q = new URLSearchParams({ workspace_id: payload.workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/workflows/${workflowId}/versions?${q.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        definition: payload.definition,
        description: payload.description ?? null,
      }),
    }
  );
  return handleResponse<WorkflowVersionResponse>(res);
}

export async function listVersions(
  workflowId: string,
  workspaceId: string
): Promise<WorkflowVersionResponse[]> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/workflows/${workflowId}/versions?${q.toString()}`
  );
  return handleResponse<WorkflowVersionResponse[]>(res);
}

// ---------------------------------------------------------------------------
// Executions
// ---------------------------------------------------------------------------

export async function startExecution(
  workflowId: string,
  payload: {
    workspaceId: string;
    contextData?: Record<string, unknown>;
    triggerId?: string;
    workflowVersionId?: string;
  }
): Promise<WorkflowExecutionResponse> {
  const q = new URLSearchParams({ workspace_id: payload.workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/workflows/${workflowId}/execute?${q.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        context_data: payload.contextData ?? {},
        trigger_id: payload.triggerId ?? null,
        workflow_version_id: payload.workflowVersionId ?? null,
      }),
    }
  );
  return handleResponse<WorkflowExecutionResponse>(res);
}

export async function listExecutions(
  workspaceId: string,
  params?: {
    workflowId?: string;
    status?: string;
    limit?: number;
    offset?: number;
  }
): Promise<WorkflowExecutionListResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  if (params?.workflowId) q.set("workflow_id", params.workflowId);
  if (params?.status) q.set("status", params.status);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const res = await fetchWithAuth(
    `/api/v1/workflows/executions?${q.toString()}`
  );
  return handleResponse<WorkflowExecutionListResponse>(res);
}

export async function getExecution(
  executionId: string,
  workspaceId: string
): Promise<WorkflowExecutionResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/workflows/executions/${executionId}?${q.toString()}`
  );
  return handleResponse<WorkflowExecutionResponse>(res);
}

export async function cancelExecution(
  executionId: string,
  workspaceId: string,
  reason?: string
): Promise<WorkflowExecutionResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/workflows/executions/${executionId}/cancel?${q.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason ?? null }),
    }
  );
  return handleResponse<WorkflowExecutionResponse>(res);
}

export async function getExecutionEvents(
  executionId: string,
  workspaceId: string
): Promise<WorkflowEventResponse[]> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/workflows/executions/${executionId}/events?${q.toString()}`
  );
  return handleResponse<WorkflowEventResponse[]>(res);
}

// ---------------------------------------------------------------------------
// Approvals
// ---------------------------------------------------------------------------

export async function approveCheckpoint(
  approvalId: string,
  workspaceId: string,
  reason?: string
): Promise<WorkflowApprovalResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/workflows/approvals/${approvalId}/approve?${q.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision_reason: reason ?? null }),
    }
  );
  return handleResponse<WorkflowApprovalResponse>(res);
}

export async function rejectCheckpoint(
  approvalId: string,
  workspaceId: string,
  reason: string
): Promise<WorkflowApprovalResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/workflows/approvals/${approvalId}/reject?${q.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision_reason: reason }),
    }
  );
  return handleResponse<WorkflowApprovalResponse>(res);
}
