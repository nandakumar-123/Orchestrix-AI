"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Network, ArrowRight } from "lucide-react";

export default function ImpactPage() {
  return (
    <AppShell>
      <PageHeader
        title="Change Impact Intelligence"
        subtitle="Powered by ImpactMind: Semantic AST blast radius mapping and dependency ripple analysis."
        actions={
          <Button size="sm" className="text-xs h-8">
            <Network className="h-3.5 w-3.5 mr-1.5" />
            Analyze Branch Blast Radius
          </Button>
        }
      />

      {/* Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="border-slate-200 bg-white">
          <CardContent className="p-4">
            <span className="text-xs text-slate-500 font-mono">Analyzed PRs</span>
            <p className="text-2xl font-bold text-slate-900 mt-1">42 PRs</p>
            <span className="text-[11px] text-emerald-600 mt-0.5 block">100% blast radius verified</span>
          </CardContent>
        </Card>

        <Card className="border-slate-200 bg-white">
          <CardContent className="p-4">
            <span className="text-xs text-slate-500 font-mono">Detected Breaking Contracts</span>
            <p className="text-2xl font-bold text-slate-900 mt-1">0</p>
            <span className="text-[11px] text-slate-400 mt-0.5 block">Zero production regressions</span>
          </CardContent>
        </Card>

        <Card className="border-slate-200 bg-white">
          <CardContent className="p-4">
            <span className="text-xs text-slate-500 font-mono">AST Nodes Mapped</span>
            <p className="text-2xl font-bold text-slate-900 mt-1">14,280</p>
            <span className="text-[11px] text-blue-600 mt-0.5 block">Graph synced with DevMemory</span>
          </CardContent>
        </Card>
      </div>

      {/* Semantic Impact Visualizer Placeholder */}
      <Card className="border-slate-200 bg-white">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Network className="h-4 w-4 text-blue-600" />
                Live AST Dependency Blast Radius Graph
              </CardTitle>
              <CardDescription>
                Visualizing target modifications in PR #104 against downstream service contracts.
              </CardDescription>
            </div>
            <Badge variant="agent">ImpactMind Active</Badge>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="h-64 sm:h-80 rounded-xl border border-dashed border-slate-200 bg-slate-50/70 flex flex-col items-center justify-center p-6 text-center">
            <div className="flex items-center gap-4 text-xs font-mono mb-4">
              <span className="p-2 rounded bg-blue-100 text-blue-700 font-semibold">
                auth.py:verify_token()
              </span>
              <ArrowRight className="h-4 w-4 text-slate-400" />
              <span className="p-2 rounded bg-amber-100 text-amber-800 font-semibold">
                Impact Area: 3 Endpoints &bull; 2 Consumers
              </span>
            </div>
            <Network className="h-10 w-10 text-blue-400 animate-pulse mb-2" />
            <h4 className="text-sm font-semibold text-slate-800">
              AST Semantic Dependency Graph Canvas
            </h4>
            <p className="text-xs text-slate-500 max-w-md mt-1">
              Interactive node topology will render real-time call trees, type signatures, and contract impacts during active repository analysis.
            </p>
          </div>
        </CardContent>
      </Card>
    </AppShell>
  );
}
