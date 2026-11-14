"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { AgentGrid } from "@/components/agents/agent-grid";
import { SPECIALIST_AGENTS } from "@/lib/mock-data";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Bot, Cpu, ShieldCheck, RefreshCw } from "lucide-react";

export default function AgentsPage() {
  const [selectedStatus, setSelectedStatus] = React.useState<string>("all");

  const filteredAgents = SPECIALIST_AGENTS.filter((agent) => {
    if (selectedStatus === "all") return true;
    return agent.status === selectedStatus;
  });

  return (
    <AppShell>
      <PageHeader
        title="AI Agent Mesh"
        subtitle="Autonomous specialist agents operating in an event-driven coordination mesh."
        badge={
          <Badge variant="success" dotColor="bg-emerald-500">
            6 Online
          </Badge>
        }
        actions={
          <Button variant="outline" size="sm" className="text-xs h-8">
            <RefreshCw className="h-3.5 w-3.5 mr-1.5 text-slate-500" />
            Check Agent Health
          </Button>
        }
      />

      {/* Mesh Status Overview */}
      <Card className="border-slate-200/90 bg-white">
        <CardContent className="p-4 sm:p-5">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 divide-y sm:divide-y-0 sm:divide-x divide-slate-100">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                <Bot className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs text-slate-400 font-mono">Specialist Roles</p>
                <h4 className="text-sm font-semibold text-slate-900">
                  Dev, Test, Impact, Sec, Flow, Mem
                </h4>
              </div>
            </div>

            <div className="flex items-center gap-3 pt-3 sm:pt-0 sm:pl-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs text-slate-400 font-mono">Execution Guardrails</p>
                <h4 className="text-sm font-semibold text-slate-900">
                  100% Deterministic Schema Gates
                </h4>
              </div>
            </div>

            <div className="flex items-center gap-3 pt-3 sm:pt-0 sm:pl-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
                <Cpu className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs text-slate-400 font-mono">Total Tasks Executed</p>
                <h4 className="text-sm font-semibold text-slate-900">
                  895 autonomous tasks
                </h4>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2">
        {["all", "busy", "operational", "idle"].map((status) => (
          <Button
            key={status}
            variant={selectedStatus === status ? "default" : "outline"}
            size="sm"
            onClick={() => setSelectedStatus(status)}
            className="capitalize text-xs h-7 px-3"
          >
            {status}
          </Button>
        ))}
      </div>

      {/* Agent Grid */}
      <AgentGrid agents={filteredAgents} />
    </AppShell>
  );
}
