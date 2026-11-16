"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { MetricCards } from "@/components/dashboard/metric-cards";
import { OrchestrationControl } from "@/components/dashboard/orchestration-control";
import { AgentGrid } from "@/components/dashboard/agent-grid";
import { DomainIntelligence } from "@/components/dashboard/domain-intelligence";
import { ActivityTimeline } from "@/components/dashboard/activity-timeline";
import { RecentTasks } from "@/components/dashboard/recent-tasks";
import { RepositoryOverview } from "@/components/dashboard/repository-overview";
import {
  getDashboardOverview,
  DashboardOverviewResponse,
} from "@/lib/dashboard";
import {
  fetchCurrentUser,
  CurrentUser,
  getStoredActiveWorkspaceId,
  setStoredActiveWorkspaceId,
  resolveActiveWorkspace,
} from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { RotateCw, Plus, Sparkles, AlertCircle, Building2 } from "lucide-react";
import Link from "next/link";

export default function DashboardPage() {
  const [currentUser, setCurrentUser] = React.useState<CurrentUser | null>(null);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = React.useState<string | null>(null);
  const [data, setData] = React.useState<DashboardOverviewResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = React.useState(false);
  const [refreshIndex, setRefreshIndex] = React.useState(0);

  // Active workspace derived consistently
  const activeWorkspace = React.useMemo(() => {
    return resolveActiveWorkspace(currentUser, selectedWorkspaceId);
  }, [currentUser, selectedWorkspaceId]);

  const activeWorkspaceId = activeWorkspace?.workspace_id ?? null;

  // 1. Initial user load
  React.useEffect(() => {
    let ignore = false;
    async function loadUser() {
      const user = await fetchCurrentUser();
      if (!ignore) {
        setCurrentUser(user);
        if (user && user.workspaces && user.workspaces.length > 0) {
          const resolved = resolveActiveWorkspace(user);
          if (resolved) {
            setSelectedWorkspaceId(resolved.workspace_id);
            setStoredActiveWorkspaceId(resolved.workspace_id);
          }
        } else {
          setLoading(false);
        }
      }
    }
    loadUser();
    return () => {
      ignore = true;
    };
  }, []);

  // 2. Synchronize workspace & repo mutation events across views and tabs
  React.useEffect(() => {
    const handleWorkspaceChanged = (e: Event) => {
      const customEvent = e as CustomEvent<{ workspaceId: string }>;
      const newWsId = customEvent.detail?.workspaceId || getStoredActiveWorkspaceId();
      if (newWsId && newWsId !== selectedWorkspaceId) {
        setSelectedWorkspaceId(newWsId);
      }
    };

    const handleStorageEvent = (e: StorageEvent) => {
      if (e.key === "orchestrix_active_workspace_id" && e.newValue && e.newValue !== selectedWorkspaceId) {
        setSelectedWorkspaceId(e.newValue);
      }
    };

    const handleRepoMutation = () => {
      setRefreshIndex((prev) => prev + 1);
    };

    const handleFocus = () => {
      const stored = getStoredActiveWorkspaceId();
      if (stored && stored !== selectedWorkspaceId) {
        setSelectedWorkspaceId(stored);
      }
    };

    window.addEventListener("orchestrix:workspace_changed", handleWorkspaceChanged);
    window.addEventListener("orchestrix:repository_connected", handleRepoMutation);
    window.addEventListener("orchestrix:repository_disconnected", handleRepoMutation);
    window.addEventListener("storage", handleStorageEvent);
    window.addEventListener("focus", handleFocus);

    return () => {
      window.removeEventListener("orchestrix:workspace_changed", handleWorkspaceChanged);
      window.removeEventListener("orchestrix:repository_connected", handleRepoMutation);
      window.removeEventListener("orchestrix:repository_disconnected", handleRepoMutation);
      window.removeEventListener("storage", handleStorageEvent);
      window.removeEventListener("focus", handleFocus);
    };
  }, [selectedWorkspaceId]);

  // 3. Load dashboard data for workspace
  React.useEffect(() => {
    if (!activeWorkspaceId) return;
    const wsId = activeWorkspaceId;
    let ignore = false;

    async function fetchData() {
      try {
        const res = await getDashboardOverview(wsId);
        if (!ignore) {
          setData(res);
          setError(null);
        }
      } catch (err: unknown) {
        if (!ignore) {
          const msg = err instanceof Error ? err.message : "Failed to load dashboard";
          setError(msg);
        }
      } finally {
        if (!ignore) {
          setLoading(false);
          setIsRefreshing(false);
        }
      }
    }

    fetchData();

    return () => {
      ignore = true;
    };
  }, [activeWorkspaceId, refreshIndex]);

  const handleRefresh = () => {
    if (activeWorkspaceId) {
      setIsRefreshing(true);
      setRefreshIndex((prev) => prev + 1);
    }
  };

  const handleWorkspaceSelect = (newWsId: string) => {
    setSelectedWorkspaceId(newWsId);
    setStoredActiveWorkspaceId(newWsId);
  };

  return (
    <AppShell>
      {/* Header */}
      <PageHeader
        title="Engineering Overview"
        subtitle="Monitor your repositories, AI agents, and autonomous engineering activity."
        badge={
          <span className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 border border-blue-100">
            <Sparkles className="h-3 w-3" />
            Active Mesh
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              className="text-xs h-8"
              disabled={isRefreshing || loading || !activeWorkspaceId}
            >
              <RotateCw
                className={`h-3.5 w-3.5 mr-1.5 text-slate-500 ${
                  isRefreshing ? "animate-spin" : ""
                }`}
              />
              Refresh Mesh
            </Button>
            <Link href="/devpilot">
              <Button size="sm" className="text-xs h-8">
                <Plus className="h-3.5 w-3.5 mr-1" />
                New Engineering Task
              </Button>
            </Link>
          </div>
        }
      />

      {/* Workspace Selector & Synchronization Bar */}
      {currentUser && currentUser.workspaces && currentUser.workspaces.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 bg-white border border-slate-200/80 rounded-lg px-4 py-2.5 mb-6 text-xs text-slate-600 shadow-2xs">
          <div className="flex items-center gap-2.5">
            <div className="flex h-6 w-6 items-center justify-center rounded-md bg-blue-50 text-blue-600">
              <Building2 className="h-3.5 w-3.5" />
            </div>
            <span className="font-semibold text-slate-400 uppercase tracking-wider text-[10px]">
              Active Workspace
            </span>
            {currentUser.workspaces.length > 1 ? (
              <select
                data-testid="dashboard-workspace-selector"
                value={selectedWorkspaceId || ""}
                onChange={(e) => handleWorkspaceSelect(e.target.value)}
                className="font-medium text-slate-900 bg-slate-50 border border-slate-300 rounded-md px-2.5 py-1 text-xs focus:outline-hidden focus:ring-2 focus:ring-blue-500 cursor-pointer"
              >
                {currentUser.workspaces.map((ws) => (
                  <option key={ws.workspace_id} value={ws.workspace_id}>
                    {ws.name} ({ws.role})
                  </option>
                ))}
              </select>
            ) : (
              <span className="font-semibold text-slate-900 text-xs">
                {activeWorkspace?.name}
              </span>
            )}
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-slate-100 text-slate-700">
              {activeWorkspace?.role}
            </span>
          </div>

          <div className="flex items-center gap-3 text-slate-500">
            <span>
              Connected Repositories:{" "}
              <strong className="text-slate-900">
                {data?.metrics?.connected_repositories ?? 0}
              </strong>
            </span>
            <span className="text-slate-300">|</span>
            <Link
              href="/repositories"
              className="text-blue-600 hover:text-blue-700 font-medium hover:underline inline-flex items-center gap-1"
            >
              Manage Repositories &rarr;
            </Link>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50/70 p-4 text-xs text-rose-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 text-rose-600 shrink-0" />
            <span>{error}</span>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            className="text-xs h-7 bg-white text-rose-800 border-rose-300 hover:bg-rose-100"
          >
            Retry
          </Button>
        </div>
      )}

      {loading && !data ? (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
            {Array.from({ length: 7 }).map((_, i) => (
              <div
                key={i}
                className="h-24 rounded-lg bg-slate-100 animate-pulse border border-slate-200/60"
              />
            ))}
          </div>
          <div className="h-48 rounded-lg bg-slate-100 animate-pulse border border-slate-200/60" />
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="h-40 rounded-lg bg-slate-100 animate-pulse border border-slate-200/60"
              />
            ))}
          </div>
        </div>
      ) : data ? (
        <div className="space-y-6">
          {/* A. Summary Metrics */}
          <section aria-label="Key engineering metrics">
            <MetricCards metrics={data.metrics} />
          </section>

          {/* B. Central Orchestration Panel */}
          <section aria-label="Central Orchestration Control">
            <OrchestrationControl
              workflows={data.workflows}
              security={data.security}
              impact={data.impact}
              memory={data.memory}
              totalRunningTasks={data.metrics.running_tasks}
            />
          </section>

          {/* C. Specialist Agent Overview */}
          <section className="space-y-3" aria-label="Specialist Engineering Agents">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <h2 className="text-sm sm:text-base font-semibold text-slate-900">
                  Specialist Engineering Agents
                </h2>
                <p className="text-xs text-slate-500">
                  Autonomous agents coordinating on code synthesis, impact blast analysis, testing, security, and knowledge recall.
                </p>
              </div>
            </div>
            <AgentGrid agents={data.agents} />
          </section>

          {/* D. Domain Intelligence (SecureFlow, ImpactMind, DevMemory, FlowForge) */}
          <section className="space-y-3" aria-label="Domain Intelligence">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm sm:text-base font-semibold text-slate-900">
                  Domain Intelligence
                </h2>
                <p className="text-xs text-slate-500">
                  Deep insights synthesized across security, impact, memory, and orchestration domains.
                </p>
              </div>
            </div>
            <DomainIntelligence
              security={data.security}
              impact={data.impact}
              memory={data.memory}
              workflows={data.workflows}
            />
          </section>

          {/* E & F. Activity & Tasks */}
          <section className="grid grid-cols-1 lg:grid-cols-2 gap-6" aria-label="Engineering Activity and Tasks">
            <ActivityTimeline activities={data.activities} />
            <RecentTasks tasks={data.tasks} />
          </section>

          {/* G. Repository Overview */}
          <section className="space-y-3" aria-label="Connected Repositories">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm sm:text-base font-semibold text-slate-900">
                  Connected Repositories
                </h2>
                <p className="text-xs text-slate-500">
                  Codebases indexed by DevMemory and guarded by active AI agents.
                </p>
              </div>
            </div>
            <RepositoryOverview repositories={data.repositories} />
          </section>
        </div>
      ) : !currentUser ? (
        <div className="rounded-lg border border-slate-200 bg-white p-12 text-center space-y-4">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-500">
            <AlertCircle className="h-6 w-6" />
          </div>
          <div className="space-y-1">
            <h3 className="text-base font-semibold text-slate-900">Sign in to view Engineering Overview</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              Authenticate with your enterprise identity to inspect repositories, active agent mesh, and system tasks.
            </p>
          </div>
          <div className="pt-2">
            <Link href="/auth/login">
              <Button size="sm">Go to Login</Button>
            </Link>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-white p-12 text-center space-y-3">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-blue-50 text-blue-600">
            <Building2 className="h-6 w-6" />
          </div>
          <div className="space-y-1">
            <h3 className="text-base font-semibold text-slate-900">No Workspace Available</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              Your account is not associated with any active workspaces. Contact your administrator or create a workspace.
            </p>
          </div>
        </div>
      )}
    </AppShell>
  );
}
