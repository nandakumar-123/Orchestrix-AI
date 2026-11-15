"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ReactFlowProvider } from "@xyflow/react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { AgentMemoryContext } from "@/components/shared/agent-memory-context";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ArrowLeft,
  RefreshCw,
  Clock,
  CheckCircle2,
  XCircle,
  UserCheck,
  Loader2,
  AlertCircle,
} from "lucide-react";
import { fetchCurrentUser, type CurrentUser } from "@/lib/auth";
import {
  getExecution,
  getExecutionEvents,
  approveCheckpoint,
  rejectCheckpoint,
  getWorkflow,
  cancelExecution,
  type WorkflowExecutionResponse,
  type WorkflowEventResponse,
  type WorkflowApprovalResponse,
  type WorkflowExecutionStatus,
  type WorkflowStepStatus,
} from "@/lib/flowforge-api";
import {
  backendGraphToReactFlow,
  type WorkflowReactFlowNode,
} from "@/lib/flowforge-graph";
import { WorkflowCanvas } from "@/components/flowforge/WorkflowCanvas";
import type { Edge } from "@xyflow/react";

const EXEC_STATUS_STYLES: Record<WorkflowExecutionStatus, string> = {
  PENDING:              "bg-slate-100 text-slate-700",
  RUNNING:              "bg-blue-100 text-blue-700",
  WAITING_FOR_APPROVAL: "bg-amber-100 text-amber-700",
  COMPLETED:            "bg-emerald-100 text-emerald-700",
  FAILED:               "bg-red-100 text-red-700",
  CANCELLED:            "bg-slate-100 text-slate-500",
  TIMED_OUT:            "bg-orange-100 text-orange-700",
};

const STEP_STATUS_STYLES: Record<WorkflowStepStatus, string> = {
  PENDING:   "bg-slate-100 text-slate-600",
  RUNNING:   "bg-blue-100 text-blue-700",
  COMPLETED: "bg-emerald-100 text-emerald-700",
  FAILED:    "bg-red-100 text-red-700",
  SKIPPED:   "bg-slate-100 text-slate-400",
  CANCELLED: "bg-slate-100 text-slate-400",
  TIMED_OUT: "bg-orange-100 text-orange-600",
};

function formatDT(d: string) {
  return new Date(d).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function ApprovalCard({
  approval,
  workspaceId,
  canDecide,
  onDecision,
}: {
  approval: WorkflowApprovalResponse;
  workspaceId: string;
  canDecide: boolean;
  onDecision: () => void;
}) {
  const [isApproving, setIsApproving] = React.useState(false);
  const [isRejecting, setIsRejecting] = React.useState(false);
  const [reason, setReason] = React.useState("");

  const handleApprove = async () => {
    setIsApproving(true);
    try {
      await approveCheckpoint(approval.id, workspaceId, reason || undefined);
      onDecision();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setIsApproving(false);
    }
  };

  const handleReject = async () => {
    if (!reason.trim()) {
      alert("A rejection reason is required.");
      return;
    }
    setIsRejecting(true);
    try {
      await rejectCheckpoint(approval.id, workspaceId, reason);
      onDecision();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Rejection failed");
    } finally {
      setIsRejecting(false);
    }
  };

  const isPending = approval.status === "PENDING";

  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <UserCheck className="h-4 w-4 text-indigo-600 shrink-0" />
        <p className="text-xs font-semibold text-indigo-800">
          Approval Checkpoint — Node {approval.node_id.slice(-6)}
        </p>
        <Badge className="text-[10px] ml-auto bg-indigo-100 text-indigo-700">
          {approval.status}
        </Badge>
      </div>
      <p className="text-[11px] text-indigo-600">
        Requested: {formatDT(approval.requested_at)}
      </p>
      {approval.decided_at && (
        <p className="text-[11px] text-indigo-600">
          Decided: {formatDT(approval.decided_at)}
          {approval.decided_by && ` by ${approval.decided_by}`}
        </p>
      )}
      {approval.decision_reason && (
        <p className="text-[11px] text-slate-600 italic">{approval.decision_reason}</p>
      )}

      {isPending && canDecide && (
        <div className="space-y-2 pt-1">
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Decision reason (required for rejection)..."
            className="w-full text-xs px-2 py-1 rounded border border-indigo-200 bg-white focus:outline-none focus:border-indigo-400"
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              className="h-7 text-xs bg-emerald-600 hover:bg-emerald-700"
              onClick={handleApprove}
              disabled={isApproving || isRejecting}
            >
              {isApproving ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
              )}
              Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs text-red-700 border-red-200 hover:bg-red-50"
              onClick={handleReject}
              disabled={isApproving || isRejecting}
            >
              {isRejecting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
              ) : (
                <XCircle className="h-3.5 w-3.5 mr-1" />
              )}
              Reject
            </Button>
          </div>
        </div>
      )}

      {isPending && !canDecide && (
        <p className="text-[10px] text-indigo-500 italic">
          Only ADMIN or OWNER can approve this checkpoint.
        </p>
      )}
    </div>
  );
}

