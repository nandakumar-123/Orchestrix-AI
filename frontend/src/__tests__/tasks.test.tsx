import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import TasksPage from "../app/tasks/page";
import * as authApi from "@/lib/auth";
import * as githubApi from "@/lib/github";
import * as devpilotApi from "@/lib/devpilot";
import * as ticketsApi from "@/lib/tickets";
import * as impactmindApi from "@/lib/impactmind";

const MOCK_USER: authApi.CurrentUser = {
  id: "user-123",
  email: "developer@orchestrix.ai",
  full_name: "Lead Developer",
  avatar_url: null,
  email_verified: true,
  workspaces: [
    {
      workspace_id: "ws-alpha-123",
      name: "Engineering Alpha",
      slug: "eng-alpha",
      role: "MEMBER",
    },
  ],
};

const MOCK_REPOS: githubApi.WorkspaceRepository[] = [
  {
    id: "repo-1",
    workspace_id: "ws-alpha-123",
    installation_id: "inst-1",
    github_repository_id: 10101,
    name: "alpha-core",
    full_name: "org/alpha-core",
    owner_login: "org",
    default_branch: "main",
    html_url: "https://github.com/org/alpha-core",
    visibility: "private",
    is_active: true,
    created_at: new Date().toISOString(),
  },
];

const MOCK_TASKS: devpilotApi.DevPilotTaskDetail[] = [
  {
    id: "task-abc-123",
    workspace_id: "ws-alpha-123",
    repository_id: "repo-1",
    task_type: "FEATURE",
    status: "AWAITING_APPROVAL",
    title: "Implement connection pooling",
    description: "Add async connection pooling to the database connector",
    prompt: "Add async connection pooling to the database connector",
    execution_mode: "STANDARD",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    latest_plan: {
      id: "plan-1",
      task_id: "task-abc-123",
      workspace_id: "ws-alpha-123",
      version: 1,
      status: "PENDING",
      summary: "Add connection pooling module",
      task_understanding: "Improve connection reuse",
      architectural_context: "Database layer",
      existing_implementation_analysis: "Single thread connection",
      proposed_changes_description: "Pool manager",
      blast_radius_summary: "Low blast radius",
      rollback_strategy: "Revert commit",
      testing_strategy: "Unit tests",
      security_implications: "No security impact",
      exposure_score: 25.0,
      exposure_tier: "LOW",
      score_type: "heuristic_structural_exposure",
      approval_comment: null,
      approved_at: null,
      created_at: new Date().toISOString(),
      steps: [
        {
          id: "step-1",
          step_number: 1,
          title: "Create pool manager",
          description: "Instantiate async pool",
          target_files: ["src/db/pool.py"],
          affected_symbols: ["PoolManager"],
          action_type: "CREATE",
          risk_level: "LOW",
          status: "PENDING",
        },
      ],
    },
    latest_diff: null,
    review_findings_count: 0,
    plan_status: "PENDING",
    is_modification_approved: false,
  },
];

