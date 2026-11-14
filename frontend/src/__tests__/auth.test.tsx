import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import LoginPage from "../app/login/page";
import { fetchCurrentUser, logout, getGoogleLoginUrl } from "../lib/auth";

describe("Orchestrix AI Authentication", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the login page with Google OAuth button and security assurances", () => {
    render(<LoginPage />);
    expect(screen.getByText("Sign in to Orchestrix AI")).toBeInTheDocument();
    expect(
      screen.getByText("Autonomous multi-agent software engineering mesh")
    ).toBeInTheDocument();
    expect(screen.getByText("Continue with Google")).toBeInTheDocument();
    expect(screen.getByText(/OpenID Connect with PKCE/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Automatic personal tenant workspace provisioning/i)
    ).toBeInTheDocument();
  });

  it("constructs the correct Google login URL", () => {
    const url = getGoogleLoginUrl();
    expect(url).toContain("/auth/google/login");
  });

  it("returns null from fetchCurrentUser when unauthenticated (401)", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
    });

    const user = await fetchCurrentUser();
    expect(user).toBeNull();
  });

  it("returns user profile from fetchCurrentUser when authenticated (200)", async () => {
    const mockUser = {
      id: "11111111-1111-1111-1111-111111111111",
      email: "engineer@orchestrix.ai",
      full_name: "Lead Engineer",
      avatar_url: null,
      email_verified: true,
      workspaces: [
        {
          workspace_id: "22222222-2222-2222-2222-222222222222",
          name: "Main Workspace",
          slug: "main-ws",
          role: "OWNER",
        },
      ],
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockUser,
    });

    const user = await fetchCurrentUser();
    expect(user).toEqual(mockUser);
  });

  it("calls logout endpoint successfully", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: "ok", message: "Logged out" }),
    });

    const success = await logout();
    expect(success).toBe(true);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/auth/logout"),
      expect.objectContaining({ method: "POST" })
    );
  });
});
