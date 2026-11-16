import * as React from "react";
import { Card, CardContent } from "@/components/ui/card";
import { DashboardMetrics } from "@/lib/dashboard";
import {
  FolderGit2,
  Workflow,
  CheckCircle2,
  Brain,
  ShieldAlert,
  PlayCircle,
  FileSearch,
} from "lucide-react";
import Link from "next/link";

interface MetricCardsProps {
  metrics: DashboardMetrics;
}

export function MetricCards({ metrics }: MetricCardsProps) {
  const cards = [
    {
      id: "repos",
      label: "Connected Repositories",
      value: metrics.connected_repositories,
      subValue: `${metrics.indexed_repositories} indexed`,
      icon: FolderGit2,
      href: "/repositories",
      color: "text-blue-600 bg-blue-50 border-blue-100",
    },
    {
      id: "workflows",
      label: "Active Workflows",
      value: metrics.active_workflows,
      subValue: `${metrics.workflow_executions} executions`,
      icon: Workflow,
      href: "/workflows",
      color: "text-indigo-600 bg-indigo-50 border-indigo-100",
    },
    {
      id: "memories",
      label: "Engineering Memories",
      value: metrics.total_memories,
      subValue: `${metrics.verified_memories} verified`,
      icon: Brain,
      href: "/memory",
      color: "text-emerald-600 bg-emerald-50 border-emerald-100",
    },
    {
      id: "security",
      label: "Security Findings",
      value: metrics.open_security_findings,
      subValue: metrics.open_security_findings > 0 ? "Awaiting remediation" : "Clean workspace",
      icon: ShieldAlert,
      href: "/security",
      color: metrics.open_security_findings > 0 
        ? "text-amber-600 bg-amber-50 border-amber-100" 
        : "text-slate-600 bg-slate-50 border-slate-100",
    },
    {
      id: "tasks",
      label: "Running Tasks",
      value: metrics.running_tasks,
      subValue: `${metrics.total_tasks} total tasks`,
      icon: PlayCircle,
      href: "/devpilot",
      color: "text-purple-600 bg-purple-50 border-purple-100",
    },
    {
      id: "approvals",
      label: "Pending Approvals",
      value: metrics.pending_approvals,
      subValue: metrics.pending_approvals > 0 ? "Action required" : "Up to date",
      icon: CheckCircle2,
      href: "/workflows",
      color: metrics.pending_approvals > 0 
        ? "text-rose-600 bg-rose-50 border-rose-100" 
        : "text-emerald-600 bg-emerald-50 border-emerald-100",
    },
    {
      id: "impact",
      label: "Impact Assessments",
      value: metrics.impact_assessments,
      subValue: "Change intelligence",
      icon: FileSearch,
      href: "/impact",
      color: "text-cyan-600 bg-cyan-50 border-cyan-100",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7">
      {cards.map((item) => {
        const IconComponent = item.icon;
        return (
          <Link key={item.id} href={item.href} className="group block focus:outline-none">
            <Card className="h-full border-slate-200/80 bg-white hover:border-slate-300 hover:shadow-xs transition-all">
              <CardContent className="p-4 flex flex-col justify-between h-full">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-500 truncate mr-2">
                    {item.label}
                  </span>
                  <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${item.color}`}>
                    <IconComponent className="h-3.5 w-3.5" />
                  </div>
                </div>

                <div className="mt-2.5">
                  <span className="text-2xl font-bold tracking-tight text-slate-900">
                    {item.value}
                  </span>
                  <p className="mt-0.5 text-[11px] text-slate-400 truncate">
                    {item.subValue}
                  </p>
                </div>
              </CardContent>
            </Card>
          </Link>
        );
      })}
    </div>
  );
}
