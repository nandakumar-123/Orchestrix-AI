"use client";

import * as React from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  ShieldAlert,
  ShieldCheck,
  Play,
  RefreshCw,
  Sparkles,
  ArrowRight,
  Filter,
} from "lucide-react";

import { fetchCurrentUser, WorkspaceMembership } from "@/lib/auth";
import { normalizeApiError } from "@/lib/api-error";
import { fetchWorkspaceRepositories, WorkspaceRepository } from "@/lib/github";
import {
  getScannerAvailability,
  startScan,
  listScans,
  getScan,
  getScanEvents,
  listFindings,
  updateFindingStatus,
  remediateFinding,
  getFindingRemediation,
  ScannerStatusItem,
  SecureFlowFinding,
  SecureFlowScan,
  SecureFlowScanEvent,
  RemediationTaskResponse,
  ScanType,
  FindingStatus,
} from "@/lib/secureflow";

export default function SecurityPage() {
  const [workspaces, setWorkspaces] = React.useState<WorkspaceMembership[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = React.useState<string>("");
  const [currentRole, setCurrentRole] = React.useState<string>("VIEWER");
  const [repositories, setRepositories] = React.useState<WorkspaceRepository[]>([]);
  const [selectedRepoId, setSelectedRepoId] = React.useState<string>("");
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);
  const [activeTab, setActiveTab] = React.useState<string>("findings");

  // Findings explorer state
  const [findings, setFindings] = React.useState<SecureFlowFinding[]>([]);
  const [selectedFinding, setSelectedFinding] = React.useState<SecureFlowFinding | null>(null);
  const [totalFindings, setTotalFindings] = React.useState<number>(0);
  const [severityFilter, setSeverityFilter] = React.useState<string>("");
  const [statusFilter, setStatusFilter] = React.useState<string>("");
  const [categoryFilter, setCategoryFilter] = React.useState<string>("");
  const [loadingFindings, setLoadingFindings] = React.useState<boolean>(false);

  // Remediation & Triage state
  const [remediationTask, setRemediationTask] = React.useState<RemediationTaskResponse | null>(null);
  const [remediating, setRemediating] = React.useState<boolean>(false);
  const [triageStatus, setTriageStatus] = React.useState<FindingStatus>("OPEN");
  const [triageNote, setTriageNote] = React.useState<string>("");
  const [isUpdatingStatus, setIsUpdatingStatus] = React.useState<boolean>(false);

  // Scanners availability state
  const [scanners, setScanners] = React.useState<ScannerStatusItem[]>([]);
  const [allAvailable, setAllAvailable] = React.useState<boolean>(true);

  // Scan triggers & history state
  const [scans, setScans] = React.useState<SecureFlowScan[]>([]);
  const [selectedScan, setSelectedScan] = React.useState<SecureFlowScan | null>(null);
  const [scanEvents, setScanEvents] = React.useState<SecureFlowScanEvent[]>([]);
  const [selectedScanType, setSelectedScanType] = React.useState<ScanType>("FULL");
  const [scanSubpath, setScanSubpath] = React.useState<string>("");
  const [isStartingScan, setIsStartingScan] = React.useState<boolean>(false);
  const [pollScanIntervalId, setPollScanIntervalId] = React.useState<NodeJS.Timeout | null>(null);

  const canEdit = currentRole === "OWNER" || currentRole === "ADMIN" || currentRole === "MEMBER";

  // Load findings and scans for active repository
  const refreshSecurityData = React.useCallback(
    async (repoId: string, wsId: string) => {
      if (!repoId) return;
      setLoadingFindings(true);
      setErrorMessage(null);
      try {
        const [findingsRes, scansRes, scannersRes] = await Promise.all([
          listFindings(repoId, {
            severity: severityFilter || undefined,
            status: statusFilter || undefined,
            category: categoryFilter || undefined,
            limit: 50,
            workspaceId: wsId,
          }),
          listScans(repoId, { limit: 20, workspaceId: wsId }).catch(() => ({ items: [], total: 0, limit: 20, offset: 0 })),
          getScannerAvailability(repoId, wsId).catch(() => ({ scanners: [], all_available: false })),
        ]);

        setFindings(findingsRes.items);
        setTotalFindings(findingsRes.total);
        setScans(scansRes.items);
        setScanners(scannersRes.scanners);
        setAllAvailable(scannersRes.all_available);

        if (scansRes.items.length > 0 && !selectedScan) {
          setSelectedScan(scansRes.items[0]);
        }
      } catch (err: unknown) {
        setErrorMessage(normalizeApiError(err, "Failed to load SecureFlow data"));
      } finally {
        setLoadingFindings(false);
      }
    },
    [categoryFilter, selectedScan, severityFilter, statusFilter]
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
            refreshSecurityData(firstRepo.id, effectiveWsId);
          }
        }
      } catch (err: unknown) {
        setErrorMessage(normalizeApiError(err, "Failed to initialize workspace"));
      }
    }
    init();
  }, [refreshSecurityData]);

  // Clean up polling interval
  React.useEffect(() => {
    return () => {
      if (pollScanIntervalId) clearInterval(pollScanIntervalId);
    };
  }, [pollScanIntervalId]);

  // Handle finding selection
  const handleSelectFinding = async (finding: SecureFlowFinding) => {
    setSelectedFinding(finding);
    setTriageStatus((finding.status as FindingStatus) || "OPEN");
    setTriageNote("");
    setRemediationTask(null);

    // Check if remediation task already exists
    try {
      const task = await getFindingRemediation(selectedRepoId, finding.id, selectedWorkspaceId);
      setRemediationTask(task);
    } catch {
      setRemediationTask(null);
    }
  };

  // Poll active scan until finished
  const startPollingScan = (scanId: string) => {
    if (pollScanIntervalId) clearInterval(pollScanIntervalId);

    const interval = setInterval(async () => {
      try {
        const scan = await getScan(selectedRepoId, scanId, selectedWorkspaceId);
        setSelectedScan(scan);

        if (
          scan.status === "COMPLETED" ||
          scan.status === "FAILED" ||
          scan.status === "CANCELLED" ||
          scan.status === "PARTIALLY_COMPLETED"
        ) {
          clearInterval(interval);
          setPollScanIntervalId(null);
          setIsStartingScan(false);
          await refreshSecurityData(selectedRepoId, selectedWorkspaceId);
        }
      } catch {
        clearInterval(interval);
        setPollScanIntervalId(null);
        setIsStartingScan(false);
      }
    }, 2500);

    setPollScanIntervalId(interval);
  };

  // Start new security scan
  const handleStartScan = async () => {
    if (!selectedRepoId) return;
    setIsStartingScan(true);
    setErrorMessage(null);
    try {
      const newScan = await startScan(
        selectedRepoId,
        {
          scan_type: selectedScanType,
          subpath: scanSubpath.trim() || undefined,
        },
        selectedWorkspaceId
      );

      setSelectedScan(newScan);
      setScans((prev) => [newScan, ...prev.filter((s) => s.id !== newScan.id)]);

      if (newScan.status === "RUNNING" || newScan.status === "PENDING") {
        startPollingScan(newScan.id);
      } else {
        setIsStartingScan(false);
        await refreshSecurityData(selectedRepoId, selectedWorkspaceId);
      }
    } catch (err: unknown) {
      setIsStartingScan(false);
      setErrorMessage(normalizeApiError(err, "Failed to start security scan"));
    }
  };

  // Load audit events for selected scan
  const handleSelectScan = async (scan: SecureFlowScan) => {
    setSelectedScan(scan);
    try {
      const eventsRes = await getScanEvents(selectedRepoId, scan.id, { workspaceId: selectedWorkspaceId });
      setScanEvents(eventsRes.items);
    } catch {
      setScanEvents([]);
    }
  };

  // Update finding triage status
  const handleUpdateStatus = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFinding || !selectedRepoId) return;

    setIsUpdatingStatus(true);
    setErrorMessage(null);
    try {
      const updated = await updateFindingStatus(
        selectedRepoId,
        selectedFinding.id,
        triageStatus,
        triageNote.trim() || undefined,
        selectedWorkspaceId
      );

      setSelectedFinding(updated);
      setFindings((prev) => prev.map((f) => (f.id === updated.id ? updated : f)));
      setTriageNote("");
    } catch (err: unknown) {
      setErrorMessage(normalizeApiError(err, "Failed to update finding status"));
    } finally {
      setIsUpdatingStatus(false);
    }
  };

  // Initiate DevPilot Remediation Bridge
  const handleRemediate = async () => {
    if (!selectedFinding || !selectedRepoId) return;
    setRemediating(true);
    setErrorMessage(null);
    try {
      const task = await remediateFinding(selectedRepoId, selectedFinding.id, selectedWorkspaceId);
      setRemediationTask(task);
    } catch (err: unknown) {
      setErrorMessage(normalizeApiError(err, "Failed to trigger DevPilot remediation"));
    } finally {
      setRemediating(false);
    }
  };

  // Derived Overview Metrics (strictly computed from real backend data)
  let criticalCount = 0;
  let highCount = 0;
  let mediumCount = 0;
  let lowCount = 0;

  findings.forEach((f) => {
    const sev = (f.severity || "").toUpperCase();
    if (sev === "CRITICAL") criticalCount++;
    else if (sev === "HIGH") highCount++;
    else if (sev === "MEDIUM") mediumCount++;
    else if (sev === "LOW") lowCount++;
  });

  const latestScan = selectedScan || (scans.length > 0 ? scans[0] : null);

  const getSeverityBadge = (severity: string) => {
    const s = severity.toUpperCase();
    if (s === "CRITICAL") return <Badge variant="destructive" className="font-semibold text-xs uppercase">Critical</Badge>;
    if (s === "HIGH") return <Badge className="bg-amber-600 text-white font-semibold text-xs uppercase">High</Badge>;
    if (s === "MEDIUM") return <Badge variant="warning" className="text-xs uppercase">Medium</Badge>;
    if (s === "LOW") return <Badge variant="secondary" className="text-xs uppercase">Low</Badge>;
    return <Badge variant="outline" className="text-xs uppercase">{s}</Badge>;
  };

  const getScanStatusBadge = (status: string) => {
    const s = status.toUpperCase();
    if (s === "COMPLETED") return <Badge className="bg-emerald-600 text-white text-xs">Completed</Badge>;
    if (s === "RUNNING") return <Badge className="bg-blue-600 text-white text-xs animate-pulse">Running</Badge>;
    if (s === "PARTIALLY_COMPLETED") return <Badge className="bg-purple-600 text-white text-xs">Partial (Missing Tools)</Badge>;
    if (s === "FAILED") return <Badge variant="destructive" className="text-xs">Failed</Badge>;
    return <Badge variant="outline" className="text-xs">{s}</Badge>;
  };

  return (
    <AppShell>
      <div className="flex-1 space-y-6 p-8 pt-6 max-w-7xl mx-auto">
        {/* Top Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border/40 pb-5">
          <PageHeader
            title="SecureFlow — Application Security Analysis"
            subtitle="Continuous SAST scans, secret detection, taint tracking, and automated DevPilot remediation bridge."
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
                setSelectedFinding(null);
                setSelectedScan(null);
                refreshSecurityData(nextId, wsId);
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
              onClick={() => refreshSecurityData(selectedRepoId, selectedWorkspaceId)}
              disabled={loadingFindings}
              className="gap-2"
            >
              <RefreshCw className={`h-4 w-4 ${loadingFindings ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </div>

        {/* Error banner */}
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
              <span className="text-xs text-rose-600 font-semibold uppercase tracking-wider">Critical</span>
              <p className="text-2xl font-bold text-slate-900 mt-1">{criticalCount}</p>
              <span className="text-[11px] text-slate-400 mt-0.5 block">
                {criticalCount === 0 ? "Zero critical vulnerabilities" : "Requires immediate remediation"}
              </span>
            </CardContent>
          </Card>

          <Card className="border-slate-200 bg-white">
            <CardContent className="p-4">
              <span className="text-xs text-amber-600 font-semibold uppercase tracking-wider">High</span>
              <p className="text-2xl font-bold text-slate-900 mt-1">{highCount}</p>
              <span className="text-[11px] text-slate-400 mt-0.5 block">
                {highCount === 0 ? "Zero high severity findings" : "High priority security advisories"}
              </span>
            </CardContent>
          </Card>

          <Card className="border-slate-200 bg-white">
            <CardContent className="p-4">
              <span className="text-xs text-blue-600 font-semibold uppercase tracking-wider">Medium / Low</span>
              <p className="text-2xl font-bold text-slate-900 mt-1">{mediumCount + lowCount}</p>
              <span className="text-[11px] text-slate-400 mt-0.5 block">
                {mediumCount} medium, {lowCount} low
              </span>
            </CardContent>
          </Card>

          <Card className="border-slate-200 bg-white">
            <CardContent className="p-4">
              <span className="text-xs text-slate-500 font-semibold uppercase tracking-wider">Latest Scan Status</span>
              <div className="mt-1">
                {latestScan ? getScanStatusBadge(latestScan.status) : <span className="text-slate-400 text-xs">No scans run</span>}
              </div>
              <span className="text-[11px] text-slate-400 mt-1 block">
                {latestScan ? `Total findings in scan: ${latestScan.total_findings}` : "Trigger a scan to inspect repo"}
              </span>
            </CardContent>
          </Card>
        </div>

        {/* Tabbed Agent Interface */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
          <TabsList className="bg-slate-100 p-1 rounded-lg">
            <TabsTrigger value="findings" className="gap-2 text-xs">
              <ShieldAlert className="h-3.5 w-3.5" />
              Findings Explorer ({findings.length})
            </TabsTrigger>
            <TabsTrigger value="scans" className="gap-2 text-xs">
              <Play className="h-3.5 w-3.5" />
              Scan Runner & History ({scans.length})
            </TabsTrigger>
            <TabsTrigger value="scanners" className="gap-2 text-xs">
              <ShieldCheck className="h-3.5 w-3.5" />
              Scanner Engine Status ({scanners.length})
            </TabsTrigger>
          </TabsList>

          {/* TAB 1: FINDINGS EXPLORER & DETAIL DRAWER */}
          <TabsContent value="findings" className="space-y-6">
            {/* Filter Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 bg-white p-3 border border-slate-200 rounded-lg">
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex items-center gap-1.5 text-xs text-slate-600">
                  <Filter className="h-3.5 w-3.5" />
                  <span>Filters:</span>
                </div>

                <select
                  aria-label="Filter by Severity"
                  className="text-xs px-2.5 py-1.5 border rounded-md bg-white text-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-600"
                  value={severityFilter}
                  onChange={(e) => {
                    setSeverityFilter(e.target.value);
                    refreshSecurityData(selectedRepoId, selectedWorkspaceId);
                  }}
                >
                  <option value="">All Severities</option>
                  <option value="CRITICAL">Critical</option>
                  <option value="HIGH">High</option>
                  <option value="MEDIUM">Medium</option>
                  <option value="LOW">Low</option>
                </select>

                <select
                  aria-label="Filter by Status"
                  className="text-xs px-2.5 py-1.5 border rounded-md bg-white text-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-600"
                  value={statusFilter}
                  onChange={(e) => {
                    setStatusFilter(e.target.value);
                    refreshSecurityData(selectedRepoId, selectedWorkspaceId);
                  }}
                >
                  <option value="">All Lifecycle Statuses</option>
                  <option value="OPEN">Open</option>
                  <option value="CONFIRMED">Confirmed</option>
                  <option value="FALSE_POSITIVE">False Positive</option>
                  <option value="ACCEPTED_RISK">Accepted Risk</option>
                  <option value="RESOLVED">Resolved</option>
                </select>

                <select
                  aria-label="Filter by Category"
                  className="text-xs px-2.5 py-1.5 border rounded-md bg-white text-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-600"
                  value={categoryFilter}
                  onChange={(e) => {
                    setCategoryFilter(e.target.value);
                    refreshSecurityData(selectedRepoId, selectedWorkspaceId);
                  }}
                >
                  <option value="">All Categories</option>
                  <option value="secrets">Hardcoded Secrets</option>
                  <option value="sast">SAST / Code Flaws</option>
                  <option value="dependencies">Vulnerable Dependencies</option>
                </select>
              </div>

              <span className="text-xs text-slate-500 font-mono">
                Showing {findings.length} of {totalFindings} findings
              </span>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              {/* Left Column: Findings Table */}
              <div className="lg:col-span-7 space-y-4">
                <Card className="border-slate-200 bg-white">
                  <CardContent className="p-0">
                    {findings.length === 0 ? (
                      <div className="p-8 text-center text-xs text-slate-400">
                        No security findings matching the current filters. Run a scan to discover vulnerabilities.
                      </div>
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead className="text-xs">Severity</TableHead>
                            <TableHead className="text-xs">Advisory / Title</TableHead>
                            <TableHead className="text-xs">Location</TableHead>
                            <TableHead className="text-xs">Status</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {findings.map((f) => (
                            <TableRow
                              key={f.id}
                              onClick={() => handleSelectFinding(f)}
                              className={`cursor-pointer transition-colors ${
                                selectedFinding?.id === f.id ? "bg-blue-50/70" : "hover:bg-slate-50"
                              }`}
                            >
                              <TableCell className="w-24">
                                {getSeverityBadge(f.severity)}
                              </TableCell>
                              <TableCell>
                                <p className="font-semibold text-xs text-slate-800 line-clamp-1">{f.title}</p>
                                <span className="text-[10px] text-slate-400 font-mono">
                                  {f.rule_id} • {f.scanner}
                                </span>
                              </TableCell>
                              <TableCell className="text-xs font-mono text-slate-500 max-w-40 truncate">
                                {f.file_path ? `${f.file_path}:${f.line_start || 1}` : "Dependency manifest"}
                              </TableCell>
                              <TableCell>
                                <Badge variant="outline" className="text-[10px] uppercase">
                                  {f.status}
                                </Badge>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                  </CardContent>
                </Card>
              </div>

              {/* Right Column: Finding Detail & Remediation Drawer */}
              <div className="lg:col-span-5 space-y-4">
                {selectedFinding ? (
                  <Card className="border-slate-200 bg-white shadow-xs">
                    <CardHeader className="pb-3 border-b border-slate-100">
                      <div className="flex items-center justify-between">
                        {getSeverityBadge(selectedFinding.severity)}
                        <span className="text-xs text-slate-500 font-mono">{selectedFinding.category}</span>
                      </div>
                      <CardTitle className="text-sm font-semibold mt-2">{selectedFinding.title}</CardTitle>
                      <CardDescription className="text-xs font-mono">
                        Rule: {selectedFinding.rule_id} • Scanner: {selectedFinding.scanner}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="p-4 space-y-4">
                      {/* File location */}
                      <div>
                        <span className="text-xs font-semibold text-slate-700 block mb-1">Code Location:</span>
                        <p className="text-xs font-mono text-slate-800 bg-slate-50 p-2 rounded border border-slate-200/80">
                          {selectedFinding.file_path || "Repository dependency specification"}
                          {selectedFinding.line_start && ` : line ${selectedFinding.line_start}`}
                          {selectedFinding.line_end && `-${selectedFinding.line_end}`}
                        </p>
                      </div>

                      {/* Description */}
                      <div>
                        <span className="text-xs font-semibold text-slate-700 block mb-1">Vulnerability Description:</span>
                        <p className="text-xs text-slate-600 bg-slate-50/50 p-2.5 rounded border border-slate-200/60 whitespace-pre-wrap">
                          {selectedFinding.description}
                        </p>
                      </div>

                      {/* Redacted Evidence */}
                      {selectedFinding.redacted_evidence && (
                        <div>
                          <span className="text-xs font-semibold text-slate-700 block mb-1">Evidence (Secrets Redacted):</span>
                          <div className="bg-slate-900 text-slate-200 font-mono text-[11px] p-2.5 rounded overflow-x-auto">
                            <pre>{selectedFinding.redacted_evidence}</pre>
                          </div>
                        </div>
                      )}

                      {/* Remediation recommendation */}
                      {selectedFinding.remediation_recommendation && (
                        <div>
                          <span className="text-xs font-semibold text-slate-700 block mb-1">Remediation Guidance:</span>
                          <p className="text-xs text-slate-600 bg-emerald-50/50 border border-emerald-200 p-2.5 rounded">
                            {selectedFinding.remediation_recommendation}
                          </p>
                        </div>
                      )}

                      {/* DevPilot Autonomous Remediation Bridge */}
                      <div className="p-3.5 rounded-lg border border-blue-200 bg-blue-50/40 space-y-3">
                        <div className="flex items-center gap-2">
                          <Sparkles className="h-4 w-4 text-blue-600" />
                          <span className="font-semibold text-xs text-blue-900">
                            DevPilot Autonomous Remediation
                          </span>
                        </div>

                        {remediationTask ? (
                          <div className="space-y-2">
                            <p className="text-xs text-slate-700">
                              Remediation task created with DevPilot:
                            </p>
                            <div className="p-2.5 bg-white border border-blue-200 rounded flex items-center justify-between">
                              <div>
                                <p className="font-semibold text-xs text-slate-800">{remediationTask.task_title}</p>
                                <span className="text-[10px] font-mono text-slate-500">Status: {remediationTask.task_status}</span>
                              </div>
                              <Link href="/devpilot">
                                <Button size="sm" variant="outline" className="text-xs h-7 gap-1">
                                  <span>View in DevPilot</span>
                                  <ArrowRight className="h-3 w-3" />
                                </Button>
                              </Link>
                            </div>
                          </div>
                        ) : (
                          <div className="space-y-2">
                            <p className="text-xs text-slate-600">
                              Dispatch this vulnerability to DevPilot to automatically synthesize a repair plan, write safe code patches, and verify tests.
                            </p>
                            <Button
                              size="sm"
                              onClick={handleRemediate}
                              disabled={!canEdit || remediating}
                              className="w-full text-xs h-8 bg-blue-600 hover:bg-blue-700 text-white"
                            >
                              {remediating ? (
                                <>
                                  <RefreshCw className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                                  Creating DevPilot Remediation Task...
                                </>
                              ) : (
                                <>
                                  <Sparkles className="h-3.5 w-3.5 mr-1.5" />
                                  Remediate with DevPilot
                                </>
                              )}
                            </Button>
                          </div>
                        )}
                      </div>

                      {/* Status Triage Action */}
                      <form onSubmit={handleUpdateStatus} className="pt-2 border-t border-slate-100 space-y-3">
                        <span className="text-xs font-semibold text-slate-700 block">Triage Finding Status:</span>
                        <div className="flex items-center gap-2">
                          <select
                            aria-label="Triage Status Selection"
                            className="text-xs px-2.5 py-1.5 border rounded bg-white text-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-600"
                            value={triageStatus}
                            disabled={!canEdit || isUpdatingStatus}
                            onChange={(e) => setTriageStatus(e.target.value as FindingStatus)}
                          >
                            <option value="OPEN">OPEN</option>
                            <option value="CONFIRMED">CONFIRMED</option>
                            <option value="FALSE_POSITIVE">FALSE POSITIVE</option>
                            <option value="ACCEPTED_RISK">ACCEPTED RISK</option>
                            <option value="RESOLVED">RESOLVED</option>
                          </select>

                          <Input
                            placeholder="Optional audit comment / note..."
                            value={triageNote}
                            disabled={!canEdit || isUpdatingStatus}
                            onChange={(e) => setTriageNote(e.target.value)}
                            className="text-xs h-8"
                          />

                          <Button
                            type="submit"
                            size="sm"
                            disabled={!canEdit || isUpdatingStatus}
                            className="text-xs h-8"
                          >
                            Update
                          </Button>
                        </div>
                      </form>
                    </CardContent>
                  </Card>
                ) : (
                  <Card className="border-slate-200 bg-white p-8 text-center text-xs text-slate-400">
                    Select a finding from the table to view details, inspect redacted evidence, update triage status, or trigger DevPilot remediation.
                  </Card>
                )}
              </div>
            </div>
          </TabsContent>

          {/* TAB 2: SCAN RUNNER & HISTORY */}
          <TabsContent value="scans" className="space-y-6">
            <Card className="border-slate-200 bg-white">
              <CardHeader className="pb-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <Play className="h-4 w-4 text-blue-600" />
                    Trigger Security Scan
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Run static analysis, secret detection, and dependency audits across the repository.
                  </CardDescription>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <select
                    aria-label="Scan Type Selection"
                    className="text-xs px-2.5 py-1.5 border rounded-md bg-white text-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-600"
                    value={selectedScanType}
                    disabled={!canEdit || isStartingScan}
                    onChange={(e) => setSelectedScanType(e.target.value as ScanType)}
                  >
                    <option value="FULL">FULL (Secrets + SAST + Deps)</option>
                    <option value="SECRETS">Secrets Detection Only</option>
                    <option value="DEPENDENCIES">Dependency Auditing Only</option>
                    <option value="SAST">SAST Code Rules Only</option>
                  </select>

                  <Input
                    placeholder="Optional subpath (e.g. backend/)"
                    value={scanSubpath}
                    disabled={!canEdit || isStartingScan}
                    onChange={(e) => setScanSubpath(e.target.value)}
                    className="text-xs h-8 w-44"
                  />

                  <Button
                    size="sm"
                    onClick={handleStartScan}
                    disabled={!canEdit || isStartingScan || !selectedRepoId}
                    className="text-xs h-8 bg-blue-600 hover:bg-blue-700 text-white"
                  >
                    <Play className={`h-3.5 w-3.5 mr-1 ${isStartingScan ? "animate-spin" : ""}`} />
                    {isStartingScan ? "Scanning..." : "Start Security Scan"}
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-6">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-xs">Scan ID</TableHead>
                      <TableHead className="text-xs">Type</TableHead>
                      <TableHead className="text-xs">Status</TableHead>
                      <TableHead className="text-xs">Findings Count</TableHead>
                      <TableHead className="text-xs">Started At</TableHead>
                      <TableHead className="text-xs">Completed At</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {scans.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center text-xs text-slate-400 py-6">
                          No scans executed yet. Click &quot;Start Security Scan&quot; to begin.
                        </TableCell>
                      </TableRow>
                    ) : (
                      scans.map((s) => (
                        <TableRow
                          key={s.id}
                          onClick={() => handleSelectScan(s)}
                          className={`cursor-pointer transition-colors ${
                            selectedScan?.id === s.id ? "bg-blue-50/70" : "hover:bg-slate-50"
                          }`}
                        >
                          <TableCell className="font-mono text-xs text-slate-700">{s.id.slice(0, 8)}</TableCell>
                          <TableCell className="text-xs font-semibold text-slate-800">{s.scan_type}</TableCell>
                          <TableCell>{getScanStatusBadge(s.status)}</TableCell>
                          <TableCell className="text-xs font-mono">
                            <span className="text-rose-600 font-bold">{s.critical_count} C</span> •{" "}
                            <span className="text-amber-600 font-bold">{s.high_count} H</span> •{" "}
                            <span className="text-slate-600">{s.total_findings} Total</span>
                          </TableCell>
                          <TableCell className="text-xs text-slate-400">
                            {s.started_at ? new Date(s.started_at).toLocaleString() : "—"}
                          </TableCell>
                          <TableCell className="text-xs text-slate-400">
                            {s.completed_at ? new Date(s.completed_at).toLocaleString() : "—"}
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>

                {/* Audit Events for selected scan */}
                {selectedScan && (
                  <div className="pt-4 border-t border-slate-100 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-slate-800">
                        Scan Audit Log & Events (Scan: {selectedScan.id.slice(0, 8)})
                      </span>
                      {selectedScan.status === "PARTIALLY_COMPLETED" && (
                        <span className="text-xs text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-200">
                          One or more scanner tools were unavailable on host
                        </span>
                      )}
                    </div>

                    {scanEvents.length === 0 ? (
                      <p className="text-xs text-slate-400">No events recorded for this scan.</p>
                    ) : (
                      <div className="divide-y divide-slate-100 border border-slate-200 rounded max-h-56 overflow-y-auto">
                        {scanEvents.map((ev) => (
                          <div key={ev.id} className="p-2.5 text-xs flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <Badge variant="outline" className="font-mono text-[10px]">
                                {ev.event_type}
                              </Badge>
                              <span className="text-slate-700">{ev.message}</span>
                            </div>
                            <span className="text-[10px] text-slate-400 font-mono">
                              {new Date(ev.created_at).toLocaleTimeString()}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* TAB 3: SCANNER ENGINE STATUS */}
          <TabsContent value="scanners" className="space-y-6">
            <Card className="border-slate-200 bg-white">
              <CardHeader className="pb-3 flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4 text-blue-600" />
                    Security Scanner Engine Status
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Inspects host availability of static analysis tools, vulnerability databases, and secret checkers.
                  </CardDescription>
                </div>
                <Badge variant={allAvailable ? "default" : "secondary"} className="text-xs">
                  {allAvailable ? "All Scanners Available" : "Partial Availability"}
                </Badge>
              </CardHeader>
              <CardContent>
                {scanners.length === 0 ? (
                  <div className="py-8 text-center text-xs text-slate-400">
                    No scanner engines reported.
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {scanners.map((sc, i) => (
                      <div key={i} className="border border-slate-200 rounded-lg p-4 bg-slate-50/40 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-sm text-slate-800">{sc.scanner}</span>
                          <Badge variant={sc.is_available ? "default" : "destructive"} className="text-[11px]">
                            {sc.is_available ? "Available" : "Missing Tool"}
                          </Badge>
                        </div>
                        <div className="text-xs space-y-1 text-slate-600 font-mono">
                          <p>Category: <span className="text-slate-800">{sc.category}</span></p>
                          <p>Version: <span className="text-slate-800">{sc.version || "N/A"}</span></p>
                          <p>Binary: <span className="text-slate-800 max-w-44 truncate block">{sc.binary_path || "Built-in"}</span></p>
                        </div>
                        {sc.details && (
                          <p className="text-[11px] text-slate-500 pt-1 border-t border-slate-100">
                            {sc.details}
                          </p>
                        )}
                      </div>
                    ))}
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
