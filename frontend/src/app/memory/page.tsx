"use client";

import * as React from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import {
  Search,
  Plus,
  BrainCircuit,
  CheckCircle2,
  Clock,
  Archive,
  AlertTriangle,
  RotateCw,
  ShieldCheck,
  ChevronRight,
  Filter,
} from "lucide-react";
import { fetchCurrentUser, type CurrentUser } from "@/lib/auth";
import {
  getMemoryStats,
  listMemories,
  searchMemories,
  type MemoryResponse,
  type MemoryStatsResponse,
  type MemorySearchResult,
  type MemoryType,
  type MemoryVerificationStatus,
} from "@/lib/devmemory";

const STATUS_CONFIG: Record<
  MemoryVerificationStatus,
  { label: string; className: string; icon: React.ComponentType<{ className?: string }> }
> = {
  VERIFIED: {
    label: "Verified",
    className: "bg-emerald-50 text-emerald-700 border-emerald-200",
    icon: CheckCircle2,
  },
  UNVERIFIED: {
    label: "Unverified",
    className: "bg-amber-50 text-amber-700 border-amber-200",
    icon: AlertTriangle,
  },
  OUTDATED: {
    label: "Outdated",
    className: "bg-orange-50 text-orange-700 border-orange-200",
    icon: Clock,
  },
  ARCHIVED: {
    label: "Archived",
    className: "bg-slate-100 text-slate-600 border-slate-200",
    icon: Archive,
  },
};

const MEMORY_TYPE_LABELS: Record<string, string> = {
  ARCHITECTURE_DECISION: "Architecture Decision",
  TECHNICAL_DECISION: "Technical Decision",
  BUG_FIX: "Bug Fix",
  VERIFIED_BUGFIX: "Verified Bug Fix",
  REPO_KNOWLEDGE: "Repository Knowledge",
  CODE_EXPLANATION: "Code Explanation",
  ENGINEERING_CONVENTION: "Engineering Convention",
  REPOSITORY_CONVENTION: "Repository Convention",
  TASK_OUTCOME: "Task Outcome",
  IMPLEMENTATION_DISCOVERY: "Implementation Discovery",
  ENGINEERING_DISCOVERY: "Engineering Discovery",
  KNOWN_LIMITATION: "Known Limitation",
  VERIFIED_SOLUTION: "Verified Solution",
};

