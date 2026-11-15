import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import * as authModule from "../lib/auth";
import * as flowforgeApi from "../lib/flowforge-api";
import {
  backendGraphToReactFlow,
  reactFlowToBackendGraph,
  createNewReactFlowNode,
  NODE_TYPE_LABELS,
} from "../lib/flowforge-graph";
import WorkflowsPage from "../app/workflows/page";

// ============================================================
// Mocks
// ============================================================

vi.mock("@xyflow/react", () => ({
  ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  ReactFlow: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="react-flow-canvas">{children}</div>
  ),
  Background: () => null,
  Controls: () => null,
  MiniMap: () => null,
  Handle: () => null,
  Position: { Top: "top", Bottom: "bottom", Left: "left", Right: "right" },
  addEdge: (params: unknown, edges: unknown[]) => [...edges, params],
  useNodesState: (initial: unknown[]) => [
    initial,
    (v: unknown) => v,
    (v: unknown) => v,
  ],
  useEdgesState: (initial: unknown[]) => [
    initial,
    (v: unknown) => v,
    (v: unknown) => v,
  ],
  useReactFlow: () => ({
    screenToFlowPosition: (p: { x: number; y: number }) => p,
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ workflowId: "wf-test-123", executionId: "ex-test-456" }),
  usePathname: () => "/workflows",
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockUser: authModule.CurrentUser = {
  id: "user-admin-01",
  email: "admin@orchestrix.ai",
  full_name: "Workflow Admin",
  avatar_url: null,
  email_verified: true,
  workspaces: [
    {
      workspace_id: "ws-flowforge-001",
      name: "FlowForge Workspace",
      slug: "ff-ws",
      role: "ADMIN",
    },
  ],
};

const mockWorkflow: flowforgeApi.WorkflowResponse = {
  id: "wf-test-123",
  workspace_id: "ws-flowforge-001",
  name: "CI/CD Deployment Pipeline",
  description: "Automated deployment workflow with AI agents",
  status: "DRAFT",
  created_by: "user-admin-01",
  created_at: "2026-11-01T10:00:00Z",
  updated_at: "2026-11-15T08:00:00Z",
  latest_version: {
    id: "ver-001",
    workflow_id: "wf-test-123",
    workspace_id: "ws-flowforge-001",
    version_number: 1,
    workflow_definition_json: {
      nodes: [
        {
          id: "trigger_1",
          name: "PR Trigger",
          node_type: "TRIGGER",
          config: { trigger_type: "WEBHOOK" },
        },
        {
          id: "devpilot_1",
          name: "Code Analysis",
          node_type: "DEVPILOT",
          config: { task_title: "Analyse changes" },
        },
        {
          id: "end_1",
          name: "End",
          node_type: "END",
          config: {},
        },
      ],
      connections: [
        { source_node_id: "trigger_1", target_node_id: "devpilot_1" },
        { source_node_id: "devpilot_1", target_node_id: "end_1" },
      ],
    },
    created_by: "user-admin-01",
    created_at: "2026-11-15T08:00:00Z",
  },
};

const mockExecution: flowforgeApi.WorkflowExecutionResponse = {
  id: "ex-test-456",
  workflow_id: "wf-test-123",
  workspace_id: "ws-flowforge-001",
  status: "COMPLETED",
  started_at: "2026-11-15T09:00:00Z",
  completed_at: "2026-11-15T09:05:00Z",
  created_at: "2026-11-15T09:00:00Z",
  steps: [
    {
      id: "step-001",
      execution_id: "ex-test-456",
      workflow_id: "wf-test-123",
      workspace_id: "ws-flowforge-001",
      node_id: "trigger_1",
      node_type: "TRIGGER",
      status: "COMPLETED",
      attempt_number: 1,
      created_at: "2026-11-15T09:00:10Z",
    },
  ],
  approvals: [],
};

// ============================================================
// Test suite: Graph serialization
// ============================================================

describe("FlowForge Graph Serialization", () => {
  it("backendGraphToReactFlow converts nodes and edges correctly", () => {
    const def = mockWorkflow.latest_version!.workflow_definition_json;
    const { nodes, edges } = backendGraphToReactFlow(def);

    expect(nodes).toHaveLength(3);
    expect(edges).toHaveLength(2);

    const triggerNode = nodes.find((n) => n.id === "trigger_1");
    expect(triggerNode).toBeDefined();
    expect(triggerNode?.data.nodeType).toBe("TRIGGER");
    expect(triggerNode?.data.label).toBe("PR Trigger");
    expect(triggerNode?.type).toBe("workflowNode");

    const edge = edges.find(
      (e) => e.source === "trigger_1" && e.target === "devpilot_1"
    );
    expect(edge).toBeDefined();
  });

  it("reactFlowToBackendGraph round-trips correctly", () => {
    const def = mockWorkflow.latest_version!.workflow_definition_json;
    const { nodes, edges } = backendGraphToReactFlow(def);
    const restored = reactFlowToBackendGraph(nodes, edges);

    expect(restored.nodes).toHaveLength(3);
    expect(restored.connections).toHaveLength(2);

    const triggerNode = restored.nodes.find((n) => n.id === "trigger_1");
    expect(triggerNode?.node_type).toBe("TRIGGER");
    expect(triggerNode?.name).toBe("PR Trigger");

    const conn = restored.connections.find(
      (c) => c.source_node_id === "trigger_1" && c.target_node_id === "devpilot_1"
    );
    expect(conn).toBeDefined();
  });

  it("createNewReactFlowNode assigns correct type and defaults", () => {
    const node = createNewReactFlowNode("DEVPILOT", { x: 100, y: 200 });
    expect(node.data.nodeType).toBe("DEVPILOT");
    expect(node.data.label).toBe(NODE_TYPE_LABELS.DEVPILOT);
    expect(node.position).toEqual({ x: 100, y: 200 });
    expect(node.type).toBe("workflowNode");
    expect(node.id).toMatch(/^devpilot_/);
    expect(node.data.retryLimit).toBe(0);
    expect(node.data.timeoutSeconds).toBe(300);
  });

  it("condition branch connections map to condition_branch field", () => {
    const { nodes, edges } = backendGraphToReactFlow({
      nodes: [
        { id: "cond_1", node_type: "CONDITION", config: {} },
        { id: "end_true", node_type: "END", config: {} },
        { id: "end_false", node_type: "END", config: {} },
      ],
      connections: [
        { source_node_id: "cond_1", target_node_id: "end_true", condition_branch: "true" },
        { source_node_id: "cond_1", target_node_id: "end_false", condition_branch: "false" },
      ],
    });

    const trueEdge = edges.find(
      (e) => e.source === "cond_1" && e.target === "end_true"
    );
    expect(trueEdge?.sourceHandle).toBe("true");

    const backend = reactFlowToBackendGraph(nodes, edges);
    const trueConn = backend.connections.find(
      (c) => c.target_node_id === "end_true"
    );
    expect(trueConn?.condition_branch).toBe("true");
  });

  it("step execution status overlaid on nodes", () => {
    const def = mockWorkflow.latest_version!.workflow_definition_json;
    const { nodes } = backendGraphToReactFlow(def, mockExecution.steps);
    const triggerNode = nodes.find((n) => n.id === "trigger_1");
    expect(triggerNode?.data.stepStatus).toBe("COMPLETED");
  });

  it("nodes without step executions have no stepStatus", () => {
    const def = mockWorkflow.latest_version!.workflow_definition_json;
    const { nodes } = backendGraphToReactFlow(def, mockExecution.steps);
    const devpilotNode = nodes.find((n) => n.id === "devpilot_1");
    expect(devpilotNode?.data.stepStatus).toBeUndefined();
  });
});

// ============================================================
// Test suite: Workflows listing page
// ============================================================

describe("WorkflowsPage: Workflow Listing", () => {
  beforeEach(() => {
    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(flowforgeApi, "listWorkflows").mockResolvedValue({
      items: [mockWorkflow],
      total: 1,
      limit: 50,
      offset: 0,
    });
  });

  it("renders page header", async () => {
    render(<WorkflowsPage />);
    await waitFor(() => {
      expect(screen.getAllByText("Visual Workflow Builder").length).toBeGreaterThan(0);
    });
  });

  it("displays workflow cards after loading", async () => {
    render(<WorkflowsPage />);
    await waitFor(() => {
      expect(
        screen.getByText("CI/CD Deployment Pipeline")
      ).toBeInTheDocument();
    });
  });

  it("shows workflow status badge", async () => {
    render(<WorkflowsPage />);
    await waitFor(() => {
      expect(screen.getAllByText("Draft").length).toBeGreaterThan(0);
    });
  });

  it("renders New Workflow button for ADMIN role", async () => {
    render(<WorkflowsPage />);
    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: /new workflow/i })
      ).toBeInTheDocument();
    });
  });

  it("renders Open Editor link for each workflow card", async () => {
    render(<WorkflowsPage />);
    await waitFor(() => {
      expect(screen.getByText("Open Editor")).toBeInTheDocument();
    });
  });

  it("renders empty state when no workflows exist", async () => {
    vi.spyOn(flowforgeApi, "listWorkflows").mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    render(<WorkflowsPage />);
    await waitFor(() => {
      expect(screen.getByText("No workflows yet")).toBeInTheDocument();
    });
  });

  it("shows error when API call fails", async () => {
    vi.spyOn(flowforgeApi, "listWorkflows").mockRejectedValue(
      new Error("Network error")
    );
    render(<WorkflowsPage />);
    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });
  });

  it("calls activateWorkflow when Activate button is clicked", async () => {
    const user = userEvent.setup();
    const activateSpy = vi
      .spyOn(flowforgeApi, "activateWorkflow")
      .mockResolvedValue({ ...mockWorkflow, status: "ACTIVE" });

    render(<WorkflowsPage />);
    await waitFor(() => {
      expect(screen.getByText("CI/CD Deployment Pipeline")).toBeInTheDocument();
    });

    const activateBtn = screen.getByText("Activate");
    await user.click(activateBtn);
    await waitFor(() => {
      expect(activateSpy).toHaveBeenCalledWith(
        "wf-test-123",
        "ws-flowforge-001"
      );
    });
  });

  it("filters workflows by status when filter tab is clicked", async () => {
    const user = userEvent.setup();
    const listSpy = vi.spyOn(flowforgeApi, "listWorkflows").mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });

    render(<WorkflowsPage />);
    await waitFor(() =>
      expect(screen.getAllByText("Visual Workflow Builder").length).toBeGreaterThan(0)
    );

    const activeTab = screen.getByRole("button", { name: "Active" });
    await user.click(activeTab);

    await waitFor(() => {
      expect(listSpy).toHaveBeenCalledWith(
        "ws-flowforge-001",
        expect.objectContaining({ status: "ACTIVE" })
      );
    });
  });
});

