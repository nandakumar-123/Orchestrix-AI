"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import { ReactFlowProvider } from "@xyflow/react";
import { AppShell } from "@/components/layout/app-shell";
import { WorkflowCanvas, type WorkflowCanvasHandle } from "@/components/flowforge/WorkflowCanvas";
import { NodePalette } from "@/components/flowforge/NodePalette";
import { NodeConfigPanel } from "@/components/flowforge/NodeConfigPanel";
import { WorkflowToolbar } from "@/components/flowforge/WorkflowToolbar";
import { Loader2 } from "lucide-react";
import { fetchCurrentUser, type CurrentUser } from "@/lib/auth";
import {
  getWorkflow,
  updateWorkflow,
  validateWorkflow,
  createVersion,
  startExecution,
  activateWorkflow,
  pauseWorkflow,
  type WorkflowResponse,
} from "@/lib/flowforge-api";
import {
  backendGraphToReactFlow,
  reactFlowToBackendGraph,
  type WorkflowReactFlowNode,
} from "@/lib/flowforge-graph";
import type { Edge } from "@xyflow/react";

function WorkflowEditorContent() {
  const params = useParams<{ workflowId: string }>();
  const router = useRouter();
  const workflowId = params?.workflowId;
  const canvasRef = React.useRef<WorkflowCanvasHandle>(null);

  const [user, setUser] = React.useState<CurrentUser | null>(null);
  const [workflow, setWorkflow] = React.useState<WorkflowResponse | null>(null);
  const [nodes, setNodes] = React.useState<WorkflowReactFlowNode[]>([]);
  const [edges, setEdges] = React.useState<Edge[]>([]);
  const [selectedNode, setSelectedNode] = React.useState<WorkflowReactFlowNode | null>(null);
  const [isDirty, setIsDirty] = React.useState(false);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isSaving, setIsSaving] = React.useState(false);
  const [isValidating, setIsValidating] = React.useState(false);
  const [isExecuting, setIsExecuting] = React.useState(false);
  const [validationError, setValidationError] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [editedName, setEditedName] = React.useState("");

  const workspaceId = user?.workspaces?.[0]?.workspace_id ?? null;
  const userRole = user?.workspaces?.[0]?.role;
  const canEdit =
    userRole === "OWNER" || userRole === "ADMIN" || userRole === "MEMBER";
  const canActivate = canEdit;
  const canExecute = canEdit;

  React.useEffect(() => {
    let ignore = false;
    async function loadData() {
      const u = await fetchCurrentUser();
      if (ignore) return;
      setUser(u);
      const wsId = u?.workspaces?.[0]?.workspace_id;
      if (wsId && workflowId) {
        setIsLoading(true);
        try {
          const wf = await getWorkflow(workflowId, wsId);
          if (ignore) return;
          setWorkflow(wf);
          setEditedName(wf.name);
          if (wf.latest_version?.workflow_definition_json) {
            const { nodes: n, edges: e } = backendGraphToReactFlow(
              wf.latest_version.workflow_definition_json
            );
            setNodes(n);
            setEdges(e);
          }
        } catch (e) {
          if (!ignore) {
            setError(e instanceof Error ? e.message : "Failed to load workflow");
          }
        } finally {
          if (!ignore) {
            setIsLoading(false);
          }
        }
      }
    }
    loadData();
    return () => {
      ignore = true;
    };
  }, [workflowId]);

  // Track dirty state
  const handleNodesChange = React.useCallback((n: WorkflowReactFlowNode[]) => {
    setNodes(n);
    setIsDirty(true);
  }, []);
  const handleEdgesChange = React.useCallback((e: Edge[]) => {
    setEdges(e);
    setIsDirty(true);
  }, []);
  const handleNameChange = (n: string) => {
    setEditedName(n);
    setIsDirty(true);
  };

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
      setIsDirty(true);
    },
    []
  );

  const getCurrentDefinition = () => {
    const currentNodes = canvasRef.current?.getNodes() ?? nodes;
    const currentEdges = canvasRef.current?.getEdges() ?? edges;
    return reactFlowToBackendGraph(currentNodes, currentEdges);
  };

  const handleSaveDraft = async () => {
    if (!workspaceId || !workflowId) return;
    setIsSaving(true);
    setError(null);
    try {
      const definition = getCurrentDefinition();
      const updated = await updateWorkflow(workflowId, {
        workspaceId,
        name: editedName,
        definition,
      });
      setWorkflow(updated);
      setIsDirty(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setIsSaving(false);
    }
  };

  const handleValidate = async () => {
    if (!workspaceId || !workflowId) return;
    setIsValidating(true);
    setValidationError(null);
    try {
      const definition = getCurrentDefinition();
      const result = await validateWorkflow(workflowId, workspaceId, definition);
      if (result.is_valid) {
        setValidationError(null);
        alert(`✅ Workflow is valid — ${result.node_count} nodes, ${result.connection_count} connections.`);
      } else {
        const errors = result.issues
          .filter((i) => i.severity === "ERROR")
          .map((i) => i.message)
          .join("; ");
        setValidationError(errors || "Validation failed");
      }
    } catch (e) {
      setValidationError(e instanceof Error ? e.message : "Validation error");
    } finally {
      setIsValidating(false);
    }
  };

  const handlePublish = async () => {
    if (!workspaceId || !workflowId) return;
    setIsSaving(true);
    setError(null);
    try {
      const definition = getCurrentDefinition();
      // First save the draft, then publish a version
      await updateWorkflow(workflowId, { workspaceId, name: editedName, definition });
      await createVersion(workflowId, { workspaceId, definition, description: `Version from editor` });
      const updated = await getWorkflow(workflowId, workspaceId);
      setWorkflow(updated);
      setIsDirty(false);
      alert("✅ Version published successfully.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Publish failed");
    } finally {
      setIsSaving(false);
    }
  };

  const handleExecute = async () => {
    if (!workspaceId || !workflowId) return;
    setIsExecuting(true);
    setError(null);
    try {
      const execution = await startExecution(workflowId, { workspaceId });
      router.push(`/workflows/executions/${execution.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Execution failed");
      setIsExecuting(false);
    }
  };

  const handleActivate = async () => {
    if (!workspaceId || !workflowId) return;
    try {
      const updated = await activateWorkflow(workflowId, workspaceId);
      setWorkflow(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Activation failed");
    }
  };

  const handlePause = async () => {
    if (!workspaceId || !workflowId) return;
    try {
      const updated = await pauseWorkflow(workflowId, workspaceId);
      setWorkflow(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pause failed");
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  if (error && !workflow) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full -m-4 sm:-m-6 lg:-m-8">
      {/* Toolbar */}
        <WorkflowToolbar
          name={editedName}
          status={workflow?.status ?? "DRAFT"}
          isDirty={isDirty}
          isSaving={isSaving}
          isValidating={isValidating}
          isExecuting={isExecuting}
          validationError={validationError}
          canEdit={canEdit}
          canActivate={canActivate}
          canExecute={canExecute}
          onNameChange={handleNameChange}
          onSaveDraft={handleSaveDraft}
          onValidate={handleValidate}
          onPublish={handlePublish}
          onExecute={handleExecute}
          onActivate={handleActivate}
          onPause={handlePause}
        />

        {/* Error bar */}
        {error && (
          <div className="px-4 py-2 text-xs text-red-700 bg-red-50 border-b border-red-200 shrink-0">
            {error}
          </div>
        )}

        {/* Editor layout */}
        <div className="flex flex-1 overflow-hidden">
          {/* Palette */}
          <div className="w-48 shrink-0">
            <NodePalette disabled={!canEdit} />
          </div>

          {/* Canvas */}
          <div className="flex-1 overflow-hidden">
            <ReactFlowProvider>
              <WorkflowCanvas
                ref={canvasRef}
                initialNodes={nodes}
                initialEdges={edges}
                onNodesChange={handleNodesChange}
                onEdgesChange={handleEdgesChange}
                onNodeSelect={setSelectedNode}
                readOnly={!canEdit}
              />
            </ReactFlowProvider>
          </div>

          {/* Config panel */}
          <div className="w-56 shrink-0">
            <NodeConfigPanel
              node={selectedNode}
              onUpdate={handleNodeUpdate}
              readOnly={!canEdit}
            />
          </div>
        </div>
      </div>
  );
}

function WorkflowEditorPage() {
  return (
    <AppShell>
      <React.Suspense
        fallback={
          <div className="flex items-center justify-center h-64">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        }
      >
        <WorkflowEditorContent />
      </React.Suspense>
    </AppShell>
  );
}

export default WorkflowEditorPage;
