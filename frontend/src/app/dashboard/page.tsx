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
import { fetchCurrentUser, CurrentUser } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { RotateCw, Plus, Sparkles, AlertCircle } from "lucide-react";
import Link from "next/link";

export default function DashboardPage() {
  const [currentUser, setCurrentUser] = React.useState<CurrentUser | null>(null);
  const [data, setData] = React.useState<DashboardOverviewResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = React.useState(false);
  const [refreshIndex, setRefreshIndex] = React.useState(0);

  // 1. Initial user load
  React.useEffect(() => {
    let ignore = false;
    async function loadUser() {
      const user = await fetchCurrentUser();
      if (!ignore) {
        setCurrentUser(user);
        if (!user || !user.workspaces || user.workspaces.length === 0) {
          setLoading(false);
        }
      }
    }
    loadUser();
    return () => {
      ignore = true;
    };
  }, []);

  const activeWorkspaceId = currentUser?.workspaces?.[0]?.workspace_id ?? null;

  // 2. Load dashboard data for workspace
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
      ) : (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center">
          <p className="text-sm text-slate-600">No workspace available or user not logged in.</p>
        </div>
      )}
    </AppShell>
  );
}
