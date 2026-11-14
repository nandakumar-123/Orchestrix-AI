import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    vi.spyOn(indexingModule, "fetchRepositoryIntelligence").mockResolvedValue(mockIntelligence);
    vi.spyOn(indexingModule, "fetchSemanticIndexStatus").mockResolvedValue(null);
    vi.spyOn(indexingModule, "fetchGraphIndexStatus").mockResolvedValue({
      status: "completed",
      snapshot_id: "snap-1",
      provider: "mock",
      total_nodes: 10,
      total_relationships: 12,
      indexed_at: "2026-03-01T13:00:00Z",
    });
    vi.spyOn(indexingModule, "fetchRepositoryGraph").mockResolvedValue({
      nodes: [
        {
          id: "sym:snap-1:app/auth.py:function:login",
          label: "Function",
          properties: { name: "login", file_path: "app/auth.py", start_line: 10, end_line: 25 },
        },
        {
          id: "api:snap-1:POST:/auth/login",
          label: "APIEndpoint",
          properties: { method: "POST", path: "/auth/login", file_path: "app/auth.py" },
        },
      ],
      edges: [
        {
          source_id: "sym:snap-1:app/auth.py:function:login",
          target_id: "api:snap-1:POST:/auth/login",
          type: "EXPOSES",
          properties: {},
        },
      ],
      total_nodes: 2,
      total_edges: 1,
    });
    vi.spyOn(indexingModule, "fetchImpactPreview").mockResolvedValue({
      target_id: "sym:snap-1:app/auth.py:function:login",
      target_name: "login",
      target_type: "Function",
      risk_level: "HIGH",
      risk_score: 55.0,
      reasons: ["Exposes 1 public API endpoint", "1 direct caller affected"],
      direct_dependents: [],
      indirect_dependents: [],
      affected_endpoints: [{ id: "api:1", name: "/auth/login", label: "APIEndpoint", file_path: "app/auth.py", relationship: "EXPOSES", depth: 1 }],
      affected_tests: [],
      affected_database_models: [],
      subgraph: { nodes: [], edges: [], total_nodes: 0, total_edges: 0 },
    });
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
    vi.spyOn(indexingModule, "fetchRepositoryIntelligence").mockResolvedValue(mockIntelligence);

    render(<RepositoriesPage />);

    const exploreBtn = await screen.findByRole("button", { name: /Explore Intelligence/i });
    fireEvent.click(exploreBtn);

    await waitFor(() => {
      expect(screen.getByTestId("repository-intelligence-modal")).toBeInTheDocument();
      expect(screen.getByText("FastAPI")).toBeInTheDocument();
      expect(screen.getByText("React")).toBeInTheDocument();
      expect(screen.getByText("Next.js")).toBeInTheDocument();
    });

    // Switch to Registry tab
    const registryTab = screen.getByRole("button", { name: /Registry/i });
    fireEvent.click(registryTab);

    await waitFor(() => {
      expect(screen.getByText(/Universal Parser Registry/i)).toBeInTheDocument();
      expect(screen.getByText("Rust")).toBeInTheDocument();
      expect(screen.getByText("Go")).toBeInTheDocument();
      expect(screen.getAllByText("Python").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("executes semantic search query and displays retrieved code chunks", async () => {
    const user = userEvent.setup();
    vi.spyOn(indexingModule, "fetchRepositoryIntelligence").mockResolvedValue(mockIntelligence);
    vi.spyOn(indexingModule, "fetchSemanticIndexStatus").mockResolvedValue({
      repository_id: "repo-1",
      snapshot_id: "snap-1",
      provider_name: "fastembed",
      model_name: "sentence-transformers/all-MiniLM-L6-v2",
      dimension: 384,
      total_chunks: 12,
      status: "completed",
    });
    vi.spyOn(indexingModule, "executeSemanticSearch").mockResolvedValue({
      repository_id: "repo-1",
      query: "Where is user authentication handled?",
      total_results: 1,
      results: [
        {
          chunk_id: "chunk-1",
          repository_id: "repo-1",
          repository_name: "orchestrix-core",
          snapshot_id: "snap-1",
          file_path: "backend/app/api/v1/auth.py",
          language: "Python",
          symbol_name: "google_oauth_callback",
          symbol_type: "function",
          parent_symbol_name: null,
          start_line: 25,
          end_line: 55,
          source_code_excerpt: "async def google_oauth_callback(code: str): ...",
          similarity_score: 0.94,
          vector_score: 0.92,
          lexical_score: 0.95,
          symbol_score: 0.90,
          metadata: {},
        },
      ],
    });

    render(<RepositoriesPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Explore Intelligence/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /Explore Intelligence/i }));

    await waitFor(() => {
      expect(screen.getByTestId("repository-intelligence-modal")).toBeInTheDocument();
    });

    // Switch to Semantic Search tab
    await user.click(screen.getByTestId("tab-semantic-search"));

    await waitFor(() => {
      expect(screen.getByTestId("semantic-search-panel")).toBeInTheDocument();
      expect(screen.getByText(/12 Chunks Indexed/i)).toBeInTheDocument();
    });

    // Enter query and search
    const searchInput = screen.getByTestId("semantic-search-input");
    await user.type(searchInput, "Where is user authentication handled?");
    await user.click(screen.getByTestId("semantic-search-button"));

    // Verify results displayed
    await waitFor(() => {
      expect(screen.getByTestId("semantic-results-list")).toBeInTheDocument();
      expect(screen.getByText("backend/app/api/v1/auth.py")).toBeInTheDocument();
      expect(screen.getByText("94% Match")).toBeInTheDocument();
      expect(screen.getByText(/async def google_oauth_callback/i)).toBeInTheDocument();
    });
  });

  it("should display Knowledge Graph tab, render nodes, and preview blast radius impact", async () => {
    const user = userEvent.setup();
    render(<RepositoriesPage />);

    await waitFor(() => {
      expect(screen.getByText("orchestrix-core")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Explore Intelligence/i })).toBeInTheDocument();
    });

    // Open Intelligence modal
    const viewButton = screen.getByRole("button", { name: /Explore Intelligence/i });
    await user.click(viewButton);

    await waitFor(() => {
      expect(screen.getByTestId("repository-intelligence-modal")).toBeInTheDocument();
    });

    // Switch to Knowledge Graph tab
    const graphTab = screen.getByTestId("tab-knowledge-graph");
    await user.click(graphTab);

    // Verify Graph Header and nodes
    await waitFor(() => {
      expect(screen.getByText(/Code Knowledge Graph & Relationship Engine/i)).toBeInTheDocument();
      expect(screen.getByText("login")).toBeInTheDocument();
    });

    // Click on node 'login' to select it
    await user.click(screen.getByText("login"));

    // Verify Inspector opened and click Blast Radius Preview
    await waitFor(() => {
      expect(screen.getByTestId("analyze-impact-button")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("analyze-impact-button"));

    // Verify Impact Preview results displayed
    await waitFor(() => {
      expect(screen.getByText(/Blast Radius & Structural Exposure Score/i)).toBeInTheDocument();
      expect(screen.getByText(/HIGH \(55\/100\)/i)).toBeInTheDocument();
      expect(screen.getByText(/Exposes 1 public API endpoint/i)).toBeInTheDocument();
    });
  });
});
