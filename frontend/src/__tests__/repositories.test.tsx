import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import RepositoriesPage from "../app/repositories/page";
import * as authModule from "../lib/auth";
import * as githubModule from "../lib/github";

describe("RepositoriesPage Integration", () => {
  const mockUser: authModule.CurrentUser = {
    id: "usr-123",
    email: "lead@orchestrix.ai",
    full_name: "Lead Engineer",
    avatar_url: null,
    email_verified: true,
    workspaces: [
      {
        workspace_id: "ws-123",
        name: "Acme Production",
        slug: "acme-prod",
        role: "OWNER",
      },
    ],
  };

  const mockMultiWorkspaceUser: authModule.CurrentUser = {
    id: "usr-123",
    email: "lead@orchestrix.ai",
    full_name: "Lead Engineer",
    avatar_url: null,
    email_verified: true,
    workspaces: [
      {
        workspace_id: "ws-123",
        name: "Acme Production",
        slug: "acme-prod",
        role: "OWNER",
      },
      {
        workspace_id: "ws-456",
        name: "Beta Research",
        slug: "beta-research",
        role: "VIEWER",
      },
    ],
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    window.history.pushState({}, "Test", "/repositories");
  });

  it("renders GitHub connection banner and disconnected state", async () => {
    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(githubModule, "fetchGitHubStatus").mockResolvedValue({ connected: false });
    vi.spyOn(githubModule, "fetchWorkspaceRepositories").mockResolvedValue([]);

    render(<RepositoriesPage />);

    expect(screen.getByText("Connected Repositories")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Not Connected")).toBeInTheDocument();
      expect(screen.getByText("No repositories connected")).toBeInTheDocument();
      expect(screen.getAllByText("Acme Production").length).toBeGreaterThan(0);
    });
  });

  it("opens professional account connection modal with Option A and Option B", async () => {
    const user = userEvent.setup();

    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(githubModule, "fetchGitHubStatus").mockResolvedValue({ connected: false });
    vi.spyOn(githubModule, "fetchWorkspaceRepositories").mockResolvedValue([]);

    render(<RepositoriesPage />);

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: /Connect GitHub Account/i }).length).toBeGreaterThan(0);
    });

    // Click "Connect GitHub Account"
    const connectButtons = screen.getAllByRole("button", { name: /Connect GitHub Account/i });
    await user.click(connectButtons[0]);

    // Modal should appear
    await waitFor(() => {
      expect(screen.getByTestId("connect-account-modal")).toBeInTheDocument();
      expect(screen.getByText(/Option A — Use Current GitHub Account/i)).toBeInTheDocument();
      expect(screen.getByText(/Option B — Connect a Different GitHub Account/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Connect Current Account/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Proceed to GitHub/i })).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Sign out of GitHub\.com/i })).toHaveAttribute(
        "href",
        "https://github.com/logout"
      );
    });
  });

  it("renders connected GitHub status and active workspace repositories", async () => {
    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(githubModule, "fetchGitHubStatus").mockResolvedValue({
      connected: true,
      github_login: "octo-engineer",
      scope: "repo,read:user",
      avatar_url: "https://github.com/images/error/octocat_happy.gif",
    });

    const mockRepos: githubModule.WorkspaceRepository[] = [
      {
        id: "repo-1",
        workspace_id: "ws-123",
        installation_id: "inst-1",
        github_repository_id: 111,
        name: "orchestrix-core",
        full_name: "octo-engineer/orchestrix-core",
        owner_login: "octo-engineer",
        description: "Core autonomous agent framework",
        default_branch: "main",
        html_url: "https://github.com/octo-engineer/orchestrix-core",
        visibility: "private",
        language: "Python",
        is_active: true,
        created_at: new Date().toISOString(),
      },
    ];

    vi.spyOn(githubModule, "fetchWorkspaceRepositories").mockResolvedValue(mockRepos);

    render(<RepositoriesPage />);

    await waitFor(() => {
      expect(screen.getAllByText("Connected").length).toBeGreaterThan(0);
      expect(screen.getByText(/@octo-engineer/)).toBeInTheDocument();
      expect(screen.getByText("orchestrix-core")).toBeInTheDocument();
      expect(screen.getByText("octo-engineer")).toBeInTheDocument();
      expect(screen.getByText("Core autonomous agent framework")).toBeInTheDocument();
      expect(screen.getByText("Python")).toBeInTheDocument();
      expect(screen.getAllByText("Connect GitHub Repository").length).toBeGreaterThan(0);
      expect(screen.getByRole("button", { name: /Switch Account/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Disconnect Account/i })).toBeInTheDocument();
    });
  });

  it("opens repository modal and connects accessible repository", async () => {
    const user = userEvent.setup();

    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(githubModule, "fetchGitHubStatus").mockResolvedValue({
      connected: true,
      github_login: "octo-engineer",
    });
    vi.spyOn(githubModule, "fetchWorkspaceRepositories").mockResolvedValue([]);

    const mockAccessible: githubModule.AccessibleGitHubRepo[] = [
      {
        id: 999,
        name: "agent-pipeline",
        full_name: "octo-engineer/agent-pipeline",
        owner_login: "octo-engineer",
        description: "Agent execution pipeline",
        default_branch: "main",
        html_url: "https://github.com/octo-engineer/agent-pipeline",
        visibility: "public",
        language: "TypeScript",
        stargazers_count: 12,
        forks_count: 2,
        open_issues_count: 1,
        is_connected: false,
      },
    ];

    vi.spyOn(githubModule, "fetchAccessibleGitHubRepos").mockResolvedValue(mockAccessible);
    const connectSpy = vi.spyOn(githubModule, "connectRepositoryToWorkspace").mockResolvedValue({
      id: "repo-new",
      workspace_id: "ws-123",
      installation_id: "inst-1",
      github_repository_id: 999,
      name: "agent-pipeline",
      full_name: "octo-engineer/agent-pipeline",
      owner_login: "octo-engineer",
      default_branch: "main",
      html_url: "https://github.com/octo-engineer/agent-pipeline",
      visibility: "public",
      is_active: true,
      created_at: new Date().toISOString(),
    });

    render(<RepositoriesPage />);

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: /Connect GitHub Repository/i }).length).toBeGreaterThan(0);
    });

    // Click "Connect GitHub Repository" button
    const triggerButtons = screen.getAllByRole("button", { name: /Connect GitHub Repository/i });
    await user.click(triggerButtons[0]);

    // Modal should appear
    await waitFor(() => {
      expect(screen.getByText("Connect GitHub Repositories")).toBeInTheDocument();
      expect(screen.getByText("octo-engineer/agent-pipeline")).toBeInTheDocument();
    });

    // Click "Connect" button inside modal
    const connectBtn = screen.getByRole("button", { name: "Connect" });
    await user.click(connectBtn);

    await waitFor(() => {
      expect(connectSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          workspace_id: "ws-123",
          github_repository_id: 999,
          full_name: "octo-engineer/agent-pipeline",
        })
      );
    });
  });

  it("opens disconnect confirmation modal and purges credentials while preserving repositories", async () => {
    const user = userEvent.setup();

    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(githubModule, "fetchGitHubStatus").mockResolvedValue({
      connected: true,
      github_login: "octo-engineer",
    });
    vi.spyOn(githubModule, "fetchWorkspaceRepositories").mockResolvedValue([]);
    const disconnectSpy = vi.spyOn(githubModule, "disconnectGitHub").mockResolvedValue(true);

    render(<RepositoriesPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Disconnect Account/i })).toBeInTheDocument();
    });

    // Click "Disconnect Account"
    await user.click(screen.getByRole("button", { name: /Disconnect Account/i }));

    // Disconnect modal should appear
    await waitFor(() => {
      expect(screen.getByTestId("disconnect-modal")).toBeInTheDocument();
      expect(screen.getByText(/Credentials purged:/i)).toBeInTheDocument();
      expect(screen.getByText(/Repositories preserved:/i)).toBeInTheDocument();
      expect(screen.getByText(/GitHub session remains:/i)).toBeInTheDocument();
    });

    // Confirm Disconnect
    const confirmBtn = screen.getByRole("button", { name: /Confirm Disconnect/i });
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(disconnectSpy).toHaveBeenCalled();
      expect(screen.getByText(/stored credentials purged/i)).toBeInTheDocument();
    });
  });

  it("displays account confirmation banner with avatar when returning from GitHub OAuth", async () => {
    // Simulate OAuth callback query params: ?github=connected&login=octo-fresh
    window.history.pushState({}, "Test", "/repositories?github=connected&login=octo-fresh");

    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(githubModule, "fetchGitHubStatus").mockResolvedValue({
      connected: true,
      github_login: "octo-fresh",
      avatar_url: "https://avatars.githubusercontent.com/u/12345?v=4",
    });
    vi.spyOn(githubModule, "fetchWorkspaceRepositories").mockResolvedValue([]);

    render(<RepositoriesPage />);

    await waitFor(() => {
      expect(screen.getByTestId("account-confirmation-banner")).toBeInTheDocument();
      expect(screen.getAllByText(/@octo-fresh/).length).toBeGreaterThan(0);
      expect(screen.getByText(/Verified Identity/i)).toBeInTheDocument();
      expect(screen.getByRole("img", { name: "octo-fresh" })).toHaveAttribute(
        "src",
        "https://avatars.githubusercontent.com/u/12345?v=4"
      );
      expect(screen.getByRole("button", { name: /Confirm & Continue/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Not your account\? Switch/i })).toBeInTheDocument();
    });
  });

  it("renders workspace selector for multi-workspace users and switches workspace", async () => {
    const user = userEvent.setup();

    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockMultiWorkspaceUser);
    vi.spyOn(githubModule, "fetchGitHubStatus").mockResolvedValue({
      connected: true,
      github_login: "octo-engineer",
    });

    const fetchReposSpy = vi
      .spyOn(githubModule, "fetchWorkspaceRepositories")
      .mockResolvedValue([]);

    render(<RepositoriesPage />);

    // Selector should be visible
    await waitFor(() => {
      const select = screen.getByTestId("workspace-selector");
      expect(select).toBeInTheDocument();
    });

    expect(fetchReposSpy).toHaveBeenCalledWith("ws-123");

    // Change to "Beta Research" (ws-456, VIEWER role)
    const select = screen.getByTestId("workspace-selector");
    await user.selectOptions(select, "ws-456");

    await waitFor(() => {
      expect(fetchReposSpy).toHaveBeenCalledWith("ws-456");
      // VIEWER role warning should be visible
      expect(screen.getByText(/Read-only \(VIEWER\)/i)).toBeInTheDocument();
    });

    // Connect repository button should be disabled for VIEWER
    const connectBtn = screen.getByRole("button", { name: /Connect GitHub Repository/i });
    expect(connectBtn).toBeDisabled();
  });

  it("displays error notification when callback contains github_error", async () => {
    window.history.pushState({}, "Test", "/repositories?github_error=access_denied");

    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(githubModule, "fetchGitHubStatus").mockResolvedValue({ connected: false });
    vi.spyOn(githubModule, "fetchWorkspaceRepositories").mockResolvedValue([]);

    render(<RepositoriesPage />);

    await waitFor(() => {
      expect(screen.getByText(/GitHub connection failed: access_denied/i)).toBeInTheDocument();
    });
  });
});
