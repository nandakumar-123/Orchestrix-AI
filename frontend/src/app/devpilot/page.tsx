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
  Sparkles,
  Bot,
  CheckCircle2,
  AlertTriangle,
  ShieldCheck,
  FileCode,
  RefreshCw,
  XCircle,
  Play,
  Check,
  ListTodo,
  ShieldAlert,
} from "lucide-react";

import { fetchCurrentUser } from "@/lib/auth";
import { normalizeApiError } from "@/lib/api-error";
import { fetchWorkspaceRepositories, WorkspaceRepository } from "@/lib/github";
import {
  DevPilotTaskDetail,
  DevPilotTaskType,
  DevPilotExecutionMode,
  DevPilotEngineeringPlan,
  DevPilotDiffResponse,
  DevPilotReviewResponse,
  DevPilotValidationResponse,
  createDevPilotTask,
  listDevPilotTasks,
  getDevPilotTask,
  getDevPilotPlan,
  approveDevPilotPlan,
  approveDevPilotChanges,
  getDevPilotDiff,
  getDevPilotReview,
  triggerDevPilotValidation,
  cancelDevPilotTask,
} from "@/lib/devpilot";

const TASK_TYPES: { type: DevPilotTaskType; label: string; desc: string }[] = [
  { type: "FEATURE", label: "New Feature", desc: "Design & implement end-to-end functionality" },
  { type: "BUG_FIX", label: "Bug Fix", desc: "Diagnose stack trace & repair root cause" },
  { type: "REFACTOR", label: "Refactor", desc: "Improve structure while preserving behavior" },
  { type: "TESTING", label: "Add Tests", desc: "Generate targeted regression & unit tests" },
  { type: "API_DEVELOPMENT", label: "API Endpoint", desc: "Build REST/GraphQL endpoints with schemas" },
  { type: "PERFORMANCE_OPTIMIZATION", label: "Performance", desc: "Optimize queries, loops, and caching" },
];

const LIFECYCLE_STEPS = [
  { key: "CREATED", label: "Created" },
  { key: "ANALYZING", label: "Context Analysis" },
  { key: "PLANNING", label: "Planning" },
  { key: "AWAITING_APPROVAL", label: "Plan Approval Gate" },
  { key: "GENERATING", label: "Generating Code" },
  { key: "REVIEWING", label: "Code Review" },
  { key: "AWAITING_MODIFICATION_APPROVAL", label: "Change Approval Gate" },
  { key: "APPLYING", label: "Applying" },
  { key: "VALIDATING", label: "Validation" },
  { key: "COMPLETED", label: "Completed" },
];

