import * as React from "react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Cpu, Bot, Play, RotateCw, GitFork, ArrowRight } from "lucide-react";

export function OrchestrationControl() {
  return (
    <Card className="border-slate-200/90 bg-white">
      <CardHeader className="pb-3">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 items-center justify-center rounded-md bg-blue-600 text-white">
                <Cpu className="h-3.5 w-3.5" />
              </div>
              <CardTitle className="text-sm sm:text-base font-semibold">
                Orchestration Control
              </CardTitle>
              <Badge variant="success" dotColor="bg-emerald-500">
                Orchestrator Online
              </Badge>
            </div>
            <CardDescription className="mt-1">
              Central LangGraph state coordinator directing specialist agent execution mesh.
            </CardDescription>
          </div>

          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="text-xs h-8">
              <RotateCw className="h-3.5 w-3.5 mr-1 text-slate-500" />
              Sync Graph
            </Button>
            <Button size="sm" className="text-xs h-8">
              <Play className="h-3.5 w-3.5 mr-1" />
              Trigger Cycle
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* State Overview */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-3 rounded-lg bg-slate-50 border border-slate-200/60 text-xs">
          <div>
            <span className="text-slate-400 block text-[11px]">Mesh State</span>
            <span className="font-semibold text-slate-800">Autonomous Active</span>
          </div>
          <div>
            <span className="text-slate-400 block text-[11px]">Active Tasks</span>
            <span className="font-semibold text-blue-600">12 Concurrent</span>
          </div>
          <div>
            <span className="text-slate-400 block text-[11px]">Specialist Agents</span>
            <span className="font-semibold text-slate-800">6 / 6 Assigned</span>
          </div>
          <div>
            <span className="text-slate-400 block text-[11px]">Cycle Frequency</span>
            <span className="font-semibold text-slate-800">Continuous Event-Driven</span>
          </div>
        </div>

        {/* Visual Relationship Diagram between Orchestrator & Specialist Agents */}
        <div className="p-3 rounded-lg border border-slate-200 bg-white">
          <div className="flex items-center justify-between text-xs text-slate-500 mb-2">
            <span className="font-medium text-slate-700 flex items-center gap-1.5">
              <GitFork className="h-3.5 w-3.5 text-blue-600" />
              Agent Coordination Topology
            </span>
            <span className="text-[11px]">LangGraph State Machine</span>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 text-xs pt-1">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-blue-50 border border-blue-200 text-blue-900 font-medium">
              <Bot className="h-4 w-4 text-blue-600" />
              <span>Central Coordinator</span>
            </div>
            <ArrowRight className="h-3.5 w-3.5 text-slate-400 hidden sm:block" />
            
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2 w-full sm:w-auto flex-1">
              {[
                "DevPilot",
                "ImpactMind",
                "TestPilot",
                "SecureFlow",
                "FlowForge",
                "DevMemory",
              ].map((agent) => (
                <div
                  key={agent}
                  className="flex items-center justify-center px-2 py-1.5 rounded bg-slate-50 border border-slate-200 text-slate-700 font-mono text-[11px] text-center"
                >
                  {agent}
                </div>
              ))}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

