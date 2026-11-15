"use client";

import * as React from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import {
  Plus,
  Play,
  Pause,
  Clock,
  Workflow,
  Settings2,
  RefreshCw,
  List,
} from "lucide-react";
import { fetchCurrentUser, type CurrentUser } from "@/lib/auth";
import {
  listWorkflows,
  activateWorkflow,
  pauseWorkflow,
  type WorkflowResponse,
  type WorkflowStatus,
} from "@/lib/flowforge-api";

const STATUS_BADGES: Record<WorkflowStatus, { label: string; variant: string; className: string }> = {
  DRAFT:    { label: "Draft",    variant: "secondary", className: "bg-slate-100 text-slate-700" },
  ACTIVE:   { label: "Active",   variant: "secondary", className: "bg-emerald-100 text-emerald-700" },
  PAUSED:   { label: "Paused",   variant: "secondary", className: "bg-amber-100 text-amber-700" },
  ARCHIVED: { label: "Archived", variant: "secondary", className: "bg-red-100 text-red-700" },
};

const STATUS_FILTERS: Array<{ label: string; value: string }> = [
  { label: "All", value: "" },
  { label: "Draft", value: "DRAFT" },
  { label: "Active", value: "ACTIVE" },
  { label: "Paused", value: "PAUSED" },
  { label: "Archived", value: "ARCHIVED" },
];

