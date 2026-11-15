// DevMemory API client — types and fetch functions
// Mirrors backend schemas in backend/app/services/devmemory/schemas.py
// and backend/app/db/models/devmemory.py

import { fetchWithAuth } from "./auth";
import { getResponseErrorMessage } from "./api-error";

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type MemoryType =
  | "ARCHITECTURE_DECISION"
  | "TECHNICAL_DECISION"
  | "BUG_FIX"
  | "VERIFIED_BUGFIX"
  | "REPO_KNOWLEDGE"
  | "CODE_EXPLANATION"
  | "ENGINEERING_CONVENTION"
  | "REPOSITORY_CONVENTION"
  | "TASK_OUTCOME"
  | "IMPLEMENTATION_DISCOVERY"
  | "ENGINEERING_DISCOVERY"
  | "KNOWN_LIMITATION"
  | "VERIFIED_SOLUTION";

export type MemoryVerificationStatus =
  | "UNVERIFIED"
  | "VERIFIED"
  | "OUTDATED"
  | "ARCHIVED";

export type EvidenceType =
  | "CODE_REFERENCE"
  | "GIT_COMMIT"
  | "CODE_DIFF"
  | "TEST_RESULT";

export type MemoryRelationshipType =
  | "EXTENDS"
  | "SUPERSEDES"
  | "CONTRADICTS"
  | "RELATES_TO"
  | "CAUSED_BY"
  | "RESOLVED_BY";

export type MemoryConsumerAgent =
  | "DEVPILOT"
  | "IMPACTMIND"
  | "TESTPILOT"
  | "SECUREFLOW"
  | "FLOWFORGE"
  | "USER";

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

export interface MemoryEvidenceResponse {
  id: string;
  memory_id: string;
  workspace_id: string;
  evidence_type: EvidenceType | string;
  source_reference: string | null;
  evidence_content: string;
  created_at: string;
}

export interface MemoryRelationshipResponse {
  id: string;
  workspace_id: string;
  source_memory_id: string;
  target_memory_id: string;
  relationship_type: MemoryRelationshipType | string;
  confidence_score: number;
  created_at: string;
  metadata?: Record<string, unknown> | null;
}

export interface MemoryResponse {
  id: string;
  workspace_id: string;
  repository_id: string | null;
  memory_type: MemoryType | string;
  title: string;
  content: string;
  summary: string | null;
  source_type: string;
  source_reference: string | null;
  confidence_score: number;
  verification_status: MemoryVerificationStatus;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
  content_hash: string;
  metadata?: Record<string, unknown> | null;
  evidence: MemoryEvidenceResponse[];
}

export interface MemorySearchResult {
  memory: MemoryResponse;
  relevance_score: number;
  semantic_score: number;
  lexical_score: number;
  is_verified: boolean;
  evidence_count: number;
}

export interface MemoryStatsResponse {
  total_count: number;
  verified_count: number;
  unverified_count: number;
  outdated_count: number;
  archived_count: number;
  type_counts: Record<string, number>;
}

export interface MemoryContextResponse {
  context_markdown: string;
  citations: string[];
  memories_used: number;
  verified_count: number;
  unverified_count: number;
}

export interface MemoryGraphNeighborhood {
  nodes: Array<{
    id: string;
    title: string;
    type: string;
    status: string;
  }>;
  edges: Array<{
    source: string;
    target: string;
    type: string;
    confidence: number;
  }>;
}

// ---------------------------------------------------------------------------
// Error Handling
// ---------------------------------------------------------------------------

class DevMemoryApiError extends Error {
  constructor(
    public statusCode: number,
    message: string
  ) {
    super(message);
    this.name = "DevMemoryApiError";
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const message = await getResponseErrorMessage(res);
    throw new DevMemoryApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// API Methods
// ---------------------------------------------------------------------------

export async function getMemoryStats(
  workspaceId: string,
  repositoryId?: string | null
): Promise<MemoryStatsResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  if (repositoryId) q.set("repository_id", repositoryId);
  const res = await fetchWithAuth(`/api/v1/devmemory/stats?${q.toString()}`);
  return handleResponse<MemoryStatsResponse>(res);
}

export async function listMemories(
  workspaceId: string,
  params?: {
    repositoryId?: string | null;
    verificationStatus?: string | null;
    memoryType?: string | null;
    includeArchived?: boolean;
    limit?: number;
    offset?: number;
  }
): Promise<MemoryResponse[]> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  if (params?.repositoryId) q.set("repository_id", params.repositoryId);
  if (params?.verificationStatus) q.set("verification_status", params.verificationStatus);
  if (params?.memoryType) q.set("memory_type", params.memoryType);
  if (params?.includeArchived) q.set("include_archived", "true");
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));

  const res = await fetchWithAuth(`/api/v1/devmemory/memories?${q.toString()}`);
  return handleResponse<MemoryResponse[]>(res);
}

