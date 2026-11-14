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

  beforeEach(() => {
    vi.restoreAllMocks();
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
    });
  });

  it("renders connected GitHub status and active workspace repositories", async () => {
    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(githubModule, "fetchGitHubStatus").mockResolvedValue({
      connected: true,
      github_login: "octo-engineer",
      scope: "repo,read:user",
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
});
