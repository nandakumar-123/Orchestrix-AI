import { fetchWithAuth } from "./auth";

export type ImpactComparisonMode = "diff_input" | "commit_range" | "working_tree";
export type ExposureTier = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type TestPriority = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
export type ExecutionStatus =
  | "PENDING"
  | "RUNNING"
  | "PASSED"
  | "FAILED"
  | "TIMED_OUT"
  | "CANCELLED"
  | "SKIPPED"
  | "NOT_EXECUTED";

export interface ChangeClassificationItem {
  id: string;
  file_path: string;
  symbol_name?: string | null;
  symbol_id?: string | null;
  category: string;
  is_breaking: boolean;
  breaking_reason?: string | null;
  confidence: number;
  evidence?: string | null;
  status: string;
}

export interface ImpactedEntityItem {
  id: string;
  entity_id: string;
  name: string;
  label: string;
  file_path?: string | null;
  impact_type: string;
  depth: number;
  relationship_type?: string | null;
  confidence: number;
  evidence?: string | null;
}

export interface TestRecommendationItem {
  id: string;
  test_file: string;
  test_name?: string | null;
  test_framework: string;
  priority: TestPriority;
  reason: string;
  related_symbol?: string | null;
  evidence_source: string;
  confidence: number;
}

export interface TestExecutionRunItem {
  id: string;
  command: string;
  status: ExecutionStatus;
  exit_code?: number | null;
  stdout?: string | null;
  stderr?: string | null;
  passed_count: number;
  failed_count: number;
  skipped_count: number;
  duration_ms?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface ImpactAssessment {
  id: string;
  workspace_id: string;
  repository_id: string;
  snapshot_id?: string | null;
  base_commit_sha?: string | null;
  target_commit_sha?: string | null;
  comparison_mode: ImpactComparisonMode | string;
  status: string;
  structural_exposure_score: number;
  exposure_tier: ExposureTier;
  score_type: string;
  score_label: string;
  change_summary: {
    total_files_changed?: number;
    total_additions?: number;
    total_deletions?: number;
    breaking_changes_count?: number;
    impacted_symbols_count?: number;
    exposed_endpoints_count?: number;
    affected_tests_count?: number;
    is_graph_degraded?: boolean;
    is_semantic_degraded?: boolean;
    [key: string]: unknown;
  };
  reasons: string[];
  recommended_actions: string[];
  error_message?: string | null;
  classifications: ChangeClassificationItem[];
  impacted_entities: ImpactedEntityItem[];
  test_recommendations: TestRecommendationItem[];
  test_executions: TestExecutionRunItem[];
  created_at: string;
  completed_at?: string | null;
}

export interface ImpactAssessmentListResponse {
  assessments: ImpactAssessment[];
  total: number;
  limit: number;
  offset: number;
}

export interface ImpactAnalyzeRequest {
  diff_text?: string;
  base_commit_sha?: string;
  target_commit_sha?: string;
  comparison_mode?: ImpactComparisonMode | string;
  snapshot_id?: string;
  file_contents_before?: Record<string, string>;
  file_contents_after?: Record<string, string>;
}

export interface RunTestsRequest {
  run_approved: boolean;
  working_dir?: string;
  custom_command?: string;
  timeout_seconds?: number;
}

// -----------------------------------------------------------------------------
// API Client Functions
// -----------------------------------------------------------------------------

export async function analyzeChangeImpact(
  repositoryId: string,
  workspaceId: string,
  payload: ImpactAnalyzeRequest
): Promise<ImpactAssessment> {
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/impact/analyze?workspace_id=${workspaceId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Analysis failed (${res.status})`);
  }
  return res.json();
}

export async function fetchImpactAssessment(
  repositoryId: string,
  workspaceId: string,
  assessmentId: string
): Promise<ImpactAssessment> {
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/impact/${assessmentId}?workspace_id=${workspaceId}`
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch impact assessment (${res.status})`);
  }
  return res.json();
}

export async function fetchImpactHistory(
  repositoryId: string,
  workspaceId: string,
  limit: number = 10,
  offset: number = 0
): Promise<ImpactAssessmentListResponse> {
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/impact/history?workspace_id=${workspaceId}&limit=${limit}&offset=${offset}`
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch impact history (${res.status})`);
  }
  return res.json();
}

export async function fetchRecommendedTests(
  repositoryId: string,
  workspaceId: string,
  assessmentId: string
): Promise<TestRecommendationItem[]> {
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/impact/${assessmentId}/tests?workspace_id=${workspaceId}`
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch recommended tests (${res.status})`);
  }
  return res.json();
}

export async function executeRegressionTests(
  repositoryId: string,
  workspaceId: string,
  assessmentId: string,
  payload: RunTestsRequest
): Promise<TestExecutionRunItem> {
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/impact/${assessmentId}/tests/run?workspace_id=${workspaceId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Test execution request failed (${res.status})`);
  }
  return res.json();
}

export async function fetchTestExecutionStatus(
  repositoryId: string,
  workspaceId: string,
  assessmentId: string,
  executionId?: string
): Promise<TestExecutionRunItem> {
  const url = executionId
    ? `/api/v1/repositories/${repositoryId}/impact/${assessmentId}/tests/status?workspace_id=${workspaceId}&execution_id=${executionId}`
    : `/api/v1/repositories/${repositoryId}/impact/${assessmentId}/tests/status?workspace_id=${workspaceId}`;
  const res = await fetchWithAuth(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch test execution status (${res.status})`);
  }
  return res.json();
}

export async function cancelTestExecution(
  repositoryId: string,
  workspaceId: string,
  assessmentId: string,
  executionId: string
): Promise<{ status: string; execution_id: string }> {
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/impact/${assessmentId}/tests/cancel?workspace_id=${workspaceId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ execution_id: executionId }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to cancel test execution (${res.status})`);
  }
  return res.json();
}