function formatDate(d: string) {
  return new Date(d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function WorkflowsPage() {
  const [user, setUser] = React.useState<CurrentUser | null>(null);
  const [workflows, setWorkflows] = React.useState<WorkflowResponse[]>([]);
  const [total, setTotal] = React.useState(0);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [statusFilter, setStatusFilter] = React.useState("");
  const [actionLoading, setActionLoading] = React.useState<string | null>(null);

  const workspaceId = user?.workspaces?.[0]?.workspace_id ?? null;
  const userRole = user?.workspaces?.[0]?.role;
  const canEdit = userRole === "OWNER" || userRole === "ADMIN" || userRole === "MEMBER";

  const loadWorkflows = React.useCallback(async () => {
    if (!workspaceId) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await listWorkflows(workspaceId, {
        status: statusFilter || undefined,
        limit: 50,
      });
      setWorkflows(res.items);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load workflows");
    } finally {
      setIsLoading(false);
    }
  }, [workspaceId, statusFilter]);

  React.useEffect(() => {
    let ignore = false;
    async function loadData() {
      const u = await fetchCurrentUser();
      if (ignore) return;
      setUser(u);
      const wsId = u?.workspaces?.[0]?.workspace_id;
      if (wsId) {
        setIsLoading(true);
        setError(null);
        try {
          const res = await listWorkflows(wsId, {
            status: statusFilter || undefined,
            limit: 50,
          });
          if (!ignore) {
            setWorkflows(res.items);
            setTotal(res.total);
          }
        } catch (e) {
          if (!ignore) {
            setError(e instanceof Error ? e.message : "Failed to load workflows");
          }
        } finally {
          if (!ignore) {
            setIsLoading(false);
          }
        }
      } else {
        setIsLoading(false);
      }
    }
    loadData();
    return () => {
      ignore = true;
    };
  }, [statusFilter]);

  const handleActivate = async (wf: WorkflowResponse) => {
    if (!workspaceId) return;
    setActionLoading(wf.id);
    try {
      await activateWorkflow(wf.id, workspaceId);
      await loadWorkflows();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to activate workflow");
    } finally {
      setActionLoading(null);
    }
  };

  const handlePause = async (wf: WorkflowResponse) => {
    if (!workspaceId) return;
    setActionLoading(wf.id);
    try {
      await pauseWorkflow(wf.id, workspaceId);
      await loadWorkflows();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to pause workflow");
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <AppShell>
      <PageHeader
        title="Visual Workflow Builder"
        subtitle={`Powered by FlowForge — ${total} workflow${total !== 1 ? "s" : ""} in workspace`}
        actions={
          canEdit ? (
            <Link href="/workflows/new">
              <Button size="sm" className="text-xs h-8">
                <Plus className="h-3.5 w-3.5 mr-1" />
                New Workflow
              </Button>
            </Link>
          ) : null
        }
      />

      {/* Status filter tabs */}
      <div className="flex gap-1">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setStatusFilter(f.value)}
            className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
              statusFilter === f.value
                ? "bg-blue-50 text-blue-700 border border-blue-200"
                : "text-slate-500 hover:bg-slate-100"
            }`}
          >
            {f.label}
          </button>
        ))}
        <div className="flex-1" />
        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs"
          onClick={loadWorkflows}
          disabled={isLoading}
        >
          <RefreshCw className={`h-3.5 w-3.5 mr-1 ${isLoading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Loading skeleton */}
      {isLoading && !error && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-36 rounded-xl border border-slate-200 bg-slate-50 animate-pulse"
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && workflows.length === 0 && (
        <Card className="border-dashed border-slate-200">
          <CardContent className="flex flex-col items-center justify-center py-12 gap-3">
            <Workflow className="h-10 w-10 text-slate-300" />
            <p className="text-sm font-medium text-slate-500">No workflows yet</p>
            <p className="text-xs text-slate-400">
              {statusFilter
                ? `No workflows with status "${statusFilter}"`
                : "Create your first FlowForge workflow"}
            </p>
            {canEdit && (
              <Link href="/workflows/new">
                <Button size="sm" className="mt-2 text-xs">
                  <Plus className="h-3.5 w-3.5 mr-1" />
                  Create Workflow
                </Button>
              </Link>
            )}
          </CardContent>
        </Card>
      )}

      {/* Workflow cards */}
      {!isLoading && workflows.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {workflows.map((wf) => {
            const badge = STATUS_BADGES[wf.status] ?? STATUS_BADGES.DRAFT;
            const nodeCount =
              wf.latest_version?.workflow_definition_json?.nodes?.length ?? 0;
            return (
              <Card
                key={wf.id}
                className="border-slate-200 bg-white hover:border-slate-300 transition-colors flex flex-col"
              >
                <CardHeader className="p-4 pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="text-sm font-semibold text-slate-900 leading-snug line-clamp-1">
                      {wf.name}
                    </CardTitle>
                    <Badge className={`text-[10px] ${badge.className} shrink-0`}>
                      {badge.label}
                    </Badge>
                  </div>
                  {wf.description && (
                    <CardDescription className="text-xs text-slate-500 mt-1 line-clamp-2">
                      {wf.description}
                    </CardDescription>
                  )}
                </CardHeader>

                <CardContent className="p-4 pt-2 flex flex-col gap-2 flex-1">
                  <div className="flex items-center gap-3 text-[11px] text-slate-400">
                    <span className="flex items-center gap-1">
                      <Workflow className="h-3 w-3" />
                      {nodeCount} node{nodeCount !== 1 ? "s" : ""}
                    </span>
                    {wf.latest_version && (
                      <span className="font-mono">v{wf.latest_version.version_number}</span>
                    )}
                    <span className="flex items-center gap-1 ml-auto">
                      <Clock className="h-3 w-3" />
                      {formatDate(wf.updated_at)}
                    </span>
                  </div>

                  <div className="flex items-center gap-2 mt-auto pt-2 border-t border-slate-100">
                    <Link href={`/workflows/${wf.id}`} className="flex-1">
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-full h-7 text-xs"
                      >
                        <Settings2 className="h-3 w-3 mr-1" />
                        Open Editor
                      </Button>
                    </Link>

                    {canEdit && wf.status === "DRAFT" && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs text-emerald-700"
                        onClick={() => handleActivate(wf)}
                        disabled={actionLoading === wf.id}
                      >
                        <Play className="h-3 w-3 mr-1" />
                        Activate
                      </Button>
                    )}

                    {canEdit && wf.status === "ACTIVE" && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs text-amber-700"
                        onClick={() => handlePause(wf)}
                        disabled={actionLoading === wf.id}
                      >
                        <Pause className="h-3 w-3 mr-1" />
                        Pause
                      </Button>
                    )}

                    <Link href={`/workflows/${wf.id}/executions`}>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs text-slate-600"
                        title="Execution history"
                      >
                        <List className="h-3 w-3" />
                      </Button>
                    </Link>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </AppShell>
  );
}
