"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { SAMPLE_MEMORIES } from "@/lib/mock-data";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Search, Plus } from "lucide-react";

export default function MemoryPage() {
  const [searchQuery, setSearchQuery] = React.useState("");

  const filtered = SAMPLE_MEMORIES.filter((m) =>
    m.key.toLowerCase().includes(searchQuery.toLowerCase()) ||
    m.summary.toLowerCase().includes(searchQuery.toLowerCase()) ||
    m.scope.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <AppShell>
      <PageHeader
        title="Engineering Memory & ADRs"
        subtitle="Powered by DevMemory: Persistent vector recall of architectural decisions and code conventions."
        actions={
          <Button size="sm" className="text-xs h-8">
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add Engineering Context
          </Button>
        }
      />

      {/* Memory Search */}
      <div className="flex items-center gap-3 bg-white p-3 rounded-xl border border-slate-200">
        <Input
          placeholder="Semantic search across stored decisions, patterns, and ADRs..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          icon={<Search className="h-3.5 w-3.5" />}
          className="h-8 text-xs"
        />
      </div>

      {/* Memory Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {filtered.map((mem) => (
          <Card key={mem.id} className="border-slate-200 bg-white hover:border-slate-300 transition-colors flex flex-col justify-between">
            <CardHeader className="p-4 pb-2">
              <div className="flex items-start justify-between gap-2">
                <span className="font-mono text-xs font-semibold text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
                  {mem.key}
                </span>
                <Badge variant="outline" className="text-[10px] capitalize">
                  {mem.scope}
                </Badge>
              </div>
            </CardHeader>

            <CardContent className="p-4 pt-2 space-y-3">
              <p className="text-xs text-slate-700 leading-relaxed">
                {mem.summary}
              </p>
              <div className="flex items-center justify-between text-[11px] text-slate-400 pt-2 border-t border-slate-100">
                <span>Relevance {mem.relevanceScore}%</span>
                <span>{mem.updatedAt}</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </AppShell>
  );
}
