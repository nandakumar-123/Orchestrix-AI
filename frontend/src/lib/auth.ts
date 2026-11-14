export interface WorkspaceMembership {
  workspace_id: string;
  name: string;
  slug: string;
  role: "OWNER" | "ADMIN" | "MEMBER" | "VIEWER";
}

export interface CurrentUser {
  id: string;
  email: string;
  full_name: string | null;
  avatar_url: string | null;
  email_verified: boolean;
  workspaces: WorkspaceMembership[];
}

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function getGoogleLoginUrl(): string {
  return `${API_BASE_URL}/auth/google/login`;
}

export async function fetchCurrentUser(): Promise<CurrentUser | null> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: "application/json",
      },
    });

    if (res.status === 401 || res.status === 403 || !res.ok) {
      return null;
    }

    const data: CurrentUser = await res.json();
    return data;
  } catch {
    return null;
  }
}

export async function logout(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/logout`, {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
      },
    });
    return res.ok;
  } catch {
    return false;
  }
}
