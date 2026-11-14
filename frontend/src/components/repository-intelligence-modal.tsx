"use client";

import * as React from "react";
import {
  CodeSymbolItem,
  FileDependencyItem,
  GraphIndexStatusResponse,
  GraphNode,
  ImpactPreviewResponse,
  RepositoryFileItem,
  RepositoryIntelligenceOverview,
  SemanticIndexStatusResponse,
  SemanticSearchResultItem,
  SubgraphResponse,
  SupportedLanguagesResponse,
  executeSemanticSearch,
  fetchGraphIndexStatus,
  fetchImpactPreview,
  fetchRepositoryDependencies,
  fetchRepositoryFiles,
  fetchRepositoryGraph,
  fetchRepositorySymbols,
  fetchSemanticIndexStatus,
  fetchSupportedLanguages,
  triggerGraphIndexing,
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
  Globe2,
  BrainCircuit,
  Network,
  AlertTriangle,
  RefreshCw,
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
  const [activeTab, setActiveTab] = React.useState<
    "overview" | "semantic" | "graph" | "files" | "symbols" | "dependencies" | "languages"
  >("overview");
  const [supportedLangs, setSupportedLangs] = React.useState<SupportedLanguagesResponse | null>(null);

  // Tab Data States
  const [files, setFiles] = React.useState<RepositoryFileItem[]>([]);
  const [symbols, setSymbols] = React.useState<CodeSymbolItem[]>([]);
  const [dependencies, setDependencies] = React.useState<FileDependencyItem[]>([]);

  // Knowledge Graph States
  const [graphSubgraph, setGraphSubgraph] = React.useState<SubgraphResponse | null>(null);
  const [graphStatus, setGraphStatus] = React.useState<GraphIndexStatusResponse | null>(null);
  const [selectedGraphNode, setSelectedGraphNode] = React.useState<GraphNode | null>(null);
  const [impactPreview, setImpactPreview] = React.useState<ImpactPreviewResponse | null>(null);
  const [isIndexingGraph, setIsIndexingGraph] = React.useState(false);
  const [isLoadingImpact, setIsLoadingImpact] = React.useState(false);
  const [graphSearch, setGraphSearch] = React.useState("");
  const [graphTypeFilter, setGraphTypeFilter] = React.useState<string>("all");

  // Semantic Search States
  const [semanticQuery, setSemanticQuery] = React.useState("");
  const [semanticResults, setSemanticResults] = React.useState<SemanticSearchResultItem[]>([]);
  const [semanticStatus, setSemanticStatus] = React.useState<SemanticIndexStatusResponse | null>(null);
  const [isSearchingSemantic, setIsSearchingSemantic] = React.useState(false);
  const [hasSearchedSemantic, setHasSearchedSemantic] = React.useState(false);
  const [selectedChunk, setSelectedChunk] = React.useState<SemanticSearchResultItem | null>(null);

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
      if (activeTab === "semantic") {
        const res = await fetchSemanticIndexStatus(repositoryId, workspaceId);
        if (isMounted && res) setSemanticStatus(res);
      } else if (activeTab === "graph") {
        const snapId = overview?.latest_snapshot?.id;
        const [gStatus, gSub] = await Promise.all([
          fetchGraphIndexStatus(repositoryId, workspaceId, snapId),
          fetchRepositoryGraph(repositoryId, workspaceId, { snapshot_id: snapId, limit: 150 }),
        ]);
        if (isMounted) {
          if (gStatus) setGraphStatus(gStatus);
          if (gSub) setGraphSubgraph(gSub);
        }
      } else if (activeTab === "files") {
        const res = await fetchRepositoryFiles(repositoryId, workspaceId, { limit: 100 });
        if (isMounted && res) setFiles(res.files);
      } else if (activeTab === "symbols") {
        const res = await fetchRepositorySymbols(repositoryId, workspaceId, { limit: 150 });
        if (isMounted && res) setSymbols(res.symbols);
      } else if (activeTab === "dependencies") {
        const res = await fetchRepositoryDependencies(repositoryId, workspaceId, { limit: 150 });
        if (isMounted && res) setDependencies(res.dependencies);
      } else if (activeTab === "languages") {
        const res = await fetchSupportedLanguages();
        if (isMounted && res) setSupportedLangs(res);
      }
      if (isMounted) setLoadingTab(false);
    }

    loadData();
    return () => {
      isMounted = false;
    };
  }, [isOpen, activeTab, repositoryId, workspaceId, overview?.latest_snapshot?.id]);

  const handleSemanticSearch = async (queryToRun?: string) => {
    const q = (queryToRun !== undefined ? queryToRun : semanticQuery).trim();
    if (!q || !repositoryId || !workspaceId) return;

    setIsSearchingSemantic(true);
    setHasSearchedSemantic(true);
    try {
      const res = await executeSemanticSearch(repositoryId, workspaceId, q, {
        language: selectedLanguage !== "all" ? selectedLanguage : undefined,
        symbol_type: selectedSymbolType !== "all" ? selectedSymbolType : undefined,
        limit: 15,
      });
      if (res && res.results) {
        setSemanticResults(res.results);
      } else {
        setSemanticResults([]);
      }
    } catch {
      setSemanticResults([]);
    } finally {
      setIsSearchingSemantic(false);
    }
  };

  const handleTriggerGraphIndexing = async () => {
    if (!overview?.latest_snapshot?.id || isIndexingGraph) return;
    setIsIndexingGraph(true);
    try {
      const res = await triggerGraphIndexing(
        repositoryId,
        workspaceId,
        overview.latest_snapshot.id,
        true,
      );
      if (res) {
        setGraphStatus(res);
        const sub = await fetchRepositoryGraph(repositoryId, workspaceId, {
          snapshot_id: overview.latest_snapshot.id,
          limit: 150,
        });
        if (sub) setGraphSubgraph(sub);
      }
    } finally {
      setIsIndexingGraph(false);
    }
  };

  const handleAnalyzeImpact = async (node: GraphNode) => {
    if (!overview?.latest_snapshot?.id || isLoadingImpact) return;
    setIsLoadingImpact(true);
    try {
      const res = await fetchImpactPreview(repositoryId, workspaceId, {
        snapshot_id: overview.latest_snapshot.id,
        file_path: node.properties.file_path,
        symbol_name: node.properties.name,
        symbol_id: node.id,
        max_depth: 3,
      });
      if (res) {
        setImpactPreview(res);
      }
    } finally {
      setIsLoadingImpact(false);
    }
  };

  if (!isOpen) return null;

  const snapshot = overview?.latest_snapshot;

  // Filtered Graph Nodes
  const filteredGraphNodes = (graphSubgraph?.nodes || []).filter((node) => {
    const matchesSearch =
      graphSearch === "" ||
      node.id.toLowerCase().includes(graphSearch.toLowerCase()) ||
      (node.properties.name && node.properties.name.toLowerCase().includes(graphSearch.toLowerCase())) ||
      (node.properties.file_path && node.properties.file_path.toLowerCase().includes(graphSearch.toLowerCase()));
    const matchesType = graphTypeFilter === "all" || node.label === graphTypeFilter;
    return matchesSearch && matchesType;
  });

  const getNodeBadgeStyle = (label: string) => {
    switch (label) {
      case "APIEndpoint":
        return "bg-emerald-50 text-emerald-700 border-emerald-200";
      case "DatabaseTable":
      case "DatabaseModel":
        return "bg-amber-50 text-amber-700 border-amber-200";
      case "TestCase":
        return "bg-purple-50 text-purple-700 border-purple-200";
      case "Class":
      case "Interface":
        return "bg-blue-50 text-blue-700 border-blue-200";
      case "Function":
      case "Method":
        return "bg-indigo-50 text-indigo-700 border-indigo-200";
      default:
        return "bg-slate-50 text-slate-700 border-slate-200";
    }
  };

  const getRiskBadgeStyle = (risk: string) => {
    switch (risk) {
      case "CRITICAL":
        return "bg-rose-500 text-white";
      case "HIGH":
        return "bg-orange-500 text-white";
      case "MEDIUM":
        return "bg-amber-500 text-white";
      default:
        return "bg-emerald-500 text-white";
    }
  };

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
            className={`py-3 flex items-center gap-1.5 border-b-2 font-medium transition-colors ${activeTab === "overview"
              ? "border-indigo-600 text-indigo-600 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
          >
            <Sparkles className="h-3.5 w-3.5" />
            Overview
          </button>
          <button
            data-testid="tab-semantic-search"
            onClick={() => {
              setActiveTab("semantic");
              setSearchQuery("");
            }}
            className={`py-3 flex items-center gap-1.5 border-b-2 font-medium transition-colors ${
              activeTab === "semantic"
                ? "border-indigo-600 text-indigo-600 font-semibold"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            <BrainCircuit className="h-3.5 w-3.5 text-indigo-600" />
            Semantic Search
            <Badge
              variant="secondary"
              className="text-[9px] py-0 px-1 font-mono bg-indigo-50 text-indigo-700 border-indigo-200"
            >
              AI Vector
            </Badge>
          </button>
          <button
            data-testid="tab-knowledge-graph"
            onClick={() => {
              setActiveTab("graph");
              setSearchQuery("");
            }}
            className={`py-3 flex items-center gap-1.5 border-b-2 font-medium transition-colors ${
              activeTab === "graph"
                ? "border-indigo-600 text-indigo-600 font-semibold"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            <Network className="h-3.5 w-3.5 text-purple-600" />
            Knowledge Graph
            <Badge
              variant="secondary"
              className="text-[9px] py-0 px-1 font-mono bg-purple-50 text-purple-700 border-purple-200"
            >
              Neo4j
            </Badge>
          </button>
          <button
            onClick={() => {
              setActiveTab("files");
              setSearchQuery("");
            }}
            className={`py-3 flex items-center gap-1.5 border-b-2 font-medium transition-colors ${activeTab === "files"
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
            className={`py-3 flex items-center gap-1.5 border-b-2 font-medium transition-colors ${activeTab === "symbols"
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
            className={`py-3 flex items-center gap-1.5 border-b-2 font-medium transition-colors ${activeTab === "dependencies"
              ? "border-indigo-600 text-indigo-600 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
          >
            <Package className="h-3.5 w-3.5" />
            Dependencies ({snapshot?.total_dependencies ?? 0})
          </button>
          <button
            onClick={() => {
              setActiveTab("languages");
              setSearchQuery("");
            }}
            className={`py-3 flex items-center gap-1.5 border-b-2 font-medium transition-colors ${activeTab === "languages"
              ? "border-indigo-600 text-indigo-600 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
          >
            <Globe2 className="h-3.5 w-3.5" />
            Registry ({supportedLangs?.total_supported ?? "40+"})
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

                  {/* Detected Frameworks */}
                  {(overview?.detected_frameworks ||
                    overview?.latest_snapshot?.detected_frameworks) &&
                    (overview?.detected_frameworks ||
                      overview?.latest_snapshot?.detected_frameworks ||
                      []).length > 0 && (
                      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs space-y-2">
                        <h4 className="text-xs font-semibold text-slate-800 uppercase tracking-wider">
                          Recognized Frameworks & Technologies
                        </h4>
                        <div className="flex flex-wrap gap-2">
                          {(
                            overview?.detected_frameworks ||
                            overview?.latest_snapshot?.detected_frameworks ||
                            []
                          ).map((fw) => (
                            <Badge
                              key={fw}
                              variant="secondary"
                              className="text-xs bg-indigo-50 text-indigo-800 border-indigo-200 font-medium py-1 px-2.5"
                            >
                              <Sparkles className="h-3 w-3 mr-1 text-indigo-600" />
                              {fw}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}

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

          {/* TAB 2: SEMANTIC CODE SEARCH & RETRIEVAL */}
          {activeTab === "semantic" && (
            <div className="space-y-4" data-testid="semantic-search-panel">
              {/* Header & Status Banner */}
              <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-2xs space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="text-xs font-semibold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
                        <BrainCircuit className="h-4 w-4 text-indigo-600" />
                        Semantic Code Intelligence & Retrieval
                      </h4>
                      <Badge
                        variant="outline"
                        className="text-[10px] font-mono text-indigo-700 bg-indigo-50 border-indigo-200"
                      >
                        Hybrid Vector + AST
                      </Badge>
                    </div>
                    <p className="text-xs text-slate-500 mt-1">
                      Query repository functions, classes, and logic using natural language.
                    </p>
                  </div>
                  {semanticStatus && (
                    <div className="flex items-center gap-2 text-[11px] font-mono text-slate-600 bg-slate-50 px-2.5 py-1 rounded-lg border border-slate-200">
                      <span className="h-2 w-2 rounded-full bg-emerald-500" />
                      <span>{semanticStatus.model_name.split("/").pop()}</span>
                      <span className="text-slate-400">•</span>
                      <span>{semanticStatus.total_chunks} Chunks Indexed</span>
                    </div>
                  )}
                </div>

                {/* Natural Language Search Input */}
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    handleSemanticSearch();
                  }}
                  className="flex gap-2"
                >
                  <div className="relative flex-1">
                    <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                    <Input
                      data-testid="semantic-search-input"
                      type="text"
                      placeholder="Ask where logic is implemented (e.g. 'Where is user authentication handled?')..."
                      value={semanticQuery}
                      onChange={(e) => setSemanticQuery(e.target.value)}
                      className="pl-9 text-xs h-9 bg-slate-50/50 border-slate-200 focus-visible:ring-indigo-500"
                    />
                  </div>
                  <Button
                    data-testid="semantic-search-button"
                    type="submit"
                    size="sm"
                    disabled={isSearchingSemantic || !semanticQuery.trim()}
                    className="h-9 px-4 text-xs bg-indigo-600 hover:bg-indigo-700 text-white font-medium"
                  >
                    {isSearchingSemantic ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                        Retrieving...
                      </>
                    ) : (
                      <>
                        <BrainCircuit className="h-3.5 w-3.5 mr-1.5" />
                        Semantic Search
                      </>
                    )}
                  </Button>
                </form>

                {/* Suggested Natural Language Queries */}
                <div className="flex items-center gap-1.5 flex-wrap pt-1">
                  <span className="text-[11px] text-slate-400 font-medium">Try:</span>
                  {[
                    "Where is user authentication handled?",
                    "Database connection and pool settings",
                    "GitHub OAuth redirect and callback",
                    "Repository intelligence indexing job",
                  ].map((chip) => (
                    <button
                      key={chip}
                      type="button"
                      onClick={() => {
                        setSemanticQuery(chip);
                        handleSemanticSearch(chip);
                      }}
                      className="text-[11px] font-mono text-slate-600 bg-slate-100 hover:bg-indigo-50 hover:text-indigo-700 hover:border-indigo-200 border border-slate-200/80 px-2 py-0.5 rounded-md transition-colors"
                    >
                      {chip}
                    </button>
                  ))}
                </div>
              </div>

              {/* Filters */}
              <div className="flex items-center justify-between gap-3 text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-slate-500 text-xs font-medium">Filters:</span>
                  <select
                    value={selectedLanguage}
                    onChange={(e) => setSelectedLanguage(e.target.value)}
                    className="h-7.5 px-2.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700"
                  >
                    <option value="all">All Languages</option>
                    {Object.keys(snapshot?.languages_summary || {}).map((lang) => (
                      <option key={lang} value={lang}>
                        {lang}
                      </option>
                    ))}
                  </select>
                  <select
                    value={selectedSymbolType}
                    onChange={(e) => setSelectedSymbolType(e.target.value)}
                    className="h-7.5 px-2.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700"
                  >
                    <option value="all">All Symbol Types</option>
                    <option value="function">Function</option>
                    <option value="method">Method</option>
                    <option value="class">Class</option>
                    <option value="interface">Interface</option>
                    <option value="struct">Struct</option>
                    <option value="file_summary">File Overview</option>
                  </select>
                </div>

                {hasSearchedSemantic && (
                  <span className="text-xs text-slate-500 font-medium">
                    Found <strong className="text-slate-800">{semanticResults.length}</strong> matching chunks
                  </span>
                )}
              </div>

              {/* Results Container */}
              {isSearchingSemantic ? (
                <div className="p-12 text-center bg-white rounded-xl border border-slate-200">
                  <Loader2 className="h-7 w-7 animate-spin text-indigo-600 mx-auto" />
                  <p className="text-xs font-medium text-slate-700 mt-2">
                    Computing query vector and ranking code chunks...
                  </p>
                  <p className="text-[11px] text-slate-400 mt-1">
                    Executing HNSW cosine similarity and lexical token fusion
                  </p>
                </div>
              ) : hasSearchedSemantic && semanticResults.length === 0 ? (
                <div className="p-8 text-center bg-white rounded-xl border border-slate-200">
                  <Search className="h-6 w-6 text-slate-400 mx-auto mb-2" />
                  <p className="text-xs font-medium text-slate-700">No code chunks matched your query.</p>
                  <p className="text-[11px] text-slate-400 mt-1">
                    Try broadening your search terms or clearing language filters.
                  </p>
                </div>
              ) : semanticResults.length > 0 ? (
                <div className="space-y-3" data-testid="semantic-results-list">
                  {semanticResults.map((result) => {
                    const matchPercent = Math.round(result.similarity_score * 100);
                    return (
                      <div
                        key={result.chunk_id}
                        data-testid="semantic-result-item"
                        className="p-3.5 bg-white rounded-xl border border-slate-200 shadow-2xs hover:border-indigo-300 transition-colors space-y-2.5"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-mono font-semibold text-xs text-indigo-950 truncate">
                                {result.file_path}
                              </span>
                              <span className="text-slate-400 font-mono text-[11px]">
                                L{result.start_line}-L{result.end_line}
                              </span>
                              <Badge
                                variant="outline"
                                className="text-[10px] py-0 px-1.5 font-mono text-slate-600"
                              >
                                {result.language}
                              </Badge>
                              {result.symbol_name && (
                                <Badge
                                  variant="secondary"
                                  className="text-[10px] py-0 px-1.5 font-mono bg-slate-100 text-slate-700"
                                >
                                  {result.symbol_type || "symbol"}: {result.symbol_name}
                                  {result.parent_symbol_name && ` (${result.parent_symbol_name})`}
                                </Badge>
                              )}
                            </div>
                          </div>

                          <div className="flex items-center gap-2 shrink-0">
                            <span
                              className={`text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full border ${
                                matchPercent >= 80
                                  ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                                  : matchPercent >= 60
                                  ? "bg-indigo-50 text-indigo-800 border-indigo-200"
                                  : "bg-slate-50 text-slate-700 border-slate-200"
                              }`}
                            >
                              {matchPercent}% Match
                            </span>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() =>
                                setSelectedChunk(
                                  selectedChunk?.chunk_id === result.chunk_id ? null : result
                                )
                              }
                              className="text-[11px] h-7 px-2 text-indigo-600 hover:text-indigo-700"
                            >
                              {selectedChunk?.chunk_id === result.chunk_id ? "Hide Code" : "Inspect Code"}
                            </Button>
                          </div>
                        </div>

                        {/* Code snippet preview */}
                        <pre className="bg-slate-900 text-slate-100 p-2.5 rounded-lg text-[11px] font-mono overflow-x-auto leading-relaxed max-h-48 border border-slate-800">
                          <code>
                            {selectedChunk?.chunk_id === result.chunk_id
                              ? result.source_code_excerpt
                              : result.source_code_excerpt}
                          </code>
                        </pre>

                        <div className="flex items-center gap-3 text-[10px] text-slate-400 font-mono">
                          <span>Vector Score: {(result.vector_score * 100).toFixed(1)}%</span>
                          <span>•</span>
                          <span>Lexical Score: {(result.lexical_score * 100).toFixed(1)}%</span>
                          <span>•</span>
                          <span>Symbol Score: {(result.symbol_score * 100).toFixed(1)}%</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="p-8 text-center bg-white rounded-xl border border-slate-200">
                  <BrainCircuit className="h-8 w-8 text-indigo-400 mx-auto mb-2" />
                  <p className="text-xs font-semibold text-slate-800">
                    Ask a Question About the Codebase
                  </p>
                  <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto">
                    Type a query above or click one of the suggested prompts to semantically search
                    across classes, functions, and architecture.
                  </p>
                </div>
              )}
            </div>
          )}

          {/* TAB: KNOWLEDGE GRAPH */}
          {activeTab === "graph" && (
            <div className="space-y-4">
              {/* Graph Status Header Banner */}
              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-purple-50 text-purple-600 border border-purple-100">
                    <Network className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-xs font-semibold text-slate-900">
                        Code Knowledge Graph & Relationship Engine
                      </h3>
                      <Badge variant="outline" className="text-[10px] bg-slate-50 border-slate-200 font-mono">
                        Provider: {graphStatus?.provider || "Neo4j / In-Memory"}
                      </Badge>
                    </div>
                    <p className="text-[11px] text-slate-500 mt-0.5">
                      Multi-language AST symbols, callers, imports, inheritance, API endpoints, and database models.
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2 text-xs">
                    <span className="px-2.5 py-1 bg-slate-100 rounded-md font-mono text-slate-700 border border-slate-200">
                      <strong>{graphStatus?.total_nodes ?? graphSubgraph?.total_nodes ?? 0}</strong> Nodes
                    </span>
                    <span className="px-2.5 py-1 bg-slate-100 rounded-md font-mono text-slate-700 border border-slate-200">
                      <strong>{graphStatus?.total_relationships ?? graphSubgraph?.total_edges ?? 0}</strong> Relationships
                    </span>
                  </div>

                  <Button
                    data-testid="index-graph-button"
                    size="sm"
                    onClick={handleTriggerGraphIndexing}
                    disabled={isIndexingGraph || !snapshot?.id}
                    className="h-8 px-3 text-xs bg-purple-600 hover:bg-purple-700 text-white font-medium"
                  >
                    {isIndexingGraph ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                        Indexing Graph...
                      </>
                    ) : (
                      <>
                        <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                        Re-Index Graph
                      </>
                    )}
                  </Button>
                </div>
              </div>

              {/* Search & Type Filter Controls */}
              <div className="flex items-center justify-between gap-3 text-xs">
                <div className="relative flex-1 max-w-sm">
                  <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-400" />
                  <Input
                    type="text"
                    placeholder="Filter graph nodes by name or path..."
                    value={graphSearch}
                    onChange={(e) => setGraphSearch(e.target.value)}
                    className="pl-8 text-xs h-7.5 bg-white border-slate-200"
                  />
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-slate-500 text-xs font-medium">Node Type:</span>
                  <select
                    value={graphTypeFilter}
                    onChange={(e) => setGraphTypeFilter(e.target.value)}
                    className="h-7.5 px-2.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700"
                  >
                    <option value="all">All Types</option>
                    <option value="File">Files</option>
                    <option value="Function">Functions</option>
                    <option value="Method">Methods</option>
                    <option value="Class">Classes</option>
                    <option value="Interface">Interfaces</option>
                    <option value="APIEndpoint">API Endpoints</option>
                    <option value="DatabaseTable">Database Tables</option>
                    <option value="TestCase">Test Cases</option>
                    <option value="ExternalDependency">Dependencies</option>
                  </select>
                </div>
              </div>

              {/* Two-Column Explorer Layout */}
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
                {/* Left Panel: Nodes & Relationships List */}
                <div className="lg:col-span-7 bg-white rounded-xl border border-slate-200 shadow-xs p-3 max-h-[500px] overflow-y-auto space-y-2">
                  {filteredGraphNodes.length === 0 ? (
                    <div className="p-8 text-center text-slate-500 text-xs">
                      {isIndexingGraph ? "Extracting knowledge graph relationships..." : "No graph entities matched your filter."}
                    </div>
                  ) : (
                    filteredGraphNodes.map((node) => {
                      const isSelected = selectedGraphNode?.id === node.id;
                      const incomingEdges = (graphSubgraph?.edges || []).filter((e) => e.target_id === node.id);
                      const outgoingEdges = (graphSubgraph?.edges || []).filter((e) => e.source_id === node.id);

                      return (
                        <div
                          key={node.id}
                          onClick={() => {
                            setSelectedGraphNode(node);
                            setImpactPreview(null);
                          }}
                          className={`p-3 rounded-lg border transition-all cursor-pointer text-xs ${
                            isSelected
                              ? "bg-purple-50/60 border-purple-300 ring-1 ring-purple-400"
                              : "bg-slate-50/50 hover:bg-slate-100/70 border-slate-200/80"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <Badge variant="outline" className={`text-[10px] font-mono ${getNodeBadgeStyle(node.label)}`}>
                                {node.label}
                              </Badge>
                              <span className="font-semibold text-slate-900 font-mono">
                                {node.properties.name || node.properties.table_name || node.properties.path || node.id}
                              </span>
                            </div>
                            <div className="flex items-center gap-1.5 text-[10px] text-slate-500">
                              {incomingEdges.length > 0 && (
                                <span className="bg-white px-1.5 py-0.5 rounded border border-slate-200 font-mono">
                                  {incomingEdges.length} in
                                </span>
                              )}
                              {outgoingEdges.length > 0 && (
                                <span className="bg-white px-1.5 py-0.5 rounded border border-slate-200 font-mono">
                                  {outgoingEdges.length} out
                                </span>
                              )}
                            </div>
                          </div>

                          {node.properties.file_path && (
                            <div className="mt-1 text-[11px] text-slate-500 font-mono truncate">
                              {node.properties.file_path}
                              {node.properties.start_line && `:${node.properties.start_line}`}
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>

                {/* Right Panel: Interactive Node Inspector & Blast Radius Impact Preview */}
                <div className="lg:col-span-5 bg-white rounded-xl border border-slate-200 shadow-xs p-4 max-h-[500px] overflow-y-auto space-y-4">
                  {!selectedGraphNode ? (
                    <div className="p-8 text-center text-slate-400 text-xs">
                      <Network className="h-8 w-8 text-slate-300 mx-auto mb-2" />
                      <p>Select any node on the left to inspect code relationships, callers, and blast radius impact.</p>
                    </div>
                  ) : (
                    <>
                      {/* Node Details Header */}
                      <div className="border-b border-slate-100 pb-3">
                        <div className="flex items-center justify-between gap-2">
                          <Badge variant="outline" className={`text-[10px] font-mono ${getNodeBadgeStyle(selectedGraphNode.label)}`}>
                            {selectedGraphNode.label}
                          </Badge>
                          <Button
                            size="sm"
                            data-testid="analyze-impact-button"
                            onClick={() => handleAnalyzeImpact(selectedGraphNode)}
                            disabled={isLoadingImpact}
                            className="h-7 px-2.5 text-xs bg-indigo-600 hover:bg-indigo-700 text-white font-medium"
                          >
                            {isLoadingImpact ? (
                              <>
                                <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                                Analyzing...
                              </>
                            ) : (
                              <>
                                <AlertTriangle className="h-3 w-3 mr-1" />
                                Blast Radius Preview
                              </>
                            )}
                          </Button>
                        </div>
                        <h4 className="text-sm font-bold text-slate-900 mt-2 font-mono">
                          {selectedGraphNode.properties.name || selectedGraphNode.properties.table_name || selectedGraphNode.properties.path || selectedGraphNode.id}
                        </h4>
                        {selectedGraphNode.properties.file_path && (
                          <p className="text-[11px] text-slate-500 font-mono mt-0.5">
                            {selectedGraphNode.properties.file_path}
                            {selectedGraphNode.properties.start_line && ` (lines ${selectedGraphNode.properties.start_line}-${selectedGraphNode.properties.end_line})`}
                          </p>
                        )}
                        {selectedGraphNode.properties.signature && (
                          <pre className="mt-2 text-[10px] bg-slate-900 text-slate-100 p-2 rounded-md overflow-x-auto font-mono">
                            {selectedGraphNode.properties.signature}
                          </pre>
                        )}
                      </div>

                      {/* Impact Preview Section if calculated */}
                      {impactPreview && (
                        <div className="p-3 rounded-lg border border-indigo-200 bg-indigo-50/40 space-y-2 text-xs">
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-slate-800 flex items-center gap-1.5">
                              <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
                              Blast Radius & Structural Exposure Score
                            </span>
                            <Badge className={`text-[10px] ${getRiskBadgeStyle(impactPreview.risk_level)}`}>
                              {impactPreview.risk_level} ({impactPreview.risk_score}/100)
                            </Badge>
                          </div>
                          <p className="text-[10px] text-slate-500 leading-tight">
                            Heuristic structural exposure metric based on graph topology (callers, dependencies, API exposure). Not a statistical regression prediction.
                          </p>

                          <ul className="space-y-1 text-[11px] text-slate-700 list-disc list-inside">
                            {impactPreview.reasons.map((r, idx) => (
                              <li key={idx}>{r}</li>
                            ))}
                          </ul>

                          {impactPreview.affected_endpoints.length > 0 && (
                            <div className="pt-1">
                              <span className="text-[11px] font-semibold text-emerald-800 block">
                                Affected API Endpoints ({impactPreview.affected_endpoints.length})
                              </span>
                              <div className="space-y-1 mt-1">
                                {impactPreview.affected_endpoints.map((ep, idx) => (
                                  <div key={idx} className="text-[10px] font-mono bg-white p-1 rounded border border-emerald-200 text-emerald-900">
                                    {ep.name}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {impactPreview.affected_tests.length > 0 && (
                            <div className="pt-1">
                              <span className="text-[11px] font-semibold text-purple-800 block">
                                Recommended Tests to Run ({impactPreview.affected_tests.length})
                              </span>
                              <div className="space-y-1 mt-1">
                                {impactPreview.affected_tests.map((tc, idx) => (
                                  <div key={idx} className="text-[10px] font-mono bg-white p-1 rounded border border-purple-200 text-purple-900">
                                    {tc.name}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Direct Relationships */}
                      <div className="space-y-2 text-xs">
                        <span className="font-semibold text-slate-800 block">Direct Graph Relationships</span>
                        <div className="space-y-1">
                          {(graphSubgraph?.edges || [])
                            .filter((e) => e.source_id === selectedGraphNode.id || e.target_id === selectedGraphNode.id)
                            .map((e, idx) => {
                              const isOut = e.source_id === selectedGraphNode.id;
                              const otherId = isOut ? e.target_id : e.source_id;
                              return (
                                <div key={idx} className="p-2 rounded bg-slate-50 border border-slate-200/80 flex items-center justify-between text-[11px]">
                                  <div className="flex items-center gap-1.5 font-mono">
                                    <Badge variant="secondary" className="text-[9px] px-1 py-0">
                                      {e.type}
                                    </Badge>
                                    <span className="text-slate-600 truncate max-w-[180px]">{otherId}</span>
                                  </div>
                                  <span className="text-[10px] text-slate-400 font-mono">
                                    {isOut ? "outgoing" : "incoming"}
                                  </span>
                                </div>
                              );
                            })}
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: FILES */}
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

          {/* TAB 5: SUPPORTED LANGUAGES REGISTRY */}
          {activeTab === "languages" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-xs font-semibold text-slate-800 uppercase tracking-wider">
                    Universal Parser Registry
                  </h4>
                  <p className="text-xs text-slate-500 mt-0.5">
                    Multi-language AST grammar engines verified and active in Orchestrix backend.
                  </p>
                </div>
                <Badge variant="outline" className="text-xs font-mono">
                  {supportedLangs?.total_supported ?? 40} Languages Active
                </Badge>
              </div>

              {loadingTab ? (
                <div className="p-8 text-center">
                  <Loader2 className="h-6 w-6 animate-spin text-indigo-600 mx-auto" />
                  <p className="text-xs text-slate-500 mt-2">Loading registry capabilities...</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                  {(supportedLangs?.languages || []).map((lang) => (
                    <div
                      key={lang.name}
                      className="p-3 bg-white rounded-xl border border-slate-200/90 shadow-2xs space-y-1.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-xs text-slate-900">{lang.name}</span>
                        {lang.available ? (
                          <span className="inline-flex items-center text-[10px] text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full font-medium border border-emerald-200">
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 mr-1" />
                            Ready
                          </span>
                        ) : (
                          <span className="inline-flex items-center text-[10px] text-slate-500 bg-slate-100 px-2 py-0.5 rounded-full font-medium">
                            Fallback
                          </span>
                        )}
                      </div>
                      <p className="text-[10px] font-mono text-slate-400 truncate">
                        {lang.package_name}
                      </p>
                      <div className="flex flex-wrap gap-1 pt-1">
                        {lang.extensions.slice(0, 4).map((ext) => (
                          <span
                            key={ext}
                            className="text-[10px] font-mono text-slate-600 bg-slate-50 px-1.5 py-0.5 rounded border border-slate-100"
                          >
                            {ext}
                          </span>
                        ))}
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
