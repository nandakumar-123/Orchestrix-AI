"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { WorkflowCanvas, type WorkflowCanvasHandle } from "@/components/flowforge/WorkflowCanvas";
import { NodePalette } from "@/components/flowforge/NodePalette";
import { NodeConfigPanel } from "@/components/flowforge/NodeConfigPanel";
import { ArrowLeft, Loader2 } from "lucide-react";
import { fetchCurrentUser, type CurrentUser } from "@/lib/auth";
import { createWorkflow } from "@/lib/flowforge-api";
import {
  reactFlowToBackendGraph,
  type WorkflowReactFlowNode,
} from "@/lib/flowforge-graph";
import type { Edge } from "@xyflow/react";
import { ReactFlowProvider } from "@xyflow/react";

export default function NewWorkflowPage() {
  const router = useRouter();
  const canvasRef = React.useRef<WorkflowCanvasHandle>(null);

  const [user, setUser] = React.useState<CurrentUser | null>(null);
  const [name, setName] = React.useState("New Workflow");
  const [description, setDescription] = React.useState("");
  const [selectedNode, setSelectedNode] = React.useState<WorkflowReactFlowNode | null>(null);
  const [nodes, setNodes] = React.useState<WorkflowReactFlowNode[]>([]);
  const [edges, setEdges] = React.useState<Edge[]>([]);
  const [isSaving, setIsSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    fetchCurrentUser().then(setUser);
  }, []);

  const workspaceId = user?.workspaces?.[0]?.workspace_id ?? null;

  const handleNodeUpdate = React.useCallback(
    (nodeId: string, updates: Partial<WorkflowReactFlowNode["data"]>) => {
      setNodes((prev) =>
        prev.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, ...updates } } : n
        )
      );
      setSelectedNode((prev) =>
        prev && prev.id === nodeId
          ? { ...prev, data: { ...prev.data, ...updates } }
          : prev
      );
    },
    []
  );

  const handleCreate = async () => {
    if (!workspaceId) {
      setError("No workspace found. Please log in again.");
      return;
    }
    setIsSaving(true);
    setError(null);
    try {
      const currentNodes = canvasRef.current?.getNodes() ?? nodes;
      const currentEdges = canvasRef.current?.getEdges() ?? edges;
      const definition = reactFlowToBackendGraph(currentNodes, currentEdges);
      const wf = await createWorkflow({
        workspaceId,
        name,
        description: description || undefined,
        definition,
      });
      router.push(`/workflows/${wf.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create workflow");
      setIsSaving(false);
    }
  };

  return (
    <AppShell>
      <div className="flex flex-col h-full -m-4 sm:-m-6 lg:-m-8">
        {/* Top bar */}
        <div className="flex items-center gap-3 px-4 h-12 border-b border-slate-200 bg-white shrink-0">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs"
            onClick={() => router.push("/workflows")}
          >
            <ArrowLeft className="h-3.5 w-3.5 mr-1" />
            Back
          </Button>
          <div className="h-4 w-px bg-slate-200" />
          <div className="flex items-center gap-2 flex-1">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-7 text-sm font-semibold w-56 border-transparent bg-transparent hover:border-slate-200 focus:border-blue-300"
              placeholder="Workflow name..."
            />
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="h-7 text-xs w-72 border-transparent bg-transparent hover:border-slate-200 focus:border-blue-300 text-slate-500"
              placeholder="Description (optional)..."
            />
          </div>
          {error && (
            <span className="text-xs text-red-600 font-mono">{error}</span>
          )}
          <Button
            size="sm"
            className="h-7 text-xs"
            onClick={handleCreate}
            disabled={isSaving || !name.trim()}
          >
            {isSaving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
            ) : null}
            Create Workflow
          </Button>
        </div>

        {/* Editor layout */}
        <div className="flex flex-1 overflow-hidden">
          {/* Palette */}
          <div className="w-48 shrink-0">
            <NodePalette />
          </div>

          {/* Canvas */}
          <div className="flex-1 overflow-hidden">
            <ReactFlowProvider>
              <WorkflowCanvas
                ref={canvasRef}
                initialNodes={nodes}
                initialEdges={edges}
                onNodesChange={setNodes}
                onEdgesChange={setEdges}
                onNodeSelect={setSelectedNode}
              />
            </ReactFlowProvider>
          </div>

          {/* Config panel */}
          <div className="w-56 shrink-0">
            <NodeConfigPanel
              node={selectedNode}
              onUpdate={handleNodeUpdate}
            />
          </div>
        </div>
      </div>
    </AppShell>
  );
}
