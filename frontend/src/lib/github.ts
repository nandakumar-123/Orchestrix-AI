import { API_BASE_URL, fetchWithAuth } from "./auth";

export interface GitHubStatus {
  connected: boolean;
  github_login?: string | null;
  name?: string | null;
  avatar_url?: string | null;
  html_url?: string | null;
  scope?: string | null;
  connected_at?: string | null;
}

export interface AccessibleGitHubRepo {
  id: number;
  name: string;
  full_name: string;
  owner_login: string;
  owner_avatar_url?: string | null;
  description?: string | null;
  default_branch: string;
  html_url: string;
  visibility: string;
  language?: string | null;
  updated_at?: string | null;
  stargazers_count: number;
  forks_count: number;
  open_issues_count: number;
  is_connected: boolean;
}

export interface WorkspaceRepository {
  id: string;
  workspace_id: string;
  installation_id: string;
  github_repository_id: number;
  name: string;
  full_name: string;
  owner_login: string;
  description?: string | null;
  default_branch: string;
  html_url: string;
  visibility: string;
  language?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at?: string | null;
}

export interface ConnectRepositoryInput {
  workspace_id: string;
  github_repository_id: number;
  name: string;
  full_name: string;
  owner_login: string;
  owner_avatar_url?: string | null;
  description?: string | null;
  default_branch: string;
  html_url: string;
  visibility: string;
  language?: string | null;
}

/**
 * Get direct URL to initiate GitHub OAuth connect flow.
 */
export function getGitHubConnectUrl(): string {
  return `${API_BASE_URL}/api/v1/github/connect?redirect=true`;
}

/**
 * Fetch status of the current user's connected GitHub account.
 */
export async function fetchGitHubStatus(): Promise<GitHubStatus> {
  try {
    const res = await fetchWithAuth("/api/v1/github/status");
    if (!res.ok) {
      return { connected: false };
    }
    return await res.json();
  } catch {
    return { connected: false };
  }
}

/**
 * Disconnect current user's GitHub account and purge stored credentials.
 */
export async function disconnectGitHub(): Promise<boolean> {
  try {
    const res = await fetchWithAuth("/api/v1/github/disconnect", {
      method: "DELETE",
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Fetch repositories accessible to the user via their connected GitHub account.
 */
export async function fetchAccessibleGitHubRepos(
  workspaceId: string,
  page: number = 1,
  perPage: number = 50
): Promise<AccessibleGitHubRepo[]> {
  try {
    const res = await fetchWithAuth(
      `/api/v1/github/repositories?workspace_id=${encodeURIComponent(
        workspaceId
      )}&page=${page}&per_page=${perPage}`
    );
    if (!res.ok) {
      return [];
    }
    const data = await res.json();
    return data.items || [];
  } catch {
    return [];
  }
}

/**
 * Fetch all active repositories connected to a specific workspace.
 */
export async function fetchWorkspaceRepositories(
  workspaceId: string
): Promise<WorkspaceRepository[]> {
  try {
    const res = await fetchWithAuth(
      `/api/v1/repositories?workspace_id=${encodeURIComponent(workspaceId)}`
    );
    if (!res.ok) {
      return [];
    }
    const data = await res.json();
    return data.items || [];
  } catch {
    return [];
  }
}

/**
 * Connect an accessible GitHub repository to a workspace.
 */
export async function connectRepositoryToWorkspace(
  payload: ConnectRepositoryInput
): Promise<WorkspaceRepository> {
  const res = await fetchWithAuth("/api/v1/github/repositories/connect", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to connect repository");
  }

  return await res.json();
}

/**
 * Disconnect (soft-delete) a repository from a workspace.
 */
export async function disconnectWorkspaceRepository(
  repositoryId: string,
  workspaceId: string
): Promise<boolean> {
  const res = await fetchWithAuth(
    `/api/v1/github/repositories/${encodeURIComponent(
      repositoryId
    )}?workspace_id=${encodeURIComponent(workspaceId)}`,
    {
      method: "DELETE",
    }
  );

  return res.ok;
}

/**
 * Refresh repository metadata from GitHub.
 */
export async function refreshWorkspaceRepository(
  repositoryId: string,
  workspaceId: string
): Promise<WorkspaceRepository> {
  const res = await fetchWithAuth(
    `/api/v1/github/repositories/${encodeURIComponent(
      repositoryId
    )}/refresh?workspace_id=${encodeURIComponent(workspaceId)}`,
    {
      method: "POST",
    }
  );

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to refresh repository metadata");
  }

  return await res.json();
}
