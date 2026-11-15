import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import TestingPage from "../app/testing/page";
import * as authModule from "../lib/auth";
import * as githubModule from "../lib/github";
import * as testpilotModule from "../lib/testpilot";

describe("TestPilot: Autonomous Software Testing UI", () => {
  const mockUser: authModule.CurrentUser = {
    id: "user-123",
    email: "qa@orchestrix.ai",
    full_name: "QA Lead",
    avatar_url: null,
    email_verified: true,
    workspaces: [
      {
        workspace_id: "ws-123",
        name: "Enterprise Workspace",
        slug: "ent-ws",
        role: "ADMIN",
      },
    ],
  };

  const mockRepo: githubModule.WorkspaceRepository = {
    id: "repo-123",
    workspace_id: "ws-123",
    installation_id: "inst-123",
    github_repository_id: 112233,
    name: "backend-service",
    full_name: "orchestrix/backend-service",
    owner_login: "orchestrix",
    html_url: "https://github.com/orchestrix/backend-service",
    default_branch: "main",
    visibility: "private",
    language: "Python",
    is_active: true,
    created_at: "2026-03-01T12:00:00Z",
  };

  const mockSuite: testpilotModule.TestPilotSuite = {
    id: "suite-123",
    workspace_id: "ws-123",
    repository_id: "repo-123",
    snapshot_id: null,
    framework: "pytest",
    target_files: ["app/core.py"],
    test_type: "unit",
    status: "GENERATED",
    created_at: "2026-03-01T12:00:00Z",
    test_cases: [
      {
        id: "tc-1",
        name: "test_token_verification_success",
        description: "Validates valid JWT token returns decoded payload",
        test_type: "unit",
        target_symbol: "verify_token",
        code: "def test_token_verification_success():\n    assert verify_token('valid') is not None",
        is_edge_case: false,
        relevance_explanation: "Core authentication invariant",
      },
      {
        id: "tc-2",
        name: "test_token_verification_expired",
        description: "Validates expired JWT raises ExpiredTokenError",
        test_type: "edge_case",
        target_symbol: "verify_token",
        code: "def test_token_verification_expired():\n    with pytest.raises(ExpiredTokenError):\n        verify_token('expired')",
        is_edge_case: true,
        relevance_explanation: "Critical edge case vulnerability check",
      },
    ],
  };

  const mockCoverage: testpilotModule.CoverageReport = {
    id: "cov-12345678-abcd",
    workspace_id: "ws-123",
    repository_id: "repo-123",
    execution_id: "exec-123",
    line_coverage_pct: 88.5,
    branch_coverage_pct: 76.2,
    uncovered_files: ["app/legacy.py"],
    uncovered_functions: [],
    created_at: "2026-03-01T12:00:00Z",
  };

  const mockExecution: testpilotModule.TestExecution = {
    id: "exec-123",
    suite_id: "suite-123",
    workspace_id: "ws-123",
    repository_id: "repo-123",
    command: "pytest tests/",
    status: "PASSED",
    exit_code: 0,
    duration_ms: 1250,
    passed_count: 2,
    failed_count: 0,
    skipped_count: 0,
    stdout: "================== 2 passed in 1.25s ==================",
    stderr: "",
    executed_at: "2026-03-01T12:05:00Z",
    created_at: "2026-03-01T12:05:00Z",
  };

  const mockResults: testpilotModule.IndividualTestResult[] = [
    {
      id: "res-1",
      execution_id: "exec-123",
      test_name: "test_token_verification_success",
      status: "PASSED",
      duration_ms: 60,
    },
    {
      id: "res-2",
      execution_id: "exec-123",
      test_name: "test_token_verification_expired",
      status: "PASSED",
      duration_ms: 45,
    },
  ];

  const mockFrameworks: testpilotModule.DetectedFramework[] = [
    {
      language: "Python",
      framework: "pytest",
      config_file: "pytest.ini",
      test_directory: "tests",
      naming_convention: "test_*.py",
      runner_command: "pytest",
      is_available: true,
      confidence: 0.95,
      missing_requirements: [],
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(githubModule, "fetchWorkspaceRepositories").mockResolvedValue([mockRepo]);
    vi.spyOn(testpilotModule, "listTestSuites").mockResolvedValue({
      items: [mockSuite],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.spyOn(testpilotModule, "listCoverageReports").mockResolvedValue({
      items: [mockCoverage],
      total: 1,
      limit: 20,
      offset: 0,
    });
    vi.spyOn(testpilotModule, "detectFrameworks").mockResolvedValue(mockFrameworks);
    vi.spyOn(testpilotModule, "generateTestSuite").mockResolvedValue(mockSuite);
    vi.spyOn(testpilotModule, "approveTestSuite").mockResolvedValue({
      ...mockSuite,
      status: "APPROVED",
    });
    vi.spyOn(testpilotModule, "executeTestSuite").mockResolvedValue(mockExecution);
    vi.spyOn(testpilotModule, "getTestExecution").mockResolvedValue(mockExecution);
    vi.spyOn(testpilotModule, "getTestResults").mockResolvedValue(mockResults);
  });

  it("renders TestPilot header, workspace role badge, and repository selector", async () => {
    render(<TestingPage />);

    expect(
      await screen.findByText("TestPilot — Autonomous Software Testing")
    ).toBeInTheDocument();
    expect(screen.getByText("ADMIN")).toBeInTheDocument();
    expect(screen.getByText("orchestrix/backend-service")).toBeInTheDocument();
  });

  it("loads and displays overview metrics derived from real backend data", async () => {
    render(<TestingPage />);

    // Wait for suites to load
    await waitFor(() => {
      expect(screen.getByText("Test Suites Created")).toBeInTheDocument();
    });

    // Overview cards values
    expect(screen.getByText("88.5%")).toBeInTheDocument(); // Line coverage
    expect(screen.getByText("76.2%")).toBeInTheDocument(); // Branch coverage
  });

  it("displays test cases and triggers suite approval", async () => {
    render(<TestingPage />);

    await waitFor(() => {
      expect(screen.getByText("test_token_verification_success")).toBeInTheDocument();
    });

    expect(screen.getByText("Edge Case")).toBeInTheDocument();

    // Click Approve button
    const approveBtn = screen.getByRole("button", { name: /Approve/i });
    expect(approveBtn).toBeInTheDocument();
    await userEvent.click(approveBtn);

    await waitFor(() => {
      expect(testpilotModule.approveTestSuite).toHaveBeenCalledWith(
        "repo-123",
        "suite-123",
        "ws-123"
      );
    });
  });

  it("navigates to Framework Detection tab and runs detection", async () => {
    render(<TestingPage />);

    const detectTab = await screen.findByRole("tab", { name: /Framework Detection/i });
    await userEvent.click(detectTab);

    const runDetectBtn = screen.getByRole("button", { name: /Run Detection/i });
    await userEvent.click(runDetectBtn);

    await waitFor(() => {
      expect(testpilotModule.detectFrameworks).toHaveBeenCalledWith(
        "repo-123",
        undefined,
        "ws-123"
      );
    });

    expect(await screen.findByText("pytest (Python)")).toBeInTheDocument();
    expect(screen.getByText("Available")).toBeInTheDocument();
  });

  it("executes a test suite and renders test results table and stdout logs", async () => {
    render(<TestingPage />);

    await waitFor(() => {
      expect(screen.getByText("test_token_verification_success")).toBeInTheDocument();
    });

    const execBtn = screen.getByRole("button", { name: /Execute Suite/i });
    await userEvent.click(execBtn);

    await waitFor(() => {
      expect(testpilotModule.executeTestSuite).toHaveBeenCalledWith(
        "repo-123",
        "suite-123",
        { custom_command: undefined },
        "ws-123"
      );
    });

    expect(await screen.findByText("Individual Test Outcomes")).toBeInTheDocument();
    expect(screen.getByText("2 Passed")).toBeInTheDocument();
  });
});
