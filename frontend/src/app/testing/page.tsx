"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { AgentMemoryContext } from "@/components/shared/agent-memory-context";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  FlaskConical,
  Play,
  RefreshCw,
  Search,
  Check,
  X,
  StopCircle,
  Stethoscope,
  BarChart3,
  Code2,
  ShieldAlert,
  Sparkles,
} from "lucide-react";

import { fetchCurrentUser, WorkspaceMembership } from "@/lib/auth";
import { normalizeApiError } from "@/lib/api-error";
import { fetchWorkspaceRepositories, WorkspaceRepository } from "@/lib/github";
import {
  detectFrameworks,
  generateTestSuite,
  listTestSuites,
  approveTestSuite,
  rejectTestSuite,
  executeTestSuite,
  getTestExecution,
  getTestResults,
  listCoverageReports,
  diagnoseFailure,
  cancelExecution,
  DetectedFramework,
  TestPilotSuite,
  TestExecution,
  IndividualTestResult,
  CoverageReport,
  DiagnosisResponse,
  TestPilotFramework,
  TestPilotTestType,
} from "@/lib/testpilot";

export default function TestingPage() {
  const [workspaces, setWorkspaces] = React.useState<WorkspaceMembership[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = React.useState<string>("");
  const [currentRole, setCurrentRole] = React.useState<string>("VIEWER");
  const [repositories, setRepositories] = React.useState<WorkspaceRepository[]>([]);
  const [selectedRepoId, setSelectedRepoId] = React.useState<string>("");
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);
  const [activeTab, setActiveTab] = React.useState<string>("suites");

  // Overview metrics state
  const [suites, setSuites] = React.useState<TestPilotSuite[]>([]);
  const [executions, setExecutions] = React.useState<TestExecution[]>([]);
  const [coverageReports, setCoverageReports] = React.useState<CoverageReport[]>([]);
  const [loadingData, setLoadingData] = React.useState<boolean>(false);

  // Framework detection state
  const [subpath, setSubpath] = React.useState<string>("");
  const [detectedFrameworksList, setDetectedFrameworksList] = React.useState<DetectedFramework[]>([]);
  const [detecting, setDetecting] = React.useState<boolean>(false);

  // Suite generation state
  const [selectedFramework, setSelectedFramework] = React.useState<TestPilotFramework>("pytest");
  const [targetFilesInput, setTargetFilesInput] = React.useState<string>("tests/test_core.py");
  const [sourceCodeContext, setSourceCodeContext] = React.useState<string>("");
  const [testType, setTestType] = React.useState<TestPilotTestType>("unit");
  const [isGenerating, setIsGenerating] = React.useState<boolean>(false);
  const [selectedSuite, setSelectedSuite] = React.useState<TestPilotSuite | null>(null);

  // Execution & results state
  const [activeExecution, setActiveExecution] = React.useState<TestExecution | null>(null);
  const [testResults, setTestResults] = React.useState<IndividualTestResult[]>([]);
  const [customCommand, setCustomCommand] = React.useState<string>("");
  const [isExecuting, setIsExecuting] = React.useState<boolean>(false);
  const [pollIntervalId, setPollIntervalId] = React.useState<NodeJS.Timeout | null>(null);

  // Diagnosis state
  const [diagnosis, setDiagnosis] = React.useState<DiagnosisResponse | null>(null);
  const [isDiagnosing, setIsDiagnosing] = React.useState<boolean>(false);

  // Rejection modal/input
  const [rejectingSuiteId, setRejectingSuiteId] = React.useState<string | null>(null);
  const [rejectionReason, setRejectionReason] = React.useState<string>("");

  const canEdit = currentRole === "OWNER" || currentRole === "ADMIN" || currentRole === "MEMBER";
  const canApprove = currentRole === "OWNER" || currentRole === "ADMIN";

  // Load repositories and suites
  const refreshRepositoryData = React.useCallback(
    async (repoId: string, wsId: string) => {
      if (!repoId) return;
      setLoadingData(true);
      setErrorMessage(null);
      try {
        const [suitesRes, coverageRes] = await Promise.all([
          listTestSuites(repoId, { workspaceId: wsId }),
          listCoverageReports(repoId, { workspaceId: wsId }).catch(() => ({ items: [], total: 0, limit: 20, offset: 0 })),
        ]);
        setSuites(suitesRes.items);
        setCoverageReports(coverageRes.items);

        if (suitesRes.items.length > 0 && !selectedSuite) {
          setSelectedSuite(suitesRes.items[0]);
        }
      } catch (err: unknown) {
        setErrorMessage(normalizeApiError(err, "Failed to load TestPilot data"));
      } finally {
        setLoadingData(false);
      }
    },
    [selectedSuite]
  );

  // Initial user & workspace setup
  React.useEffect(() => {
    async function init() {
      try {
        const user = await fetchCurrentUser();
        if (user && user.workspaces && user.workspaces.length > 0) {
          setWorkspaces(user.workspaces);
          const firstWs = user.workspaces[0];
          setSelectedWorkspaceId(firstWs.workspace_id);
          setCurrentRole(firstWs.role);

          const repos = await fetchWorkspaceRepositories(firstWs.workspace_id);
          setRepositories(repos);
          if (repos.length > 0) {
            const firstRepo = repos[0];
            setSelectedRepoId(firstRepo.id);
            const effectiveWsId = firstRepo.workspace_id || firstWs.workspace_id;
            setSelectedWorkspaceId(effectiveWsId);
            refreshRepositoryData(firstRepo.id, effectiveWsId);
          }
        }
      } catch (err: unknown) {
        setErrorMessage(normalizeApiError(err, "Failed to initialize workspace"));
      }
    }
    init();
  }, [refreshRepositoryData]);

  // Clean up polling interval
  React.useEffect(() => {
    return () => {
      if (pollIntervalId) clearInterval(pollIntervalId);
    };
  }, [pollIntervalId]);

  // Framework Detection Handler
  const handleDetectFrameworks = async () => {
    if (!selectedRepoId) return;
    setDetecting(true);
    setErrorMessage(null);
    try {
      const results = await detectFrameworks(selectedRepoId, subpath.trim() || undefined, selectedWorkspaceId);
      setDetectedFrameworksList(results);
      if (results.length > 0) {
        const primary = results[0];
        if (
          ["pytest", "unittest", "vitest", "jest", "mocha", "custom"].includes(primary.framework.toLowerCase())
        ) {
          setSelectedFramework(primary.framework.toLowerCase() as TestPilotFramework);
        }
      }
    } catch (err: unknown) {
      setErrorMessage(normalizeApiError(err, "Failed to detect testing frameworks"));
    } finally {
      setDetecting(false);
    }
  };

  // Test Suite Generation Handler
  const handleGenerateSuite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedRepoId || !sourceCodeContext.trim()) return;

    setIsGenerating(true);
    setErrorMessage(null);
    try {
      const targetFiles = targetFilesInput
        .split(",")
        .map((f) => f.trim())
        .filter(Boolean);

      const newSuite = await generateTestSuite(
        selectedRepoId,
        {
          framework: selectedFramework,
          target_files: targetFiles.length > 0 ? targetFiles : ["tests/test_generated.py"],
          source_context: sourceCodeContext,
          test_type: testType,
        },
        selectedWorkspaceId
      );

      setSelectedSuite(newSuite);
      setSourceCodeContext("");
      await refreshRepositoryData(selectedRepoId, selectedWorkspaceId);
    } catch (err: unknown) {
      setErrorMessage(normalizeApiError(err, "Failed to synthesize test suite"));
    } finally {
      setIsGenerating(false);
    }
  };

  // Suite Approval Handler
  const handleApproveSuite = async (suiteId: string) => {
    if (!selectedRepoId) return;
    setErrorMessage(null);
    try {
      const approved = await approveTestSuite(selectedRepoId, suiteId, selectedWorkspaceId);
      setSelectedSuite(approved);
      await refreshRepositoryData(selectedRepoId, selectedWorkspaceId);
    } catch (err: unknown) {
      setErrorMessage(normalizeApiError(err, "Failed to approve test suite"));
    }
  };

  // Suite Rejection Handler
  const handleRejectSuite = async (suiteId: string) => {
    if (!selectedRepoId) return;
    setErrorMessage(null);
    try {
      const rejected = await rejectTestSuite(selectedRepoId, suiteId, rejectionReason || undefined, selectedWorkspaceId);
      setSelectedSuite(rejected);
      setRejectingSuiteId(null);
      setRejectionReason("");
      await refreshRepositoryData(selectedRepoId, selectedWorkspaceId);
    } catch (err: unknown) {
      setErrorMessage(normalizeApiError(err, "Failed to reject test suite"));
    }
  };

  // Poll execution status
  const startPollingExecution = (executionId: string) => {
    if (pollIntervalId) clearInterval(pollIntervalId);

    const interval = setInterval(async () => {
      try {
        const execution = await getTestExecution(selectedRepoId, executionId, selectedWorkspaceId);
        setActiveExecution(execution);

        if (
          execution.status === "PASSED" ||
          execution.status === "FAILED" ||
          execution.status === "ERROR" ||
          execution.status === "TIMED_OUT" ||
          execution.status === "CANCELLED" ||
          execution.status === "BLOCKED"
        ) {
          clearInterval(interval);
          setPollIntervalId(null);
          setIsExecuting(false);

          // Fetch individual test results
          getTestResults(selectedRepoId, executionId, selectedWorkspaceId)
            .then(setTestResults)
            .catch(() => setTestResults([]));

          // Refresh coverage reports
          listCoverageReports(selectedRepoId, { workspaceId: selectedWorkspaceId })
            .then((res) => setCoverageReports(res.items))
            .catch(() => {});
        }
      } catch {
        clearInterval(interval);
        setPollIntervalId(null);
        setIsExecuting(false);
      }
    }, 2000);

    setPollIntervalId(interval);
  };

  // Execute Suite Handler
  const handleExecuteSuite = async (suiteId: string) => {
    if (!selectedRepoId) return;
    setIsExecuting(true);
    setErrorMessage(null);
    setDiagnosis(null);
    try {
      const exec = await executeTestSuite(
        selectedRepoId,
        suiteId,
        {
          custom_command: customCommand.trim() || undefined,
        },
        selectedWorkspaceId
      );
      setActiveExecution(exec);
      setExecutions((prev) => [exec, ...prev.filter((x) => x.id !== exec.id)]);
      setActiveTab("execution");

      if (exec.status === "RUNNING" || exec.status === "PENDING") {
        startPollingExecution(exec.id);
      } else {
        setIsExecuting(false);
        const results = await getTestResults(selectedRepoId, exec.id, selectedWorkspaceId);
        setTestResults(results);
      }
    } catch (err: unknown) {
      setIsExecuting(false);
      setErrorMessage(normalizeApiError(err, "Failed to initiate test execution"));
    }
  };

  // Cancel Execution Handler
  const handleCancelExecution = async () => {
    if (!activeExecution || !selectedRepoId) return;
    try {
      const cancelled = await cancelExecution(selectedRepoId, activeExecution.id, selectedWorkspaceId);
      setActiveExecution(cancelled);
      setIsExecuting(false);
      if (pollIntervalId) {
        clearInterval(pollIntervalId);
        setPollIntervalId(null);
      }
    } catch (err: unknown) {
      setErrorMessage(normalizeApiError(err, "Failed to cancel test execution"));
    }
  };

  // Diagnose Failure Handler
  const handleDiagnose = async () => {
    if (!activeExecution || !selectedRepoId) return;
    setIsDiagnosing(true);
    setErrorMessage(null);
    try {
      const diag = await diagnoseFailure(selectedRepoId, activeExecution.id, undefined, selectedWorkspaceId);
      setDiagnosis(diag);
      setActiveTab("diagnose");
    } catch (err: unknown) {
      setErrorMessage(normalizeApiError(err, "Failed to diagnose test failures"));
    } finally {
      setIsDiagnosing(false);
    }
  };

  // Derived Overview Metrics (strictly computed from real backend data)
  const totalSuitesCount = suites.length;
  const latestCoverage = coverageReports.length > 0 ? coverageReports[0] : null;
  const latestLineCoverage = latestCoverage?.line_coverage_pct != null ? `${latestCoverage.line_coverage_pct.toFixed(1)}%` : "Not measured";
  const latestBranchCoverage = latestCoverage?.branch_coverage_pct != null ? `${latestCoverage.branch_coverage_pct.toFixed(1)}%` : "Not measured";

  const latestExec = activeExecution || (executions.length > 0 ? executions[0] : null);
  let passRateText = "No runs yet";
  if (latestExec) {
    const totalRan = latestExec.passed_count + latestExec.failed_count;
    if (totalRan > 0) {
      passRateText = `${Math.round((latestExec.passed_count / totalRan) * 100)}%`;
    } else if (latestExec.status === "PASSED") {
      passRateText = "100%";
    } else if (latestExec.status === "FAILED") {
      passRateText = "0%";
    }
  }

  return (
    <AppShell>
      <div className="flex-1 space-y-6 p-8 pt-6 max-w-7xl mx-auto">
        {/* Header with Workspace & Repo selector */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border/40 pb-5">
          <PageHeader
            title="TestPilot — Autonomous Software Testing"
            subtitle="Framework detection, test synthesis, controlled sandboxed execution, failure diagnosis, and coverage metrics."
          />
          <div className="flex items-center gap-3">
            <div className="flex flex-col sm:flex-row items-end sm:items-center gap-2">
              <span className="text-xs text-slate-500 font-medium">Workspace Role:</span>
              <Badge variant="outline" className="font-mono text-xs uppercase bg-slate-50">
                {currentRole}
              </Badge>
            </div>

            <select
              aria-label="Repository Selection"
              className="px-3 py-2 text-sm rounded-md border border-input bg-background focus:outline-none focus:ring-2 focus:ring-primary shadow-sm"
              value={selectedRepoId}
              onChange={(e) => {
                const nextId = e.target.value;
                setSelectedRepoId(nextId);
                const r = repositories.find((x) => x.id === nextId);
                const wsId = r?.workspace_id || selectedWorkspaceId;
                if (r?.workspace_id) {
                  setSelectedWorkspaceId(r.workspace_id);
                  const mem = workspaces.find((w) => w.workspace_id === r.workspace_id);
                  if (mem) setCurrentRole(mem.role);
                }
                setSelectedSuite(null);
                setActiveExecution(null);
                setTestResults([]);
                setDiagnosis(null);
                refreshRepositoryData(nextId, wsId);
              }}
            >
              {repositories.length === 0 ? (
                <option value="">No repositories found</option>
              ) : (
                repositories.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.full_name || r.name}
                  </option>
                ))
              )}
            </select>

            <Button
              variant="outline"
              size="sm"
              onClick={() => refreshRepositoryData(selectedRepoId, selectedWorkspaceId)}
              disabled={loadingData}
              className="gap-2"
            >
              <RefreshCw className={`h-4 w-4 ${loadingData ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </div>

        {/* DevMemory Active Context */}
        <AgentMemoryContext
          agent="TESTPILOT"
          query="Testing conventions, failure edge cases, and test fixtures"
          workspaceId={selectedWorkspaceId}
          repositoryId={selectedRepoId}
          title="TestPilot: Testing Conventions & Known Failures (DevMemory)"
        />

        {/* Error alert banner */}
        {errorMessage && (
          <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 text-sm flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 flex-shrink-0" />
              <span>{errorMessage}</span>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setErrorMessage(null)}>
              Dismiss
            </Button>
          </div>
        )}

        {/* Real Dynamic Overview Stats Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
          <Card className="border-slate-200 bg-white">
            <CardContent className="p-4">
              <span className="text-xs text-slate-500 font-mono">Test Suites Created</span>
              <p className="text-2xl font-bold text-slate-900 mt-1">{totalSuitesCount}</p>
              <span className="text-[11px] text-slate-400 mt-0.5 block">Stored for current repository</span>
            </CardContent>
          </Card>

          <Card className="border-slate-200 bg-white">
            <CardContent className="p-4">
              <span className="text-xs text-slate-500 font-mono">Latest Run Pass Rate</span>
              <p className={`text-2xl font-bold mt-1 ${passRateText.includes("100") ? "text-emerald-600" : "text-blue-600"}`}>
                {passRateText}
              </p>
              <span className="text-[11px] text-slate-400 mt-0.5 block">
                {latestExec ? `Status: ${latestExec.status} (${latestExec.passed_count} passed, ${latestExec.failed_count} failed)` : "No test runs executed yet"}
              </span>
            </CardContent>
          </Card>

          <Card className="border-slate-200 bg-white">
            <CardContent className="p-4">
              <span className="text-xs text-slate-500 font-mono">Line Coverage</span>
              <p className="text-2xl font-bold text-blue-600 mt-1">{latestLineCoverage}</p>
              <span className="text-[11px] text-slate-400 mt-0.5 block">
                {latestCoverage ? `Report: ${latestCoverage.id.slice(0, 8)}` : "No coverage data recorded"}
              </span>
            </CardContent>
          </Card>

          <Card className="border-slate-200 bg-white">
            <CardContent className="p-4">
              <span className="text-xs text-slate-500 font-mono">Branch Coverage</span>
              <p className="text-2xl font-bold text-slate-900 mt-1">{latestBranchCoverage}</p>
              <span className="text-[11px] text-slate-400 mt-0.5 block">
                {latestCoverage?.branch_coverage_pct != null ? "Measured with branch instrumentation" : "Not measured for this runner"}
              </span>
            </CardContent>
          </Card>
        </div>

        {/* Tabbed Agent Interface */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
          <TabsList className="bg-slate-100 p-1 rounded-lg">
            <TabsTrigger value="suites" className="gap-2 text-xs">
              <FlaskConical className="h-3.5 w-3.5" />
              Test Suites ({suites.length})
            </TabsTrigger>
            <TabsTrigger value="detect" className="gap-2 text-xs">
              <Search className="h-3.5 w-3.5" />
              Framework Detection
            </TabsTrigger>
            <TabsTrigger value="execution" className="gap-2 text-xs">
              <Play className="h-3.5 w-3.5" />
              Execution Runner
            </TabsTrigger>
            <TabsTrigger value="diagnose" className="gap-2 text-xs">
              <Stethoscope className="h-3.5 w-3.5" />
              Failure Diagnoser
            </TabsTrigger>
            <TabsTrigger value="coverage" className="gap-2 text-xs">
              <BarChart3 className="h-3.5 w-3.5" />
              Coverage Dashboard
            </TabsTrigger>
          </TabsList>

          {/* TAB 1: TEST SUITES & GENERATION */}
          <TabsContent value="suites" className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              {/* Left Column: Generate New Suite Form */}
              <div className="lg:col-span-5 space-y-4">
                <Card className="border-slate-200 bg-white shadow-xs">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm font-semibold flex items-center gap-2">
                      <Sparkles className="h-4 w-4 text-blue-600" />
                      Synthesize Test Suite
                    </CardTitle>
                    <CardDescription className="text-xs">
                      Generate targeted unit, regression, or edge-case test suites.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {!canEdit && (
                      <div className="mb-4 p-2.5 rounded bg-amber-50 text-amber-800 text-xs border border-amber-200">
                        Workspace role <strong>{currentRole}</strong> is read-only. Test synthesis requires MEMBER or higher.
                      </div>
                    )}
                    <form onSubmit={handleGenerateSuite} className="space-y-4">
                      <div>
                        <label className="text-xs font-semibold text-slate-700 block mb-1">Target Framework</label>
                        <select
                          className="w-full text-xs px-3 py-2 border rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-blue-600"
                          value={selectedFramework}
                          disabled={!canEdit || isGenerating}
                          onChange={(e) => setSelectedFramework(e.target.value as TestPilotFramework)}
                        >
                          <option value="pytest">pytest (Python)</option>
                          <option value="unittest">unittest (Python)</option>
                          <option value="vitest">Vitest (TypeScript / JavaScript)</option>
                          <option value="jest">Jest (JavaScript / TypeScript)</option>
                          <option value="mocha">Mocha (JavaScript)</option>
                          <option value="custom">Custom Framework</option>
                        </select>
                      </div>

                      <div>
                        <label className="text-xs font-semibold text-slate-700 block mb-1">Test Type</label>
                        <select
                          className="w-full text-xs px-3 py-2 border rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-blue-600"
                          value={testType}
                          disabled={!canEdit || isGenerating}
                          onChange={(e) => setTestType(e.target.value as TestPilotTestType)}
                        >
                          <option value="unit">Unit Tests</option>
                          <option value="integration">Integration Tests</option>
                          <option value="regression">Regression Tests</option>
                          <option value="edge_case">Edge Cases & Fuzzing</option>
                          <option value="negative">Negative / Fault-Injection</option>
                        </select>
                      </div>

                      <div>
                        <label className="text-xs font-semibold text-slate-700 block mb-1">Target Files</label>
                        <Input
                          placeholder="e.g. app/core.py, tests/test_core.py"
                          value={targetFilesInput}
                          disabled={!canEdit || isGenerating}
                          onChange={(e) => setTargetFilesInput(e.target.value)}
                          className="text-xs"
                        />
                        <span className="text-[10px] text-slate-400 mt-1 block">Comma-separated list of target files</span>
                      </div>

                      <div>
                        <label className="text-xs font-semibold text-slate-700 block mb-1">Source Code / Context</label>
                        <textarea
                          placeholder="Paste function definition, code context, or interface to test..."
                          value={sourceCodeContext}
                          disabled={!canEdit || isGenerating}
                          onChange={(e) => setSourceCodeContext(e.target.value)}
                          rows={6}
                          className="w-full font-mono text-xs p-3 border rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-blue-600"
                          required
                        />
                      </div>

                      <Button
                        type="submit"
                        disabled={!canEdit || isGenerating || !sourceCodeContext.trim()}
                        className="w-full text-xs h-9 bg-blue-600 hover:bg-blue-700 text-white"
                      >
                        {isGenerating ? (
                          <>
                            <RefreshCw className="h-3.5 w-3.5 mr-2 animate-spin" />
                            Synthesizing Test Suite...
                          </>
                        ) : (
                          <>
                            <Sparkles className="h-3.5 w-3.5 mr-2" />
                            Synthesize Tests with TestPilot
                          </>
                        )}
                      </Button>
                    </form>
                  </CardContent>
                </Card>

                {/* Suites List */}
                <Card className="border-slate-200 bg-white shadow-xs">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm font-semibold">Existing Test Suites</CardTitle>
                  </CardHeader>
                  <CardContent className="p-0">
                    {suites.length === 0 ? (
                      <div className="p-6 text-center text-xs text-slate-400">
                        No test suites generated yet for this repository.
                      </div>
                    ) : (
                      <div className="divide-y divide-slate-100 max-h-72 overflow-y-auto">
                        {suites.map((s) => (
                          <div
                            key={s.id}
                            onClick={() => setSelectedSuite(s)}
                            className={`p-3 text-xs cursor-pointer transition-colors flex items-center justify-between ${
                              selectedSuite?.id === s.id ? "bg-blue-50/70 border-l-4 border-blue-600" : "hover:bg-slate-50"
                            }`}
                          >
                            <div className="min-w-0 pr-2">
                              <p className="font-semibold text-slate-800 truncate">
                                {s.framework} • {s.test_type}
                              </p>
                              <p className="text-[10px] text-slate-400 font-mono mt-0.5">
                                {s.target_files.join(", ")}
                              </p>
                            </div>
                            <div className="flex items-center gap-2">
                              <Badge
                                variant={
                                  s.status === "APPROVED"
                                    ? "default"
                                    : s.status === "REJECTED"
                                    ? "destructive"
                                    : "secondary"
                                }
                                className="text-[10px]"
                              >
                                {s.status}
                              </Badge>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>

              {/* Right Column: Selected Suite Details & Approval Gating */}
              <div className="lg:col-span-7 space-y-4">
                {selectedSuite ? (
                  <Card className="border-slate-200 bg-white shadow-xs">
                    <CardHeader className="pb-3 border-b border-slate-100 flex flex-row items-center justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <CardTitle className="text-sm font-semibold">
                            Suite: {selectedSuite.framework} ({selectedSuite.test_type})
                          </CardTitle>
                          <Badge
                            variant={
                              selectedSuite.status === "APPROVED"
                                ? "default"
                                : selectedSuite.status === "REJECTED"
                                ? "destructive"
                                : "secondary"
                            }
                          >
                            {selectedSuite.status}
                          </Badge>
                        </div>
                        <span className="text-[11px] text-slate-400 font-mono block mt-1">
                          ID: {selectedSuite.id} • Target: {selectedSuite.target_files.join(", ")}
                        </span>
                      </div>

                      {/* Approval and Execution Actions */}
                      <div className="flex items-center gap-2">
                        {selectedSuite.status === "GENERATED" && canApprove && (
                          <>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setRejectingSuiteId(selectedSuite.id)}
                              className="text-xs h-8 text-rose-600 border-rose-200 hover:bg-rose-50"
                            >
                              <X className="h-3.5 w-3.5 mr-1" />
                              Reject
                            </Button>
                            <Button
                              size="sm"
                              onClick={() => handleApproveSuite(selectedSuite.id)}
                              className="text-xs h-8 bg-emerald-600 hover:bg-emerald-700 text-white"
                            >
                              <Check className="h-3.5 w-3.5 mr-1" />
                              Approve
                            </Button>
                          </>
                        )}

                        <Button
                          size="sm"
                          disabled={!canEdit || selectedSuite.status === "REJECTED" || isExecuting}
                          onClick={() => handleExecuteSuite(selectedSuite.id)}
                          className="text-xs h-8 bg-blue-600 hover:bg-blue-700 text-white"
                        >
                          <Play className="h-3.5 w-3.5 mr-1" />
                          Execute Suite
                        </Button>
                      </div>
                    </CardHeader>

                    {/* Rejection Input Box (if active) */}
                    {rejectingSuiteId === selectedSuite.id && (
                      <div className="p-4 bg-rose-50 border-b border-rose-200 space-y-2">
                        <label className="text-xs font-semibold text-rose-800 block">
                          Reason for rejection (optional audit comment):
                        </label>
                        <div className="flex items-center gap-2">
                          <Input
                            placeholder="e.g. Inappropriate assertion or unsupported fixture..."
                            value={rejectionReason}
                            onChange={(e) => setRejectionReason(e.target.value)}
                            className="text-xs bg-white"
                          />
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => handleRejectSuite(selectedSuite.id)}
                            className="text-xs h-8"
                          >
                            Confirm Reject
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setRejectingSuiteId(null)}
                            className="text-xs h-8"
                          >
                            Cancel
                          </Button>
                        </div>
                      </div>
                    )}

                    <CardContent className="p-4 space-y-4">
                      <div className="text-xs font-semibold text-slate-700">
                        Synthesized Test Cases ({selectedSuite.test_cases?.length || 0})
                      </div>

                      {(!selectedSuite.test_cases || selectedSuite.test_cases.length === 0) ? (
                        <div className="p-6 text-center text-xs text-slate-400">
                          No test cases contained in this suite.
                        </div>
                      ) : (
                        <div className="space-y-4">
                          {selectedSuite.test_cases.map((tc, idx) => (
                            <div key={idx} className="border border-slate-200 rounded-md p-3 bg-slate-50/50 space-y-2">
                              <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                  <Code2 className="h-4 w-4 text-blue-600" />
                                  <span className="font-semibold text-xs text-slate-800">{tc.name}</span>
                                  {tc.is_edge_case && (
                                    <Badge variant="warning" className="text-[10px]">
                                      Edge Case
                                    </Badge>
                                  )}
                                </div>
                                <span className="text-[10px] text-slate-500 font-mono">{tc.test_type}</span>
                              </div>
                              <p className="text-xs text-slate-600">{tc.description}</p>
                              {tc.relevance_explanation && (
                                <p className="text-[11px] text-slate-500 italic">
                                  Rationale: {tc.relevance_explanation}
                                </p>
                              )}
                              <div className="bg-slate-900 text-slate-100 font-mono text-[11px] p-3 rounded overflow-x-auto">
                                <pre>{tc.code}</pre>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                ) : (
                  <Card className="border-slate-200 bg-white p-8 text-center text-xs text-slate-400">
                    Select a test suite from the left or generate a new one to view details and code.
                  </Card>
                )}
              </div>
            </div>
          </TabsContent>

          {/* TAB 2: FRAMEWORK DETECTION */}
          <TabsContent value="detect" className="space-y-6">
            <Card className="border-slate-200 bg-white">
              <CardHeader className="pb-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <Search className="h-4 w-4 text-blue-600" />
                    Automated Test Framework Detection
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Inspects repository configuration files, test directories, and runner binaries.
                  </CardDescription>
                </div>
                <div className="flex items-center gap-2">
                  <Input
                    placeholder="Optional subpath (e.g. backend/)"
                    value={subpath}
                    onChange={(e) => setSubpath(e.target.value)}
                    className="text-xs h-8 w-56"
                  />
                  <Button
                    size="sm"
                    onClick={handleDetectFrameworks}
                    disabled={detecting || !selectedRepoId}
                    className="text-xs h-8 bg-blue-600 hover:bg-blue-700 text-white"
                  >
                    <RefreshCw className={`h-3.5 w-3.5 mr-1 ${detecting ? "animate-spin" : ""}`} />
                    Run Detection
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {detectedFrameworksList.length === 0 ? (
                  <div className="py-8 text-center text-xs text-slate-400">
                    Click &quot;Run Detection&quot; to inspect available testing frameworks in this repository.
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {detectedFrameworksList.map((f, i) => (
                      <div key={i} className="border border-slate-200 rounded-lg p-4 bg-slate-50/40 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-sm text-slate-800">
                            {f.framework} ({f.language})
                          </span>
                          <Badge variant={f.is_available ? "default" : "destructive"} className="text-xs">
                            {f.is_available ? "Available" : "Missing Tools"}
                          </Badge>
                        </div>
                        <div className="text-xs space-y-1 text-slate-600 font-mono">
                          <p>Config file: <span className="text-slate-800">{f.config_file || "None detected"}</span></p>
                          <p>Test dir: <span className="text-slate-800">{f.test_directory}</span></p>
                          <p>Naming: <span className="text-slate-800">{f.naming_convention}</span></p>
                          <p>Command: <span className="text-blue-700">{f.runner_command}</span></p>
                          <p>Confidence: <span className="text-emerald-700">{Math.round(f.confidence * 100)}%</span></p>
                        </div>
                        {f.missing_requirements && f.missing_requirements.length > 0 && (
                          <div className="mt-2 text-xs text-rose-600">
                            Missing: {f.missing_requirements.join(", ")}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* TAB 3: EXECUTION RUNNER */}
          <TabsContent value="execution" className="space-y-6">
            <Card className="border-slate-200 bg-white">
              <CardHeader className="pb-3 flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <Play className="h-4 w-4 text-blue-600" />
                    Controlled Test Execution Runner
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Sandboxed, timeout-guarded test suite execution with live status and output capture.
                  </CardDescription>
                </div>
                <div className="flex items-center gap-2">
                  <Input
                    placeholder="Custom command (optional)"
                    value={customCommand}
                    onChange={(e) => setCustomCommand(e.target.value)}
                    className="text-xs h-8 w-52"
                  />
                  {activeExecution && (activeExecution.status === "RUNNING" || activeExecution.status === "PENDING") && (
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={handleCancelExecution}
                      className="text-xs h-8"
                    >
                      <StopCircle className="h-3.5 w-3.5 mr-1" />
                      Cancel Execution
                    </Button>
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-6">
                {activeExecution ? (
                  <div className="space-y-4">
                    {/* Status header card */}
                    <div className="p-4 rounded-lg border border-slate-200 bg-slate-50 flex flex-wrap items-center justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-xs text-slate-800">Execution Status:</span>
                          <Badge
                            variant={
                              activeExecution.status === "PASSED"
                                ? "default"
                                : activeExecution.status === "FAILED"
                                ? "destructive"
                                : activeExecution.status === "RUNNING"
                                ? "warning"
                                : "secondary"
                            }
                          >
                            {activeExecution.status}
                          </Badge>
                          {activeExecution.status === "RUNNING" && (
                            <RefreshCw className="h-3.5 w-3.5 text-blue-600 animate-spin" />
                          )}
                        </div>
                        <p className="text-[11px] text-slate-500 font-mono mt-1">
                          Command: {activeExecution.command} • Duration: {activeExecution.duration_ms}ms
                        </p>
                      </div>

                      <div className="flex items-center gap-4 text-xs font-mono">
                        <span className="text-emerald-600 font-semibold">{activeExecution.passed_count} Passed</span>
                        <span className="text-rose-600 font-semibold">{activeExecution.failed_count} Failed</span>
                        <span className="text-slate-500">{activeExecution.skipped_count} Skipped</span>
                      </div>

                      {activeExecution.failed_count > 0 && (
                        <Button
                          size="sm"
                          onClick={handleDiagnose}
                          disabled={isDiagnosing}
                          className="text-xs h-8 bg-purple-600 hover:bg-purple-700 text-white"
                        >
                          <Stethoscope className="h-3.5 w-3.5 mr-1" />
                          {isDiagnosing ? "Diagnosing..." : "Diagnose Failures with AI"}
                        </Button>
                      )}
                    </div>

                    {/* Results Table */}
                    <div>
                      <h4 className="text-xs font-semibold text-slate-800 mb-2">Individual Test Outcomes</h4>
                      {testResults.length === 0 ? (
                        <div className="text-xs text-slate-400 p-4 border rounded text-center">
                          {activeExecution.status === "RUNNING"
                            ? "Waiting for runner to conclude..."
                            : "No individual test results recorded."}
                        </div>
                      ) : (
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="text-xs">Test Name</TableHead>
                              <TableHead className="text-xs">Status</TableHead>
                              <TableHead className="text-xs">Duration</TableHead>
                              <TableHead className="text-xs">Message / Traceback</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {testResults.map((tr) => (
                              <TableRow key={tr.id}>
                                <TableCell className="font-mono text-xs text-slate-800">{tr.test_name}</TableCell>
                                <TableCell>
                                  <Badge
                                    variant={
                                      tr.status === "PASSED"
                                        ? "default"
                                        : tr.status === "FAILED"
                                        ? "destructive"
                                        : "secondary"
                                    }
                                    className="text-[10px]"
                                  >
                                    {tr.status}
                                  </Badge>
                                </TableCell>
                                <TableCell className="text-xs font-mono text-slate-500">{tr.duration_ms}ms</TableCell>
                                <TableCell className="text-xs font-mono text-rose-600 max-w-md truncate">
                                  {tr.failure_message || tr.traceback || "—"}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      )}
                    </div>

                    {/* Stdout / Stderr logs */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <span className="text-xs font-semibold text-slate-700 block mb-1">Standard Output (stdout)</span>
                        <div className="bg-slate-900 text-slate-200 font-mono text-[11px] p-3 rounded h-48 overflow-y-auto">
                          <pre>{activeExecution.stdout || "(empty stdout)"}</pre>
                        </div>
                      </div>
                      <div>
                        <span className="text-xs font-semibold text-slate-700 block mb-1">Standard Error (stderr)</span>
                        <div className="bg-slate-900 text-rose-300 font-mono text-[11px] p-3 rounded h-48 overflow-y-auto">
                          <pre>{activeExecution.stderr || "(empty stderr)"}</pre>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="py-8 text-center text-xs text-slate-400">
                    No active execution. Select an approved test suite from the &quot;Test Suites&quot; tab and click &quot;Execute Suite&quot;.
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* TAB 4: FAILURE DIAGNOSER */}
          <TabsContent value="diagnose" className="space-y-6">
            <Card className="border-slate-200 bg-white">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <Stethoscope className="h-4 w-4 text-purple-600" />
                  AI Root Cause & Failure Diagnosis
                </CardTitle>
                <CardDescription className="text-xs">
                  Automated stack trace analysis, AST error localization, and concrete fix recommendations.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {diagnosis ? (
                  <div className="space-y-4">
                    <div className="p-4 rounded-lg bg-purple-50/60 border border-purple-200 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-xs text-purple-900">
                          Failing Test: {diagnosis.failing_test}
                        </span>
                        <Badge variant="outline" className="text-purple-700 border-purple-300 text-xs">
                          Confidence: {Math.round(diagnosis.confidence * 100)}%
                        </Badge>
                      </div>
                      <p className="text-xs text-rose-700 font-mono">{diagnosis.error_message}</p>
                    </div>

                    <div className="space-y-2">
                      <h4 className="text-xs font-semibold text-slate-800">Root Cause Analysis</h4>
                      <div className="text-xs text-slate-700 p-3 bg-slate-50 border rounded whitespace-pre-wrap">
                        {diagnosis.root_cause_analysis}
                      </div>
                    </div>

                    <div className="space-y-2">
                      <h4 className="text-xs font-semibold text-slate-800">Suggested Fixes</h4>
                      <ul className="space-y-1.5">
                        {diagnosis.fix_suggestions.map((sug, i) => (
                          <li key={i} className="text-xs text-slate-700 flex items-start gap-2">
                            <span className="font-bold text-blue-600">•</span>
                            <span>{sug}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    {diagnosis.affected_files && diagnosis.affected_files.length > 0 && (
                      <div className="space-y-1">
                        <h4 className="text-xs font-semibold text-slate-800">Affected Files</h4>
                        <div className="flex flex-wrap gap-2">
                          {diagnosis.affected_files.map((f, i) => (
                            <Badge key={i} variant="secondary" className="font-mono text-xs">
                              {f}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="py-8 text-center text-xs text-slate-400">
                    No active failure diagnosis. Execute a test suite with failing assertions and click &quot;Diagnose Failures with AI&quot;.
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* TAB 5: COVERAGE DASHBOARD */}
          <TabsContent value="coverage" className="space-y-6">
            <Card className="border-slate-200 bg-white">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <BarChart3 className="h-4 w-4 text-blue-600" />
                  Code Coverage Reports
                </CardTitle>
                <CardDescription className="text-xs">
                  Line and branch level test coverage collected during sandboxed executions.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {coverageReports.length === 0 ? (
                  <div className="py-8 text-center text-xs text-slate-400">
                    No coverage reports recorded yet. Run a test suite with coverage collection enabled to view metrics.
                  </div>
                ) : (
                  <div className="space-y-6">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="text-xs">Report ID</TableHead>
                          <TableHead className="text-xs">Line Coverage</TableHead>
                          <TableHead className="text-xs">Branch Coverage</TableHead>
                          <TableHead className="text-xs">Uncovered Files</TableHead>
                          <TableHead className="text-xs">Recorded At</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {coverageReports.map((c) => (
                          <TableRow key={c.id}>
                            <TableCell className="font-mono text-xs text-slate-600">{c.id.slice(0, 8)}</TableCell>
                            <TableCell className="font-semibold text-xs text-blue-600">
                              {c.line_coverage_pct != null ? `${c.line_coverage_pct.toFixed(1)}%` : "Not measured"}
                            </TableCell>
                            <TableCell className="text-xs text-slate-700">
                              {c.branch_coverage_pct != null ? `${c.branch_coverage_pct.toFixed(1)}%` : "Not measured"}
                            </TableCell>
                            <TableCell className="text-xs text-slate-500 font-mono">
                              {c.uncovered_files?.length || 0} files
                            </TableCell>
                            <TableCell className="text-xs text-slate-400">
                              {new Date(c.created_at).toLocaleString()}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>

                    {/* Uncovered Files Details of Latest Report */}
                    {latestCoverage && latestCoverage.uncovered_files && latestCoverage.uncovered_files.length > 0 && (
                      <div className="space-y-2 pt-2 border-t border-slate-100">
                        <span className="text-xs font-semibold text-slate-800">
                          Uncovered Files in Latest Report ({latestCoverage.uncovered_files.length})
                        </span>
                        <div className="flex flex-wrap gap-2">
                          {latestCoverage.uncovered_files.map((file, idx) => (
                            <Badge key={idx} variant="outline" className="font-mono text-[11px] text-slate-600">
                              {file}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}
