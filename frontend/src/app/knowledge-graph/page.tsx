"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Share2, RefreshCw, ZoomIn, ZoomOut, Maximize2, Network } from "lucide-react";

export default function KnowledgeGraphPage() {
  return (
    <AppShell>
      <PageHeader
        title="Knowledge Graph Workspace"
        subtitle="Interactive visual ontology of software entities, modules, dependencies, and PR history."
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="text-xs h-8">
              <RefreshCw className="h-3.5 w-3.5 mr-1 text-slate-500" />
              Re-Index Graph
            </Button>
            <Button size="sm" className="text-xs h-8">
              <Share2 className="h-3.5 w-3.5 mr-1" />
              Query Graph
            </Button>
          </div>
        }
      />

      <Card className="border-slate-200 bg-white">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Network className="h-4 w-4 text-blue-600" />
                Cross-Repository Knowledge Ontology
              </CardTitle>
              <CardDescription>
                Neo4j property graph mapping AST entities, schemas, agents, and engineering tasks.
              </CardDescription>
            </div>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="icon" className="h-8 w-8 text-slate-500">
                <ZoomIn className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" className="h-8 w-8 text-slate-500">
                <ZoomOut className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" className="h-8 w-8 text-slate-500">
                <Maximize2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardHeader>

        <CardContent>
          <div className="h-96 rounded-xl border border-dashed border-slate-200 bg-slate-50/70 flex flex-col items-center justify-center p-6 text-center">
            <Share2 className="h-12 w-12 text-blue-400 animate-pulse mb-3" />
            <h4 className="text-sm font-semibold text-slate-800">
              Interactive Neo4j Graph Canvas Workspace
            </h4>
            <p className="text-xs text-slate-500 max-w-md mt-1">
              Displays entity nodes (Files, Functions, Classes, Commits, Tasks) connected by semantic relationships (`IMPACTS`, `CALLS`, `TESTS`, `AUDITS`).
            </p>
          </div>
        </CardContent>
      </Card>
    </AppShell>
  );
}
