"use client";

import * as React from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Edge,
  type ReactFlowInstance,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { WorkflowCustomNode } from "./CustomNodes/WorkflowCustomNode";
import {
  type WorkflowReactFlowNode,
  type WorkflowNodeData,
  createNewReactFlowNode,
} from "@/lib/flowforge-graph";
import { type WorkflowNodeType } from "@/lib/flowforge-api";

// Custom node registration with loose typing for compatibility with ReactFlow NodeTypes
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const nodeTypes: NodeTypes = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  workflowNode: WorkflowCustomNode as any,
};

interface WorkflowCanvasProps {
  initialNodes: WorkflowReactFlowNode[];
  initialEdges: Edge[];
  onNodesChange?: (nodes: WorkflowReactFlowNode[]) => void;
  onEdgesChange?: (edges: Edge[]) => void;
  onNodeSelect?: (node: WorkflowReactFlowNode | null) => void;
  readOnly?: boolean;
}

export interface WorkflowCanvasHandle {
  getNodes: () => WorkflowReactFlowNode[];
  getEdges: () => Edge[];
}

export const WorkflowCanvas = React.forwardRef<
  WorkflowCanvasHandle,
  WorkflowCanvasProps
>(function WorkflowCanvas(
  { initialNodes, initialEdges, onNodesChange, onEdgesChange, onNodeSelect, readOnly },
  ref
) {
  const [nodes, setNodes, onNodesChangeInternal] = useNodesState<WorkflowReactFlowNode>(initialNodes);
  const [edges, setEdges, onEdgesChangeInternal] = useEdgesState(initialEdges);
  const [reactFlowInstance, setReactFlowInstance] = React.useState<ReactFlowInstance | null>(null);

  // Expose imperative handle
  React.useImperativeHandle(ref, () => ({
    getNodes: () => nodes,
    getEdges: () => edges,
  }));

  // Forward node changes to parent
  React.useEffect(() => {
    onNodesChange?.(nodes);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes]);

  React.useEffect(() => {
    onEdgesChange?.(edges);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edges]);

  // Reset when initial data changes (e.g. workflow loaded from API)
  const prevInitialRef = React.useRef<string>("");
  React.useEffect(() => {
    const key = JSON.stringify({ n: initialNodes.length, e: initialEdges.length });
    if (key !== prevInitialRef.current) {
      prevInitialRef.current = key;
      setNodes(initialNodes);
      setEdges(initialEdges);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialNodes, initialEdges]);

  const onConnect = React.useCallback(
    (params: Connection) => {
      if (readOnly) return;
      setEdges((eds) =>
        addEdge(
          {
            ...params,
            type: "smoothstep",
            style: { stroke: "#64748b", strokeWidth: 1.5 },
          },
          eds
        )
      );
    },
    [readOnly, setEdges]
  );

  const onDragOver = React.useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = React.useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      if (readOnly || !reactFlowInstance) return;

      const nodeType = event.dataTransfer.getData(
        "application/flowforge-node-type"
      ) as WorkflowNodeType | "";
      if (!nodeType) return;

      const position = reactFlowInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const newNode = createNewReactFlowNode(nodeType, position);
      setNodes((nds) => nds.concat(newNode));
    },
    [readOnly, reactFlowInstance, setNodes]
  );

  const onNodeClick = React.useCallback(
    (_: React.MouseEvent, node: WorkflowReactFlowNode) => {
      onNodeSelect?.(node);
    },
    [onNodeSelect]
  );

  const onPaneClick = React.useCallback(() => {
    onNodeSelect?.(null);
  }, [onNodeSelect]);

  return (
    <div className="flex-1 h-full bg-slate-50">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        onNodesChange={onNodesChangeInternal as any}
        onEdgesChange={onEdgesChangeInternal}
        onConnect={onConnect}
        onInit={setReactFlowInstance}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeClick={onNodeClick as (event: React.MouseEvent, node: { id: string }) => void}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        elementsSelectable={!readOnly}
        deleteKeyCode={readOnly ? null : "Delete"}
        className="bg-slate-50"
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#e2e8f0" />
        <Controls className="bg-white border border-slate-200 rounded-lg shadow-sm" />
        <MiniMap
          className="bg-white border border-slate-200 rounded-lg shadow-sm"
          nodeStrokeWidth={2}
          nodeColor={(n) => {
            const data = n.data as unknown as WorkflowNodeData;
            const colorMap: Partial<Record<WorkflowNodeType, string>> = {
              TRIGGER: "#f59e0b",
              DEVPILOT: "#3b82f6",
              IMPACTMIND: "#8b5cf6",
              TESTPILOT: "#10b981",
              SECUREFLOW: "#ef4444",
              CONDITION: "#f97316",
              APPROVAL: "#6366f1",
              PARALLEL: "#06b6d4",
              MERGE: "#14b8a6",
              NOTIFICATION: "#0ea5e9",
              END: "#64748b",
            };
            return colorMap[data.nodeType] ?? "#94a3b8";
          }}
        />
      </ReactFlow>
    </div>
  );
});
