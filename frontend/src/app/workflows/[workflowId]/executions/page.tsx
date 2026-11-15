"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ArrowLeft, Clock, RefreshCw, Play, XCircle, Loader2 } from "lucide-react";
import { fetchCurrentUser, type CurrentUser } from "@/lib/auth";
import {
  getWorkflow,
  listExecutions,
  cancelExecution,
  type WorkflowResponse,
  type WorkflowExecutionResponse,
  type WorkflowExecutionStatus,
} from "@/lib/flowforge-api";

const STATUS_STYLES: Record<WorkflowExecutionStatus, string> = {
  PENDING:              "bg-slate-100 text-slate-700",
  RUNNING:              "bg-blue-100 text-blue-700",
  WAITING_FOR_APPROVAL: "bg-amber-100 text-amber-700",
  COMPLETED:            "bg-emerald-100 text-emerald-700",
  FAILED:               "bg-red-100 text-red-700",
  CANCELLED:            "bg-slate-100 text-slate-500",
  TIMED_OUT:            "bg-orange-100 text-orange-700",
};

function duration(start?: string | null, end?: string | null): string {
  if (!start) return "—";
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const secs = Math.floor((e - s) / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  return `${mins}m ${secs % 60}s`;
}

function formatDT(d: string) {
  return new Date(d).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function WorkflowExecutionsContent() {
  const params = useParams<{ workflowId: string }>();
  const workflowId = params?.workflowId;

  const [user, setUser] = React.useState<CurrentUser | null>(null);
  const [workflow, setWorkflow] = React.useState<WorkflowResponse | null>(null);
  const [executions, setExecutions] = React.useState<WorkflowExecutionResponse[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [cancellingId, setCancellingId] = React.useState<string | null>(null);

  const workspaceId = user?.workspaces?.[0]?.workspace_id ?? null;
  const userRole = user?.workspaces?.[0]?.role;
  const canCancel =
    userRole === "OWNER" || userRole === "ADMIN" || userRole === "MEMBER";

  const load = React.useCallback(async () => {
    if (!workspaceId || !workflowId) return;
    setIsLoading(true);
    setError(null);
    try {
      const [wf, exRes] = await Promise.all([
        getWorkflow(workflowId, workspaceId),
        listExecutions(workspaceId, { workflowId, limit: 50 }),
      ]);
      setWorkflow(wf);
      setExecutions(exRes.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setIsLoading(false);
    }
  }, [workspaceId, workflowId]);

  React.useEffect(() => {
    let ignore = false;
    async function init() {
      const u = await fetchCurrentUser();
      if (ignore) return;
      setUser(u);
      const wsId = u?.workspaces?.[0]?.workspace_id;
      if (wsId && workflowId) {
        setIsLoading(true);
        setError(null);
        try {
          const [wf, exRes] = await Promise.all([
            getWorkflow(workflowId, wsId),
            listExecutions(wsId, { workflowId, limit: 50 }),
          ]);
          if (!ignore) {
            setWorkflow(wf);
            setExecutions(exRes.items);
          }
        } catch (e) {
          if (!ignore) {
            setError(e instanceof Error ? e.message : "Failed to load");
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
  }, [workflowId]);

  const handleCancel = async (execId: string) => {
    if (!workspaceId) return;
    setCancellingId(execId);
    try {
      await cancelExecution(execId, workspaceId, "Cancelled by user");
      await load();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Cancel failed");
    } finally {
      setCancellingId(null);
    }
  };

  return (
    <>
      <PageHeader
        title={workflow ? `${workflow.name} — Executions` : "Workflow Executions"}
        subtitle={`${executions.length} execution${executions.length !== 1 ? "s" : ""}`}
        actions={
          <div className="flex items-center gap-2">
            <Link href={`/workflows/${workflowId}`}>
              <Button variant="outline" size="sm" className="h-8 text-xs">
                <ArrowLeft className="h-3.5 w-3.5 mr-1" />
                Back to Editor
              </Button>
            </Link>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 text-xs"
              onClick={load}
              disabled={isLoading}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        }
      />

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {isLoading && (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
        </div>
      )}

      {!isLoading && executions.length === 0 && (
        <Card className="border-dashed border-slate-200">
          <CardContent className="flex flex-col items-center justify-center py-12 gap-2">
            <Play className="h-8 w-8 text-slate-300" />
            <p className="text-sm text-slate-500">No executions yet</p>
            <p className="text-xs text-slate-400">Run the workflow from the editor to see results here.</p>
          </CardContent>
        </Card>
      )}

      {!isLoading && executions.length > 0 && (
        <div className="space-y-3">
          {executions.map((ex) => (
            <Card key={ex.id} className="border-slate-200 bg-white">
              <CardContent className="p-4">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3 min-w-0">
                    <Badge className={`text-[10px] font-mono shrink-0 ${STATUS_STYLES[ex.status] ?? ""}`}>
                      {ex.status}
                    </Badge>
                    <div className="min-w-0">
                      <p className="text-xs font-mono text-slate-500 truncate">
                        {ex.id.slice(0, 16)}…
                      </p>
                      <p className="text-[10px] text-slate-400 mt-0.5 flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {ex.started_at ? formatDT(ex.started_at) : formatDT(ex.created_at)}
                        <span className="ml-2">Duration: {duration(ex.started_at, ex.completed_at)}</span>
                        <span className="ml-2">{ex.steps.length} step{ex.steps.length !== 1 ? "s" : ""}</span>
                      </p>
                      {ex.error_message && (
                        <p className="text-[10px] text-red-600 mt-0.5 truncate">
                          {ex.error_message}
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <Link href={`/workflows/executions/${ex.id}`}>
                      <Button variant="outline" size="sm" className="h-7 text-xs">
                        View Details
                      </Button>
                    </Link>
                    {canCancel &&
                      (ex.status === "RUNNING" ||
                        ex.status === "PENDING" ||
                        ex.status === "WAITING_FOR_APPROVAL") && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs text-red-600"
                          onClick={() => handleCancel(ex.id)}
                          disabled={cancellingId === ex.id}
                        >
                          {cancellingId === ex.id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <XCircle className="h-3.5 w-3.5" />
                          )}
                        </Button>
                      )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}

function WorkflowExecutionsPage() {
  return (
    <AppShell>
      <React.Suspense
        fallback={
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
          </div>
        }
      >
        <WorkflowExecutionsContent />
      </React.Suspense>
    </AppShell>
  );
}

export default WorkflowExecutionsPage;
