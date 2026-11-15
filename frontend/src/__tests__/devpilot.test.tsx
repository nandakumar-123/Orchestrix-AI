import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import DevPilotPage from "../app/devpilot/page";
import * as authModule from "../lib/auth";
import * as githubModule from "../lib/github";
import * as devpilotModule from "../lib/devpilot";

describe("DevPilot: Autonomous AI Software Engineer UI", () => {
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

  const mockPlan: devpilotModule.DevPilotEngineeringPlan = {
    id: "plan-123",
    task_id: "task-123",
    workspace_id: "ws-123",
    version: 1,
    status: "PENDING",
    summary: "Implement token rotation with secure blacklist",
    task_understanding: "Add refresh token verification endpoint and invalidate used tokens",
    architectural_context: "Modifies authentication pipeline in app/services/auth.py",
    existing_implementation_analysis: "Current tokens do not have rotation tracking",
    proposed_changes_description: "Add TokenBlacklist table and check validity in middleware",
    blast_radius_summary: "Low risk to external callers, modifies auth pipeline",
    rollback_strategy: "Revert migration and restore prior token validator",
    testing_strategy: "Unit test token rotation and concurrent refresh attempts",
    security_implications: "Significantly mitigates token theft attack vectors",
    exposure_score: 18.5,
    exposure_tier: "LOW",
    score_type: "heuristic_structural_exposure",
    steps: [
      {
        id: "step-1",
        step_number: 1,
        title: "Create TokenBlacklist database model",
        description: "Add table with token_id and revoked_at timestamps",
        target_files: ["app/models/auth.py"],
        affected_symbols: ["TokenBlacklist"],
        action_type: "CREATE_FILE",
        reason: "Required for persistent revocation tracking",
        risk_level: "LOW",
        status: "PENDING",
      },
    ],
    created_at: "2026-03-01T12:00:00Z",
  };

  const mockTask: devpilotModule.DevPilotTaskDetail = {
    id: "task-123",
    workspace_id: "ws-123",
    repository_id: "repo-123",
    task_type: "FEATURE",
    status: "AWAITING_APPROVAL",
    title: "Implement JWT Refresh Rotation",
    description: "Add refresh token rotation and revocation list",
    execution_mode: "STANDARD",
    created_at: "2026-03-01T12:00:00Z",
    updated_at: "2026-03-01T12:01:00Z",
    review_findings_count: 0,
    is_modification_approved: false,
    latest_plan: mockPlan,
  };

  const mockDiff: devpilotModule.DevPilotDiffResponse = {
    task_id: "task-123",
    total_files_changed: 1,
    additions: 25,
    deletions: 4,
    unified_diff: "--- a/app/models/auth.py\n+++ b/app/models/auth.py\n@@ -10,2 +10,12 @@\n+class TokenBlacklist(Base): pass",
    changes: [
      {
        id: "ch-1",
        file_path: "app/models/auth.py",
        change_type: "MODIFY",
        diff_hunk: "+class TokenBlacklist(Base): pass",
      },
    ],
  };

  const mockReview: devpilotModule.DevPilotReviewResponse = {
    task_id: "task-123",
    total_findings: 1,
    critical_count: 0,
    high_count: 0,
    medium_count: 1,
    low_count: 0,
    info_count: 0,
    findings: [
      {
        id: "rf-1",
        task_id: "task-123",
        category: "SECURITY",
        severity: "MEDIUM",
        file_path: "app/models/auth.py",
        line_start: 12,
        title: "Ensure index on token hash",
        description: "Token lookup queries require index on token_hash",
        suggested_fix: "Index('ix_token_hash', 'token_hash')",
        is_resolved: false,
      },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(githubModule, "fetchWorkspaceRepositories").mockResolvedValue([mockRepo]);
    vi.spyOn(devpilotModule, "listDevPilotTasks").mockResolvedValue({
      tasks: [mockTask],
      total: 1,
    });
    vi.spyOn(devpilotModule, "getDevPilotTask").mockResolvedValue(mockTask);
    vi.spyOn(devpilotModule, "getDevPilotPlan").mockResolvedValue(mockPlan);
    vi.spyOn(devpilotModule, "getDevPilotDiff").mockResolvedValue(mockDiff);
    vi.spyOn(devpilotModule, "getDevPilotReview").mockResolvedValue(mockReview);
    vi.spyOn(devpilotModule, "approveDevPilotPlan").mockResolvedValue({
      ...mockTask,
      status: "GENERATING",
    });
    vi.spyOn(devpilotModule, "approveDevPilotChanges").mockResolvedValue({
      ...mockTask,
      status: "VALIDATING",
      is_modification_approved: true,
    });
  });

  it("renders page header and repository selector", async () => {
    render(<DevPilotPage />);
    expect(
      screen.getByText("DevPilot — Autonomous AI Software Engineer")
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("orchestrix/core-service")).toBeInTheDocument();
      expect(screen.getByText("Initiate DevPilot Task")).toBeInTheDocument();
    });
  });

  it("displays task lifecycle progress and Plan Approval checkpoint", async () => {
    render(<DevPilotPage />);

    await waitFor(() => {
      expect(screen.getAllByText("Implement JWT Refresh Rotation").length).toBeGreaterThanOrEqual(1);
      expect(
        screen.getByText("Human-in-the-Loop Gate 1: Plan Approval Required")
      ).toBeInTheDocument();
      expect(screen.getByText("Approve Plan & Generate")).toBeInTheDocument();
    });
  });

  it("renders 14-section plan details and action steps", async () => {
    render(<DevPilotPage />);

    await waitFor(() => {
      expect(
        screen.getByText("Implement token rotation with secure blacklist")
      ).toBeInTheDocument();
      expect(
        screen.getByText("18.5/100")
      ).toBeInTheDocument();
      expect(
        screen.getByText("Create TokenBlacklist database model")
      ).toBeInTheDocument();
    });
  });

  it("triggers approveDevPilotPlan when user clicks Approve Plan & Generate", async () => {
    const user = userEvent.setup();
    render(<DevPilotPage />);

    await waitFor(() => {
      expect(screen.getByText("Approve Plan & Generate")).toBeInTheDocument();
    });

    const approveBtn = screen.getByText("Approve Plan & Generate");
    await user.click(approveBtn);

    await waitFor(() => {
      expect(devpilotModule.approveDevPilotPlan).toHaveBeenCalledWith(
        "repo-123",
        "task-123",
        true,
        undefined,
        undefined
      );
    });
  });

  it("switches to diff and review tabs", async () => {
    const user = userEvent.setup();
    render(<DevPilotPage />);

    await waitFor(() => {
      expect(screen.getAllByText("Implement JWT Refresh Rotation").length).toBeGreaterThanOrEqual(1);
    });

    const diffTab = screen.getByRole("button", { name: /Code Modifications/i });
    await user.click(diffTab);

    await waitFor(() => {
      expect(screen.getByText(/Modified Files: 1/i)).toBeInTheDocument();
      expect(screen.getByText("+25 lines")).toBeInTheDocument();
    });

    const reviewTab = screen.getByRole("button", { name: /Review Findings/i });
    await user.click(reviewTab);

    await waitFor(() => {
      expect(screen.getByText("Ensure index on token hash")).toBeInTheDocument();
    });
  });
});
