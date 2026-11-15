"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { AgentMemoryContext } from "@/components/shared/agent-memory-context";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Code2,
  FileCode,
  Flame,
  FolderGit2,
  Layers,
  Loader2,
  Play,
  Shield,
  ShieldCheck,
  Terminal,
} from "lucide-react";

import { CurrentUser, fetchCurrentUser } from "@/lib/auth";
import { fetchWorkspaceRepositories, WorkspaceRepository } from "@/lib/github";
import {
  analyzeChangeImpact,
  cancelTestExecution,
  executeRegressionTests,
  fetchImpactAssessment,
  fetchImpactHistory,
  fetchTestExecutionStatus,
  ImpactAssessment,
  TestExecutionRunItem,
} from "@/lib/impactmind";

const SAMPLE_DIFF = `diff --git a/app/services/auth.py b/app/services/auth.py
--- a/app/services/auth.py
+++ b/app/services/auth.py
@@ -12,4 +12,6 @@ def authenticate_user(username: str, password: str):
-    token = create_access_token(username)
+    # Enforce multi-factor verification
+    mfa_verified = verify_mfa_token(username)
+    token = create_access_token(username, mfa_verified=mfa_verified)
     return token
diff --git a/app/routes/api.py b/app/routes/api.py
--- a/app/routes/api.py
+++ b/app/routes/api.py
@@ -45,3 +45,4 @@ async def login_endpoint(payload: LoginRequest):
+    audit_log_login_attempt(payload.username)
     return {"token": token}
`;

