import * as React from "react";
import Link from "next/link";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AgentStatusSummary } from "@/lib/dashboard";
import { ArrowUpRight, Activity, Bot, Terminal, ShieldAlert, Cpu, Sparkles, Brain } from "lucide-react";

interface AgentGridProps {
  agents: AgentStatusSummary[];
  showDetailsLink?: boolean;
}

const AGENT_ICON_MAP: Record<string, React.ElementType> = {
  devpilot: Terminal,
  impactmind: Cpu,
  testpilot: Sparkles,
  secureflow: ShieldAlert,
  flowforge: Bot,
  devmemory: Brain,
};

const AGENT_PAGE_MAP: Record<string, string> = {
  devpilot: "/devpilot",
  impactmind: "/impact",
  testpilot: "/testing",
  secureflow: "/security",
  flowforge: "/workflows",
  devmemory: "/memory",
};

export function AgentGrid({ agents, showDetailsLink = true }: AgentGridProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {agents.map((agent) => {
        const isRunning = agent.status === "RUNNING";
        const isAvailable = agent.status === "AVAILABLE" || agent.status === "IDLE";
        const isFailed = agent.status === "FAILED";

        const IconComponent = AGENT_ICON_MAP[agent.agent_id.toLowerCase()] || Bot;
        const pageHref = AGENT_PAGE_MAP[agent.agent_id.toLowerCase()] || "/dashboard";

        return (
          <Card
            key={agent.agent_id}
            className="flex flex-col justify-between border-slate-200/90 bg-white hover:border-slate-300 transition-all shadow-xs"
          >
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 border border-blue-100">
                    <IconComponent className="h-5 w-5" />
                  </div>
                  <div>
                    <CardTitle className="text-sm font-semibold text-slate-900">
                      {agent.name}
                    </CardTitle>
                    <span className="text-[11px] text-slate-500 font-mono">
                      {agent.role}
                    </span>
                  </div>
                </div>

                <Badge
                  variant={isRunning ? "default" : isAvailable ? "success" : isFailed ? "destructive" : "secondary"}
                  dotColor={
                    isRunning
                      ? "bg-blue-500 animate-pulse"
                      : isAvailable
                      ? "bg-emerald-500"
                      : isFailed
                      ? "bg-rose-500"
                      : "bg-slate-400"
                  }
                  className="capitalize text-[11px]"
                >
                  {agent.status.toLowerCase()}
                </Badge>
              </div>

              <CardDescription className="mt-2 text-xs leading-relaxed text-slate-600 line-clamp-2">
                Specialized autonomous engineering specialist assigned to verified workspace tasks.
              </CardDescription>
            </CardHeader>

            <CardContent className="space-y-3 pt-0">
              {/* Current Activity Box */}
              <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200/70 text-xs">
                <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500 mb-1">
                  <Activity className="h-3 w-3 text-blue-600" />
                  <span>Current Activity</span>
                </div>
                <p className="text-slate-800 font-mono text-[11px] truncate">
                  {agent.current_task || (agent.active_executions > 0 ? `${agent.active_executions} active runs` : "Idle / Ready for assignment")}
                </p>
              </div>

              {/* Stats Box */}
              <div className="grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded bg-slate-50 p-1.5 border border-slate-100">
                  <span className="block text-[10px] text-slate-400">Active</span>
                  <span className="font-semibold text-slate-800">{agent.active_executions}</span>
                </div>
                <div className="rounded bg-slate-50 p-1.5 border border-slate-100">
                  <span className="block text-[10px] text-slate-400">Done</span>
                  <span className="font-semibold text-emerald-600">{agent.completed_executions}</span>
                </div>
                <div className="rounded bg-slate-50 p-1.5 border border-slate-100">
                  <span className="block text-[10px] text-slate-400">Failed</span>
                  <span className="font-semibold text-rose-600">{agent.failed_executions}</span>
                </div>
              </div>

              {/* Footer details & Action */}
              <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-xs text-slate-500">
                <span>
                  {agent.last_execution_time
                    ? `Last active ${new Date(agent.last_execution_time).toLocaleDateString()}`
                    : "No executions yet"}
                </span>
                {showDetailsLink && (
                  <Link href={pageHref}>
                    <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-blue-600 hover:text-blue-700">
                      Open console
                      <ArrowUpRight className="h-3 w-3 ml-1" />
                    </Button>
                  </Link>
                )}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
