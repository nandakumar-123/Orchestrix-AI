"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { MetricCards } from "@/components/dashboard/metric-cards";
import { OrchestrationControl } from "@/components/dashboard/orchestration-control";
import { AgentGrid } from "@/components/agents/agent-grid";
import { ActivityTimeline } from "@/components/dashboard/activity-timeline";
import { RecentTasks } from "@/components/dashboard/recent-tasks";
import { RepositoryOverview } from "@/components/dashboard/repository-overview";
import {
  SAMPLE_METRICS,
  SPECIALIST_AGENTS,
  SAMPLE_ACTIVITIES,
  SAMPLE_TASKS,
  SAMPLE_REPOSITORIES,
} from "@/lib/mock-data";
import { Button } from "@/components/ui/button";
import { RotateCw, Plus, Sparkles } from "lucide-react";

export default function DashboardPage() {
  const [isRefreshing, setIsRefreshing] = React.useState(false);

  const handleRefresh = () => {
    setIsRefreshing(true);
    setTimeout(() => setIsRefreshing(false), 600);
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
              disabled={isRefreshing}
            >
              <RotateCw
                className={`h-3.5 w-3.5 mr-1.5 text-slate-500 ${
                  isRefreshing ? "animate-spin" : ""
                }`}
              />
              Refresh Mesh
            </Button>
            <Button size="sm" className="text-xs h-8">
              <Plus className="h-3.5 w-3.5 mr-1" />
              New Engineering Task
            </Button>
          </div>
        }
      />

      {/* A. Summary Metrics */}
      <section aria-label="Key engineering metrics">
        <MetricCards metrics={SAMPLE_METRICS} />
      </section>

      {/* B. Central Orchestration Panel */}
      <section aria-label="Central Orchestration Control">
        <OrchestrationControl />
      </section>

      {/* C. Six AI Agent Cards */}
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
        <AgentGrid agents={SPECIALIST_AGENTS} />
      </section>

      {/* D & E. Activity & Tasks */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6" aria-label="Engineering Activity and Tasks">
        <ActivityTimeline activities={SAMPLE_ACTIVITIES} />
        <RecentTasks tasks={SAMPLE_TASKS} />
      </section>

      {/* F. Repository Overview */}
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
        <RepositoryOverview repositories={SAMPLE_REPOSITORIES} />
      </section>
    </AppShell>
  );
}