const MOCK_TICKETS: ticketsApi.TicketListResponse = {
  items: [
    {
      id: "ticket-xyz-789",
      workspace_id: "ws-alpha-123",
      repository_id: "repo-1",
      repository_name: "alpha-core",
      title: "Worker timeout leak under high concurrency",
      description: "Workers fail to terminate idle connection pool threads.",
      priority: "CRITICAL",
      status: "OPEN",
      creator_id: "user-123",
      creator_name: "Lead Developer",
      creator_email: "developer@orchestrix.ai",
      assignee_id: "user-123",
      assignee_name: "Lead Developer",
      assignee_email: "developer@orchestrix.ai",
      tags: ["worker", "critical"],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      activities: [
        {
          id: "act-1",
          ticket_id: "ticket-xyz-789",
          workspace_id: "ws-alpha-123",
          actor_id: "user-123",
          actor_name: "Lead Developer",
          activity_type: "CREATED",
          comment: "Ticket created by Lead Developer",
          created_at: new Date().toISOString(),
        },
      ],
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};

const MOCK_RISK: impactmindApi.WorkspaceRiskOverview = {
  workspace_id: "ws-alpha-123",
  repository_id: null,
  total_assessments: 3,
  has_assessment_data: true,
  latest_risk_score: 82.5,
  latest_risk_tier: "CRITICAL",
  latest_assessment_at: new Date().toISOString(),
  tier_distribution: {
    CRITICAL: 1,
    HIGH: 1,
    MEDIUM: 1,
    LOW: 0,
  },
  breaking_changes_total: 2,
  recent_assessments: [
    {
      id: "asst-1",
      repository_id: "repo-1",
      repository_name: "alpha-core",
      comparison_mode: "commit_range",
      status: "completed",
      structural_exposure_score: 82.5,
      exposure_tier: "CRITICAL",
      breaking_changes_count: 2,
      impacted_entities_count: 5,
      test_recommendations_count: 3,
      created_at: new Date().toISOString(),
    },
  ],
  top_exposed_files: [
    {
      file_path: "src/worker/pool.py",
      impact_count: 4,
      highest_severity: "CRITICAL",
    },
  ],
};

describe("Tasks, Tickets & Risk Pipeline UI", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.spyOn(authApi, "fetchCurrentUser").mockResolvedValue(MOCK_USER);
    vi.spyOn(githubApi, "fetchWorkspaceRepositories").mockResolvedValue(MOCK_REPOS);
    vi.spyOn(devpilotApi, "listWorkspaceDevPilotTasks").mockResolvedValue({
      tasks: MOCK_TASKS,
      total: 1,
    });
    vi.spyOn(ticketsApi, "listTickets").mockResolvedValue(MOCK_TICKETS);
    vi.spyOn(impactmindApi, "getWorkspaceRiskOverview").mockResolvedValue(MOCK_RISK);
  });

  it("renders the page header and loads real engineering tasks", async () => {
    render(<TasksPage />);

    expect(screen.getByText("Tasks, Tickets & Risk Pipeline")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Implement connection pooling")).toBeInTheDocument();
    });

    expect(screen.getAllByText("alpha-core").length).toBeGreaterThan(0);
    expect(screen.getAllByText("awaiting approval").length).toBeGreaterThan(0);
    expect(screen.getByText("1 steps")).toBeInTheDocument();
  });

  it("switches to the Workspace Tickets tab and displays ticket items", async () => {
    render(<TasksPage />);

    await waitFor(() => {
      expect(screen.getByText("Implement connection pooling")).toBeInTheDocument();
    });

    const ticketsTab = screen.getByRole("tab", { name: /Workspace Tickets/i });
    fireEvent.click(ticketsTab);

    await waitFor(() => {
      expect(
        screen.getByText("Worker timeout leak under high concurrency")
      ).toBeInTheDocument();
    });

    expect(screen.getByText("critical")).toBeInTheDocument();
    expect(screen.getAllByText("open").length).toBeGreaterThan(0);
    expect(screen.getByText("#worker")).toBeInTheDocument();
  });

  it("switches to the Risk Management tab and displays exposure scores", async () => {
    render(<TasksPage />);

    await waitFor(() => {
      expect(screen.getByText("Implement connection pooling")).toBeInTheDocument();
    });

    const riskTab = screen.getByRole("tab", { name: /Risk Management/i });
    fireEvent.click(riskTab);

    await waitFor(() => {
      expect(screen.getAllByText("82.5").length).toBeGreaterThan(0);
    });

    expect(screen.getAllByText("CRITICAL").length).toBeGreaterThan(0);
    expect(screen.getByText("src/worker/pool.py")).toBeInTheDocument();
  });

  it("renders distinct empty states when no data is returned from APIs", async () => {
    vi.spyOn(devpilotApi, "listWorkspaceDevPilotTasks").mockResolvedValue({
      tasks: [],
      total: 0,
    });
    vi.spyOn(ticketsApi, "listTickets").mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    vi.spyOn(impactmindApi, "getWorkspaceRiskOverview").mockResolvedValue({
      workspace_id: "ws-alpha-123",
      repository_id: null,
      total_assessments: 0,
      has_assessment_data: false,
      latest_risk_score: null,
      latest_risk_tier: null,
      latest_assessment_at: null,
      tier_distribution: { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 },
      breaking_changes_total: 0,
      recent_assessments: [],
      top_exposed_files: [],
    });

    render(<TasksPage />);

    // 1. Tasks empty state
    await waitFor(() => {
      expect(screen.getByText("No engineering tasks found")).toBeInTheDocument();
    });

    // 2. Tickets empty state
    const ticketsTab = screen.getByRole("tab", { name: /Workspace Tickets/i });
    fireEvent.click(ticketsTab);
    await waitFor(() => {
      expect(screen.getByText("No tickets created yet")).toBeInTheDocument();
    });

    // 3. Risk empty state (distinct from zero-risk)
    const riskTab = screen.getByRole("tab", { name: /Risk Management/i });
    fireEvent.click(riskTab);
    await waitFor(() => {
      expect(screen.getByText("No ImpactMind Risk Data Available")).toBeInTheDocument();
      expect(screen.getByText("Unavailable")).toBeInTheDocument();
    });
  });

  it("handles ticket creation modal and submission with real API payload", async () => {
    const createTicketSpy = vi.spyOn(ticketsApi, "createTicket").mockResolvedValue({
      id: "ticket-new-999",
      workspace_id: "ws-alpha-123",
      repository_id: "repo-1",
      repository_name: "alpha-core",
      title: "Newly created bug ticket",
      description: "Bug description details",
      priority: "HIGH",
      status: "OPEN",
      creator_id: "user-123",
      creator_name: "Lead Developer",
      creator_email: "developer@orchestrix.ai",
      assignee_id: null,
      assignee_name: null,
      assignee_email: null,
      tags: ["bug", "urgent"],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      activities: [],
    });

    render(<TasksPage />);

    // Switch to tickets tab
    await waitFor(() => {
      expect(screen.getByText("Implement connection pooling")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("tab", { name: /Workspace Tickets/i }));

    await waitFor(() => {
      expect(screen.getByText("Worker timeout leak under high concurrency")).toBeInTheDocument();
    });

    // Open Create Ticket modal
    const createBtn = screen.getByRole("button", { name: /Create Issue Ticket/i });
    fireEvent.click(createBtn);

    expect(screen.getByText("Create Workspace Ticket")).toBeInTheDocument();

    // Fill form
    const titleInput = screen.getByPlaceholderText(/Memory leak in worker connection pool/i);
    fireEvent.change(titleInput, { target: { value: "Newly created bug ticket" } });

    const descInput = screen.getByPlaceholderText(/Detailed breakdown of the issue or requirement/i);
    fireEvent.change(descInput, { target: { value: "Bug description details" } });

    const tagsInput = screen.getByPlaceholderText(/backend, performance, security/i);
    fireEvent.change(tagsInput, { target: { value: "bug, urgent" } });

    // Submit
    const submitBtn = screen.getByRole("button", { name: "Create Ticket" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(createTicketSpy).toHaveBeenCalledWith("ws-alpha-123", {
        title: "Newly created bug ticket",
        description: "Bug description details",
        priority: "MEDIUM",
        repository_id: undefined,
        tags: ["bug", "urgent"],
      });
    });
  });

  it("opens ticket detail drawer with audit activity log and allows status transition", async () => {
    const updateStatusSpy = vi.spyOn(ticketsApi, "updateTicketStatus").mockResolvedValue({
      ...MOCK_TICKETS.items[0],
      status: "RESOLVED",
    });

    render(<TasksPage />);

    await waitFor(() => {
      expect(screen.getByText("Implement connection pooling")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("tab", { name: /Workspace Tickets/i }));

    await waitFor(() => {
      expect(screen.getByText("Worker timeout leak under high concurrency")).toBeInTheDocument();
    });

    // Click on ticket row to open drawer
    const ticketRow = screen.getByText("Worker timeout leak under high concurrency");
    fireEvent.click(ticketRow);

    // Verify drawer contents
    await waitFor(() => {
      expect(screen.getByText("Activity History & Audit Trail")).toBeInTheDocument();
      expect(screen.getByText("Ticket created by Lead Developer")).toBeInTheDocument();
    });

    // Change status from button in drawer (pick the one inside drawer)
    const resolvedButtons = screen.getAllByRole("button", { name: "resolved" });
    fireEvent.click(resolvedButtons[resolvedButtons.length - 1]);

    await waitFor(() => {
      expect(updateStatusSpy).toHaveBeenCalledWith("ws-alpha-123", "ticket-xyz-789", "RESOLVED");
    });
  });

  it("displays error alert when API call fails", async () => {
    vi.spyOn(devpilotApi, "listWorkspaceDevPilotTasks").mockRejectedValue(
      new Error("Network timeout: failed to reach DevPilot orchestrator")
    );

    render(<TasksPage />);

    await waitFor(() => {
      expect(
        screen.getByText(/Network timeout: failed to reach DevPilot orchestrator/i)
      ).toBeInTheDocument();
    });
  });
});
