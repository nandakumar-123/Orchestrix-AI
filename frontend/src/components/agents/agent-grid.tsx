import * as React from "react";
import Link from "next/link";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AgentInfo } from "@/types";
import { DynamicIcon } from "@/components/shared/icons";
import { ArrowUpRight, Activity } from "lucide-react";

interface AgentGridProps {
  agents: AgentInfo[];
  showDetailsLink?: boolean;
}

export function AgentGrid({ agents, showDetailsLink = true }: AgentGridProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {agents.map((agent) => {
        const isBusy = agent.status === "busy";
        const isOperational = agent.status === "operational";

        return (
          <Card
            key={agent.id}
            className="flex flex-col justify-between border-slate-200/90 bg-white hover:border-slate-300 transition-all shadow-xs"
          >
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 border border-blue-100">
                    <DynamicIcon name={agent.iconName} className="h-5 w-5" />
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
                  variant={isBusy ? "default" : isOperational ? "success" : "secondary"}
                  dotColor={
                    isBusy
                      ? "bg-blue-500 animate-pulse"
                      : isOperational
                      ? "bg-emerald-500"
                      : "bg-slate-400"
                  }
                  className="capitalize text-[11px]"
                >
                  {agent.status}
                </Badge>
              </div>

              <CardDescription className="mt-2 text-xs leading-relaxed text-slate-600 line-clamp-2">
                {agent.purpose}
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
                  {agent.currentTask || "Idle / Ready for assignment"}
                </p>
              </div>

              {/* Capabilities Pills */}
              <div className="flex flex-wrap gap-1">
                {agent.capabilities.slice(0, 3).map((cap) => (
                  <span
                    key={cap}
                    className="inline-flex items-center rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600 font-medium"
                  >
                    {cap}
                  </span>
                ))}
                {agent.capabilities.length > 3 && (
                  <span className="inline-flex items-center rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-400 font-medium">
                    +{agent.capabilities.length - 3}
                  </span>
                )}
              </div>

              {/* Footer details & Action */}
              <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-xs text-slate-500">
                <span>{agent.completedTasks} tasks done</span>
                {showDetailsLink ? (
                  <Link href={`/agents?agent=${agent.id}`}>
                    <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-blue-600 hover:text-blue-700">
                      View details
                      <ArrowUpRight className="h-3 w-3 ml-1" />
                    </Button>
                  </Link>
                ) : (
                  <span className="text-[11px] text-slate-400">{agent.lastActive}</span>
                )}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
