import { fetchWithAuth } from "./auth";

export type IndexingStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";

export interface IndexingJob {
  id: string;
  workspace_id: string;
  repository_id: string;
  commit_sha: string;
  branch: string;
  status: IndexingStatus;
  progress_percent: number;
  current_step?: string | null;
  error_message?: string | null;
  files_count: number;
  symbols_count: number;
  dependencies_count: number;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface IndexingJobListResponse {
  jobs: IndexingJob[];
  total: number;
}

export interface RepositorySnapshotOverview {
  id: string;
  repository_id: string;
  workspace_id: string;
  commit_sha: string;
  branch: string;
  total_files: number;
  total_lines: number;
  total_bytes: number;
  total_symbols: number;
  total_dependencies: number;
  languages_summary: Record<string, { files: number; lines: number }>;
  entry_points: string[];
  detected_frameworks?: string[];
  created_at: string;
}

export interface RepositoryIntelligenceOverview {
  repository_id: string;
  workspace_id: string;
  latest_snapshot?: RepositorySnapshotOverview | null;
  active_job?: IndexingJob | null;
  detected_frameworks?: string[];
  last_indexed_at?: string | null;
}

export interface SupportedLanguageCapability {
  name: string;
  package_name: string;
  available: boolean;
  extensions: string[];
}

export interface SupportedLanguagesResponse {
  total_supported: number;
  languages: SupportedLanguageCapability[];
}

export interface RepositoryFileItem {
  id: string;
  path: string;
  file_name: string;
  extension?: string | null;
  language?: string | null;
  size_bytes: number;
  line_count: number;
}

export interface RepositoryFileListResponse {
  files: RepositoryFileItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface CodeSymbolItem {
  id: string;
  file_path: string;
  name: string;
  symbol_type: string;
  language: string;
  start_line: number;
  end_line: number;
  start_column?: number | null;
  end_column?: number | null;
  signature?: string | null;
  parent_symbol_name?: string | null;
}

export interface CodeSymbolListResponse {
  symbols: CodeSymbolItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface FileDependencyItem {
  id: string;
  file_path: string;
  name: string;
  version_spec?: string | null;
  dependency_type: string;
  package_manager?: string | null;
}

export interface FileDependencyListResponse {
  dependencies: FileDependencyItem[];
  total: number;
  limit: number;
  offset: number;
}

// -----------------------------------------------------------------------------
// Semantic Intelligence & Retrieval Types & Functions
// -----------------------------------------------------------------------------

export interface SemanticSearchResultItem {
  chunk_id: string;
  repository_id: string;
  repository_name: string;
  snapshot_id: string;
  file_path: string;
  language: string;
  symbol_name?: string | null;
  symbol_type?: string | null;
  parent_symbol_name?: string | null;
  start_line: number;
  end_line: number;
  source_code_excerpt: string;
  similarity_score: number;
  vector_score: number;
  lexical_score: number;
  symbol_score: number;
  metadata?: Record<string, unknown>;
}

export interface SemanticSearchResponse {
  repository_id: string;
  query: string;
  total_results: number;
  results: SemanticSearchResultItem[];
}

export interface SemanticIndexStatusResponse {
  repository_id: string;
  snapshot_id?: string | null;
  provider_name: string;
  model_name: string;
  dimension: number;
  total_chunks: number;
  status: "pending" | "indexing" | "completed" | "failed" | "unindexed";
  error_message?: string | null;
  completed_at?: string | null;
}

/**
 * Execute semantic & hybrid code retrieval query against a repository.
 */
export async function executeSemanticSearch(
  repositoryId: string,
  workspaceId: string,
  query: string,
  options?: {
    language?: string;
    symbol_type?: string;
    file_path_prefix?: string;
    limit?: number;
  },
): Promise<SemanticSearchResponse | null> {
  try {
    const res = await fetchWithAuth(
      `/api/v1/repositories/${repositoryId}/semantic-search?workspace_id=${workspaceId}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          language: options?.language || undefined,
          symbol_type: options?.symbol_type || undefined,
          file_path_prefix: options?.file_path_prefix || undefined,
          limit: options?.limit || 10,
        }),
      },
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * Get semantic embedding and indexing status.
 */
export async function fetchSemanticIndexStatus(
  repositoryId: string,
  workspaceId: string,
): Promise<SemanticIndexStatusResponse | null> {
  try {
    const res = await fetchWithAuth(
      `/api/v1/repositories/${repositoryId}/semantic-index/status?workspace_id=${workspaceId}`,
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * Trigger semantic AST chunking and embedding generation.
 */
export async function triggerSemanticIndex(
  repositoryId: string,
  workspaceId: string,
  forceReembed: boolean = false,
): Promise<SemanticIndexStatusResponse | null> {
  try {
    const res = await fetchWithAuth(
      `/api/v1/repositories/${repositoryId}/semantic-index?workspace_id=${workspaceId}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force_reembed: forceReembed }),
      },
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * Trigger an indexing job for a repository.
 */
export async function startIndexingJob(
  repositoryId: string,
  workspaceId: string,
  branch?: string,
): Promise<{ ok: boolean; job?: IndexingJob; error?: string }> {
  try {
    const url = `/api/v1/repositories/${repositoryId}/indexing/start?workspace_id=${workspaceId}${
      branch ? `&branch=${encodeURIComponent(branch)}` : ""
    }`;
    const res = await fetchWithAuth(url, {
      method: "POST",
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      return { ok: false, error: data.detail || `Failed to start indexing (${res.status})` };
    }
    const job: IndexingJob = await res.json();
    return { ok: true, job };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Network error";
    return { ok: false, error: message };
  }
}

/**
 * Fetch list of all supported languages and parser availability in Orchestrix registry.
 */
export async function fetchSupportedLanguages(): Promise<SupportedLanguagesResponse | null> {
  try {
    const res = await fetchWithAuth("/api/v1/repositories/intelligence/supported-languages");
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function fetchRepositoryIntelligence(
  repositoryId: string,
  workspaceId: string,
): Promise<RepositoryIntelligenceOverview | null> {
  try {
    const res = await fetchWithAuth(
      `/api/v1/repositories/${repositoryId}/intelligence?workspace_id=${workspaceId}`,
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * Fetch a specific indexing job by ID.
 */
export async function fetchIndexingJob(
  repositoryId: string,
  jobId: string,
  workspaceId: string,
): Promise<IndexingJob | null> {
  try {
    const res = await fetchWithAuth(
      `/api/v1/repositories/${repositoryId}/indexing/jobs/${jobId}?workspace_id=${workspaceId}`,
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * Cancel an active or pending indexing job.
 */
export async function cancelIndexingJob(
  repositoryId: string,
  jobId: string,
  workspaceId: string,
): Promise<{ ok: boolean; job?: IndexingJob; error?: string }> {
  try {
    const res = await fetchWithAuth(
      `/api/v1/repositories/${repositoryId}/indexing/jobs/${jobId}/cancel?workspace_id=${workspaceId}`,
      { method: "POST" },
    );
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      return { ok: false, error: data.detail || "Failed to cancel job" };
    }
    const job = await res.json();
    return { ok: true, job };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Network error";
    return { ok: false, error: message };
  }
}

/**
 * List indexing jobs for a repository.
 */
export async function fetchIndexingJobs(
  repositoryId: string,
  workspaceId: string,
): Promise<IndexingJobListResponse | null> {
  try {
    const res = await fetchWithAuth(
      `/api/v1/repositories/${repositoryId}/indexing/jobs?workspace_id=${workspaceId}`,
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * List indexed files in repository.
 */
export async function fetchRepositoryFiles(
  repositoryId: string,
  workspaceId: string,
  options?: { language?: string; limit?: number; offset?: number },
): Promise<RepositoryFileListResponse | null> {
  try {
    const params = new URLSearchParams({ workspace_id: workspaceId });
    if (options?.language) params.append("language", options.language);
    if (options?.limit) params.append("limit", options.limit.toString());
    if (options?.offset) params.append("offset", options.offset.toString());

    const res = await fetchWithAuth(
      `/api/v1/repositories/${repositoryId}/files?${params.toString()}`,
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * List indexed code symbols.
 */
export async function fetchRepositorySymbols(
  repositoryId: string,
  workspaceId: string,
  options?: {
    symbol_type?: string;
    language?: string;
    query?: string;
    limit?: number;
    offset?: number;
  },
): Promise<CodeSymbolListResponse | null> {
  try {
    const params = new URLSearchParams({ workspace_id: workspaceId });
    if (options?.symbol_type) params.append("symbol_type", options.symbol_type);
    if (options?.language) params.append("language", options.language);
    if (options?.query) params.append("query", options.query);
    if (options?.limit) params.append("limit", options.limit.toString());
    if (options?.offset) params.append("offset", options.offset.toString());

    const res = await fetchWithAuth(
      `/api/v1/repositories/${repositoryId}/symbols?${params.toString()}`,
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * List indexed dependencies.
 */
export async function fetchRepositoryDependencies(
  repositoryId: string,
  workspaceId: string,
  options?: {
    dependency_type?: string;
    package_manager?: string;
    query?: string;
    limit?: number;
    offset?: number;
  },
): Promise<FileDependencyListResponse | null> {
  try {
    const params = new URLSearchParams({ workspace_id: workspaceId });
    if (options?.dependency_type) params.append("dependency_type", options.dependency_type);
    if (options?.package_manager) params.append("package_manager", options.package_manager);
    if (options?.query) params.append("query", options.query);
    if (options?.limit) params.append("limit", options.limit.toString());
    if (options?.offset) params.append("offset", options.offset.toString());

    const res = await fetchWithAuth(
      `/api/v1/repositories/${repositoryId}/dependencies?${params.toString()}`,
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}