// ============================================================
// Test suite: API error handling
// ============================================================

describe("FlowForge API: Error handling", () => {
  it("403 error is propagated to caller", async () => {
    vi.spyOn(flowforgeApi, "listWorkflows").mockRejectedValue(
      new Error("403 Forbidden")
    );

    let caughtError: Error | null = null;
    try {
      await flowforgeApi.listWorkflows("ws-no-access", {});
    } catch (e) {
      caughtError = e as Error;
    }
    expect(caughtError).not.toBeNull();
    expect(caughtError?.message).toContain("403");
  });

  it("approveCheckpoint requires ADMIN/OWNER — 403 propagated", async () => {
    vi.spyOn(flowforgeApi, "approveCheckpoint").mockRejectedValue(
      new Error("403 Only ADMIN or OWNER may approve")
    );

    let caughtError: Error | null = null;
    try {
      await flowforgeApi.approveCheckpoint("ap-001", "ws-member-only", "approve");
    } catch (e) {
      caughtError = e as Error;
    }
    expect(caughtError?.message).toContain("403");
  });

  it("rejectCheckpoint 403 propagated for MEMBER", async () => {
    vi.spyOn(flowforgeApi, "rejectCheckpoint").mockRejectedValue(
      new Error("403 Only ADMIN or OWNER may reject")
    );

    let caughtError: Error | null = null;
    try {
      await flowforgeApi.rejectCheckpoint("ap-002", "ws-member-only", "not allowed");
    } catch (e) {
      caughtError = e as Error;
    }
    expect(caughtError?.message).toContain("403");
  });
});

