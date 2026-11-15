import { fetchWithAuth } from "./auth";
import { getResponseErrorMessage } from "./api-error";

export type TestPilotFramework =
  | "pytest"
  | "unittest"
  | "vitest"
  | "jest"
  | "mocha"
  | "custom";

export type TestPilotTestType =
  | "unit"
  | "integration"
  | "regression"
  | "edge_case"
  | "negative";

export type TestSuiteStatus = "GENERATED" | "APPROVED" | "REJECTED";

export type TestExecutionStatus =
  | "PENDING"
  | "RUNNING"
  | "PASSED"
  | "FAILED"
  | "ERROR"
  | "TIMED_OUT"
  | "CANCELLED"
  | "BLOCKED";

export type TestResultOutcome =
  | "PASSED"
  | "FAILED"
  | "ERROR"
  | "SKIPPED"
  | "BLOCKED";

export interface DetectedFramework {
  language: string;
  framework: string;
  config_file: string | null;
  test_directory: string;
  naming_convention: string;
  runner_command: string;
  is_available: boolean;
  confidence: number;
  missing_requirements: string[];
}

export interface TestCaseItem {
  id?: string | null;
  name: string;
  description: string;
  test_type: string;
  target_symbol?: string | null;
  code: string;
  is_edge_case: boolean;
  relevance_explanation?: string;
}

export interface TestPilotSuite {
  id: string;
  workspace_id: string;
  repository_id: string;
  snapshot_id?: string | null;
  framework: string;
  target_files: string[];
  test_type: string;
  test_cases: TestCaseItem[];
  status: TestSuiteStatus | string;
  created_at: string;
  approved_at?: string | null;
  approved_by?: string | null;
}

export interface TestPilotSuiteListResponse {
  items: TestPilotSuite[];
  total: number;
  limit: number;
  offset: number;
}

export interface IndividualTestResult {
  id: string;
  execution_id: string;
  test_name: string;
  status: TestResultOutcome | string;
  duration_ms: number;
  failure_message?: string | null;
  traceback?: string | null;
}

export interface TestExecution {
  id: string;
  suite_id?: string | null;
  workspace_id: string;
  repository_id: string;
  command: string;
  status: TestExecutionStatus | string;
  exit_code?: number | null;
  duration_ms: number;
  passed_count: number;
  failed_count: number;
  skipped_count: number;
  error_message?: string | null;
  stdout: string;
  stderr: string;
  executed_at?: string | null;
  created_at: string;
}

export interface TestExecutionListResponse {
  items: TestExecution[];
  total: number;
  limit: number;
  offset: number;
}

export interface CoverageReport {
  id: string;
  workspace_id: string;
  repository_id: string;
  execution_id?: string | null;
  line_coverage_pct: number | null;
  branch_coverage_pct: number | null;
  uncovered_files: string[];
  uncovered_functions: Array<Record<string, unknown>>;
  raw_report?: Record<string, unknown> | null;
  created_at: string;
}

export interface CoverageReportListResponse {
  items: CoverageReport[];
  total: number;
  limit: number;
  offset: number;
}

export interface DiagnosisResponse {
  failing_test: string;
  error_message: string;
  traceback_parsed: Record<string, unknown>;
  root_cause_analysis: string;
  fix_suggestions: string[];
  affected_files: string[];
  confidence: number;
  target_symbol?: string | null;
}

export interface ImpactTestSelectionResponse {
  selected_tests: Array<Record<string, unknown>>;
  impacted_symbols: string[];
  risk_exposure_score: number;
  change_summary: string;
  rationale: string[];
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

export async function detectFrameworks(
  repositoryId: string,
  subpath?: string,
  workspaceId?: string
): Promise<DetectedFramework[]> {
  const query = buildQuery({ workspace_id: workspaceId });
  const payload = subpath ? { subpath } : {};

  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/testpilot/detect${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to detect frameworks (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function generateTestSuite(
  repositoryId: string,
  data: {
    framework: TestPilotFramework | string;
    target_files: string[];
    source_context: string;
    test_type?: TestPilotTestType;
    snapshot_id?: string | null;
    symbols_info?: Array<Record<string, unknown>>;
  },
  workspaceId?: string
): Promise<TestPilotSuite> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/testpilot/suites${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        framework: data.framework,
        target_files: data.target_files,
        source_context: data.source_context,
        test_type: data.test_type || "unit",
        snapshot_id: data.snapshot_id || null,
        symbols_info: data.symbols_info || null,
      }),
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to generate test suite (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function listTestSuites(
  repositoryId: string,
  params?: {
    status?: string;
    limit?: number;
    offset?: number;
    workspaceId?: string;
  }
): Promise<TestPilotSuiteListResponse> {
  const query = buildQuery({
    status: params?.status,
    limit: params?.limit ?? 50,
    offset: params?.offset ?? 0,
    workspace_id: params?.workspaceId,
  });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/testpilot/suites${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to list test suites (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function getTestSuite(
  repositoryId: string,
  suiteId: string,
  workspaceId?: string
): Promise<TestPilotSuite> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/testpilot/suites/${suiteId}${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to get test suite (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function approveTestSuite(
  repositoryId: string,
  suiteId: string,
  workspaceId?: string
): Promise<TestPilotSuite> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/testpilot/suites/${suiteId}/approve${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to approve test suite (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function rejectTestSuite(
  repositoryId: string,
  suiteId: string,
  reason?: string,
  workspaceId?: string
): Promise<TestPilotSuite> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/testpilot/suites/${suiteId}/reject${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason || null }),
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to reject test suite (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function executeTestSuite(
  repositoryId: string,
  suiteId: string,
  options?: {
    custom_command?: string;
    timeout_seconds?: number;
  },
  workspaceId?: string
): Promise<TestExecution> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/testpilot/suites/${suiteId}/execute${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        custom_command: options?.custom_command || null,
        timeout_seconds: options?.timeout_seconds ?? 120,
      }),
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to execute test suite (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function getTestExecution(
  repositoryId: string,
  executionId: string,
  workspaceId?: string
): Promise<TestExecution> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/testpilot/executions/${executionId}${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to get test execution (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function getTestResults(
  repositoryId: string,
  executionId: string,
  workspaceId?: string
): Promise<IndividualTestResult[]> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/testpilot/executions/${executionId}/results${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to fetch test results (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function listCoverageReports(
  repositoryId: string,
  params?: {
    limit?: number;
    offset?: number;
    workspaceId?: string;
  }
): Promise<CoverageReportListResponse> {
  const query = buildQuery({
    limit: params?.limit ?? 20,
    offset: params?.offset ?? 0,
    workspace_id: params?.workspaceId,
  });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/testpilot/coverage${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to fetch coverage reports (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function diagnoseFailure(
  repositoryId: string,
  executionId: string,
  sourceContext?: string,
  workspaceId?: string
): Promise<DiagnosisResponse> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/testpilot/executions/${executionId}/diagnose${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_context: sourceContext || null }),
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to diagnose failure (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function cancelExecution(
  repositoryId: string,
  executionId: string,
  workspaceId?: string
): Promise<TestExecution> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/testpilot/executions/${executionId}/cancel${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to cancel execution (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function selectImpactTests(
  repositoryId: string,
  diffText: string,
  allTestFiles?: string[],
  workspaceId?: string
): Promise<ImpactTestSelectionResponse> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/testpilot/impact/select${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        diff_text: diffText,
        all_test_files: allTestFiles || null,
      }),
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to select impact tests (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}
