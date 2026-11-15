import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ImpactPage from "../app/impact/page";
import * as authModule from "../lib/auth";
import * as githubModule from "../lib/github";
import * as impactModule from "../lib/impactmind";

describe("ImpactMind: Change Impact Analysis & Regression Testing UI", () => {
  const mockUser: authModule.CurrentUser = {
    id: "user-123",
    email: "dev@orchestrix.ai",
    full_name: "Staff Engineer",
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
    github_repository_id: 998877,
    name: "core-service",
    full_name: "orchestrix/core-service",
    owner_login: "orchestrix",
    html_url: "https://github.com/orchestrix/core-service",
    default_branch: "main",
    visibility: "private",
    language: "Python",
    is_active: true,
    created_at: "2026-03-01T12:00:00Z",
  };

  const mockAssessment: impactModule.ImpactAssessment = {
    id: "asm-123",
    workspace_id: "ws-123",
    repository_id: "repo-123",
    snapshot_id: "snap-123",
    comparison_mode: "diff_input",
    status: "completed",
    structural_exposure_score: 52.5,
    exposure_tier: "HIGH",
    score_type: "heuristic_structural_exposure",
    score_label: "Blast Radius & Structural Exposure Score",
    change_summary: {
      total_files_changed: 2,
      total_additions: 12,
      total_deletions: 2,
      breaking_changes_count: 1,
      exposed_endpoints_count: 1,
      affected_tests_count: 2,
    },
    reasons: [
      "1 potentially breaking contract change(s) detected (+10.0)",
      "Directly exposes/modifies 1 public API endpoint(s)",
    ],
    recommended_actions: [
      "Ensure breaking changes are versioned or backward-compatible before merging.",
      "Verify API route contracts and client integrations.",
    ],
    classifications: [
      {
        id: "cls-1",
        file_path: "app/services/billing.py",
        symbol_name: "process_payment",
        category: "SIGNATURE_CHANGE",
        is_breaking: true,
        breaking_reason: "Added currency parameter without default",
        confidence: 0.98,
        evidence: "Signature altered: def process_payment(amount, currency)",
        status: "resolved",
      },
    ],
    impacted_entities: [
      {
        id: "imp-1",
        entity_id: "sym:api.py:checkout",
        name: "checkout_handler",
        label: "Function",
        file_path: "app/api.py",
        impact_type: "direct_dependent",
        depth: 1,
        relationship_type: "CALLS",
        confidence: 1.0,
      },
      {
        id: "imp-2",
        entity_id: "ep:post:checkout",
        name: "POST /api/v1/checkout",
        label: "APIEndpoint",
        file_path: "app/api.py",
        impact_type: "exposed_endpoint",
        depth: 1,
        relationship_type: "EXPOSES",
        confidence: 1.0,
      },
    ],
    test_recommendations: [
      {
        id: "rec-1",
        test_file: "tests/test_billing.py",
        test_name: "test_process_payment_mfa",
        test_framework: "pytest",
        priority: "CRITICAL",
        reason: "Directly tests modified symbol process_payment with breaking change",
        related_symbol: "process_payment",
        evidence_source: "direct_call",
        confidence: 0.95,
      },
    ],
    test_executions: [],
    created_at: "2026-03-01T14:00:00Z",
  };

  const mockTestRun: impactModule.TestExecutionRunItem = {
    id: "run-123",
    command: "pytest tests/test_billing.py",
    status: "PASSED",
    exit_code: 0,
    stdout: "============================= 3 passed in 0.85s =============================\nPASSED tests/test_billing.py::test_process_payment_mfa",
    stderr: "",
    passed_count: 3,
    failed_count: 0,
    skipped_count: 0,
    duration_ms: 850,
    started_at: "2026-03-01T14:05:00Z",
    completed_at: "2026-03-01T14:05:01Z",
  };

  beforeEach(() => {
    vi.resetAllMocks();
    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(githubModule, "fetchWorkspaceRepositories").mockResolvedValue([mockRepo]);
    vi.spyOn(impactModule, "fetchImpactHistory").mockResolvedValue({
      assessments: [mockAssessment],
      total: 1,
      limit: 10,
      offset: 0,
    });
    vi.spyOn(impactModule, "analyzeChangeImpact").mockResolvedValue(mockAssessment);
    vi.spyOn(impactModule, "fetchImpactAssessment").mockResolvedValue(mockAssessment);
    vi.spyOn(impactModule, "executeRegressionTests").mockResolvedValue(mockTestRun);
  });

  it("renders the ImpactMind page header and input specification card", async () => {
    render(<ImpactPage />);

    expect(
      screen.getByText(/ImpactMind: Change Impact & Regression Intelligence/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Target Change Specification/i)
    ).toBeInTheDocument();
    expect(screen.getByText("Unified Diff Input")).toBeInTheDocument();
    expect(screen.getByText("Commit Range")).toBeInTheDocument();
  });

  it("loads assessment and displays Blast Radius & Structural Exposure Score with Tier Badge", async () => {
    render(<ImpactPage />);

    await waitFor(() => {
      expect(screen.getByText("Blast Radius & Structural Exposure Score")).toBeInTheDocument();
      expect(screen.getByText("HIGH EXPOSURE")).toBeInTheDocument();
      expect(screen.getByText("52.5")).toBeInTheDocument();
    });

    // Check heuristic explanation disclaimer
    expect(
      screen.getByText(/Heuristic structural exposure metric based on graph topology and change surface/i)
    ).toBeInTheDocument();

    // Check breaking alterations count
    expect(screen.getByText("Breaking Alterations")).toBeInTheDocument();
  });

  it("renders change classifications table and breaking change badges", async () => {
    render(<ImpactPage />);

    await waitFor(() => {
      expect(screen.getByText("app/services/billing.py")).toBeInTheDocument();
      expect(screen.getByText("process_payment")).toBeInTheDocument();
      expect(screen.getByText("SIGNATURE_CHANGE")).toBeInTheDocument();
      expect(screen.getByText("BREAKING")).toBeInTheDocument();
    });
  });

  it("navigates to Downstream Blast Radius tab", async () => {
    const user = userEvent.setup();
    render(<ImpactPage />);

    await waitFor(() => {
      expect(screen.getByText(/Downstream Blast Radius/i)).toBeInTheDocument();
    });

    const dependentsTab = screen.getByText(/Downstream Blast Radius/i);
    await user.click(dependentsTab);

    expect(screen.getByText("checkout_handler")).toBeInTheDocument();
    expect(screen.getByText("POST /api/v1/checkout")).toBeInTheDocument();
    expect(screen.getByText("exposed_endpoint")).toBeInTheDocument();
  });

  it("navigates to Regression Test Selection & Controlled Runner tab and enforces approval", async () => {
    const user = userEvent.setup();
    render(<ImpactPage />);

    await waitFor(() => {
      expect(screen.getByText(/Regression Test Selection & Execution/i)).toBeInTheDocument();
    });

    const testsTab = screen.getByText(/Regression Test Selection & Execution/i);
    await user.click(testsTab);

    // Recommended test item
    expect(screen.getByText("tests/test_billing.py")).toBeInTheDocument();
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();

    // Controlled Runner Panel
    const runBtn = screen.getByRole("button", { name: /Approve & Run Tests/i });
    expect(runBtn).toBeDisabled();

    // Approve execution
    const approveCheckbox = screen.getByLabelText(/Explicitly Approve Execution/i);
    await user.click(approveCheckbox);
    expect(runBtn).toBeEnabled();

    // Click run
    await user.click(runBtn);

    await waitFor(() => {
      expect(impactModule.executeRegressionTests).toHaveBeenCalledWith(
        "repo-123",
        "ws-123",
        "asm-123",
        expect.objectContaining({ run_approved: true })
      );
    });

    // Check execution output logs
    await waitFor(() => {
      expect(screen.getByText(/3 passed in 0.85s/i)).toBeInTheDocument();
      expect(screen.getByText("PASSED")).toBeInTheDocument();
    });
  });
});
