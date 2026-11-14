"use client";

import * as React from "react";
import {
  CodeSymbolItem,
  FileDependencyItem,
  RepositoryFileItem,
  RepositoryIntelligenceOverview,
  fetchRepositoryDependencies,
  fetchRepositoryFiles,
  fetchRepositorySymbols,
} from "@/lib/indexing";
import {
  X,
  FileCode,
  Layers,
  Package,
  Sparkles,
  Search,
  Loader2,
  CheckCircle2,
  GitCommit,
  Clock,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface RepositoryIntelligenceModalProps {
  isOpen: boolean;
  onClose: () => void;
  repositoryId: string;
  workspaceId: string;
  repositoryName: string;
  overview: RepositoryIntelligenceOverview | null;
  onReindex?: () => void;
  isIndexing?: boolean;
}

export function RepositoryIntelligenceModal({
  isOpen,
  onClose,
  repositoryId,
  workspaceId,
  repositoryName,
  overview,
  onReindex,
  isIndexing,
}: RepositoryIntelligenceModalProps) {
  const [activeTab, setActiveTab] = React.useState<"overview" | "files" | "symbols" | "dependencies">("overview");

  // Tab Data States
  const [files, setFiles] = React.useState<RepositoryFileItem[]>([]);
  const [symbols, setSymbols] = React.useState<CodeSymbolItem[]>([]);
  const [dependencies, setDependencies] = React.useState<FileDependencyItem[]>([]);

  // Search & Filter States
  const [searchQuery, setSearchQuery] = React.useState("");
  const [selectedLanguage, setSelectedLanguage] = React.useState<string>("all");
  const [selectedSymbolType, setSelectedSymbolType] = React.useState<string>("all");
  const [loadingTab, setLoadingTab] = React.useState(false);

  // Load Tab Data when Tab changes
  React.useEffect(() => {
    if (!isOpen || !repositoryId || !workspaceId) return;

    let isMounted = true;
    async function loadData() {
      setLoadingTab(true);
      if (activeTab === "files") {
        const res = await fetchRepositoryFiles(repositoryId, workspaceId, { limit: 100 });
        if (isMounted && res) setFiles(res.files);
      } else if (activeTab === "symbols") {
        const res = await fetchRepositorySymbols(repositoryId, workspaceId, { limit: 150 });
        if (isMounted && res) setSymbols(res.symbols);
      } else if (activeTab === "dependencies") {
        const res = await fetchRepositoryDependencies(repositoryId, workspaceId, { limit: 150 });
        if (isMounted && res) setDependencies(res.dependencies);
      }
      if (isMounted) setLoadingTab(false);
    }

    loadData();
    return () => {
      isMounted = false;
    };
  }, [isOpen, activeTab, repositoryId, workspaceId]);

  if (!isOpen) return null;

  const snapshot = overview?.latest_snapshot;

  // Filtered Files
  const filteredFiles = files.filter((f) => {
    const matchesSearch = f.path.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesLang = selectedLanguage === "all" || f.language === selectedLanguage;
    return matchesSearch && matchesLang;
  });

  // Filtered Symbols
  const filteredSymbols = symbols.filter((s) => {
    const matchesSearch =
      s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      s.file_path.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesType = selectedSymbolType === "all" || s.symbol_type === selectedSymbolType;
    return matchesSearch && matchesType;
  });

  // Filtered Dependencies
  const filteredDependencies = dependencies.filter((d) => {
    const matchesSearch =
      d.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      d.file_path.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesSearch;
  });

  return (
    <div
      data-testid="repository-intelligence-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4 animate-in fade-in duration-150"
    >
      <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-4xl w-full max-h-[88vh] flex flex-col overflow-hidden">
        {/* Modal Header */}
        <div className="p-4 px-6 border-b border-slate-100 flex items-center justify-between bg-slate-50/70">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-indigo-600 text-white flex items-center justify-center shadow-xs">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-slate-900">{repositoryName}</h2>
                <Badge variant="outline" className="text-[10px] font-mono">
                  Repository Intelligence
                </Badge>
              </div>
              <p className="text-xs text-slate-500 mt-0.5">
                Structural indexing, Tree-sitter code symbols, and package dependencies
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {onReindex && (
              <Button
                size="sm"
                variant="outline"
                onClick={onReindex}
                disabled={isIndexing}
                className="text-xs h-8 border-indigo-200 text-indigo-700 hover:bg-indigo-50"
              >
                {isIndexing ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                    Indexing...
                  </>
                ) : (
                  <>Re-Index Snapshot</>
                )}
              </Button>
            )}
            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-200/50 rounded-lg transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="px-6 border-b border-slate-200/80 bg-white flex items-center gap-6 text-xs font-medium text-slate-600">
          <button
            onClick={() => {
              setActiveTab("overview");
              setSearchQuery("");
            }}
            className={`py-3 flex items-center gap-1.5 border-b-2 font-medium transition-colors ${
              activeTab === "overview"
                ? "border-indigo-600 text-indigo-600 font-semibold"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            <Sparkles className="h-3.5 w-3.5" />
            Overview
          </button>
          <button
            onClick={() => {
              setActiveTab("files");
              setSearchQuery("");
            }}
            className={`py-3 flex items-center gap-1.5 border-b-2 font-medium transition-colors ${
              activeTab === "files"
                ? "border-indigo-600 text-indigo-600 font-semibold"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            <FileCode className="h-3.5 w-3.5" />
            Files ({snapshot?.total_files ?? 0})
          </button>
          <button
            onClick={() => {
              setActiveTab("symbols");
              setSearchQuery("");
            }}
            className={`py-3 flex items-center gap-1.5 border-b-2 font-medium transition-colors ${
              activeTab === "symbols"
                ? "border-indigo-600 text-indigo-600 font-semibold"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            <Layers className="h-3.5 w-3.5" />
            Symbols ({snapshot?.total_symbols ?? 0})
          </button>
          <button
            onClick={() => {
              setActiveTab("dependencies");
              setSearchQuery("");
            }}
            className={`py-3 flex items-center gap-1.5 border-b-2 font-medium transition-colors ${
              activeTab === "dependencies"
                ? "border-indigo-600 text-indigo-600 font-semibold"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            <Package className="h-3.5 w-3.5" />
            Dependencies ({snapshot?.total_dependencies ?? 0})
          </button>
        </div>

        {/* Tab Content Body */}
        <div className="flex-1 overflow-y-auto p-6 bg-slate-50/40">
          {/* TAB 1: OVERVIEW */}
          {activeTab === "overview" && (
            <div className="space-y-6">
              {!snapshot ? (
                <div className="p-8 text-center bg-white rounded-xl border border-slate-200">
                  <Sparkles className="h-8 w-8 text-indigo-400 mx-auto mb-2" />
                  <h3 className="text-sm font-semibold text-slate-800">No snapshot indexed yet</h3>
                  <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
                    Click &quot;Index Repository&quot; to parse code symbols, manifests, and file hierarchies.
                  </p>
                </div>
              ) : (
                <>
                  {/* Top Stats Cards */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div className="bg-white p-3.5 rounded-xl border border-slate-200 shadow-xs">
                      <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
                        Total Files
                      </span>
                      <span className="text-xl font-bold text-slate-900 mt-1 block">
                        {snapshot.total_files}
                      </span>
                      <span className="text-[11px] text-slate-500 font-mono">
                        {(snapshot.total_bytes / 1024).toFixed(1)} KB indexed
                      </span>
                    </div>

                    <div className="bg-white p-3.5 rounded-xl border border-slate-200 shadow-xs">
                      <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
                        Lines of Code
                      </span>
                      <span className="text-xl font-bold text-slate-900 mt-1 block">
                        {snapshot.total_lines.toLocaleString()}
                      </span>
                      <span className="text-[11px] text-emerald-600 font-medium">Source lines</span>
                    </div>

                    <div className="bg-white p-3.5 rounded-xl border border-slate-200 shadow-xs">
                      <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
                        Code Symbols
                      </span>
                      <span className="text-xl font-bold text-slate-900 mt-1 block">
                        {snapshot.total_symbols}
                      </span>
                      <span className="text-[11px] text-indigo-600 font-medium">
                        AST Extracted
                      </span>
                    </div>

                    <div className="bg-white p-3.5 rounded-xl border border-slate-200 shadow-xs">
                      <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
                        Dependencies
                      </span>
                      <span className="text-xl font-bold text-slate-900 mt-1 block">
                        {snapshot.total_dependencies}
                      </span>
                      <span className="text-[11px] text-amber-600 font-medium">
                        Packages & Imports
                      </span>
                    </div>
                  </div>

                  {/* Commit SHA & Branch Metadata */}
                  <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs flex flex-wrap items-center justify-between gap-3 text-xs">
                    <div className="flex items-center gap-3">
                      <GitCommit className="h-4 w-4 text-slate-400" />
                      <div>
                        <span className="text-slate-500">Indexed Commit: </span>
                        <code className="bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded-md font-mono text-[11px]">
                          {snapshot.commit_sha.substring(0, 10)}
                        </code>
                        <span className="text-slate-400 text-[11px] ml-2 font-mono">
                          ({snapshot.branch})
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 text-slate-500 text-[11px]">
                      <Clock className="h-3.5 w-3.5" />
                      <span>{new Date(snapshot.created_at).toLocaleString()}</span>
                    </div>
                  </div>

                  {/* Languages Distribution */}
                  <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs space-y-3">
                    <h4 className="text-xs font-semibold text-slate-800 uppercase tracking-wider">
                      Language Distribution
                    </h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {Object.entries(snapshot.languages_summary || {}).map(([lang, stat]) => (
                        <div
                          key={lang}
                          className="flex items-center justify-between p-2.5 rounded-lg bg-slate-50 border border-slate-100 text-xs"
                        >
                          <div className="flex items-center gap-2">
                            <span className="h-2.5 w-2.5 rounded-full bg-indigo-500" />
                            <span className="font-semibold text-slate-800">{lang}</span>
                          </div>
                          <div className="text-right font-mono text-[11px] text-slate-500">
                            <span>{stat.files} files</span>
                            <span className="text-slate-300 mx-1.5">|</span>
                            <span>{stat.lines.toLocaleString()} lines</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Entry Point Candidates */}
                  {snapshot.entry_points && snapshot.entry_points.length > 0 && (
                    <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs space-y-2">
                      <h4 className="text-xs font-semibold text-slate-800 uppercase tracking-wider">
                        Detected Entry Points
                      </h4>
                      <div className="flex flex-wrap gap-2">
                        {snapshot.entry_points.map((ep) => (
                          <span
                            key={ep}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-800 border border-emerald-200 text-xs font-mono"
                          >
                            <CheckCircle2 className="h-3 w-3 text-emerald-600" />
                            {ep}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* TAB 2: FILES */}
          {activeTab === "files" && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-slate-400" />
                  <Input
                    placeholder="Search files by path (e.g. app/main.py)..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-9 h-8 text-xs bg-white"
                  />
                </div>
                <select
                  value={selectedLanguage}
                  onChange={(e) => setSelectedLanguage(e.target.value)}
                  className="h-8 text-xs bg-white border border-slate-200 rounded-md px-2.5 text-slate-700"
                >
                  <option value="all">All Languages</option>
                  {Object.keys(snapshot?.languages_summary || {}).map((lang) => (
                    <option key={lang} value={lang}>
                      {lang}
                    </option>
                  ))}
                </select>
              </div>

              {loadingTab ? (
                <div className="p-8 text-center">
                  <Loader2 className="h-6 w-6 animate-spin text-indigo-600 mx-auto" />
                  <p className="text-xs text-slate-500 mt-2">Loading repository files...</p>
                </div>
              ) : filteredFiles.length === 0 ? (
                <div className="p-8 text-center bg-white rounded-xl border border-slate-200 text-xs text-slate-500">
                  No files found matching criteria.
                </div>
              ) : (
                <div className="bg-white rounded-xl border border-slate-200 overflow-hidden divide-y divide-slate-100">
                  {filteredFiles.map((f) => (
                    <div
                      key={f.id}
                      className="p-3 flex items-center justify-between text-xs hover:bg-slate-50 transition-colors"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <FileCode className="h-4 w-4 text-slate-400 shrink-0" />
                        <span className="font-mono text-slate-800 truncate font-medium">
                          {f.path}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 shrink-0 font-mono text-[11px] text-slate-500">
                        {f.language && (
                          <Badge variant="outline" className="text-[10px] py-0 px-1.5 font-normal">
                            {f.language}
                          </Badge>
                        )}
                        <span>{f.line_count} lines</span>
                        <span>{(f.size_bytes / 1024).toFixed(1)} KB</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* TAB 3: SYMBOLS */}
          {activeTab === "symbols" && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-slate-400" />
                  <Input
                    placeholder="Search symbols by name or file..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-9 h-8 text-xs bg-white"
                  />
                </div>
                <select
                  value={selectedSymbolType}
                  onChange={(e) => setSelectedSymbolType(e.target.value)}
                  className="h-8 text-xs bg-white border border-slate-200 rounded-md px-2.5 text-slate-700"
                >
                  <option value="all">All Symbol Types</option>
                  <option value="function">Function</option>
                  <option value="class">Class</option>
                  <option value="method">Method</option>
                  <option value="interface">Interface</option>
                </select>
              </div>

              {loadingTab ? (
                <div className="p-8 text-center">
                  <Loader2 className="h-6 w-6 animate-spin text-indigo-600 mx-auto" />
                  <p className="text-xs text-slate-500 mt-2">Extracting AST code symbols...</p>
                </div>
              ) : filteredSymbols.length === 0 ? (
                <div className="p-8 text-center bg-white rounded-xl border border-slate-200 text-xs text-slate-500">
                  No code symbols found matching criteria.
                </div>
              ) : (
                <div className="bg-white rounded-xl border border-slate-200 overflow-hidden divide-y divide-slate-100">
                  {filteredSymbols.map((s) => (
                    <div
                      key={s.id}
                      className="p-3 flex items-start justify-between text-xs hover:bg-slate-50 transition-colors"
                    >
                      <div className="min-w-0 pr-4">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-slate-900 font-mono">{s.name}</span>
                          <Badge
                            variant="secondary"
                            className="text-[10px] py-0 px-1.5 font-mono capitalize"
                          >
                            {s.symbol_type}
                          </Badge>
                          {s.parent_symbol_name && (
                            <span className="text-[11px] text-slate-400 font-mono">
                              in {s.parent_symbol_name}
                            </span>
                          )}
                        </div>
                        {s.signature && (
                          <div className="mt-1 font-mono text-[11px] text-slate-600 truncate bg-slate-50 p-1 rounded-sm border border-slate-100">
                            {s.signature}
                          </div>
                        )}
                        <div className="text-[11px] text-slate-400 font-mono mt-1">
                          {s.file_path}:{s.start_line}–{s.end_line}
                        </div>
                      </div>

                      <Badge variant="outline" className="text-[10px] font-mono shrink-0">
                        {s.language}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* TAB 4: DEPENDENCIES */}
          {activeTab === "dependencies" && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-slate-400" />
                  <Input
                    placeholder="Search package dependencies or imports..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-9 h-8 text-xs bg-white"
                  />
                </div>
              </div>

              {loadingTab ? (
                <div className="p-8 text-center">
                  <Loader2 className="h-6 w-6 animate-spin text-indigo-600 mx-auto" />
                  <p className="text-xs text-slate-500 mt-2">Loading parsed dependencies...</p>
                </div>
              ) : filteredDependencies.length === 0 ? (
                <div className="p-8 text-center bg-white rounded-xl border border-slate-200 text-xs text-slate-500">
                  No dependencies found matching criteria.
                </div>
              ) : (
                <div className="bg-white rounded-xl border border-slate-200 overflow-hidden divide-y divide-slate-100">
                  {filteredDependencies.map((d) => (
                    <div
                      key={d.id}
                      className="p-3 flex items-center justify-between text-xs hover:bg-slate-50 transition-colors"
                    >
                      <div className="min-w-0 pr-4">
                        <div className="flex items-center gap-2">
                          <Package className="h-3.5 w-3.5 text-amber-500 shrink-0" />
                          <span className="font-semibold text-slate-900 font-mono">{d.name}</span>
                          {d.version_spec && (
                            <Badge
                              variant="outline"
                              className="text-[10px] py-0 px-1.5 font-mono text-slate-600"
                            >
                              {d.version_spec}
                            </Badge>
                          )}
                        </div>
                        <p className="text-[11px] text-slate-400 font-mono mt-0.5 truncate">
                          declared in {d.file_path}
                        </p>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        {d.package_manager && (
                          <Badge
                            variant="secondary"
                            className="text-[10px] py-0 px-1.5 font-mono uppercase"
                          >
                            {d.package_manager}
                          </Badge>
                        )}
                        <Badge
                          variant="outline"
                          className="text-[10px] py-0 px-1.5 font-mono capitalize"
                        >
                          {d.dependency_type}
                        </Badge>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="p-3.5 border-t border-slate-100 bg-slate-50 flex items-center justify-between text-xs text-slate-500">
          <span className="font-mono text-[11px]">
            {snapshot ? `Snapshot ID: ${snapshot.id.substring(0, 8)}...` : "No active snapshot"}
          </span>
          <Button variant="outline" size="sm" onClick={onClose} className="text-xs h-7.5">
            Close
          </Button>
        </div>
      </div>
    </div>
  );
}
