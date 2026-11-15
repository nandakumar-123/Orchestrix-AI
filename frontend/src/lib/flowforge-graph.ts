// Graph serialization layer: convert between React Flow format and FlowForge backend format
// Backend schema: WorkflowGraphDefinition { nodes: WorkflowNodeDefinition[], connections: WorkflowNodeConnection[] }

import {
  type Node as ReactFlowNode,
  type Edge as ReactFlowEdge,
} from "@xyflow/react";
import {
  type WorkflowNodeDefinition,
  type WorkflowNodeConnection,
  type WorkflowGraphDefinition,
  type WorkflowNodeType,
  type WorkflowStepExecutionResponse,
  type WorkflowStepStatus,
} from "./flowforge-api";

export { type WorkflowNodeType } from "./flowforge-api";

// Extended ReactFlow node data for workflow nodes
export interface WorkflowNodeData extends Record<string, unknown> {
  nodeType: WorkflowNodeType;
  label: string;
  config: Record<string, unknown>;
  retryLimit?: number;
  retryDelaySeconds?: number;
  timeoutSeconds?: number;
  // Execution overlay (populated during execution view)
  stepStatus?: WorkflowStepStatus;
  errorMessage?: string | null;
}

export type WorkflowReactFlowNode = ReactFlowNode<WorkflowNodeData>;

// Default positions by node type for new nodes dropped from palette
const NODE_TYPE_DEFAULTS: Record<
  WorkflowNodeType,
  { width: number; height: number }
> = {
  TRIGGER: { width: 180, height: 60 },
  DEVPILOT: { width: 180, height: 60 },
  IMPACTMIND: { width: 180, height: 60 },
  TESTPILOT: { width: 180, height: 60 },
  SECUREFLOW: { width: 180, height: 60 },
  CONDITION: { width: 180, height: 70 },
  APPROVAL: { width: 180, height: 70 },
  PARALLEL: { width: 160, height: 55 },
  MERGE: { width: 160, height: 55 },
  NOTIFICATION: { width: 180, height: 60 },
  END: { width: 140, height: 50 },
};

// Default label for each node type
export const NODE_TYPE_LABELS: Record<WorkflowNodeType, string> = {
  TRIGGER: "Trigger",
  DEVPILOT: "DevPilot",
  IMPACTMIND: "ImpactMind",
  TESTPILOT: "TestPilot",
  SECUREFLOW: "SecureFlow",
  CONDITION: "Condition",
  APPROVAL: "Approval Gate",
  PARALLEL: "Parallel Split",
  MERGE: "Merge",
  NOTIFICATION: "Notification",
  END: "End",
};

/**
 * Convert backend WorkflowGraphDefinition to React Flow nodes + edges.
 * Positions are stored in `config._position` if present (we write them on save).
 */
export function backendGraphToReactFlow(
  definition: WorkflowGraphDefinition,
  stepExecutions?: WorkflowStepExecutionResponse[]
): { nodes: WorkflowReactFlowNode[]; edges: ReactFlowEdge[] } {
  // Build a step status map keyed by node_id
  const stepStatusMap = new Map<
    string,
    { status: WorkflowStepStatus; errorMessage?: string | null }
  >();
  if (stepExecutions) {
    for (const step of stepExecutions) {
      stepStatusMap.set(step.node_id, {
        status: step.status,
        errorMessage: step.error_message,
      });
    }
  }

  const nodes: WorkflowReactFlowNode[] = definition.nodes.map((n, index) => {
    const pos = n.config._position as
      | { x: number; y: number }
      | undefined
      | null;
    const stepInfo = stepStatusMap.get(n.id);
    const dims = NODE_TYPE_DEFAULTS[n.node_type] ?? { width: 180, height: 60 };

    return {
      id: n.id,
      type: "workflowNode",
      position: pos ?? { x: (index % 4) * 220 + 40, y: Math.floor(index / 4) * 140 + 40 },
      data: {
        nodeType: n.node_type,
        label: n.name ?? NODE_TYPE_LABELS[n.node_type],
        config: Object.fromEntries(
          Object.entries(n.config).filter(([k]) => k !== "_position")
        ),
        retryLimit: n.retry_limit,
        retryDelaySeconds: n.retry_delay_seconds,
        timeoutSeconds: n.timeout_seconds,
        stepStatus: stepInfo?.status,
        errorMessage: stepInfo?.errorMessage,
      },
      width: dims.width,
      height: dims.height,
    };
  });

  const edges: ReactFlowEdge[] = definition.connections.map((c, index) => {
    const edgeId = `${c.source_node_id}-${c.target_node_id}${c.condition_branch ? `-${c.condition_branch}` : ""}-${index}`;
    return {
      id: edgeId,
      source: c.source_node_id,
      target: c.target_node_id,
      sourceHandle: c.condition_branch ?? undefined,
      label: c.condition_branch ?? undefined,
      type: "smoothstep",
      style: { stroke: "#64748b", strokeWidth: 1.5 },
      labelStyle: { fontSize: 10, fill: "#64748b" },
      labelBgStyle: { fill: "#f8fafc" },
    };
  });

  return { nodes, edges };
}

/**
 * Convert React Flow nodes + edges back to backend WorkflowGraphDefinition.
 * Embeds position in `config._position` so it round-trips.
 */
export function reactFlowToBackendGraph(
  nodes: WorkflowReactFlowNode[],
  edges: ReactFlowEdge[]
): WorkflowGraphDefinition {
  const backendNodes: WorkflowNodeDefinition[] = nodes.map((n) => ({
    id: n.id,
    name: n.data.label,
    node_type: n.data.nodeType,
    config: {
      ...n.data.config,
      _position: n.position,
    },
    retry_limit: n.data.retryLimit ?? 0,
    retry_delay_seconds: n.data.retryDelaySeconds ?? 0,
    timeout_seconds: n.data.timeoutSeconds ?? 300,
  }));

  const connections: WorkflowNodeConnection[] = edges.map((e) => ({
    source_node_id: e.source,
    target_node_id: e.target,
    condition_branch: (e.sourceHandle as string | null | undefined) ?? null,
  }));

  return { nodes: backendNodes, connections };
}

/** Create a fresh React Flow node for a node dropped from the palette */
export function createNewReactFlowNode(
  nodeType: WorkflowNodeType,
  position: { x: number; y: number }
): WorkflowReactFlowNode {
  const id = `${nodeType.toLowerCase()}_${Date.now()}`;
  const dims = NODE_TYPE_DEFAULTS[nodeType] ?? { width: 180, height: 60 };
  return {
    id,
    type: "workflowNode",
    position,
    data: {
      nodeType,
      label: NODE_TYPE_LABELS[nodeType],
      config: {},
      retryLimit: 0,
      retryDelaySeconds: 0,
      timeoutSeconds: 300,
    },
    width: dims.width,
    height: dims.height,
  };
}