// ============================================================
// Test suite: RBAC enforcement in listing page
// ============================================================

describe("WorkflowsPage: VIEWER role restrictions", () => {
  it("does not show Create Workflow button for VIEWER", async () => {
    const viewerUser: authModule.CurrentUser = {
      ...mockUser,
      workspaces: [{ ...mockUser.workspaces[0], role: "VIEWER" }],
    };
    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(viewerUser);
    vi.spyOn(flowforgeApi, "listWorkflows").mockResolvedValue({
      items: [mockWorkflow],
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(<WorkflowsPage />);
    await waitFor(() => {
      expect(screen.getByText("CI/CD Deployment Pipeline")).toBeInTheDocument();
    });

    // VIEWER should not see New Workflow link
    expect(screen.queryByRole("link", { name: /new workflow/i })).toBeNull();
  });

  it("does not show Activate button for VIEWER", async () => {
    const viewerUser: authModule.CurrentUser = {
      ...mockUser,
      workspaces: [{ ...mockUser.workspaces[0], role: "VIEWER" }],
    };
    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(viewerUser);
    vi.spyOn(flowforgeApi, "listWorkflows").mockResolvedValue({
      items: [{ ...mockWorkflow, status: "DRAFT" }],
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(<WorkflowsPage />);
    await waitFor(() => {
      expect(screen.getByText("CI/CD Deployment Pipeline")).toBeInTheDocument();
    });

    expect(screen.queryByText("Activate")).toBeNull();
  });
});