export default function ImpactPage() {
  const [, setUser] = React.useState<CurrentUser | null>(null);
  const [repositories, setRepositories] = React.useState<WorkspaceRepository[]>([]);
  const [selectedRepoId, setSelectedRepoId] = React.useState<string>("");
  const [selectedWorkspaceId, setSelectedWorkspaceId] = React.useState<string>("");

  // Input states
  const [comparisonMode, setComparisonMode] = React.useState<"diff_input" | "commit_range">("diff_input");
  const [diffText, setDiffText] = React.useState<string>(SAMPLE_DIFF);
  const [baseCommitSha, setBaseCommitSha] = React.useState<string>("");
  const [targetCommitSha, setTargetCommitSha] = React.useState<string>("");

  // Analysis state
  const [isAnalyzing, setIsAnalyzing] = React.useState(false);
  const [assessment, setAssessment] = React.useState<ImpactAssessment | null>(null);
  const [history, setHistory] = React.useState<ImpactAssessment[]>([]);
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

  // Active view tab inside assessment
  const [activeTab, setActiveTab] = React.useState<"classifications" | "dependents" | "tests">("classifications");

  // Controlled Test Runner state
  const [runApproved, setRunApproved] = React.useState(false);
  const [customCommand, setCustomCommand] = React.useState<string>("");
  const [isExecutingTests, setIsExecutingTests] = React.useState(false);
  const [activeExecution, setActiveExecution] = React.useState<TestExecutionRunItem | null>(null);
  const [executionError, setExecutionError] = React.useState<string | null>(null);

  const loadHistory = React.useCallback(async (repoId: string, wsId: string) => {
    try {
      const res = await fetchImpactHistory(repoId, wsId, 10, 0);
      setHistory(res.assessments);
      if (res.assessments.length > 0) {
        setAssessment((prev) => {
          if (!prev) {
            if (res.assessments[0].test_executions.length > 0) {
              setActiveExecution(res.assessments[0].test_executions.slice(-1)[0]);
            }
            return res.assessments[0];
          }
          return prev;
        });
      }
    } catch {
      // Ignored for clean UI
    }
  }, []);

  // Initial load: User, Workspace, Repositories
  React.useEffect(() => {
    async function init() {
      try {
        const u = await fetchCurrentUser();
        if (u) {
          setUser(u);
          const ws = u.workspaces[0];
          if (ws) {
            setSelectedWorkspaceId(ws.workspace_id);
            const repos = await fetchWorkspaceRepositories(ws.workspace_id);
            setRepositories(repos);
            if (repos.length > 0) {
              setSelectedRepoId(repos[0].id);
              loadHistory(repos[0].id, ws.workspace_id);
            }
          }
        }
      } catch (err: unknown) {
        console.error("Init failed:", err);
      }
    }
    init();
  }, [loadHistory]);


  // Handle Triggering Change Analysis
  async function handleAnalyze() {
    if (!selectedRepoId || !selectedWorkspaceId) {
      setErrorMessage("Please select a repository first.");
      return;
    }
    setIsAnalyzing(true);
    setErrorMessage(null);
    try {
      const result = await analyzeChangeImpact(selectedRepoId, selectedWorkspaceId, {
        comparison_mode: comparisonMode,
        diff_text: comparisonMode === "diff_input" ? diffText : undefined,
        base_commit_sha: comparisonMode === "commit_range" ? baseCommitSha : undefined,
        target_commit_sha: comparisonMode === "commit_range" ? targetCommitSha : undefined,
      });
      setAssessment(result);
      if (result.test_executions && result.test_executions.length > 0) {
        setActiveExecution(result.test_executions.slice(-1)[0]);
      } else {
        setActiveExecution(null);
      }
      // Refresh history list
      loadHistory(selectedRepoId, selectedWorkspaceId);
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setIsAnalyzing(false);
    }
  }

  // Handle Controlled Test Execution
  async function handleRunTests() {
    if (!assessment || !selectedRepoId || !selectedWorkspaceId) return;
    if (!runApproved) {
      setExecutionError("Approval required: Please review and approve execution.");
      return;
    }
    setIsExecutingTests(true);
    setExecutionError(null);
    try {
      const run = await executeRegressionTests(selectedRepoId, selectedWorkspaceId, assessment.id, {
        run_approved: true,
        custom_command: customCommand.trim() || undefined,
      });
      setActiveExecution(run);

      // Re-fetch assessment to get updated structural exposure score
      const updated = await fetchImpactAssessment(selectedRepoId, selectedWorkspaceId, assessment.id);
      setAssessment(updated);
    } catch (err: unknown) {
      setExecutionError(err instanceof Error ? err.message : "Test execution failed");
    } finally {
      setIsExecutingTests(false);
    }
  }

  // Handle Test Cancellation
  async function handleCancelTest() {
    if (!assessment || !activeExecution || !selectedRepoId || !selectedWorkspaceId) return;
    try {
      await cancelTestExecution(selectedRepoId, selectedWorkspaceId, assessment.id, activeExecution.id);
      const status = await fetchTestExecutionStatus(
        selectedRepoId,
        selectedWorkspaceId,
        assessment.id,
        activeExecution.id
      );
      setActiveExecution(status);
    } catch (err: unknown) {
      console.error("Cancel failed:", err);
    }
  }

  // Helper for tier color
  function getTierBadge(tier: string) {
    switch (tier) {
      case "CRITICAL":
        return <Badge variant="destructive" className="bg-red-600 text-white font-mono text-xs">CRITICAL EXPOSURE</Badge>;
      case "HIGH":
        return <Badge variant="secondary" className="bg-amber-500 text-white font-mono text-xs">HIGH EXPOSURE</Badge>;
      case "MEDIUM":
        return <Badge variant="secondary" className="bg-blue-500 text-white font-mono text-xs">MEDIUM EXPOSURE</Badge>;
      default:
        return <Badge variant="secondary" className="bg-emerald-600 text-white font-mono text-xs">LOW EXPOSURE</Badge>;
    }
  }

  function getPriorityBadge(priority: string) {
    switch (priority) {
      case "CRITICAL":
        return <Badge variant="destructive" className="text-[10px] px-1.5 py-0 font-mono">CRITICAL</Badge>;
      case "HIGH":
        return <Badge variant="secondary" className="bg-amber-100 text-amber-800 text-[10px] px-1.5 py-0 font-mono">HIGH</Badge>;
      case "MEDIUM":
        return <Badge variant="secondary" className="bg-blue-100 text-blue-800 text-[10px] px-1.5 py-0 font-mono">MEDIUM</Badge>;
      default:
        return <Badge variant="secondary" className="bg-slate-100 text-slate-700 text-[10px] px-1.5 py-0 font-mono">LOW</Badge>;
    }
  }

  return (
    <AppShell>
      <PageHeader
        title="ImpactMind: Change Impact & Regression Intelligence"
        subtitle="Intelligent AST blast radius mapping, contract breaking change detection, and controlled regression testing."
        actions={
          <div className="flex items-center gap-3">
            {repositories.length > 0 && (
              <div className="flex items-center gap-2 bg-white border border-slate-200 rounded-lg px-2.5 py-1 shadow-sm">
                <FolderGit2 className="h-4 w-4 text-slate-500" />
                <select
                  aria-label="Select Repository"
                  value={selectedRepoId}
                  onChange={(e) => {
                    setSelectedRepoId(e.target.value);
                    if (selectedWorkspaceId) loadHistory(e.target.value, selectedWorkspaceId);
                  }}
                  className="text-xs bg-transparent border-0 focus:ring-0 text-slate-800 font-medium cursor-pointer"
                >
                  {repositories.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.full_name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {history.length > 1 && (
              <div className="hidden lg:flex items-center gap-1.5 bg-white border border-slate-200 rounded-lg px-2 py-1 shadow-sm text-xs">
                <span className="text-slate-400 font-mono text-[11px]">History:</span>
                <select
                  aria-label="Select Historical Assessment"
                  value={assessment?.id || ""}
                  onChange={(e) => {
                    const found = history.find((h) => h.id === e.target.value);
                    if (found) {
                      setAssessment(found);
                      if (found.test_executions.length > 0) {
                        setActiveExecution(found.test_executions.slice(-1)[0]);
                      }
                    }
                  }}
                  className="text-xs bg-transparent border-0 focus:ring-0 text-slate-700 font-mono cursor-pointer"
                >
                  {history.map((h, idx) => (
                    <option key={h.id} value={h.id}>
                      #{history.length - idx} ({h.exposure_tier} - {h.structural_exposure_score.toFixed(0)})
                    </option>
                  ))}
                </select>
              </div>
            )}
            <Button
              size="sm"
              onClick={handleAnalyze}
              disabled={isAnalyzing || !selectedRepoId}
              className="bg-blue-600 hover:bg-blue-700 text-white text-xs h-8 gap-1.5 shadow-sm"
            >
              {isAnalyzing ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Analyzing Impact...
                </>
              ) : (
                <>
                  <Activity className="h-3.5 w-3.5" />
                  Run Impact Analysis
                </>
              )}
            </Button>
          </div>
        }
      />

      {/* DevMemory Active Context */}
      <AgentMemoryContext
        agent="IMPACTMIND"
        query={targetCommitSha ? `Change impact and constraints for commit ${targetCommitSha}` : "Breaking changes and architectural constraints"}
        workspaceId={selectedWorkspaceId}
        repositoryId={selectedRepoId}
        title="ImpactMind: Architectural Constraints & Past Discoveries (DevMemory)"
      />

      {errorMessage && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2.5 text-xs text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0 text-red-600" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Input Configuration Card */}
      <Card className="border-slate-200 bg-white shadow-sm">
        <CardHeader className="pb-3 border-b border-slate-100">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <CardTitle className="text-sm font-semibold flex items-center gap-2 text-slate-900">
                <Code2 className="h-4 w-4 text-blue-600" />
                Target Change Specification
              </CardTitle>
              <CardDescription className="text-xs">
                Inspect a proposed git diff or compare commit ranges before merging into staging/production.
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant={comparisonMode === "diff_input" ? "default" : "outline"}
                size="sm"
                onClick={() => setComparisonMode("diff_input")}
                className="text-xs h-7 px-2.5"
              >
                Unified Diff Input
              </Button>
              <Button
                variant={comparisonMode === "commit_range" ? "default" : "outline"}
                size="sm"
                onClick={() => setComparisonMode("commit_range")}
                className="text-xs h-7 px-2.5"
              >
                Commit Range
              </Button>
              {comparisonMode === "diff_input" && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setDiffText(SAMPLE_DIFF)}
                  className="text-[11px] text-blue-600 h-7 px-2"
                >
                  Load Sample
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-3">
          {comparisonMode === "diff_input" ? (
            <div className="space-y-1.5">
              <textarea
                value={diffText}
                onChange={(e) => setDiffText(e.target.value)}
                placeholder="Paste unified git diff here (e.g. diff --git a/... b/...)..."
                rows={5}
                className="w-full text-xs font-mono p-3 rounded-lg border border-slate-200 bg-slate-50/70 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 py-1">
              <div>
                <label className="text-[11px] font-medium text-slate-600 block mb-1">
                  Base Commit SHA
                </label>
                <Input
                  value={baseCommitSha}
                  onChange={(e) => setBaseCommitSha(e.target.value)}
                  placeholder="e.g. main or 7a8e9d1"
                  className="text-xs font-mono h-8"
                />
              </div>
              <div>
                <label className="text-[11px] font-medium text-slate-600 block mb-1">
                  Target / Head Commit SHA
                </label>
                <Input
                  value={targetCommitSha}
                  onChange={(e) => setTargetCommitSha(e.target.value)}
                  placeholder="e.g. feature-branch or 3bd0f75"
                  className="text-xs font-mono h-8"
                />
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Assessment Overview Section */}
      {assessment ? (
        <div className="space-y-4">
          {/* Blast Radius & Structural Exposure Score Card */}
          <Card className="border-slate-200 bg-white shadow-sm overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex flex-col md:flex-row md:items-center md:justify-between gap-4 bg-gradient-to-r from-slate-50 via-white to-blue-50/30">
              <div className="space-y-1">
                <div className="flex items-center gap-2.5">
                  <Flame className="h-5 w-5 text-amber-500" />
                  <span className="text-xs font-mono text-slate-500 uppercase tracking-wider">
                    {assessment.score_label}
                  </span>
                  {getTierBadge(assessment.exposure_tier)}
                </div>
                <div className="flex items-baseline gap-2 pt-1">
                  <span className="text-3xl font-extrabold text-slate-900 tracking-tight">
                    {assessment.structural_exposure_score.toFixed(1)}
                  </span>
                  <span className="text-xs text-slate-400 font-mono">/ 100.0</span>
                </div>
                <p className="text-[11px] text-slate-500 max-w-xl italic">
                  Heuristic structural exposure metric based on graph topology and change surface;
                  NOT an empirical regression prediction.
                </p>
              </div>

              {/* Quick Component Breakdown */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-white p-3 rounded-lg border border-slate-200/80 shadow-xs text-center">
                <div>
                  <span className="text-[10px] text-slate-400 font-mono block">Files Modified</span>
                  <span className="text-sm font-bold text-slate-800">
                    {assessment.change_summary.total_files_changed ?? 0}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-slate-400 font-mono block">Breaking Alterations</span>
                  <span className={`text-sm font-bold ${(assessment.change_summary.breaking_changes_count ?? 0) > 0 ? "text-red-600" : "text-emerald-600"}`}>
                    {assessment.change_summary.breaking_changes_count ?? 0}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-slate-400 font-mono block">Exposed Endpoints</span>
                  <span className="text-sm font-bold text-blue-600">
                    {assessment.change_summary.exposed_endpoints_count ?? 0}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-slate-400 font-mono block">Recommended Tests</span>
                  <span className="text-sm font-bold text-slate-800">
                    {assessment.test_recommendations?.length ?? 0}
                  </span>
                </div>
              </div>
            </div>

            {/* Reasons and Recommended Actions */}
            <CardContent className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div>
                <span className="font-semibold text-slate-700 block mb-1.5 flex items-center gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
                  Key Exposure Factors & Rationale:
                </span>
                <ul className="space-y-1 text-slate-600">
                  {assessment.reasons.length > 0 ? (
                    assessment.reasons.map((r, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <span className="text-slate-400">•</span>
                        <span>{r}</span>
                      </li>
                    ))
                  ) : (
                    <li className="text-slate-400">Minimal structural exposure detected.</li>
                  )}
                </ul>
              </div>
              <div>
                <span className="font-semibold text-slate-700 block mb-1.5 flex items-center gap-1.5">
                  <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
                  Recommended Engineering Actions:
                </span>
                <ul className="space-y-1 text-slate-600">
                  {assessment.recommended_actions.length > 0 ? (
                    assessment.recommended_actions.map((act, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <span className="text-emerald-500 font-bold">✓</span>
                        <span>{act}</span>
                      </li>
                    ))
                  ) : (
                    <li className="text-slate-400">Safe for standard review and deployment.</li>
                  )}
                </ul>
              </div>
            </CardContent>
          </Card>

          {/* Navigation Tabs */}
          <div className="flex border-b border-slate-200 gap-6 text-xs font-medium">
            <button
              onClick={() => setActiveTab("classifications")}
              className={`pb-2.5 transition-colors border-b-2 flex items-center gap-1.5 ${
                activeTab === "classifications"
                  ? "border-blue-600 text-blue-600 font-semibold"
                  : "border-transparent text-slate-500 hover:text-slate-900"
              }`}
            >
              <FileCode className="h-3.5 w-3.5" />
              Change Classifications ({assessment.classifications?.length ?? 0})
            </button>
            <button
              onClick={() => setActiveTab("dependents")}
              className={`pb-2.5 transition-colors border-b-2 flex items-center gap-1.5 ${
                activeTab === "dependents"
                  ? "border-blue-600 text-blue-600 font-semibold"
                  : "border-transparent text-slate-500 hover:text-slate-900"
              }`}
            >
              <Layers className="h-3.5 w-3.5" />
              Downstream Blast Radius ({assessment.impacted_entities?.length ?? 0})
            </button>
            <button
              onClick={() => setActiveTab("tests")}
              className={`pb-2.5 transition-colors border-b-2 flex items-center gap-1.5 ${
                activeTab === "tests"
                  ? "border-blue-600 text-blue-600 font-semibold"
                  : "border-transparent text-slate-500 hover:text-slate-900"
              }`}
            >
              <Play className="h-3.5 w-3.5" />
              Regression Test Selection & Execution ({assessment.test_recommendations?.length ?? 0})
            </button>
          </div>

          {/* TAB 1: Change Classifications */}
          {activeTab === "classifications" && (
            <Card className="border-slate-200 bg-white shadow-sm">
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-50/80 border-b border-slate-200 text-slate-500 font-mono text-[11px]">
                      <tr>
                        <th className="py-2.5 px-4">File Path</th>
                        <th className="py-2.5 px-4">Symbol / Component</th>
                        <th className="py-2.5 px-4">Category</th>
                        <th className="py-2.5 px-4">Breaking?</th>
                        <th className="py-2.5 px-4">Evidence & Provenance</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {assessment.classifications.length > 0 ? (
                        assessment.classifications.map((c) => (
                          <tr key={c.id} className="hover:bg-slate-50/50">
                            <td className="py-2.5 px-4 font-mono font-medium text-slate-800">
                              {c.file_path}
                            </td>
                            <td className="py-2.5 px-4 text-slate-700">
                              {c.symbol_name ? (
                                <code className="bg-slate-100 px-1 py-0.5 rounded text-blue-700 font-mono">
                                  {c.symbol_name}
                                </code>
                              ) : (
                                <span className="text-slate-400 italic">Entire file</span>
                              )}
                            </td>
                            <td className="py-2.5 px-4">
                              <Badge variant="outline" className="text-[10px] font-mono">
                                {c.category}
                              </Badge>
                            </td>
                            <td className="py-2.5 px-4">
                              {c.is_breaking ? (
                                <Badge variant="destructive" className="text-[10px] bg-red-100 text-red-800 border-red-200">
                                  BREAKING
                                </Badge>
                              ) : (
                                <span className="text-slate-400 text-[11px]">Non-breaking</span>
                              )}
                            </td>
                            <td className="py-2.5 px-4 text-slate-500 max-w-xs truncate" title={c.evidence || ""}>
                              {c.evidence || c.breaking_reason || "AST modification detected"}
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={5} className="py-6 text-center text-slate-400">
                            No code classifications recorded.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* TAB 2: Downstream Dependents */}
          {activeTab === "dependents" && (
            <Card className="border-slate-200 bg-white shadow-sm">
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-50/80 border-b border-slate-200 text-slate-500 font-mono text-[11px]">
                      <tr>
                        <th className="py-2.5 px-4">Entity Name</th>
                        <th className="py-2.5 px-4">Label</th>
                        <th className="py-2.5 px-4">Impact Type</th>
                        <th className="py-2.5 px-4">Hop Depth</th>
                        <th className="py-2.5 px-4">Relationship & Confidence</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {assessment.impacted_entities.length > 0 ? (
                        assessment.impacted_entities.map((e) => (
                          <tr key={e.id} className="hover:bg-slate-50/50">
                            <td className="py-2.5 px-4 font-mono font-medium text-slate-900">
                              {e.name}
                            </td>
                            <td className="py-2.5 px-4">
                              <Badge variant="outline" className="text-[10px] font-mono">
                                {e.label}
                              </Badge>
                            </td>
                            <td className="py-2.5 px-4">
                              <Badge
                                variant="secondary"
                                className={`text-[10px] ${
                                  e.impact_type === "exposed_endpoint"
                                    ? "bg-purple-100 text-purple-800"
                                    : e.impact_type === "direct_dependent"
                                    ? "bg-blue-100 text-blue-800"
                                    : "bg-slate-100 text-slate-700"
                                }`}
                              >
                                {e.impact_type}
                              </Badge>
                            </td>
                            <td className="py-2.5 px-4 font-mono text-slate-600">
                              {e.depth} hop{e.depth > 1 ? "s" : ""}
                            </td>
                            <td className="py-2.5 px-4 text-slate-500 font-mono text-[11px]">
                              {e.relationship_type || "CALLS"} ({Math.round(e.confidence * 100)}%)
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={5} className="py-6 text-center text-slate-400">
                            No downstream graph callers identified.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* TAB 3: Regression Test Recommendations & Controlled Test Runner */}
          {activeTab === "tests" && (
            <div className="space-y-4">
              {/* Recommendations Table */}
              <Card className="border-slate-200 bg-white shadow-sm">
                <CardHeader className="py-3 px-4 border-b border-slate-100">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-xs font-semibold text-slate-800 flex items-center gap-2">
                      <Shield className="h-4 w-4 text-blue-600" />
                      Ranked Regression Test Recommendations
                    </CardTitle>
                    <span className="text-[11px] text-slate-400">
                      Ranked by graph calls, API route exposure, naming conventions & semantic proximity
                    </span>
                  </div>
                </CardHeader>
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-50/80 border-b border-slate-200 text-slate-500 font-mono text-[11px]">
                        <tr>
                          <th className="py-2.5 px-4">Priority</th>
                          <th className="py-2.5 px-4">Test File / Spec</th>
                          <th className="py-2.5 px-4">Framework</th>
                          <th className="py-2.5 px-4">Reason & Evidence</th>
                          <th className="py-2.5 px-4">Confidence</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {assessment.test_recommendations.length > 0 ? (
                          assessment.test_recommendations.map((t) => (
                            <tr key={t.id} className="hover:bg-slate-50/50">
                              <td className="py-2.5 px-4">
                                {getPriorityBadge(t.priority)}
                              </td>
                              <td className="py-2.5 px-4 font-mono font-medium text-slate-800">
                                {t.test_file}
                              </td>
                              <td className="py-2.5 px-4">
                                <Badge variant="outline" className="text-[10px] font-mono">
                                  {t.test_framework}
                                </Badge>
                              </td>
                              <td className="py-2.5 px-4 text-slate-600 max-w-sm">
                                {t.reason}
                              </td>
                              <td className="py-2.5 px-4 font-mono text-slate-500 text-[11px]">
                                {Math.round(t.confidence * 100)}%
                              </td>
                            </tr>
                          ))
                        ) : (
                          <tr>
                            <td colSpan={5} className="py-6 text-center text-slate-400">
                              No automated regression tests recommended.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>

              {/* Controlled Test Runner Panel */}
              <Card className="border-blue-200 bg-gradient-to-b from-blue-50/30 to-white shadow-sm">
                <CardHeader className="py-3.5 px-4 border-b border-blue-100">
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div>
                      <CardTitle className="text-xs font-semibold text-slate-900 flex items-center gap-2">
                        <Terminal className="h-4 w-4 text-blue-600" />
                        Controlled Regression Test Runner
                      </CardTitle>
                      <CardDescription className="text-[11px]">
                        Safeguarded subprocess environment. Requires explicit user approval, strictly enforces command allowlists, redacts credentials, and bounds output to 50KB.
                      </CardDescription>
                    </div>

                    <div className="flex items-center gap-3">
                      <label className="flex items-center gap-2 text-xs font-medium text-slate-700 cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={runApproved}
                          onChange={(e) => setRunApproved(e.target.checked)}
                          className="rounded border-slate-300 text-blue-600 focus:ring-blue-500 h-4 w-4"
                        />
                        <span>Explicitly Approve Execution</span>
                      </label>

                      <Button
                        size="sm"
                        onClick={handleRunTests}
                        disabled={!runApproved || isExecutingTests}
                        className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs h-8 gap-1.5 shadow-sm"
                      >
                        {isExecutingTests ? (
                          <>
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            Executing Tests...
                          </>
                        ) : (
                          <>
                            <Play className="h-3.5 w-3.5" />
                            Approve & Run Tests
                          </>
                        )}
                      </Button>

                      {isExecutingTests && activeExecution && (
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={handleCancelTest}
                          className="text-xs h-8"
                        >
                          Cancel
                        </Button>
                      )}
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="p-4 space-y-3">
                  {executionError && (
                    <div className="p-2.5 bg-red-50 border border-red-200 rounded text-xs text-red-700">
                      {executionError}
                    </div>
                  )}

                  {/* Optional Custom Test Command Input */}
                  <div className="flex flex-col sm:flex-row sm:items-center gap-2 p-2.5 bg-white rounded-lg border border-slate-200">
                    <span className="text-[11px] font-medium text-slate-600 whitespace-nowrap">
                      Custom Test Command (optional):
                    </span>
                    <Input
                      value={customCommand}
                      onChange={(e) => setCustomCommand(e.target.value)}
                      placeholder="e.g. pytest tests/test_billing.py -v"
                      className="text-xs font-mono h-7 flex-1 bg-slate-50/50"
                    />
                  </div>

                  {/* Active / Latest Execution Metrics */}
                  {activeExecution && (
                    <div className="space-y-3">
                      <div className="flex flex-wrap items-center justify-between gap-2 p-3 bg-white rounded-lg border border-slate-200 text-xs">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-slate-700">Status:</span>
                          <Badge
                            variant={activeExecution.status === "PASSED" ? "secondary" : "destructive"}
                            className={`font-mono text-[11px] ${
                              activeExecution.status === "PASSED"
                                ? "bg-emerald-100 text-emerald-800"
                                : activeExecution.status === "RUNNING"
                                ? "bg-blue-100 text-blue-800"
                                : "bg-red-100 text-red-800"
                            }`}
                          >
                            {activeExecution.status}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-4 text-slate-600 font-mono text-[11px]">
                          <span>Passed: <b className="text-emerald-600">{activeExecution.passed_count}</b></span>
                          <span>Failed: <b className="text-red-600">{activeExecution.failed_count}</b></span>
                          <span>Duration: <b>{activeExecution.duration_ms ?? 0}ms</b></span>
                        </div>
                        <div className="text-[11px] text-slate-500 font-mono truncate max-w-xs">
                          Command: {activeExecution.command}
                        </div>
                      </div>

                      {/* Log Output Console */}
                      <div className="rounded-lg bg-slate-900 text-slate-100 p-3.5 font-mono text-[11px] space-y-2 overflow-x-auto max-h-64 shadow-inner">
                        <div className="flex items-center justify-between text-slate-400 border-b border-slate-800 pb-1.5">
                          <span>$ {activeExecution.command}</span>
                          <span>Exit code: {activeExecution.exit_code ?? "—"}</span>
                        </div>
                        {activeExecution.stdout && (
                          <pre className="whitespace-pre-wrap text-emerald-400/90 leading-relaxed">
                            {activeExecution.stdout}
                          </pre>
                        )}
                        {activeExecution.stderr && (
                          <pre className="whitespace-pre-wrap text-red-400/90 leading-relaxed">
                            {activeExecution.stderr}
                          </pre>
                        )}
                        {!activeExecution.stdout && !activeExecution.stderr && (
                          <p className="text-slate-500 italic">No output captured.</p>
                        )}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      ) : (
        /* Empty State */
        <Card className="border-slate-200 bg-white shadow-sm p-12 text-center">
          <CardContent className="space-y-3">
            <div className="h-12 w-12 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center mx-auto">
              <Activity className="h-6 w-6" />
            </div>
            <h3 className="text-sm font-semibold text-slate-800">No Change Impact Assessment Selected</h3>
            <p className="text-xs text-slate-500 max-w-md mx-auto">
              Paste a unified git diff above or select a commit range, then click <b>Run Impact Analysis</b> to inspect structural blast radius, downstream callers, and recommended regression tests.
            </p>
          </CardContent>
        </Card>
      )}
    </AppShell>
  );
}
