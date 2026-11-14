import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import RepositoriesPage from "../app/repositories/page";
import * as authModule from "../lib/auth";
import * as githubModule from "../lib/github";
import * as indexingModule from "../lib/indexing";

describe("Repository Intelligence & Indexing Integration", () => {
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

  const mockRepo: githubModule.WorkspaceRepository = {
    id: "repo-1",
    workspace_id: "ws-123",
    installation_id: "inst-1",
    github_repository_id: 1001,
    name: "orchestrix-core",
    full_name: "orchestrix-org/orchestrix-core",
    owner_login: "orchestrix-org",
    description: "Multi-agent engineering core",
    default_branch: "main",
    html_url: "https://github.com/orchestrix-org/orchestrix-core",
    visibility: "private",
    language: "Python",
    is_active: true,
    created_at: "2026-03-01T12:00:00Z",
  };

  const mockSnapshotOverview: indexingModule.RepositorySnapshotOverview = {
    id: "snap-1",
    repository_id: "repo-1",
    workspace_id: "ws-123",
    commit_sha: "abcd1234ef567890",
    branch: "main",
    total_files: 12,
    total_lines: 3450,
    total_bytes: 45000,
    total_symbols: 85,
    total_dependencies: 14,
    languages_summary: {
      Python: { files: 8, lines: 2500 },
      TypeScript: { files: 4, lines: 950 },
    },
    entry_points: ["app/main.py"],
    created_at: "2026-03-01T13:00:00Z",
  };

  const mockIntelligence: indexingModule.RepositoryIntelligenceOverview = {
    repository_id: "repo-1",
    workspace_id: "ws-123",
    latest_snapshot: mockSnapshotOverview,
    active_job: null,
    last_indexed_at: "2026-03-01T13:00:00Z",
    detected_frameworks: ["FastAPI", "React", "Next.js"],
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(githubModule, "fetchGitHubStatus").mockResolvedValue({
      connected: true,
      github_login: "orchestrix-org",
    });
    vi.spyOn(githubModule, "fetchWorkspaceRepositories").mockResolvedValue([mockRepo]);
    vi.spyOn(indexingModule, "fetchRepositoryFiles").mockResolvedValue({
      files: [],
      total: 0,
      limit: 100,
      offset: 0,
    });
    vi.spyOn(indexingModule, "fetchRepositorySymbols").mockResolvedValue({
      symbols: [],
      total: 0,
      limit: 150,
      offset: 0,
    });
    vi.spyOn(indexingModule, "fetchRepositoryDependencies").mockResolvedValue({
      dependencies: [],
      total: 0,
      limit: 150,
      offset: 0,
    });
    vi.spyOn(indexingModule, "fetchSupportedLanguages").mockResolvedValue({
      total_supported: 40,
      languages: [
        {
          name: "Python",
          package_name: "tree_sitter_python",
          available: true,
          extensions: [".py", ".pyi"],
        },
        {
          name: "Go",
          package_name: "tree_sitter_go",
          available: true,
          extensions: [".go"],
        },
        {
          name: "Rust",
          package_name: "tree_sitter_rust",
          available: true,
          extensions: [".rs"],
        },
      ],
    });
  });

  it("displays repository intelligence badge and indexed summary", async () => {
    vi.spyOn(indexingModule, "fetchRepositoryIntelligence").mockResolvedValue(mockIntelligence);

    render(<RepositoriesPage />);

    await waitFor(() => {
      expect(screen.getByText("orchestrix-core")).toBeInTheDocument();
      expect(screen.getByText("Repository Intelligence")).toBeInTheDocument();
      expect(screen.getByText("Indexed")).toBeInTheDocument();
      expect(screen.getByText(/12 files • 85 symbols • 14 deps/i)).toBeInTheDocument();
    });
  });

  it("triggers indexing job when Index button is clicked", async () => {
    const user = userEvent.setup();
    vi.spyOn(indexingModule, "fetchRepositoryIntelligence").mockResolvedValue(null);
    const startJobSpy = vi.spyOn(indexingModule, "startIndexingJob").mockResolvedValue({
      ok: true,
      job: {
        id: "job-1",
        workspace_id: "ws-123",
        repository_id: "repo-1",
        commit_sha: "abcd123",
        branch: "main",
        status: "RUNNING",
        progress_percent: 25,
        files_count: 0,
        symbols_count: 0,
        dependencies_count: 0,
        created_at: "2026-03-01T14:00:00Z",
      },
    });

    render(<RepositoriesPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Index" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Index" }));

    expect(startJobSpy).toHaveBeenCalledWith("repo-1", "ws-123", "main");
  });

  it("opens Repository Intelligence Modal and explores files, symbols, and dependencies", async () => {
    const user = userEvent.setup();
    vi.spyOn(indexingModule, "fetchRepositoryIntelligence").mockResolvedValue(mockIntelligence);
    vi.spyOn(indexingModule, "fetchRepositoryFiles").mockResolvedValue({
      files: [
        {
          id: "f-1",
          path: "app/main.py",
          file_name: "main.py",
          extension: ".py",
          language: "Python",
          size_bytes: 1200,
          line_count: 45,
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    });
    vi.spyOn(indexingModule, "fetchRepositorySymbols").mockResolvedValue({
      symbols: [
        {
          id: "s-1",
          file_path: "app/main.py",
          name: "start_engine",
          symbol_type: "function",
          language: "Python",
          start_line: 10,
          end_line: 25,
          signature: "def start_engine(config: Config) -> Engine:",
        },
      ],
      total: 1,
      limit: 150,
      offset: 0,
    });
    vi.spyOn(indexingModule, "fetchRepositoryDependencies").mockResolvedValue({
      dependencies: [
        {
          id: "d-1",
          file_path: "pyproject.toml",
          name: "fastapi",
          version_spec: "^0.115.0",
          dependency_type: "manifest_dependency",
          package_manager: "pip",
        },
      ],
      total: 1,
      limit: 150,
      offset: 0,
    });

    render(<RepositoriesPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Explore Intelligence/i })).toBeInTheDocument();
    });

    // Open Explorer Modal
    await user.click(screen.getByRole("button", { name: /Explore Intelligence/i }));

    await waitFor(() => {
      expect(screen.getByTestId("repository-intelligence-modal")).toBeInTheDocument();
      expect(screen.getByText("3,450")).toBeInTheDocument(); // total lines
      expect(screen.getByText("app/main.py")).toBeInTheDocument(); // entry point
    });

    // Switch to Files tab
    await user.click(screen.getByRole("button", { name: /Files/i }));
    await waitFor(() => {
      expect(screen.getByText("app/main.py")).toBeInTheDocument();
      expect(screen.getByText("45 lines")).toBeInTheDocument();
    });

    // Switch to Symbols tab
    await user.click(screen.getByRole("button", { name: /Symbols/i }));
    await waitFor(() => {
      expect(screen.getByText("start_engine")).toBeInTheDocument();
      expect(screen.getByText("app/main.py:10–25")).toBeInTheDocument();
    });

    // Switch to Dependencies tab
    await user.click(screen.getByRole("button", { name: /Dependencies/i }));
    await waitFor(() => {
      expect(screen.getByText("fastapi")).toBeInTheDocument();
      expect(screen.getByText("^0.115.0")).toBeInTheDocument();
    });
  });

  it("renders detected frameworks and explores parser registry in modal", async () => {
    const user = userEvent.setup();
    vi.spyOn(indexingModule, "fetchRepositoryIntelligence").mockResolvedValue(mockIntelligence);

    render(<RepositoriesPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Explore Intelligence/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /Explore Intelligence/i }));

    await waitFor(() => {
      expect(screen.getByTestId("repository-intelligence-modal")).toBeInTheDocument();
      expect(screen.getByText("FastAPI")).toBeInTheDocument();
      expect(screen.getByText("React")).toBeInTheDocument();
      expect(screen.getByText("Next.js")).toBeInTheDocument();
    });

    // Switch to Registry tab
    await user.click(screen.getByRole("button", { name: /Registry/i }));

    await waitFor(() => {
      expect(screen.getByText(/Universal Parser Registry/i)).toBeInTheDocument();
      expect(screen.getByText("Rust")).toBeInTheDocument();
      expect(screen.getByText("Go")).toBeInTheDocument();
      expect(screen.getAllByText("Python").length).toBeGreaterThanOrEqual(1);
    });
  });
});
