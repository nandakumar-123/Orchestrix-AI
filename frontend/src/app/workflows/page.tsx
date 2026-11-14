"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { SAMPLE_WORKFLOWS } from "@/lib/mock-data";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Workflow, Plus, Play, ArrowRight, Settings2 } from "lucide-react";

export default function WorkflowsPage() {
  return (
    <AppShell>
      <PageHeader
        title="Visual Workflow Builder"
        subtitle="Powered by FlowForge: Autonomous multi-agent CI/CD orchestration and release guardrails."
        actions={
          <Button size="sm" className="text-xs h-8">
            <Plus className="h-3.5 w-3.5 mr-1" />
            Create Workflow
          </Button>
        }
      />

      {/* Visual Workflow Studio Entry point */}
      <Card className="border-slate-200 bg-white">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Workflow className="h-4 w-4 text-blue-600" />
                Autonomous Workflow Canvas
              </CardTitle>
              <CardDescription>
                Design multi-agent sequential and parallel pipelines with deterministic logic gates.
              </CardDescription>
            </div>
            <Badge variant="agent">FlowForge Studio</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="h-48 rounded-xl border border-dashed border-slate-200 bg-slate-50 flex flex-col items-center justify-center p-6 text-center">
            <div className="flex items-center gap-2 text-xs font-mono text-slate-600 mb-3">
              <span className="px-2 py-1 bg-white border border-slate-200 rounded">Trigger: PR</span>
              <ArrowRight className="h-3.5 w-3.5 text-slate-400" />
              <span className="px-2 py-1 bg-blue-50 border border-blue-200 text-blue-700 rounded font-semibold">ImpactMind</span>
              <ArrowRight className="h-3.5 w-3.5 text-slate-400" />
              <span className="px-2 py-1 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded font-semibold">TestPilot</span>
              <ArrowRight className="h-3.5 w-3.5 text-slate-400" />
              <span className="px-2 py-1 bg-white border border-slate-200 rounded">Automated Merge</span>
            </div>
            <Button variant="outline" size="sm" className="text-xs">
              <Settings2 className="h-3.5 w-3.5 mr-1.5" />
              Open Visual Canvas
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Active Workflows List */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-slate-900">Configured Workflows</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {SAMPLE_WORKFLOWS.map((wf) => (
            <Card key={wf.id} className="border-slate-200 bg-white hover:border-slate-300 transition-colors flex flex-col justify-between">
              <CardHeader className="p-4 pb-2">
                <div className="flex items-start justify-between gap-2">
                  <h4 className="font-semibold text-xs text-slate-900 leading-snug">{wf.name}</h4>
                  <Badge variant="success" className="text-[10px] capitalize">{wf.status}</Badge>
                </div>
                <CardDescription className="text-xs text-slate-500 mt-1 line-clamp-2">
                  {wf.description}
                </CardDescription>
              </CardHeader>

              <CardContent className="p-4 pt-2 space-y-3">
                <div className="text-[11px] font-mono text-slate-600 bg-slate-50 p-2 rounded border border-slate-100">
                  <span className="text-slate-400 block text-[10px]">Trigger</span>
                  <span>{wf.trigger}</span>
                </div>
                <div className="flex items-center justify-between text-xs text-slate-400 pt-1 border-t border-slate-100">
                  <span>{wf.stepsCount} agent steps</span>
                  <Button variant="ghost" size="sm" className="h-7 text-xs text-blue-600">
                    <Play className="h-3 w-3 mr-1" />
                    Run
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