export async function getMemory(
  memoryId: string,
  workspaceId: string
): Promise<MemoryResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/devmemory/memories/${memoryId}?${q.toString()}`
  );
  return handleResponse<MemoryResponse>(res);
}

export async function createMemory(
  workspaceId: string,
  payload: {
    title: string;
    content: string;
    memory_type: MemoryType;
    summary?: string;
    repository_id?: string | null;
    confidence_score?: number;
    evidence?: Array<{
      evidence_type: EvidenceType;
      evidence_content: string;
      source_reference?: string;
    }>;
  }
): Promise<MemoryResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(`/api/v1/devmemory/memories?${q.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<MemoryResponse>(res);
}

export async function searchMemories(
  workspaceId: string,
  payload: {
    query: string;
    repository_id?: string | null;
    memory_types?: MemoryType[];
    verification_statuses?: MemoryVerificationStatus[];
    include_archived?: boolean;
    include_outdated?: boolean;
    limit?: number;
    min_score?: number;
    hybrid_weight_semantic?: number;
  }
): Promise<MemorySearchResult[]> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(`/api/v1/devmemory/search?${q.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<MemorySearchResult[]>(res);
}

export async function getMemoryContext(
  workspaceId: string,
  payload: {
    query: string;
    repository_id?: string | null;
    agent?: MemoryConsumerAgent;
    max_tokens?: number;
    include_unverified?: boolean;
    limit?: number;
  }
): Promise<MemoryContextResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(`/api/v1/devmemory/context?${q.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<MemoryContextResponse>(res);
}

export async function verifyMemory(
  memoryId: string,
  workspaceId: string,
  payload: {
    reason?: string;
    evidence?: {
      evidence_type: EvidenceType;
      evidence_content: string;
      source_reference?: string;
    };
  }
): Promise<MemoryResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/devmemory/memories/${memoryId}/verify?${q.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  return handleResponse<MemoryResponse>(res);
}

export async function outdateMemory(
  memoryId: string,
  workspaceId: string,
  reason?: string
): Promise<MemoryResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/devmemory/memories/${memoryId}/outdate?${q.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason || null }),
    }
  );
  return handleResponse<MemoryResponse>(res);
}

export async function archiveMemory(
  memoryId: string,
  workspaceId: string,
  reason?: string
): Promise<MemoryResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  if (reason) q.set("reason", reason);
  const res = await fetchWithAuth(
    `/api/v1/devmemory/memories/${memoryId}/archive?${q.toString()}`,
    { method: "POST" }
  );
  return handleResponse<MemoryResponse>(res);
}

export async function listEvidence(
  memoryId: string,
  workspaceId: string
): Promise<MemoryEvidenceResponse[]> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/devmemory/memories/${memoryId}/evidence?${q.toString()}`
  );
  return handleResponse<MemoryEvidenceResponse[]>(res);
}

export async function attachEvidence(
  memoryId: string,
  workspaceId: string,
  payload: {
    evidence_type: EvidenceType;
    evidence_content: string;
    source_reference?: string;
  }
): Promise<MemoryEvidenceResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/devmemory/memories/${memoryId}/evidence?${q.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  return handleResponse<MemoryEvidenceResponse>(res);
}

export async function listRelationships(
  memoryId: string,
  workspaceId: string
): Promise<MemoryRelationshipResponse[]> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/devmemory/memories/${memoryId}/relationships?${q.toString()}`
  );
  return handleResponse<MemoryRelationshipResponse[]>(res);
}

export async function createRelationship(
  workspaceId: string,
  payload: {
    source_memory_id: string;
    target_memory_id: string;
    relationship_type: MemoryRelationshipType;
    confidence_score?: number;
  }
): Promise<MemoryRelationshipResponse> {
  const q = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithAuth(
    `/api/v1/devmemory/relationships?${q.toString()}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  return handleResponse<MemoryRelationshipResponse>(res);
}

export async function getMemoryNeighborhoodGraph(
  memoryId: string,
  workspaceId: string,
  depth: number = 2
): Promise<MemoryGraphNeighborhood> {
  const q = new URLSearchParams({
    workspace_id: workspaceId,
    depth: String(depth),
  });
  const res = await fetchWithAuth(
    `/api/v1/devmemory/memories/${memoryId}/graph?${q.toString()}`
  );
  return handleResponse<MemoryGraphNeighborhood>(res);
}