function ExecutionDetailContent() {
  const params = useParams<{ executionId: string }>();
  const executionId = params?.executionId;

  const [user, setUser] = React.useState<CurrentUser | null>(null);
  const [execution, setExecution] = React.useState<WorkflowExecutionResponse | null>(null);
  const [events, setEvents] = React.useState<WorkflowEventResponse[]>([]);
  const [nodes, setNodes] = React.useState<WorkflowReactFlowNode[]>([]);
  const [edges, setEdges] = React.useState<Edge[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [isCancelling, setIsCancelling] = React.useState(false);

  const workspaceId = user?.workspaces?.[0]?.workspace_id ?? null;
  const userRole = user?.workspaces?.[0]?.role;
  const canDecide = userRole === "OWNER" || userRole === "ADMIN";
  const canCancel =
    userRole === "OWNER" || userRole === "ADMIN" || userRole === "MEMBER";

  const load = React.useCallback(async () => {
    if (!workspaceId || !executionId) return;
    setIsLoading(true);
    setError(null);
    try {
      const [exec, evts] = await Promise.all([
        getExecution(executionId, workspaceId),
        getExecutionEvents(executionId, workspaceId),
      ]);
      setExecution(exec);
      setEvents(evts);

      // Load workflow graph for visualization
      if (exec.workflow_id) {
        try {
          const wf = await getWorkflow(exec.workflow_id, workspaceId);
          if (wf.latest_version?.workflow_definition_json) {
            const { nodes: n, edges: e } = backendGraphToReactFlow(
              wf.latest_version.workflow_definition_json,
              exec.steps
            );
            setNodes(n);
            setEdges(e);
          }
        } catch {
          // graph visualization is optional
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load execution");
    } finally {
      setIsLoading(false);
    }
  }, [workspaceId, executionId]);

  React.useEffect(() => {
    let ignore = false;
    async function init() {
      const u = await fetchCurrentUser();
      if (ignore) return;
      setUser(u);
      const wsId = u?.workspaces?.[0]?.workspace_id;
      if (wsId && executionId) {
        setIsLoading(true);
        setError(null);
        try {
          const [exec, evts] = await Promise.all([
            getExecution(executionId, wsId),
            getExecutionEvents(executionId, wsId),
          ]);
          if (ignore) return;
          setExecution(exec);
          setEvents(evts);

          if (exec.workflow_id) {
            try {
              const wf = await getWorkflow(exec.workflow_id, wsId);
              if (wf.latest_version?.workflow_definition_json && !ignore) {
                const { nodes: n, edges: e } = backendGraphToReactFlow(
                  wf.latest_version.workflow_definition_json,
                  exec.steps
                );
                setNodes(n);
                setEdges(e);
              }
            } catch {
              // graph visualization is optional
            }
          }
        } catch (e) {
          if (!ignore) {
            setError(e instanceof Error ? e.message : "Failed to load execution");
          }
        } finally {
          if (!ignore) {
            setIsLoading(false);
          }
        }
      }
    }
    init();
    return () => {
      ignore = true;
    };
  }, [executionId]);

  const handleCancel = async () => {
    if (!workspaceId || !executionId) return;
    setIsCancelling(true);
    try {
      await cancelExecution(executionId, workspaceId, "Cancelled by user");
      await load();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Cancel failed");
    } finally {
      setIsCancelling(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  if (error || !execution) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        {error ?? "Execution not found"}
      </div>
    );
  }

  const pendingApprovals = execution.approvals.filter(
    (a) => a.status === "PENDING"
  );

  return (
    <>
      <PageHeader
        title="Execution Detail"
        subtitle={`Workflow: ${execution.workflow_id.slice(0, 8)}…`}
        actions={
          <div className="flex items-center gap-2">
            <Link href={`/workflows/${execution.workflow_id}/executions`}>
              <Button variant="outline" size="sm" className="h-8 text-xs">
                <ArrowLeft className="h-3.5 w-3.5 mr-1" />
                Back to Executions
              </Button>
            </Link>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 text-xs"
              onClick={load}
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
            {canCancel &&
              (execution.status === "RUNNING" ||
                execution.status === "PENDING" ||
                execution.status === "WAITING_FOR_APPROVAL") && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 text-xs text-red-700 border-red-200"
                  onClick={handleCancel}
                  disabled={isCancelling}
                >
                  {isCancelling ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5 mr-1" />
                  )}
                  Cancel
                </Button>
              )}
          </div>
        }
      />

      {/* DevMemory Active Context */}
      <AgentMemoryContext
        agent="FLOWFORGE"
        query={`Workflow execution ${execution.workflow_id} step coordination conventions`}
        workspaceId={workspaceId}
        title="FlowForge: Pipeline Execution Conventions & Decisions (DevMemory)"
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left column: summary + steps + approvals */}
        <div className="lg:col-span-1 space-y-4">
          {/* Summary */}
          <Card className="border-slate-200">
            <CardContent className="p-4 space-y-2">
              <div className="flex items-center gap-2">
                <Badge
                  className={`text-[10px] font-mono ${EXEC_STATUS_STYLES[execution.status] ?? ""}`}
                >
                  {execution.status}
                </Badge>
                <span className="text-[10px] text-slate-400 font-mono flex-1 truncate">
                  {execution.id}
                </span>
              </div>
              {execution.started_at && (
                <p className="text-xs text-slate-500 flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  Started: {formatDT(execution.started_at)}
                </p>
              )}
              {execution.completed_at && (
                <p className="text-xs text-slate-500">
                  Completed: {formatDT(execution.completed_at)}
                </p>
              )}
              {execution.error_message && (
                <p className="text-xs text-red-600 flex items-center gap-1 mt-1">
                  <AlertCircle className="h-3 w-3 shrink-0" />
                  {execution.error_message}
                </p>
              )}
            </CardContent>
          </Card>

          {/* Pending approvals */}
          {pendingApprovals.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-slate-700">
                Awaiting Approval ({pendingApprovals.length})
              </p>
              {pendingApprovals.map((a) => (
                <ApprovalCard
                  key={a.id}
                  approval={a}
                  workspaceId={workspaceId!}
                  canDecide={canDecide}
                  onDecision={load}
                />
              ))}
            </div>
          )}

          {/* Step executions */}
          <Card className="border-slate-200">
            <CardHeader className="p-3 pb-2">
              <CardTitle className="text-sm font-semibold text-slate-700">
                Steps ({execution.steps.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-0 space-y-2">
              {execution.steps.length === 0 && (
                <p className="text-xs text-slate-400">No steps started yet.</p>
              )}
              {execution.steps.map((step) => (
                <div
                  key={step.id}
                  className="flex items-start gap-2 py-1.5 border-b border-slate-100 last:border-0"
                >
                  <Badge
                    className={`text-[9px] font-mono shrink-0 mt-0.5 ${STEP_STATUS_STYLES[step.status] ?? ""}`}
                  >
                    {step.status}
                  </Badge>
                  <div className="min-w-0 flex-1">
                    <p className="text-[11px] font-mono text-slate-700 font-medium">
                      {step.node_type}
                    </p>
                    <p className="text-[9px] text-slate-400 font-mono truncate">
                      {step.node_id.slice(0, 20)}
                    </p>
                    {step.error_message && (
                      <p className="text-[9px] text-red-600 mt-0.5 break-all">
                        {step.error_message}
                      </p>
                    )}
                    {step.started_at && (
                      <p className="text-[9px] text-slate-400 mt-0.5">
                        {formatDT(step.started_at)}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* Right column: graph + event log */}
        <div className="lg:col-span-2 space-y-4">
          {/* Execution graph */}
          {nodes.length > 0 && (
            <Card className="border-slate-200">
              <CardHeader className="p-3 pb-2">
                <CardTitle className="text-sm font-semibold text-slate-700">
                  Workflow Graph (execution overlay)
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0 overflow-hidden rounded-b-xl" style={{ height: 320 }}>
                <ReactFlowProvider>
                  <WorkflowCanvas
                    initialNodes={nodes}
                    initialEdges={edges}
                    readOnly
                  />
                </ReactFlowProvider>
              </CardContent>
            </Card>
          )}

          {/* Event timeline */}
          <Card className="border-slate-200">
            <CardHeader className="p-3 pb-2">
              <CardTitle className="text-sm font-semibold text-slate-700">
                Event Timeline ({events.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-0 space-y-1 max-h-72 overflow-y-auto">
              {events.length === 0 && (
                <p className="text-xs text-slate-400">No events yet.</p>
              )}
              {events.map((ev) => (
                <div key={ev.id} className="flex items-start gap-2 py-1">
                  <span className="text-[9px] text-slate-400 font-mono shrink-0 mt-0.5 w-28">
                    {formatDT(ev.created_at)}
                  </span>
                  <span className="text-[11px] font-mono font-semibold text-slate-700 shrink-0">
                    {ev.event_type}
                  </span>
                  {ev.node_id && (
                    <span className="text-[10px] text-slate-400 font-mono truncate">
                      @ {ev.node_id.slice(0, 16)}
                    </span>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function ExecutionDetailPage() {
  return (
    <AppShell>
      <React.Suspense
        fallback={
          <div className="flex items-center justify-center h-64">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        }
      >
        <ExecutionDetailContent />
      </React.Suspense>
    </AppShell>
  );
}

export default ExecutionDetailPage;
