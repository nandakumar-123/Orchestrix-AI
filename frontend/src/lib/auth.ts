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

export function getCsrfTokenFromCookie(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)orchestrix_csrf=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

export async function fetchCsrfToken(): Promise<string | null> {
  const cookieToken = getCsrfTokenFromCookie();
  if (cookieToken) return cookieToken;

  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/csrf`, {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: "application/json",
      },
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.csrf_token || null;
  } catch {
    return null;
  }
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
    const csrfToken = await fetchCsrfToken();
    const headers: Record<string, string> = {
      Accept: "application/json",
    };
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }

    const res = await fetch(`${API_BASE_URL}/api/v1/auth/logout`, {
      method: "POST",
      credentials: "include",
      headers,
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function fetchWithAuth(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");

  // Attach CSRF token on state-changing requests
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrfToken = await fetchCsrfToken();
    if (csrfToken && !headers.has("X-CSRF-Token")) {
      headers.set("X-CSRF-Token", csrfToken);
    }
  }

  return fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    credentials: "include",
    headers,
  });
}
