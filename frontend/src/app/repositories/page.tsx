"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { SAMPLE_REPOSITORIES } from "@/lib/mock-data";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/shared/empty-state";
import {
  FolderGit2,
  Search,
  Plus,
  GitBranch,
  Lock,
  Globe,
  Clock,
  ExternalLink,
  Bot,
} from "lucide-react";

export default function RepositoriesPage() {
  const [searchTerm, setSearchTerm] = React.useState("");

  const filtered = SAMPLE_REPOSITORIES.filter(
    (r) =>
      r.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      r.owner.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <AppShell>
      <PageHeader
        title="Connected Repositories"
        subtitle="Manage GitHub repositories connected to the Orchestrix AI agent mesh."
        actions={
          <Button size="sm" className="text-xs h-8">
            <Plus className="h-3.5 w-3.5 mr-1" />
            Connect GitHub Repository
          </Button>
        }
      />

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-white p-3 rounded-xl border border-slate-200">
        <div className="w-full sm:max-w-md">
          <Input
            placeholder="Filter repositories by name or owner..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            icon={<Search className="h-3.5 w-3.5" />}
            className="h-8 text-xs"
          />
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500 w-full sm:w-auto justify-end">
          <span>Showing {filtered.length} of {SAMPLE_REPOSITORIES.length} repositories</span>
        </div>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={FolderGit2}
          title="No repositories found"
          description={`No repositories matched your search query "${searchTerm}".`}
          actionLabel="Clear search"
          onAction={() => setSearchTerm("")}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filtered.map((repo) => (
            <Card key={repo.id} className="border-slate-200/90 bg-white hover:border-slate-300 transition-colors">
              <CardHeader className="p-5 pb-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 border border-blue-100">
                      <FolderGit2 className="h-5 w-5" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="font-semibold text-sm text-slate-900">{repo.name}</h3>
                        {repo.visibility === "private" ? (
                          <Lock className="h-3 w-3 text-slate-400" />
                        ) : (
                          <Globe className="h-3 w-3 text-slate-400" />
                        )}
                      </div>
                      <p className="text-xs text-slate-400 font-mono mt-0.5">{repo.owner}</p>
                    </div>
                  </div>

                  <Badge
                    variant={repo.status === "synced" ? "success" : "warning"}
                    dotColor={repo.status === "synced" ? "bg-emerald-500" : "bg-amber-500 animate-pulse"}
                    className="capitalize text-[11px]"
                  >
                    {repo.status}
                  </Badge>
                </div>
              </CardHeader>

              <CardContent className="p-5 pt-0 space-y-4">
                <div className="grid grid-cols-3 gap-2 p-2.5 rounded-lg bg-slate-50 text-xs text-slate-600 border border-slate-200/60 font-mono text-[11px]">
                  <div>
                    <span className="text-slate-400 block text-[10px]">Default Branch</span>
                    <span className="font-semibold text-slate-800 flex items-center gap-1 mt-0.5">
                      <GitBranch className="h-3 w-3 text-blue-600" />
                      {repo.defaultBranch}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">Active Agents</span>
                    <span className="font-semibold text-slate-800 flex items-center gap-1 mt-0.5">
                      <Bot className="h-3 w-3 text-blue-600" />
                      {repo.agentCount}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">Last Indexed</span>
                    <span className="font-semibold text-slate-800 flex items-center gap-1 mt-0.5">
                      <Clock className="h-3 w-3 text-slate-400" />
                      {repo.lastIndexed}
                    </span>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-xs">
                  <span className="text-slate-500 text-[11px]">
                    Autonomous indexing active with DevMemory
                  </span>
                  <Button variant="ghost" size="sm" className="h-7 text-xs text-blue-600 hover:text-blue-700">
                    Inspect AST Graph
                    <ExternalLink className="h-3 w-3 ml-1" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </AppShell>
  );
}
