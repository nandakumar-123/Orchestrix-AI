import { fetchWithAuth } from "./auth";
import { getResponseErrorMessage } from "./api-error";

export type ScanType = "FULL" | "SECRETS" | "DEPENDENCIES" | "SAST";

export type ScanStatus =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "PARTIALLY_COMPLETED";

export type FindingSeverity =
  | "CRITICAL"
  | "HIGH"
  | "MEDIUM"
  | "LOW"
  | "UNKNOWN";

export type FindingStatus =
  | "OPEN"
  | "CONFIRMED"
  | "FALSE_POSITIVE"
  | "ACCEPTED_RISK"
  | "RESOLVED";

export interface ScannerStatusItem {
  scanner: string;
  category: string;
  is_available: boolean;
  version: string | null;
  binary_path: string | null;
  details: string | null;
}

export interface ScannerAvailabilityResponse {
  scanners: ScannerStatusItem[];
  all_available: boolean;
}

export interface SecureFlowFinding {
  id: string;
  workspace_id: string;
  repository_id: string;
  scan_id: string;
  scanner: string;
  category: string;
  severity: FindingSeverity | string;
  confidence: number;
  rule_id: string;
  title: string;
  description: string;
  redacted_evidence?: string | null;
  file_path?: string | null;
  line_start?: number | null;
  line_end?: number | null;
  remediation_recommendation?: string | null;
  remediation_code_snippet?: string | null;
  external_advisory_url?: string | null;
  fingerprint: string;
  status: FindingStatus | string;
  created_at: string;
  updated_at: string;
}

export interface SecureFlowFindingListResponse {
  items: SecureFlowFinding[];
  total: number;
  limit: number;
  offset: number;
}

export interface SecureFlowScan {
  id: string;
  workspace_id: string;
  repository_id: string;
  snapshot_id?: string | null;
  scan_type: ScanType | string;
  status: ScanStatus | string;
  scanners_used: Array<Record<string, unknown>>;
  total_findings: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
}

export interface SecureFlowScanListResponse {
  items: SecureFlowScan[];
  total: number;
  limit: number;
  offset: number;
}

export interface SecureFlowScanEvent {
  id: string;
  scan_id: string;
  event_type: string;
  message: string;
  details?: Record<string, unknown> | null;
  created_at: string;
}

export interface SecureFlowScanEventListResponse {
  items: SecureFlowScanEvent[];
  total: number;
  limit: number;
  offset: number;
}

export interface RemediationTaskResponse {
  finding_id: string;
  devpilot_task_id: string;
  task_title: string;
  task_status: string;
  requires_plan_approval: boolean;
  requires_code_approval: boolean;
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

export async function getScannerAvailability(
  repositoryId: string,
  workspaceId?: string
): Promise<ScannerAvailabilityResponse> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/secureflow/scanners${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to get scanner availability (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function startScan(
  repositoryId: string,
  payload?: {
    scan_type?: ScanType;
    snapshot_id?: string | null;
    subpath?: string | null;
  },
  workspaceId?: string
): Promise<SecureFlowScan> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/secureflow/scans${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        scan_type: payload?.scan_type || "FULL",
        snapshot_id: payload?.snapshot_id || null,
        subpath: payload?.subpath || null,
      }),
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to start security scan (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function listScans(
  repositoryId: string,
  params?: {
    limit?: number;
    offset?: number;
    workspaceId?: string;
  }
): Promise<SecureFlowScanListResponse> {
  const query = buildQuery({
    limit: params?.limit ?? 20,
    offset: params?.offset ?? 0,
    workspace_id: params?.workspaceId,
  });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/secureflow/scans${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to list security scans (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function getScan(
  repositoryId: string,
  scanId: string,
  workspaceId?: string
): Promise<SecureFlowScan> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/secureflow/scans/${scanId}${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to get security scan (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function getScanEvents(
  repositoryId: string,
  scanId: string,
  params?: {
    limit?: number;
    offset?: number;
    workspaceId?: string;
  }
): Promise<SecureFlowScanEventListResponse> {
  const query = buildQuery({
    limit: params?.limit ?? 50,
    offset: params?.offset ?? 0,
    workspace_id: params?.workspaceId,
  });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/secureflow/scans/${scanId}/events${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to get scan events (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function listFindings(
  repositoryId: string,
  params?: {
    severity?: string;
    status?: string;
    category?: string;
    scan_id?: string;
    limit?: number;
    offset?: number;
    workspaceId?: string;
  }
): Promise<SecureFlowFindingListResponse> {
  const query = buildQuery({
    severity: params?.severity,
    status: params?.status,
    category: params?.category,
    scan_id: params?.scan_id,
    limit: params?.limit ?? 50,
    offset: params?.offset ?? 0,
    workspace_id: params?.workspaceId,
  });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/secureflow/findings${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to list findings (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function getFinding(
  repositoryId: string,
  findingId: string,
  workspaceId?: string
): Promise<SecureFlowFinding> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/secureflow/findings/${findingId}${query}`
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to get finding (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function updateFindingStatus(
  repositoryId: string,
  findingId: string,
  status: FindingStatus | string,
  note?: string,
  workspaceId?: string
): Promise<SecureFlowFinding> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/secureflow/findings/${findingId}/status${query}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status,
        note: note || null,
      }),
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to update finding status (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function remediateFinding(
  repositoryId: string,
  findingId: string,
  workspaceId?: string
): Promise<RemediationTaskResponse> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/secureflow/findings/${findingId}/remediate${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }
  );
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to initiate DevPilot remediation (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function getFindingRemediation(
  repositoryId: string,
  findingId: string,
  workspaceId?: string
): Promise<RemediationTaskResponse | null> {
  const query = buildQuery({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/repositories/${repositoryId}/secureflow/findings/${findingId}/remediation${query}`
  );
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to get finding remediation (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}