export default function MemoryPage() {
  const [user, setUser] = React.useState<CurrentUser | null>(null);
  const [stats, setStats] = React.useState<MemoryStatsResponse | null>(null);
  const [memories, setMemories] = React.useState<MemoryResponse[]>([]);
  const [searchResults, setSearchResults] = React.useState<MemorySearchResult[] | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isSearching, setIsSearching] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = React.useState("");
  const [statusFilter, setStatusFilter] = React.useState<string>("");
  const [typeFilter, setTypeFilter] = React.useState<string>("");
  const [includeArchived, setIncludeArchived] = React.useState(false);

  const workspaceId = user?.workspaces?.[0]?.workspace_id ?? null;
  const userRole = user?.workspaces?.[0]?.role;
  const canCreate = userRole === "OWNER" || userRole === "ADMIN" || userRole === "MEMBER";

  const [refreshTrigger, setRefreshTrigger] = React.useState(0);

  React.useEffect(() => {
    let ignore = false;
    async function init() {
      const u = await fetchCurrentUser();
      if (!ignore) {
        setUser(u);
      }
    }
    init();
    return () => {
      ignore = true;
    };
  }, []);

  React.useEffect(() => {
    if (!workspaceId) return;
    const activeWorkspaceId = workspaceId;
    let ignore = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const [statsData, memoriesData] = await Promise.all([
          getMemoryStats(activeWorkspaceId),
          listMemories(activeWorkspaceId, {
            verificationStatus: statusFilter || undefined,
            memoryType: typeFilter || undefined,
            includeArchived,
            limit: 50,
          }),
        ]);
        if (!ignore) {
          setStats(statsData);
          setMemories(memoriesData);
          setSearchResults(null);
        }
      } catch (e) {
        if (!ignore) {
          setError(e instanceof Error ? e.message : "Failed to load engineering memory");
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }

    load();

    return () => {
      ignore = true;
    };
  }, [workspaceId, statusFilter, typeFilter, includeArchived, refreshTrigger]);

  const loadData = React.useCallback(() => {
    setRefreshTrigger((prev) => prev + 1);
  }, []);

  // Handle Search Submission
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!workspaceId) return;

    if (!searchQuery.trim()) {
      setSearchResults(null);
      loadData();
      return;
    }

    setIsSearching(true);
    setError(null);
    try {
      const results = await searchMemories(workspaceId, {
        query: searchQuery.trim(),
        include_archived: includeArchived,
        memory_types: typeFilter ? ([typeFilter as MemoryType]) : undefined,
        verification_statuses: statusFilter
          ? ([statusFilter as MemoryVerificationStatus])
          : undefined,
        limit: 25,
      });
      setSearchResults(results);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setIsSearching(false);
    }
  };

  const handleClearSearch = () => {
    setSearchQuery("");
    setSearchResults(null);
    loadData();
  };

  const displayedMemories = searchResults ? searchResults.map((r) => r.memory) : memories;

  return (
    <AppShell>
      <PageHeader
        title="DevMemory: Persistent Engineering Memory"
        subtitle="Institutional engineering knowledge, verified architectural decisions, and agent learning memory."
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-xs"
              onClick={loadData}
              disabled={isLoading || isSearching}
            >
              <RotateCw className={`h-3.5 w-3.5 mr-1.5 ${isLoading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            {canCreate && (
              <Button size="sm" className="h-8 text-xs">
                <Plus className="h-3.5 w-3.5 mr-1.5" />
                Record Memory
              </Button>
            )}
          </div>
        }
      />

      {/* Metric Cards Overview */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <Card className="border-slate-200 bg-white">
          <CardContent className="p-4">
            <p className="text-[11px] font-medium text-slate-500 uppercase tracking-wider">Total Stored</p>
            <p className="text-xl font-bold text-slate-900 mt-1">
              {stats ? stats.total_count : "—"}
            </p>
          </CardContent>
        </Card>
        <Card className="border-emerald-100 bg-emerald-50/40">
          <CardContent className="p-4">
            <p className="text-[11px] font-medium text-emerald-700 uppercase tracking-wider flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3" /> Verified
            </p>
            <p className="text-xl font-bold text-emerald-900 mt-1">
              {stats ? stats.verified_count : "—"}
            </p>
          </CardContent>
        </Card>
        <Card className="border-amber-100 bg-amber-50/40">
          <CardContent className="p-4">
            <p className="text-[11px] font-medium text-amber-700 uppercase tracking-wider flex items-center gap-1">
              <AlertTriangle className="h-3 w-3" /> Unverified
            </p>
            <p className="text-xl font-bold text-amber-900 mt-1">
              {stats ? stats.unverified_count : "—"}
            </p>
          </CardContent>
        </Card>
        <Card className="border-orange-100 bg-orange-50/40">
          <CardContent className="p-4">
            <p className="text-[11px] font-medium text-orange-700 uppercase tracking-wider flex items-center gap-1">
              <Clock className="h-3 w-3" /> Outdated
            </p>
            <p className="text-xl font-bold text-orange-900 mt-1">
              {stats ? stats.outdated_count : "—"}
            </p>
          </CardContent>
        </Card>
        <Card className="border-slate-200 bg-slate-50/60">
          <CardContent className="p-4">
            <p className="text-[11px] font-medium text-slate-600 uppercase tracking-wider flex items-center gap-1">
              <Archive className="h-3 w-3" /> Archived
            </p>
            <p className="text-xl font-bold text-slate-800 mt-1">
              {stats ? stats.archived_count : "—"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Search & Filter Bar */}
      <Card className="border-slate-200 bg-white">
        <CardContent className="p-3 space-y-3">
          <form onSubmit={handleSearch} className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
              <Input
                placeholder="Search semantic engineering knowledge, conventions, and architectural decisions..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9 h-9 text-xs"
              />
            </div>
            <Button
              type="submit"
              size="sm"
              className="h-9 text-xs px-4 bg-blue-600 hover:bg-blue-700"
              disabled={isSearching}
            >
              {isSearching ? "Searching..." : "Semantic Search"}
            </Button>
            {searchResults && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleClearSearch}
                className="h-9 text-xs"
              >
                Clear
              </Button>
            )}
          </form>

          {/* Filter Pills */}
          <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-100 text-xs">
            <span className="text-[11px] font-medium text-slate-400 flex items-center gap-1">
              <Filter className="h-3 w-3" /> Status:
            </span>
            {["", "VERIFIED", "UNVERIFIED", "OUTDATED", "ARCHIVED"].map((status) => (
              <button
                key={status}
                type="button"
                onClick={() => setStatusFilter(status)}
                className={`px-2.5 py-0.5 rounded-full text-[11px] font-medium border transition-colors ${
                  statusFilter === status
                    ? "bg-blue-50 text-blue-700 border-blue-200"
                    : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
                }`}
              >
                {status ? status : "All"}
              </button>
            ))}

            <div className="h-3 w-px bg-slate-200 mx-1" />

            <span className="text-[11px] font-medium text-slate-400">Type:</span>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="text-[11px] h-6 px-2 rounded border border-slate-200 bg-white text-slate-700 focus:outline-none"
            >
              <option value="">All Types</option>
              {Object.entries(MEMORY_TYPE_LABELS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>

            <label className="flex items-center gap-1.5 ml-auto text-[11px] text-slate-500 cursor-pointer">
              <input
                type="checkbox"
                checked={includeArchived}
                onChange={(e) => setIncludeArchived(e.target.checked)}
                className="rounded border-slate-300 text-blue-600"
              />
              Include Archived
            </label>
          </div>
        </CardContent>
      </Card>

      {/* Error state */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-xs text-red-700">
          {error}
        </div>
      )}

      {/* Search results banner */}
      {searchResults && (
        <div className="flex items-center justify-between text-xs text-slate-600 bg-blue-50/60 border border-blue-100 rounded-lg px-4 py-2">
          <span>
            Found <strong>{searchResults.length}</strong> semantic match{searchResults.length !== 1 ? "es" : ""} for &quot;{searchQuery}&quot;
          </span>
          <button
            onClick={handleClearSearch}
            className="text-blue-600 hover:underline font-medium text-[11px]"
          >
            Reset to full catalog
          </button>
        </div>
      )}

      {/* Loading Skeleton */}
      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="h-44 rounded-xl border border-slate-200 bg-slate-50 animate-pulse"
            />
          ))}
        </div>
      )}

      {/* Empty State */}
      {!isLoading && displayedMemories.length === 0 && (
        <Card className="border-dashed border-slate-200">
          <CardContent className="flex flex-col items-center justify-center py-12 gap-3 text-center">
            <BrainCircuit className="h-10 w-10 text-slate-300" />
            <p className="text-sm font-semibold text-slate-700">No memories found</p>
            <p className="text-xs text-slate-400 max-w-sm">
              {searchQuery
                ? `No engineering memories matched "${searchQuery}". Try refining your query or resetting filters.`
                : "No engineering memories recorded in this workspace yet. AI agents like DevPilot, ImpactMind, and TestPilot automatically store decisions and conventions as tasks complete."}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Memory Catalog Grid */}
      {!isLoading && displayedMemories.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {displayedMemories.map((mem) => {
            const statusCfg = STATUS_CONFIG[mem.verification_status] ?? STATUS_CONFIG.UNVERIFIED;
            const StatusIcon = statusCfg.icon;
            const searchResult = searchResults?.find((r) => r.memory.id === mem.id);

            return (
              <Card
                key={mem.id}
                className="border-slate-200 bg-white hover:border-slate-300 transition-colors flex flex-col justify-between"
              >
                <CardHeader className="p-4 pb-2">
                  <div className="flex items-start justify-between gap-2 mb-1.5">
                    <Badge
                      variant="outline"
                      className={`text-[10px] font-medium flex items-center gap-1 ${statusCfg.className}`}
                    >
                      <StatusIcon className="h-3 w-3" />
                      {statusCfg.label}
                    </Badge>
                    {searchResult && (
                      <span className="text-[10px] font-mono text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded border border-blue-100">
                        Score: {(searchResult.relevance_score * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                  <CardTitle className="text-sm font-semibold text-slate-900 leading-snug line-clamp-2">
                    {mem.title}
                  </CardTitle>
                  <CardDescription className="text-xs text-slate-500 mt-1 line-clamp-3">
                    {mem.summary || mem.content}
                  </CardDescription>
                </CardHeader>

                <CardContent className="p-4 pt-2 space-y-3">
                  <div className="flex items-center justify-between text-[11px] text-slate-500 border-t border-slate-100 pt-2">
                    <span className="font-mono text-slate-600 bg-slate-50 px-2 py-0.5 rounded border border-slate-200">
                      {MEMORY_TYPE_LABELS[mem.memory_type] || mem.memory_type}
                    </span>
                    <span className="flex items-center gap-1 text-[10px] text-slate-400">
                      <ShieldCheck className="h-3 w-3" />
                      {mem.evidence?.length || 0} evidence
                    </span>
                  </div>

                  <div className="flex items-center justify-between pt-1 text-[11px] text-slate-400">
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {new Date(mem.created_at).toLocaleDateString()}
                    </span>
                    <Link
                      href={`/memory/${mem.id}`}
                      className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-800"
                    >
                      Explore Evidence <ChevronRight className="h-3 w-3" />
                    </Link>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </AppShell>
  );
}