export default function DevPilotPage() {
  const [repositories, setRepositories] = React.useState<WorkspaceRepository[]>([]);
  const [selectedRepoId, setSelectedRepoId] = React.useState<string>("");
  const [selectedWorkspaceId, setSelectedWorkspaceId] = React.useState<string>("");

  // Task creation state
  const [taskType, setTaskType] = React.useState<DevPilotTaskType>("FEATURE");
  const [taskTitle, setTaskTitle] = React.useState("");
  const [taskDescription, setTaskDescription] = React.useState("");
  const [executionMode, setExecutionMode] = React.useState<DevPilotExecutionMode>("STANDARD");
  const [filesOfInterest, setFilesOfInterest] = React.useState("");
  const [isSubmitting, setIsSubmitting] = React.useState(false);

  // Active task state
  const [activeTask, setActiveTask] = React.useState<DevPilotTaskDetail | null>(null);
  const [plan, setPlan] = React.useState<DevPilotEngineeringPlan | null>(null);
  const [diff, setDiff] = React.useState<DevPilotDiffResponse | null>(null);
  const [review, setReview] = React.useState<DevPilotReviewResponse | null>(null);
  const [validation, setValidation] = React.useState<DevPilotValidationResponse | null>(null);
  const [taskList, setTaskList] = React.useState<DevPilotTaskDetail[]>([]);
  const [loadingTask, setLoadingTask] = React.useState(false);

  // Approval actions
  const [approvalComment, setApprovalComment] = React.useState("");
  const [rejectionReason, setRejectionReason] = React.useState("");
  const [isApproving, setIsApproving] = React.useState(false);
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

  // Active view tab in details
  const [activeTab, setActiveTab] = React.useState<"plan" | "diff" | "review" | "validation">("plan");

  const selectTask = React.useCallback(
    async (task: DevPilotTaskDetail, repoId: string = selectedRepoId, wsId?: string) => {
      setLoadingTask(true);
      setErrorMessage(null);
      const effectiveWsId = wsId || selectedWorkspaceId;
      try {
        const detail = await getDevPilotTask(repoId, task.id, effectiveWsId);
        setActiveTask(detail);

        if (detail.latest_plan) {
          setPlan(detail.latest_plan);
        } else {
          getDevPilotPlan(repoId, task.id, effectiveWsId)
            .then(setPlan)
            .catch(() => setPlan(null));
        }

        getDevPilotDiff(repoId, task.id, effectiveWsId)
          .then(setDiff)
          .catch(() => setDiff(null));

        getDevPilotReview(repoId, task.id, effectiveWsId)
          .then(setReview)
          .catch(() => setReview(null));

        if (detail.status === "AWAITING_APPROVAL" || detail.status === "PLANNING") {
          setActiveTab("plan");
        } else if (
          detail.status === "AWAITING_MODIFICATION_APPROVAL" ||
          detail.status === "APPLYING"
        ) {
          setActiveTab("diff");
        } else if (detail.status === "REVIEWING") {
          setActiveTab("review");
        } else if (detail.status === "VALIDATING" || detail.status === "COMPLETED") {
          setActiveTab("validation");
        }
      } catch (err: unknown) {
        const msg = normalizeApiError(err, "Failed to load task details");
        setErrorMessage(msg);
      } finally {
        setLoadingTask(false);
      }
    },
    [selectedRepoId, selectedWorkspaceId]
  );

  const refreshTasks = React.useCallback(
    async (repoId: string, wsId?: string) => {
      if (!repoId) return;
      const effectiveWsId = wsId || selectedWorkspaceId;
      try {
        const res = await listDevPilotTasks(repoId, { limit: 20, workspaceId: effectiveWsId });
        setTaskList(res.tasks);
        if (res.tasks.length > 0 && !activeTask) {
          selectTask(res.tasks[0], repoId, effectiveWsId);
        }
      } catch (err: unknown) {
        const msg = normalizeApiError(err, "Failed to load tasks");
        console.error("Failed to list tasks:", msg);
        setErrorMessage(msg);
      }
    },
    [activeTask, selectTask, selectedWorkspaceId]
  );

  // Load repositories and initial workspace
  React.useEffect(() => {
    async function init() {
      try {
        const u = await fetchCurrentUser();
        if (u && u.workspaces && u.workspaces.length > 0) {
          const wsId = u.workspaces[0].workspace_id;
          setSelectedWorkspaceId(wsId);
          const repos = await fetchWorkspaceRepositories(wsId);
          setRepositories(repos);
          if (repos.length > 0) {
            const firstRepo = repos[0];
            setSelectedRepoId(firstRepo.id);
            const repoWsId = firstRepo.workspace_id || wsId;
            setSelectedWorkspaceId(repoWsId);
            refreshTasks(firstRepo.id, repoWsId);
          }
        }
      } catch (err: unknown) {
        const msg = normalizeApiError(err, "Failed to initialize DevPilot workspace");
        console.error("Failed to initialize DevPilot:", msg);
        setErrorMessage(msg);
      }
    }
    init();
  }, [refreshTasks]);

  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedRepoId || !taskTitle.trim() || !taskDescription.trim()) return;

    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      const files = filesOfInterest
        .split(",")
        .map((f) => f.trim())
        .filter(Boolean);

      const newTask = await createDevPilotTask(
        selectedRepoId,
        {
          task_type: taskType,
          title: taskTitle.trim(),
          description: taskDescription.trim(),
          prompt: taskDescription.trim(),
          execution_mode: executionMode,
          files_of_interest: files.length > 0 ? files : undefined,
          auto_validate_tests: true,
        },
        selectedWorkspaceId
      );

      setTaskTitle("");
      setTaskDescription("");
      setFilesOfInterest("");
      await refreshTasks(selectedRepoId, selectedWorkspaceId);
      selectTask(newTask, selectedRepoId, selectedWorkspaceId);
    } catch (err: unknown) {
      const msg = normalizeApiError(err, "Failed to create task");
      setErrorMessage(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleApprovePlan = async (approved: boolean) => {
    if (!activeTask) return;
    setIsApproving(true);
    setErrorMessage(null);
    try {
      const updated = await approveDevPilotPlan(
        selectedRepoId,
        activeTask.id,
        approved,
        approved ? undefined : rejectionReason,
        approvalComment || undefined,
        selectedWorkspaceId
      );
      setActiveTask(updated);
      setApprovalComment("");
      setRejectionReason("");
      await selectTask(updated, selectedRepoId, selectedWorkspaceId);
      await refreshTasks(selectedRepoId, selectedWorkspaceId);
    } catch (err: unknown) {
      const msg = normalizeApiError(err, "Failed to process plan approval");
      setErrorMessage(msg);
    } finally {
      setIsApproving(false);
    }
  };

  const handleApproveChanges = async (approved: boolean) => {
    if (!activeTask) return;
    setIsApproving(true);
    setErrorMessage(null);
    try {
      const updated = await approveDevPilotChanges(
        selectedRepoId,
        activeTask.id,
        approved,
        approved ? undefined : rejectionReason,
        approvalComment || undefined,
        selectedWorkspaceId
      );
      setActiveTask(updated);
      setApprovalComment("");
      setRejectionReason("");
      await selectTask(updated, selectedRepoId, selectedWorkspaceId);
      await refreshTasks(selectedRepoId, selectedWorkspaceId);
    } catch (err: unknown) {
      const msg = normalizeApiError(err, "Failed to process modification approval");
      setErrorMessage(msg);
    } finally {
      setIsApproving(false);
    }
  };

  const handleTriggerValidation = async () => {
    if (!activeTask) return;
    setIsApproving(true);
    setErrorMessage(null);
    try {
      const valRes = await triggerDevPilotValidation(
        selectedRepoId,
        activeTask.id,
        true,
        undefined,
        selectedWorkspaceId
      );
      setValidation(valRes);
      await selectTask(activeTask, selectedRepoId, selectedWorkspaceId);
    } catch (err: unknown) {
      const msg = normalizeApiError(err, "Failed to trigger validation pipeline");
      setErrorMessage(msg);
    } finally {
      setIsApproving(false);
    }
  };

  const handleCancelTask = async () => {
    if (!activeTask) return;
    if (!confirm("Are you sure you want to cancel this DevPilot task?")) return;
    try {
      const updated = await cancelDevPilotTask(
        selectedRepoId,
        activeTask.id,
        "User requested cancellation",
        selectedWorkspaceId
      );
      setActiveTask(updated);
      await refreshTasks(selectedRepoId, selectedWorkspaceId);
    } catch (err: unknown) {
      const msg = normalizeApiError(err, "Failed to cancel task");
      setErrorMessage(msg);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "COMPLETED":
        return <Badge className="bg-emerald-600 text-white font-medium">Completed</Badge>;
      case "AWAITING_APPROVAL":
        return <Badge className="bg-amber-600 text-white font-medium animate-pulse">Awaiting Plan Approval</Badge>;
      case "AWAITING_MODIFICATION_APPROVAL":
        return <Badge className="bg-purple-600 text-white font-medium animate-pulse">Awaiting Code Approval</Badge>;
      case "GENERATING":
        return <Badge className="bg-blue-600 text-white font-medium">Generating Code</Badge>;
      case "VALIDATING":
        return <Badge className="bg-indigo-600 text-white font-medium">Validating</Badge>;
      case "FAILED":
        return <Badge className="bg-red-600 text-white font-medium">Failed</Badge>;
      case "CANCELLED":
        return <Badge className="bg-slate-500 text-white font-medium">Cancelled</Badge>;
      default:
        return <Badge variant="outline" className="text-slate-700 dark:text-slate-200">{status}</Badge>;
    }
  };

  return (
    <AppShell>
      <div className="flex-1 space-y-6 p-8 pt-6 max-w-7xl mx-auto">
        {/* Top Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border/40 pb-5">
          <PageHeader
            title="DevPilot — Autonomous AI Software Engineer"
            subtitle="Repository-aware engineering agent that plans, writes, reviews, and validates code under strict human approval gating."
          />
          <div className="flex items-center gap-3">
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
                }
                setActiveTask(null);
                refreshTasks(nextId, wsId);
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
              onClick={() => refreshTasks(selectedRepoId, selectedWorkspaceId)}
              className="gap-2"
            >
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
          </div>
        </div>

        {/* DevMemory Active Context */}
        <AgentMemoryContext
          agent="DEVPILOT"
          query={activeTask ? activeTask.title : "Architecture conventions and technical decisions"}
          workspaceId={selectedWorkspaceId}
          repositoryId={selectedRepoId}
        />

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

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: Task Creator & Task List (4 cols) */}
          <div className="lg:col-span-4 space-y-6">
            {/* New Task Card */}
            <Card className="border-border/60 shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-primary" />
                  Initiate DevPilot Task
                </CardTitle>
                <CardDescription>
                  Autonomous task with Phase 8 AST, Phase 9 semantics, and Phase 10 Graph awareness.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleCreateTask} className="space-y-4">
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-2">
                      Task Type
                    </label>
                    <div className="grid grid-cols-2 gap-2">
                      {TASK_TYPES.map((t) => (
                        <button
                          key={t.type}
                          type="button"
                          onClick={() => setTaskType(t.type)}
                          className={`text-left p-2 rounded-md border text-xs transition-all ${
                            taskType === t.type
                              ? "border-primary bg-primary/10 font-semibold text-primary"
                              : "border-border hover:bg-muted/50 text-muted-foreground"
                          }`}
                        >
                          {t.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-1">
                      Task Title
                    </label>
                    <Input
                      placeholder="e.g. Implement JWT refresh token rotation"
                      value={taskTitle}
                      onChange={(e) => setTaskTitle(e.target.value)}
                      required
                    />
                  </div>

                  <div>
                    <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-1">
                      Specification & Requirements
                    </label>
                    <textarea
                      rows={3}
                      className="w-full text-xs p-2.5 rounded-md border border-input bg-background focus:outline-none focus:ring-2 focus:ring-primary font-mono shadow-sm"
                      placeholder="Describe the desired behavior, constraints, or bug symptoms..."
                      value={taskDescription}
                      onChange={(e) => setTaskDescription(e.target.value)}
                      required
                    />
                  </div>

                  <div>
                    <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-1">
                      Files of Interest (Optional, comma-separated)
                    </label>
                    <Input
                      placeholder="app/auth.py, app/routes/auth.py"
                      value={filesOfInterest}
                      onChange={(e) => setFilesOfInterest(e.target.value)}
                    />
                  </div>

                  <div className="flex items-center justify-between text-xs pt-1">
                    <span className="text-muted-foreground">Execution Mode:</span>
                    <select
                      aria-label="Execution Mode"
                      value={executionMode}
                      onChange={(e) => setExecutionMode(e.target.value as DevPilotExecutionMode)}
                      className="text-xs p-1 border rounded bg-background"
                    >
                      <option value="STANDARD">Standard (Balanced)</option>
                      <option value="CAREFUL">Careful (Deep Callers)</option>
                      <option value="DIAGNOSTIC_ONLY">Diagnostic Only</option>
                    </select>
                  </div>

                  <Button
                    type="submit"
                    className="w-full gap-2 shadow"
                    disabled={isSubmitting || !selectedRepoId}
                  >
                    {isSubmitting ? (
                      <>
                        <RefreshCw className="h-4 w-4 animate-spin" />
                        Analyzing Repository...
                      </>
                    ) : (
                      <>
                        <Bot className="h-4 w-4" />
                        Draft Engineering Plan
                      </>
                    )}
                  </Button>
                </form>
              </CardContent>
            </Card>

            {/* Task History List */}
            <Card className="border-border/60 shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <ListTodo className="h-4 w-4" />
                    Task History ({taskList.length})
                  </span>
                  {selectedRepoId && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() => refreshTasks(selectedRepoId, selectedWorkspaceId)}
                    >
                      <RefreshCw className="h-3 w-3 mr-1" />
                      Reload
                    </Button>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 max-h-[380px] overflow-y-auto">
                {taskList.length === 0 ? (
                  <div className="text-xs text-muted-foreground text-center py-6 space-y-2">
                    <p>No DevPilot tasks recorded yet.</p>
                    <p className="text-[11px] text-muted-foreground/80">
                      Create an engineering task above or reload to inspect existing tasks.
                    </p>
                  </div>
                ) : (
                  taskList.map((t) => {
                    const isSelected = activeTask?.id === t.id;
                    return (
                      <div
                        key={t.id}
                        onClick={() => selectTask(t, selectedRepoId, selectedWorkspaceId)}
                        className={`p-3 rounded-lg border text-left cursor-pointer transition-all ${
                          isSelected
                            ? "border-primary bg-primary/5 shadow-sm"
                            : "border-border hover:bg-muted/40"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2 mb-1">
                          <span className="text-xs font-semibold truncate text-foreground">
                            {t.title}
                          </span>
                          <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-muted">
                            {t.task_type}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-xs text-muted-foreground">
                          <span>{getStatusBadge(t.status)}</span>
                          <span className="text-[11px]">
                            {t.created_at
                              ? new Date(t.created_at).toLocaleTimeString([], {
                                  hour: "2-digit",
                                  minute: "2-digit",
                                })
                              : "Just now"}
                          </span>
                        </div>
                      </div>
                    );
                  })
                )}
              </CardContent>
            </Card>
          </div>

          {/* Right Column: Active Task Workspace & Human-in-the-Loop Controls (8 cols) */}
          <div className="lg:col-span-8 space-y-6">
            {!activeTask ? (
              <Card className="border-border/60 shadow-sm p-12 text-center">
                <Bot className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
                <h3 className="text-lg font-semibold mb-2">No Active Task Selected</h3>
                <p className="text-sm text-muted-foreground max-w-md mx-auto mb-6">
                  Select an existing task from the history list or initiate a new task to view the
                  structured engineering plan, code diff, review findings, and validation suite.
                </p>
                {selectedRepoId && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => refreshTasks(selectedRepoId, selectedWorkspaceId)}
                    className="gap-2 mx-auto"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    Check for Existing Tasks
                  </Button>
                )}
              </Card>
            ) : (
              <>
                {/* Active Task Summary Card */}
                <Card className="border-border/60 shadow-sm">
                  <CardHeader className="pb-4">
                    <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <Badge variant="outline" className="font-mono text-[11px]">
                            {activeTask.task_type}
                          </Badge>
                          {getStatusBadge(activeTask.status)}
                          <span className="text-xs text-muted-foreground">
                            ID: {activeTask.id ? activeTask.id.substring(0, 8) : "..."}...
                          </span>
                        </div>
                        <CardTitle className="text-xl font-bold">{activeTask.title}</CardTitle>
                      </div>
                      <div className="flex items-center gap-2">
                        {activeTask.status !== "COMPLETED" && activeTask.status !== "CANCELLED" && (
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={handleCancelTask}
                            className="gap-1 text-xs"
                          >
                            <XCircle className="h-3.5 w-3.5" />
                            Cancel
                          </Button>
                        )}
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => selectTask(activeTask, selectedRepoId, selectedWorkspaceId)}
                          disabled={loadingTask}
                          className="gap-1 text-xs"
                        >
                          <RefreshCw className={`h-3.5 w-3.5 ${loadingTask ? "animate-spin" : ""}`} />
                          Refresh
                        </Button>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {/* Lifecycle Progress Stepper */}
                    <div>
                      <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-2">
                        Agent Lifecycle State
                      </span>
                      <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-center text-xs">
                        {LIFECYCLE_STEPS.map((step, idx) => {
                          const currentIdx = LIFECYCLE_STEPS.findIndex(
                            (s) => s.key === activeTask.status
                          );
                          const isDone = currentIdx > idx || activeTask.status === "COMPLETED";
                          const isCurrent = activeTask.status === step.key;

                          return (
                            <div
                              key={step.key}
                              className={`p-2 rounded border text-xs font-medium transition-all ${
                                isCurrent
                                  ? "border-primary bg-primary text-primary-foreground font-bold shadow-sm"
                                  : isDone
                                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                                  : "border-border bg-muted/20 text-muted-foreground"
                              }`}
                            >
                              <div className="truncate">{step.label}</div>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    {/* Clarification prompt alert if any */}
                    {activeTask.clarification_prompt && (
                      <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-700 dark:text-amber-300 text-xs">
                        <strong>Ambiguity Detected:</strong> {activeTask.clarification_prompt}
                      </div>
                    )}

                    {/* Mandatory Approval Checkpoint Banners */}
                    {activeTask.status === "AWAITING_APPROVAL" && (
                      <div className="p-4 rounded-lg bg-amber-500/10 border-2 border-amber-500/40 space-y-3">
                        <div className="flex items-center gap-2 text-amber-800 dark:text-amber-300 font-semibold text-sm">
                          <AlertTriangle className="h-5 w-5" />
                          <span>Human-in-the-Loop Gate 1: Plan Approval Required</span>
                        </div>
                        <p className="text-xs text-amber-900/80 dark:text-amber-200/80">
                          DevPilot has analyzed repository semantics and graph relationships to assemble the
                          14-section plan below. Review the proposed steps, blast radius exposure, and security
                          implications before authorizing code generation.
                        </p>
                        <div className="flex flex-col sm:flex-row items-center gap-2 pt-1">
                          <Input
                            placeholder="Optional feedback or guidance for DevPilot..."
                            value={approvalComment}
                            onChange={(e) => setApprovalComment(e.target.value)}
                            className="text-xs bg-background"
                          />
                          <div className="flex items-center gap-2 w-full sm:w-auto">
                            <Button
                              size="sm"
                              onClick={() => handleApprovePlan(true)}
                              disabled={isApproving}
                              className="bg-emerald-600 hover:bg-emerald-700 text-white gap-1 text-xs flex-1 sm:flex-initial"
                            >
                              <Check className="h-3.5 w-3.5" />
                              Approve Plan & Generate
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleApprovePlan(false)}
                              disabled={isApproving}
                              className="text-red-600 border-red-300 hover:bg-red-50 text-xs"
                            >
                              Reject
                            </Button>
                          </div>
                        </div>
                      </div>
                    )}

                    {activeTask.status === "AWAITING_MODIFICATION_APPROVAL" && (
                      <div className="p-4 rounded-lg bg-purple-500/10 border-2 border-purple-500/40 space-y-3">
                        <div className="flex items-center gap-2 text-purple-800 dark:text-purple-300 font-semibold text-sm">
                          <ShieldCheck className="h-5 w-5" />
                          <span>Human-in-the-Loop Gate 2: Code Modification Approval Required</span>
                        </div>
                        <p className="text-xs text-purple-900/80 dark:text-purple-200/80">
                          DevPilot generated modifications in an isolated sandbox and performed automated code review.
                          Inspect the unified diff and review findings below before authorizing these changes to be applied.
                        </p>
                        <div className="flex flex-col sm:flex-row items-center gap-2 pt-1">
                          <Input
                            placeholder="Optional comments or revision requests..."
                            value={approvalComment}
                            onChange={(e) => setApprovalComment(e.target.value)}
                            className="text-xs bg-background"
                          />
                          <div className="flex items-center gap-2 w-full sm:w-auto">
                            <Button
                              size="sm"
                              onClick={() => handleApproveChanges(true)}
                              disabled={isApproving}
                              className="bg-purple-600 hover:bg-purple-700 text-white gap-1 text-xs flex-1 sm:flex-initial"
                            >
                              <Check className="h-3.5 w-3.5" />
                              Approve Changes & Validate
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleApproveChanges(false)}
                              disabled={isApproving}
                              className="text-red-600 border-red-300 hover:bg-red-50 text-xs"
                            >
                              Reject Changes
                            </Button>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Navigation Tabs */}
                    <div className="border-b border-border flex items-center gap-6 text-sm font-medium pt-2">
                      <button
                        onClick={() => setActiveTab("plan")}
                        className={`pb-2 border-b-2 transition-all flex items-center gap-1.5 ${
                          activeTab === "plan"
                            ? "border-primary text-primary font-semibold"
                            : "border-transparent text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        <ListTodo className="h-4 w-4" />
                        Engineering Plan {plan && `(v${plan.version})`}
                      </button>
                      <button
                        onClick={() => setActiveTab("diff")}
                        className={`pb-2 border-b-2 transition-all flex items-center gap-1.5 ${
                          activeTab === "diff"
                            ? "border-primary text-primary font-semibold"
                            : "border-transparent text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        <FileCode className="h-4 w-4" />
                        Code Modifications {diff && `(${diff.total_files_changed} files)`}
                      </button>
                      <button
                        onClick={() => setActiveTab("review")}
                        className={`pb-2 border-b-2 transition-all flex items-center gap-1.5 ${
                          activeTab === "review"
                            ? "border-primary text-primary font-semibold"
                            : "border-transparent text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        <ShieldAlert className="h-4 w-4" />
                        Review Findings {review && `(${review.total_findings})`}
                      </button>
                      <button
                        onClick={() => setActiveTab("validation")}
                        className={`pb-2 border-b-2 transition-all flex items-center gap-1.5 ${
                          activeTab === "validation"
                            ? "border-primary text-primary font-semibold"
                            : "border-transparent text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        <CheckCircle2 className="h-4 w-4" />
                        Validation Coordinator
                      </button>
                    </div>

                    {/* Tab 1: Engineering Plan Viewer */}
                    {activeTab === "plan" && (
                      <div className="space-y-4 pt-2">
                        {!plan ? (
                          <div className="p-8 text-center text-muted-foreground text-xs">
                            Plan has not yet been drafted for this task.
                          </div>
                        ) : (
                          <div className="space-y-4 text-xs">
                            {/* Exposure & Risk Summary Card */}
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 p-3 rounded-lg border bg-muted/20">
                              <div>
                                <span className="text-[10px] uppercase font-bold text-muted-foreground block">
                                  Structural Exposure Score
                                </span>
                                <div className="flex items-center gap-2 mt-1">
                                  <span className="text-xl font-bold font-mono">
                                    {(plan.exposure_score || 0).toFixed(1)}/100
                                  </span>
                                  <Badge
                                    className={
                                      plan.exposure_tier === "LOW"
                                        ? "bg-emerald-600 text-white"
                                        : plan.exposure_tier === "MEDIUM"
                                        ? "bg-amber-600 text-white"
                                        : "bg-red-600 text-white"
                                    }
                                  >
                                    {plan.exposure_tier}
                                  </Badge>
                                </div>
                              </div>
                              <div>
                                <span className="text-[10px] uppercase font-bold text-muted-foreground block">
                                  Plan Approval Status
                                </span>
                                <div className="mt-1">
                                  <Badge variant="outline" className="font-semibold">
                                    {plan.status}
                                  </Badge>
                                </div>
                              </div>
                              <div>
                                <span className="text-[10px] uppercase font-bold text-muted-foreground block">
                                  Step Count
                                </span>
                                <div className="mt-1 text-sm font-semibold">
                                  {(plan.steps || []).length} Action Items
                                </div>
                              </div>
                            </div>

                            {/* Plan Sections */}
                            <div className="space-y-3">
                              <div className="p-3 rounded-md border bg-card">
                                <h4 className="font-bold text-foreground mb-1">1. Summary & Task Understanding</h4>
                                <p className="text-muted-foreground">{plan.summary || "(No summary provided)"}</p>
                                <p className="mt-1 text-foreground/90 font-mono text-[11px]">
                                  {plan.task_understanding || ""}
                                </p>
                              </div>

                              <div className="p-3 rounded-md border bg-card">
                                <h4 className="font-bold text-foreground mb-1">2. Architectural Context & Impact</h4>
                                <p className="text-muted-foreground">{plan.architectural_context || "(No context provided)"}</p>
                                <p className="mt-1 text-muted-foreground">{plan.blast_radius_summary || ""}</p>
                              </div>

                              <div className="p-3 rounded-md border bg-card">
                                <h4 className="font-bold text-foreground mb-1">3. Rollback & Testing Strategy</h4>
                                <p className="text-muted-foreground mb-1"><strong>Rollback:</strong> {plan.rollback_strategy || "Standard git revert"}</p>
                                <p className="text-muted-foreground"><strong>Testing:</strong> {plan.testing_strategy || "Automated regression tests"}</p>
                              </div>

                              <div className="p-3 rounded-md border bg-card">
                                <h4 className="font-bold text-foreground mb-1">4. Security Implications</h4>
                                <p className="text-muted-foreground">{plan.security_implications || "No immediate security risks identified."}</p>
                              </div>

                              {/* Granular Plan Steps Table */}
                              <div>
                                <h4 className="font-bold text-foreground mb-2">5. Granular Action Steps</h4>
                                <div className="border rounded-md divide-y overflow-hidden">
                                  {(plan.steps || []).map((s) => (
                                    <div key={s.id || s.step_number} className="p-3 bg-card hover:bg-muted/30">
                                      <div className="flex items-center justify-between gap-2 mb-1">
                                        <div className="flex items-center gap-2">
                                          <span className="font-mono text-xs font-bold text-primary">
                                            #{s.step_number}
                                          </span>
                                          <span className="font-semibold text-foreground text-xs">{s.title}</span>
                                        </div>
                                        <div className="flex items-center gap-1.5">
                                          <Badge variant="outline" className="text-[10px] font-mono">
                                            {s.action_type}
                                          </Badge>
                                          <Badge
                                            className={
                                              s.risk_level === "LOW"
                                                ? "bg-emerald-600 text-white text-[10px]"
                                                : s.risk_level === "MEDIUM"
                                                ? "bg-amber-600 text-white text-[10px]"
                                                : "bg-red-600 text-white text-[10px]"
                                            }
                                          >
                                            {s.risk_level}
                                          </Badge>
                                        </div>
                                      </div>
                                      <p className="text-muted-foreground text-[11px] mb-2">{s.description}</p>
                                      <div className="flex flex-wrap gap-1">
                                        {(s.target_files || []).map((tf) => (
                                          <span
                                            key={tf}
                                            className="px-1.5 py-0.5 rounded bg-muted text-[10px] font-mono text-muted-foreground"
                                          >
                                            {tf}
                                          </span>
                                        ))}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Tab 2: Code Modifications & Diff */}
                    {activeTab === "diff" && (
                      <div className="space-y-4 pt-2">
                        {!diff || !diff.changes || diff.changes.length === 0 ? (
                          <div className="p-8 text-center text-muted-foreground text-xs">
                            No code modifications have been generated yet. Complete and approve the plan to
                            generate code.
                          </div>
                        ) : (
                          <div className="space-y-4">
                            <div className="flex items-center justify-between text-xs p-3 rounded-lg border bg-muted/20">
                              <span className="font-semibold">
                                Modified Files: {diff.total_files_changed}
                              </span>
                              <div className="flex items-center gap-3 font-mono text-xs">
                                <span className="text-emerald-600 font-bold">+{diff.additions} lines</span>
                                <span className="text-red-600 font-bold">-{diff.deletions} lines</span>
                              </div>
                            </div>

                            <div className="space-y-3">
                              {diff.changes.map((change) => (
                                <div key={change.id || change.file_path} className="border rounded-md overflow-hidden">
                                  <div className="bg-muted/40 px-3 py-2 border-b flex items-center justify-between text-xs font-mono">
                                    <span className="font-semibold text-foreground flex items-center gap-1.5">
                                      <FileCode className="h-3.5 w-3.5 text-primary" />
                                      {change.file_path}
                                    </span>
                                    <Badge variant="outline" className="text-[10px]">
                                      {change.change_type}
                                    </Badge>
                                  </div>
                                  <pre className="p-3 text-[11px] font-mono overflow-x-auto bg-slate-950 text-slate-100 max-h-[320px]">
                                    <code>{change.diff_hunk || change.new_content || "(No diff content)"}</code>
                                  </pre>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Tab 3: Code Review Findings */}
                    {activeTab === "review" && (
                      <div className="space-y-4 pt-2">
                        {!review || !review.findings || review.findings.length === 0 ? (
                          <div className="p-8 text-center text-muted-foreground text-xs">
                            <ShieldCheck className="h-8 w-8 text-emerald-500 mx-auto mb-2" />
                            No code review findings or defects identified.
                          </div>
                        ) : (
                          <div className="space-y-4">
                            <div className="grid grid-cols-5 gap-2 text-center text-xs">
                              <div className="p-2 rounded border bg-red-500/10 border-red-500/30 text-red-600 font-semibold">
                                {review.critical_count} Critical
                              </div>
                              <div className="p-2 rounded border bg-orange-500/10 border-orange-500/30 text-orange-600 font-semibold">
                                {review.high_count} High
                              </div>
                              <div className="p-2 rounded border bg-amber-500/10 border-amber-500/30 text-amber-600 font-semibold">
                                {review.medium_count} Medium
                              </div>
                              <div className="p-2 rounded border bg-blue-500/10 border-blue-500/30 text-blue-600 font-semibold">
                                {review.low_count} Low
                              </div>
                              <div className="p-2 rounded border bg-slate-500/10 border-slate-500/30 text-slate-600 font-semibold">
                                {review.info_count} Info
                              </div>
                            </div>

                            <div className="border rounded-md divide-y divide-border overflow-hidden">
                              {review.findings.map((finding) => (
                                <div key={finding.id} className="p-3 bg-card hover:bg-muted/20 text-xs">
                                  <div className="flex items-center justify-between gap-2 mb-1">
                                    <div className="flex items-center gap-2">
                                      <Badge
                                        className={
                                          finding.severity === "CRITICAL"
                                            ? "bg-red-600 text-white text-[10px]"
                                            : finding.severity === "HIGH"
                                            ? "bg-orange-600 text-white text-[10px]"
                                            : finding.severity === "MEDIUM"
                                            ? "bg-amber-600 text-white text-[10px]"
                                            : "bg-blue-600 text-white text-[10px]"
                                        }
                                      >
                                        {finding.severity}
                                      </Badge>
                                      <span className="font-semibold text-foreground">{finding.title}</span>
                                    </div>
                                    <span className="font-mono text-[11px] text-muted-foreground">
                                      {finding.file_path}
                                      {finding.line_start && `:${finding.line_start}`}
                                    </span>
                                  </div>
                                  <p className="text-muted-foreground text-[11px] mb-2">{finding.description}</p>
                                  {(finding.suggested_fix || finding.suggested_correction) && (
                                    <div className="p-2 rounded bg-muted/60 text-[11px] font-mono text-foreground">
                                      <strong>Suggested Correction:</strong>{" "}
                                      {finding.suggested_fix || finding.suggested_correction}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Tab 4: Validation Coordinator */}
                    {activeTab === "validation" && (
                      <div className="space-y-4 pt-2">
                        <div className="flex items-center justify-between p-3 rounded-lg border bg-muted/20">
                          <div>
                            <h4 className="text-xs font-bold text-foreground">Multi-Stage Quality Validation</h4>
                            <p className="text-[11px] text-muted-foreground">
                              Syntactic AST checks, ImpactMind blast radius evaluation, and safe regression testing.
                            </p>
                          </div>
                          <Button
                            size="sm"
                            onClick={handleTriggerValidation}
                            disabled={isApproving}
                            className="gap-1.5 text-xs"
                          >
                            <Play className="h-3.5 w-3.5" />
                            Run Validation Pipeline
                          </Button>
                        </div>

                        {!validation || !validation.stages || validation.stages.length === 0 ? (
                          <div className="p-8 text-center text-muted-foreground text-xs">
                            No validation run executed yet. Click &apos;Run Validation Pipeline&apos; to execute AST
                            parsing, impact regression scoring, and controlled test execution.
                          </div>
                        ) : (
                          <div className="space-y-3">
                            {validation.stages.map((stage) => (
                              <div
                                key={stage.id || stage.stage_name}
                                className="p-3 rounded-lg border bg-card space-y-2 text-xs"
                              >
                                <div className="flex items-center justify-between">
                                  <div className="flex items-center gap-2">
                                    <CheckCircle2
                                      className={`h-4 w-4 ${
                                        stage.status === "PASSED"
                                          ? "text-emerald-500"
                                          : stage.status === "FAILED"
                                          ? "text-red-500"
                                          : "text-amber-500"
                                      }`}
                                    />
                                    <span className="font-bold text-foreground">{stage.stage_name}</span>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    {stage.execution_time_ms && (
                                      <span className="font-mono text-[10px] text-muted-foreground">
                                        {stage.execution_time_ms} ms
                                      </span>
                                    )}
                                    <Badge
                                      className={
                                        stage.status === "PASSED"
                                          ? "bg-emerald-600 text-white text-[10px]"
                                          : stage.status === "FAILED"
                                          ? "bg-red-600 text-white text-[10px]"
                                          : "bg-slate-500 text-white text-[10px]"
                                      }
                                    >
                                      {stage.status}
                                    </Badge>
                                  </div>
                                </div>
                                <pre className="p-2 rounded bg-muted text-[10px] font-mono overflow-x-auto text-muted-foreground">
                                  {JSON.stringify(stage.details, null, 2)}
                                </pre>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
