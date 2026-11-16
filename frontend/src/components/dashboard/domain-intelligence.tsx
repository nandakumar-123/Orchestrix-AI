import * as React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { SecuritySummary, ImpactSummary, MemorySummary, WorkflowSummary } from "@/lib/dashboard";
import { ShieldAlert, FileSearch, Brain, Workflow, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";

interface DomainIntelligenceProps {
  security: SecuritySummary;
  impact: ImpactSummary;
  memory: MemorySummary;
  workflows: WorkflowSummary;
}

export function DomainIntelligence({
  security,
  impact,
  memory,
  workflows,
}: DomainIntelligenceProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* 1. SecureFlow Widget */}
      <Card className="border-slate-200/90 bg-white hover:border-slate-300 transition-all flex flex-col justify-between">
        <CardHeader className="p-4 pb-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-amber-600" />
              <CardTitle className="text-xs font-semibold">SecureFlow</CardTitle>
            </div>
            <Link href="/security" className="text-slate-400 hover:text-blue-600">
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </div>
          <p className="text-[11px] text-slate-500 mt-1">Application security & vulnerability audit</p>
        </CardHeader>
        <CardContent className="p-4 pt-1 space-y-2">
          <div className="flex items-baseline justify-between pt-1">
            <span className="text-xl font-bold text-slate-900">{security.open_findings}</span>
            <span className="text-[11px] text-slate-400">open findings</span>
          </div>
          <div className="flex items-center gap-1.5 text-[10px] text-slate-500 pt-1 border-t border-slate-100">
            <span>{security.confirmed_findings} confirmed</span>
            <span>&bull;</span>
            <span>{security.resolved_findings} resolved</span>
          </div>
        </CardContent>
      </Card>

      {/* 2. ImpactMind Widget */}
      <Card className="border-slate-200/90 bg-white hover:border-slate-300 transition-all flex flex-col justify-between">
        <CardHeader className="p-4 pb-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileSearch className="h-4 w-4 text-cyan-600" />
              <CardTitle className="text-xs font-semibold">ImpactMind</CardTitle>
            </div>
            <Link href="/impact" className="text-slate-400 hover:text-blue-600">
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </div>
          <p className="text-[11px] text-slate-500 mt-1">Change blast radius & regression intelligence</p>
        </CardHeader>
        <CardContent className="p-4 pt-1 space-y-2">
          <div className="flex items-baseline justify-between pt-1">
            <span className="text-xl font-bold text-slate-900">{impact.total_assessments}</span>
            <span className="text-[11px] text-slate-400">assessments</span>
          </div>
          <div className="flex items-center justify-between text-[10px] text-slate-500 pt-1 border-t border-slate-100">
            <span>Risk Tier:</span>
            <Badge variant="outline" className="text-[10px] py-0 px-1 font-mono">
              {impact.latest_risk_tier || "N/A"}
            </Badge>
          </div>
        </CardContent>
      </Card>

      {/* 3. DevMemory Widget */}
      <Card className="border-slate-200/90 bg-white hover:border-slate-300 transition-all flex flex-col justify-between">
        <CardHeader className="p-4 pb-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Brain className="h-4 w-4 text-emerald-600" />
              <CardTitle className="text-xs font-semibold">DevMemory</CardTitle>
            </div>
            <Link href="/memory" className="text-slate-400 hover:text-blue-600">
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </div>
          <p className="text-[11px] text-slate-500 mt-1">Engineering memory & verified conventions</p>
        </CardHeader>
        <CardContent className="p-4 pt-1 space-y-2">
          <div className="flex items-baseline justify-between pt-1">
            <span className="text-xl font-bold text-slate-900">{memory.verified_count}</span>
            <span className="text-[11px] text-slate-400">/ {memory.total_count} verified</span>
          </div>
          <div className="flex items-center gap-1.5 text-[10px] text-slate-500 pt-1 border-t border-slate-100">
            <span>{memory.unverified_count} unverified</span>
            <span>&bull;</span>
            <span>{memory.outdated_count} outdated</span>
          </div>
        </CardContent>
      </Card>

      {/* 4. FlowForge Widget */}
      <Card className="border-slate-200/90 bg-white hover:border-slate-300 transition-all flex flex-col justify-between">
        <CardHeader className="p-4 pb-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Workflow className="h-4 w-4 text-indigo-600" />
              <CardTitle className="text-xs font-semibold">FlowForge</CardTitle>
            </div>
            <Link href="/workflows" className="text-slate-400 hover:text-blue-600">
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </div>
          <p className="text-[11px] text-slate-500 mt-1">Visual orchestration & execution engine</p>
        </CardHeader>
        <CardContent className="p-4 pt-1 space-y-2">
          <div className="flex items-baseline justify-between pt-1">
            <span className="text-xl font-bold text-slate-900">{workflows.active_workflows}</span>
            <span className="text-[11px] text-slate-400">active workflows</span>
          </div>
          <div className="flex items-center gap-1.5 text-[10px] text-slate-500 pt-1 border-t border-slate-100">
            <span>{workflows.recent_executions} executions</span>
            <span>&bull;</span>
            <span>{workflows.pending_approvals} approvals</span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
