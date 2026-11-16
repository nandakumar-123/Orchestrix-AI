import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import DashboardPage from "../app/dashboard/page";
import * as dashboardApi from "@/lib/dashboard";
import * as authApi from "@/lib/auth";

const MOCK_USER: authApi.CurrentUser = {
  id: "u-1",
  email: "engineer@orchestrix.ai",
  full_name: "Lead Engineer",
  avatar_url: null,
  email_verified: true,
  workspaces: [
    {
      workspace_id: "ws-test-123",
      name: "Orchestrix Core",
      slug: "orchestrix-core",
      role: "ADMIN",
    },
  ],
};

const MOCK_OVERVIEW: dashboardApi.DashboardOverviewResponse = {
  workspace_id: "ws-test-123",
  repository_filter_id: null,
  generated_at: new Date().toISOString(),
  metrics: {
    connected_repositories: 3,
    indexed_repositories: 2,
    active_workflows: 4,
    workflow_executions: 18,
    pending_approvals: 1,
    total_memories: 24,
    verified_memories: 19,
    open_security_findings: 2,
    running_tasks: 3,
    total_tasks: 12,
    impact_assessments: 8,
  },
  repositories: [
    {
      id: "repo-1",
      name: "orchestrix-core",
      owner: "orchestrix",
      default_branch: "main",
      primary_language: "TypeScript",
      indexing_status: "COMPLETED",
      last_indexed_at: new Date().toISOString(),
      is_private: true,
    },
  ],
  agents: [
    {
      agent_id: "devpilot",
      name: "DevPilot",
      role: "Autonomous Engineer",
      status: "RUNNING",
      active_executions: 2,
      completed_executions: 14,
      failed_executions: 1,
      last_execution_time: new Date().toISOString(),
      current_task: "Synthesizing Auth Component",
    },
    {
      agent_id: "secureflow",
      name: "SecureFlow",
      role: "Security Sentinel",
      status: "AVAILABLE",
      active_executions: 0,
      completed_executions: 8,
      failed_executions: 0,
      last_execution_time: new Date().toISOString(),
      current_task: null,
    },
  ],
  tasks: [
    {
      id: "task-abc-123",
      task_type: "devpilot",
      title: "Harden OAuth transaction replay protection",
      status: "RUNNING",
      repository_id: "repo-1",
      repository_name: "orchestrix-core",
      assigned_agent: "DevPilot",
      updated_at: new Date().toISOString(),
    },
  ],
  security: {
    open_findings: 2,
    confirmed_findings: 1,
    accepted_risks: 0,
    resolved_findings: 5,
    severity_distribution: { HIGH: 1, MEDIUM: 1 },
    scans_count: 6,
    last_scan_at: new Date().toISOString(),
    last_scan_status: "COMPLETED",
  },
  impact: {
    total_assessments: 8,
    latest_risk_score: 35.5,
    latest_risk_tier: "LOW",
    latest_assessment_at: new Date().toISOString(),
    latest_changed_files_count: 4,
    latest_status: "COMPLETED",
  },
  memory: {
    total_count: 24,
    verified_count: 19,
    unverified_count: 3,
    outdated_count: 2,
    archived_count: 0,
  },
  workflows: {
    total_workflows: 5,
    active_workflows: 4,
    paused_workflows: 1,
    draft_workflows: 0,
    recent_executions: 18,
    running_executions: 2,
    failed_executions: 1,
    pending_approvals: 1,
  },
  activities: [
    {
      id: "act-1",
      event_type: "DEVPILOT_TASK",
      title: "DevPilot task updated: Harden OAuth",
      description: "Autonomous task execution in progress",
      status: "RUNNING",
      agent: "DevPilot",
      repository_id: "repo-1",
      repository_name: "orchestrix-core",
      created_at: new Date().toISOString(),
    },
  ],
};

describe("Orchestrix AI Real Dashboard Experience", () => {
  beforeEach(() => {
    vi.spyOn(authApi, "fetchCurrentUser").mockResolvedValue(MOCK_USER);
    vi.spyOn(dashboardApi, "getDashboardOverview").mockResolvedValue(MOCK_OVERVIEW);
  });

  it("renders the primary dashboard page header and branding", async () => {
    render(<DashboardPage />);
    expect(screen.getAllByText("Engineering Overview").length).toBeGreaterThan(0);
    expect(
      screen.getByText(
        "Monitor your repositories, AI agents, and autonomous engineering activity."
      )
    ).toBeInTheDocument();
  });

  it("renders verified metrics from backend API", async () => {
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getAllByText("Connected Repositories").length).toBeGreaterThan(0);
      expect(screen.getByText("Engineering Memories")).toBeInTheDocument();
      expect(screen.getByText("Active Workflows")).toBeInTheDocument();
    });
  });

  it("renders specialist engineering agents with live backend status", async () => {
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getAllByText("DevPilot").length).toBeGreaterThan(0);
      expect(screen.getAllByText("SecureFlow").length).toBeGreaterThan(0);
      expect(screen.getByText("Synthesizing Auth Component")).toBeInTheDocument();
    });
  });

  it("renders engineering activity and task lists from backend data", async () => {
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByText("Recent Engineering Activity")).toBeInTheDocument();
      expect(screen.getByText("Active Tasks & Queue")).toBeInTheDocument();
      expect(screen.getByText("Harden OAuth transaction replay protection")).toBeInTheDocument();
      expect(screen.getByText("DevPilot task updated: Harden OAuth")).toBeInTheDocument();
    });
  });

  it("renders connected repository from backend data", async () => {
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getAllByText("orchestrix-core").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Connected Repositories").length).toBeGreaterThan(0);
    });
  });

  it("renders active workspace banner and synchronizes across workspaces", async () => {
    const multiUser: authApi.CurrentUser = {
      ...MOCK_USER,
      workspaces: [
        { workspace_id: "ws-test-123", name: "Orchestrix Core", slug: "core", role: "ADMIN" },
        { workspace_id: "ws-test-456", name: "Secondary Lab", slug: "lab", role: "MEMBER" },
      ],
    };
    vi.spyOn(authApi, "fetchCurrentUser").mockResolvedValue(multiUser);

    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-workspace-selector")).toBeInTheDocument();
      expect(screen.getByText(/Connected Repositories:/i)).toBeInTheDocument();
    });
  });

  it("displays login required message when user is not authenticated", async () => {
    vi.spyOn(authApi, "fetchCurrentUser").mockResolvedValue(null);

    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByText("Sign in to view Engineering Overview")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Go to Login/i })).toBeInTheDocument();
    });
  });
});
