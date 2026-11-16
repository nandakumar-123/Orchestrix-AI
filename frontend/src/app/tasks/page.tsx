"use client";

import * as React from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { EmptyState } from "@/components/shared/empty-state";
import {
  Search,
  Plus,
  CheckSquare,
  Ticket as TicketIcon,
  ShieldAlert,
  Bot,
  RefreshCw,
  AlertTriangle,
  ExternalLink,
  ChevronRight,
  Clock,
  User,
  Send,
  X,
  Layers,
} from "lucide-react";

import {
  CurrentUser,
  WorkspaceMembership,
  fetchCurrentUser,
  resolveActiveWorkspace,
  getStoredActiveWorkspaceId,
  setStoredActiveWorkspaceId,
} from "@/lib/auth";
import {
  fetchWorkspaceRepositories,
  WorkspaceRepository,
} from "@/lib/github";
import {
  listWorkspaceDevPilotTasks,
  createDevPilotTask,
  DevPilotTaskDetail,
  DevPilotTaskType,
} from "@/lib/devpilot";
import {
  listTickets,
  createTicket,
  updateTicketStatus,
  addTicketComment,
  getTicket,
  TicketItem,
  TicketStatus,
  TicketPriority,
} from "@/lib/tickets";
import {
  getWorkspaceRiskOverview,
  WorkspaceRiskOverview,
} from "@/lib/impactmind";

export default function TasksPage() {
  // Authentication & Workspace Scope
  const [currentUser, setCurrentUser] = React.useState<CurrentUser | null>(null);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = React.useState<string | null>(null);
  const [repositories, setRepositories] = React.useState<WorkspaceRepository[]>([]);

  // Navigation State
  const [activeTab, setActiveTab] = React.useState<string>("tasks");
  const [loading, setLoading] = React.useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = React.useState<boolean>(false);
  const [refreshTrigger, setRefreshTrigger] = React.useState<number>(0);
  const [error, setError] = React.useState<string | null>(null);

  // Data States
  const [tasks, setTasks] = React.useState<DevPilotTaskDetail[]>([]);
  const [tickets, setTickets] = React.useState<TicketItem[]>([]);
  const [riskOverview, setRiskOverview] = React.useState<WorkspaceRiskOverview | null>(null);

  // Filter States
  const [taskSearch, setTaskSearch] = React.useState<string>("");
  const [taskStatusFilter, setTaskStatusFilter] = React.useState<string>("ALL");
  const [taskRepoFilter, setTaskRepoFilter] = React.useState<string>("ALL");

  const [ticketSearch, setTicketSearch] = React.useState<string>("");
  const [ticketStatusFilter, setTicketStatusFilter] = React.useState<string>("ALL");
  const [ticketPriorityFilter, setTicketPriorityFilter] = React.useState<string>("ALL");
  const [ticketRepoFilter, setTicketRepoFilter] = React.useState<string>("ALL");

  // Modal / Drawer States
  const [showCreateTaskModal, setShowCreateTaskModal] = React.useState<boolean>(false);
  const [showCreateTicketModal, setShowCreateTicketModal] = React.useState<boolean>(false);
  const [selectedTicket, setSelectedTicket] = React.useState<TicketItem | null>(null);
  const [selectedTask, setSelectedTask] = React.useState<DevPilotTaskDetail | null>(null);
  const [newCommentText, setNewCommentText] = React.useState<string>("");
  const [commentSubmitting, setCommentSubmitting] = React.useState<boolean>(false);

  // Form States for Creation
  const [taskFormRepo, setTaskFormRepo] = React.useState<string>("");
  const [taskFormTitle, setTaskFormTitle] = React.useState<string>("");
  const [taskFormPrompt, setTaskFormPrompt] = React.useState<string>("");
  const [taskFormType, setTaskFormType] = React.useState<DevPilotTaskType>("FEATURE");
  const [taskSubmitting, setTaskSubmitting] = React.useState<boolean>(false);

  const [ticketFormTitle, setTicketFormTitle] = React.useState<string>("");
  const [ticketFormDesc, setTicketFormDesc] = React.useState<string>("");
  const [ticketFormPriority, setTicketFormPriority] = React.useState<TicketPriority>("MEDIUM");
  const [ticketFormRepo, setTicketFormRepo] = React.useState<string>("");
  const [ticketFormTags, setTicketFormTags] = React.useState<string>("");
  const [ticketSubmitting, setTicketSubmitting] = React.useState<boolean>(false);

  // Resolve Active Workspace
  const activeWorkspace: WorkspaceMembership | null = React.useMemo(() => {
    return resolveActiveWorkspace(currentUser, selectedWorkspaceId);
  }, [currentUser, selectedWorkspaceId]);

  const activeWorkspaceId = activeWorkspace?.workspace_id ?? null;

  // 1. Initial User Load
  React.useEffect(() => {
    let ignore = false;
    async function initUser() {
      try {
        const user = await fetchCurrentUser();
        if (!ignore) {
          setCurrentUser(user);
          if (user && user.workspaces && user.workspaces.length > 0) {
            const resolved = resolveActiveWorkspace(user);
            if (resolved) {
              setSelectedWorkspaceId(resolved.workspace_id);
              setStoredActiveWorkspaceId(resolved.workspace_id);
            }
          } else {
            setLoading(false);
          }
        }
      } catch (err: unknown) {
        if (!ignore) {
          setError(err instanceof Error ? err.message : "Failed to load user profile");
          setLoading(false);
        }
      }
    }
    initUser();
    return () => {
      ignore = true;
    };
  }, []);

  // 2. Workspace change listeners
  React.useEffect(() => {
    const handleWorkspaceChanged = (e: Event) => {
      const customEvent = e as CustomEvent<{ workspaceId: string }>;
      const newWsId = customEvent.detail?.workspaceId || getStoredActiveWorkspaceId();
      if (newWsId && newWsId !== selectedWorkspaceId) {
        setSelectedWorkspaceId(newWsId);
      }
    };
    const handleStorage = (e: StorageEvent) => {
      if (e.key === "orchestrix_active_workspace_id" && e.newValue && e.newValue !== selectedWorkspaceId) {
        setSelectedWorkspaceId(e.newValue);
      }
    };
    window.addEventListener("orchestrix:workspace_changed", handleWorkspaceChanged);
    window.addEventListener("storage", handleStorage);
    return () => {
      window.removeEventListener("orchestrix:workspace_changed", handleWorkspaceChanged);
      window.removeEventListener("storage", handleStorage);
    };
  }, [selectedWorkspaceId]);

  // 3. Load Repositories for Workspace
  React.useEffect(() => {
    if (!activeWorkspaceId) return;
    let ignore = false;
    async function loadRepos() {
      try {
        const repos = await fetchWorkspaceRepositories(activeWorkspaceId!);
        if (!ignore) {
          setRepositories(repos);
          if (repos.length > 0 && !taskFormRepo) {
            setTaskFormRepo(repos[0].id);
          }
        }
      } catch (err) {
        console.error("Failed to load workspace repositories:", err);
      }
    }
    loadRepos();
    return () => {
      ignore = true;
    };
  }, [activeWorkspaceId, taskFormRepo]);

  // 4. Load Data for the Active Tab
  React.useEffect(() => {
    if (!activeWorkspaceId) return;
    const wsId = activeWorkspaceId;
    let ignore = false;

    async function fetchData() {
      try {
        if (activeTab === "tasks") {
          const res = await listWorkspaceDevPilotTasks(wsId);
          if (!ignore) setTasks(res.tasks || []);
        } else if (activeTab === "tickets") {
          const res = await listTickets(wsId);
          if (!ignore) setTickets(res.items || []);
        } else if (activeTab === "risk") {
          const res = await getWorkspaceRiskOverview(wsId);
          if (!ignore) setRiskOverview(res);
        }
        if (!ignore) setError(null);
      } catch (err: unknown) {
        if (!ignore) {
          setError(err instanceof Error ? err.message : "Failed to load data");
        }
      } finally {
        if (!ignore) {
          setLoading(false);
          setIsRefreshing(false);
        }
      }
    }

    fetchData();

    return () => {
      ignore = true;
    };
  }, [activeWorkspaceId, activeTab, refreshTrigger]);

  const handleManualRefresh = () => {
    setIsRefreshing(true);
    setRefreshTrigger((prev) => prev + 1);
  };

  // Helper map for repository names
  const repoNameMap = React.useMemo(() => {
    const map = new Map<string, string>();
    repositories.forEach((r) => map.set(r.id, r.name));
    return map;
  }, [repositories]);

  // Filtering for Tasks
  const filteredTasks = React.useMemo(() => {
    return tasks.filter((t) => {
      const titleMatch =
        t.title.toLowerCase().includes(taskSearch.toLowerCase()) ||
        (t.prompt && t.prompt.toLowerCase().includes(taskSearch.toLowerCase()));
      const statusMatch = taskStatusFilter === "ALL" || t.status === taskStatusFilter;
      const repoMatch = taskRepoFilter === "ALL" || t.repository_id === taskRepoFilter;
      return titleMatch && statusMatch && repoMatch;
    });
  }, [tasks, taskSearch, taskStatusFilter, taskRepoFilter]);

  // Filtering for Tickets
  const filteredTickets = React.useMemo(() => {
    return tickets.filter((t) => {
      const searchLower = ticketSearch.toLowerCase();
      const textMatch =
        t.title.toLowerCase().includes(searchLower) ||
        (t.description && t.description.toLowerCase().includes(searchLower)) ||
        (t.assignee_name && t.assignee_name.toLowerCase().includes(searchLower));
      const statusMatch = ticketStatusFilter === "ALL" || t.status === ticketStatusFilter;
      const priorityMatch = ticketPriorityFilter === "ALL" || t.priority === ticketPriorityFilter;
      const repoMatch = ticketRepoFilter === "ALL" || t.repository_id === ticketRepoFilter;
      return textMatch && statusMatch && priorityMatch && repoMatch;
    });
  }, [tickets, ticketSearch, ticketStatusFilter, ticketPriorityFilter, ticketRepoFilter]);

  // Handlers for Task Creation
  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!taskFormRepo || !taskFormTitle.trim() || !activeWorkspaceId) return;
    setTaskSubmitting(true);
    try {
      await createDevPilotTask(
        taskFormRepo,
        {
          title: taskFormTitle.trim(),
          prompt: taskFormPrompt.trim() || taskFormTitle.trim(),
          task_type: taskFormType,
        },
        activeWorkspaceId
      );
      setShowCreateTaskModal(false);
      setTaskFormTitle("");
      setTaskFormPrompt("");
      setRefreshTrigger((prev) => prev + 1);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to create task");
    } finally {
      setTaskSubmitting(false);
    }
  };

  // Handlers for Ticket Creation
  const handleCreateTicket = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ticketFormTitle.trim() || !activeWorkspaceId) return;
    setTicketSubmitting(true);
    try {
      const tagsList = ticketFormTags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean);

      await createTicket(activeWorkspaceId, {
        title: ticketFormTitle.trim(),
        description: ticketFormDesc.trim() || undefined,
        priority: ticketFormPriority,
        repository_id: ticketFormRepo || undefined,
        tags: tagsList,
      });
      setShowCreateTicketModal(false);
      setTicketFormTitle("");
      setTicketFormDesc("");
      setTicketFormTags("");
      setRefreshTrigger((prev) => prev + 1);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to create ticket");
    } finally {
      setTicketSubmitting(false);
    }
  };

  // Handlers for Ticket Updates & Activity
  const handleStatusChange = async (ticketId: string, newStatus: TicketStatus) => {
    if (!activeWorkspaceId) return;
    try {
      const updated = await updateTicketStatus(activeWorkspaceId, ticketId, newStatus);
      setTickets((prev) => prev.map((t) => (t.id === ticketId ? updated : t)));
      if (selectedTicket && selectedTicket.id === ticketId) {
        setSelectedTicket(updated);
      }
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to update status");
    }
  };

  const handleAddComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedTicket || !newCommentText.trim() || !activeWorkspaceId) return;
    setCommentSubmitting(true);
    try {
      await addTicketComment(activeWorkspaceId, selectedTicket.id, newCommentText.trim());
      setNewCommentText("");
      const refreshed = await getTicket(activeWorkspaceId, selectedTicket.id);
      setSelectedTicket(refreshed);
      setTickets((prev) => prev.map((t) => (t.id === refreshed.id ? refreshed : t)));
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to add comment");
    } finally {
      setCommentSubmitting(false);
    }
  };

  return (
    <AppShell>
      <PageHeader
        title="Tasks, Tickets & Risk Pipeline"
        subtitle={
          activeWorkspace
            ? `Production engineering execution for workspace "${activeWorkspace.name}".`
            : "Production engineering execution and ticket pipeline."
        }
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleManualRefresh}
              disabled={isRefreshing}
              className="text-xs h-8"
            >
              <RefreshCw className={`h-3.5 w-3.5 mr-1 ${isRefreshing ? "animate-spin" : ""}`} />
              Sync
            </Button>
            {activeTab === "tasks" && (
              <Button
                size="sm"
                className="text-xs h-8"
                onClick={() => setShowCreateTaskModal(true)}
                disabled={repositories.length === 0}
              >
                <Plus className="h-3.5 w-3.5 mr-1" />
                Dispatch DevPilot Task
              </Button>
            )}
            {activeTab === "tickets" && (
              <Button
                size="sm"
                className="text-xs h-8"
                onClick={() => setShowCreateTicketModal(true)}
              >
                <Plus className="h-3.5 w-3.5 mr-1" />
                Create Issue Ticket
              </Button>
            )}
            {activeTab === "risk" && (
              <Link href="/impact">
                <Button size="sm" variant="outline" className="text-xs h-8">
                  <ExternalLink className="h-3.5 w-3.5 mr-1" />
                  ImpactMind Engine
                </Button>
              </Link>
            )}
          </div>
        }
      />

      {/* Error Notice */}
      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-800 p-3 rounded-xl flex items-center justify-between text-xs mb-4">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-rose-600 shrink-0" />
            <span>{error}</span>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="text-xs h-7 border-rose-300"
            onClick={() => {
              setLoading(true);
              setRefreshTrigger((prev) => prev + 1);
            }}
          >
            Retry
          </Button>
        </div>
      )}

      {/* Main Tabbed Interface */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList className="bg-white p-1 border border-slate-200 rounded-xl shadow-xs">
          <TabsTrigger value="tasks" className="gap-2">
            <Bot className="h-3.5 w-3.5" />
            <span>Engineering Tasks</span>
            {tasks.length > 0 && (
              <span className="ml-1 px-1.5 py-0.2 bg-slate-100 text-slate-700 rounded-full text-[10px] font-mono">
                {tasks.length}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="tickets" className="gap-2">
            <TicketIcon className="h-3.5 w-3.5" />
            <span>Workspace Tickets</span>
            {tickets.length > 0 && (
              <span className="ml-1 px-1.5 py-0.2 bg-slate-100 text-slate-700 rounded-full text-[10px] font-mono">
                {tickets.length}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="risk" className="gap-2">
            <ShieldAlert className="h-3.5 w-3.5" />
            <span>Risk Management</span>
            {riskOverview && riskOverview.has_assessment_data && (
              <span
                className={`ml-1 px-1.5 py-0.2 rounded-full text-[10px] font-bold ${
                  riskOverview.latest_risk_tier === "CRITICAL"
                    ? "bg-rose-100 text-rose-700"
                    : riskOverview.latest_risk_tier === "HIGH"
                    ? "bg-amber-100 text-amber-700"
                    : "bg-emerald-100 text-emerald-700"
                }`}
              >
                {riskOverview.latest_risk_tier}
              </span>
            )}
          </TabsTrigger>
        </TabsList>

        {/* ------------------------------------------------------------- */}
        {/* TAB 1: ENGINEERING TASKS (DEVPILOT)                          */}
        {/* ------------------------------------------------------------- */}
        <TabsContent value="tasks">
          {/* Controls Bar */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-white p-3 rounded-xl border border-slate-200">
            <div className="w-full sm:max-w-md">
              <Input
                placeholder="Search engineering tasks by title or prompt..."
                value={taskSearch}
                onChange={(e) => setTaskSearch(e.target.value)}
                icon={<Search className="h-3.5 w-3.5" />}
                className="h-8 text-xs"
              />
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto justify-end flex-wrap">
              {repositories.length > 0 && (
                <select
                  value={taskRepoFilter}
                  onChange={(e) => setTaskRepoFilter(e.target.value)}
                  className="h-8 text-xs border border-slate-200 rounded-lg px-2 bg-white text-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="ALL">All Repositories</option>
                  {repositories.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              )}

              <div className="flex items-center gap-1">
                {["ALL", "PLANNING", "AWAITING_APPROVAL", "COMPLETED", "FAILED"].map((st) => (
                  <Button
                    key={st}
                    variant={taskStatusFilter === st ? "default" : "outline"}
                    size="sm"
                    onClick={() => setTaskStatusFilter(st)}
                    className="capitalize text-xs h-7 px-2"
                  >
                    {st === "ALL" ? "All" : st.replace("_", " ").toLowerCase()}
                  </Button>
                ))}
              </div>
            </div>
          </div>

          {loading ? (
            <div className="p-12 text-center text-slate-400 bg-white rounded-xl border border-slate-200">
              <RefreshCw className="h-6 w-6 animate-spin mx-auto mb-2 text-blue-600" />
              <p className="text-xs">Loading real engineering tasks from backend...</p>
            </div>
          ) : filteredTasks.length === 0 ? (
            <EmptyState
              icon={CheckSquare}
              title={tasks.length === 0 ? "No engineering tasks found" : "No matching tasks"}
              description={
                tasks.length === 0
                  ? "Dispatch an autonomous DevPilot task to start implementing features, refactoring code, or fixing bugs."
                  : "Try clearing your search query or status filter."
              }
              actionLabel={tasks.length === 0 ? "Dispatch Task" : "Clear filters"}
              onAction={() => {
                if (tasks.length === 0) {
                  setShowCreateTaskModal(true);
                } else {
                  setTaskSearch("");
                  setTaskStatusFilter("ALL");
                  setTaskRepoFilter("ALL");
                }
              }}
            />
          ) : (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden shadow-xs">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[120px]">Task ID</TableHead>
                    <TableHead>Title & Instruction</TableHead>
                    <TableHead>Repository</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Plan Steps</TableHead>
                    <TableHead className="text-right">Updated</TableHead>
                    <TableHead className="w-[50px]"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredTasks.map((t) => (
                    <TableRow
                      key={t.id}
                      className="cursor-pointer hover:bg-slate-50 transition-colors"
                      onClick={() => setSelectedTask(t)}
                    >
                      <TableCell className="font-mono text-xs text-slate-500">
                        {t.id.slice(0, 8)}...
                      </TableCell>
                      <TableCell>
                        <div className="font-medium text-slate-900 text-xs sm:text-sm">
                          {t.title}
                        </div>
                        {t.prompt && (
                          <div className="text-[11px] text-slate-500 line-clamp-1 max-w-md">
                            {t.prompt}
                          </div>
                        )}
                      </TableCell>
                      <TableCell>
                        <span className="font-mono text-xs bg-slate-100 text-slate-700 px-2 py-0.5 rounded">
                          {repoNameMap.get(t.repository_id) || "Repository"}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-[10px] font-mono">
                          {t.task_type}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            t.status === "COMPLETED"
                              ? "success"
                              : t.status === "FAILED" || t.status === "CANCELLED"
                              ? "destructive"
                              : t.status === "AWAITING_APPROVAL"
                              ? "warning"
                              : "default"
                          }
                          className="text-[11px] capitalize"
                        >
                          {t.status.replace(/_/g, " ").toLowerCase()}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-slate-600">
                        {t.latest_plan ? (
                          <span className="inline-flex items-center gap-1 font-mono text-[11px] text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
                            <Layers className="h-3 w-3" />
                            {t.latest_plan.steps.length} steps
                          </span>
                        ) : (
                          <span className="text-slate-400 text-xs">—</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right text-xs text-slate-500 font-mono">
                        {new Date(t.updated_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell>
                        <ChevronRight className="h-4 w-4 text-slate-400" />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>

        {/* ------------------------------------------------------------- */}
        {/* TAB 2: WORKSPACE TICKETS                                      */}
        {/* ------------------------------------------------------------- */}
        <TabsContent value="tickets">
          {/* Controls Bar */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-white p-3 rounded-xl border border-slate-200">
            <div className="w-full sm:max-w-md">
              <Input
                placeholder="Search tickets by title, description, or assignee..."
                value={ticketSearch}
                onChange={(e) => setTicketSearch(e.target.value)}
                icon={<Search className="h-3.5 w-3.5" />}
                className="h-8 text-xs"
              />
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto justify-end flex-wrap">
              <select
                value={ticketPriorityFilter}
                onChange={(e) => setTicketPriorityFilter(e.target.value)}
                className="h-8 text-xs border border-slate-200 rounded-lg px-2 bg-white text-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="ALL">All Priorities</option>
                <option value="CRITICAL">Critical</option>
                <option value="HIGH">High</option>
                <option value="MEDIUM">Medium</option>
                <option value="LOW">Low</option>
              </select>

              {repositories.length > 0 && (
                <select
                  value={ticketRepoFilter}
                  onChange={(e) => setTicketRepoFilter(e.target.value)}
                  className="h-8 text-xs border border-slate-200 rounded-lg px-2 bg-white text-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="ALL">All Repositories</option>
                  {repositories.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              )}

              <div className="flex items-center gap-1">
                {["ALL", "OPEN", "IN_PROGRESS", "UNDER_REVIEW", "RESOLVED"].map((st) => (
                  <Button
                    key={st}
                    variant={ticketStatusFilter === st ? "default" : "outline"}
                    size="sm"
                    onClick={() => setTicketStatusFilter(st)}
                    className="capitalize text-xs h-7 px-2"
                  >
                    {st === "ALL" ? "All" : st.replace("_", " ").toLowerCase()}
                  </Button>
                ))}
              </div>
            </div>
          </div>

          {loading ? (
            <div className="p-12 text-center text-slate-400 bg-white rounded-xl border border-slate-200">
              <RefreshCw className="h-6 w-6 animate-spin mx-auto mb-2 text-blue-600" />
              <p className="text-xs">Loading persistent workspace tickets...</p>
            </div>
          ) : filteredTickets.length === 0 ? (
            <EmptyState
              icon={TicketIcon}
              title={tickets.length === 0 ? "No tickets created yet" : "No matching tickets"}
              description={
                tickets.length === 0
                  ? "Track engineering bugs, enhancements, and tasks directly in this workspace."
                  : "Try clearing your search query or adjusting priority and status filters."
              }
              actionLabel={tickets.length === 0 ? "Create Ticket" : "Clear filters"}
              onAction={() => {
                if (tickets.length === 0) {
                  setShowCreateTicketModal(true);
                } else {
                  setTicketSearch("");
                  setTicketStatusFilter("ALL");
                  setTicketPriorityFilter("ALL");
                  setTicketRepoFilter("ALL");
                }
              }}
            />
          ) : (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden shadow-xs">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[110px]">Ticket ID</TableHead>
                    <TableHead>Title & Tags</TableHead>
                    <TableHead>Repository</TableHead>
                    <TableHead>Priority</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Assignee</TableHead>
                    <TableHead className="text-right">Updated</TableHead>
                    <TableHead className="w-[50px]"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredTickets.map((t) => (
                    <TableRow
                      key={t.id}
                      className="cursor-pointer hover:bg-slate-50 transition-colors"
                      onClick={() => setSelectedTicket(t)}
                    >
                      <TableCell className="font-mono text-xs text-slate-500">
                        #{t.id.slice(0, 8)}
                      </TableCell>
                      <TableCell>
                        <div className="font-medium text-slate-900 text-xs sm:text-sm">
                          {t.title}
                        </div>
                        {t.tags && t.tags.length > 0 && (
                          <div className="flex items-center gap-1 mt-1 flex-wrap">
                            {t.tags.map((tag) => (
                              <span
                                key={tag}
                                className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.2 rounded font-mono"
                              >
                                #{tag}
                              </span>
                            ))}
                          </div>
                        )}
                      </TableCell>
                      <TableCell>
                        <span className="font-mono text-xs bg-slate-100 text-slate-700 px-2 py-0.5 rounded">
                          {t.repository_name || (t.repository_id ? repoNameMap.get(t.repository_id) : "Workspace")}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span
                          className={`inline-flex items-center text-xs font-semibold capitalize ${
                            t.priority === "CRITICAL"
                              ? "text-rose-600 font-bold"
                              : t.priority === "HIGH"
                              ? "text-amber-600 font-bold"
                              : t.priority === "MEDIUM"
                              ? "text-blue-600"
                              : "text-slate-600"
                          }`}
                        >
                          {t.priority.toLowerCase()}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            t.status === "RESOLVED" || t.status === "CLOSED"
                              ? "success"
                              : t.status === "IN_PROGRESS"
                              ? "default"
                              : t.status === "UNDER_REVIEW"
                              ? "warning"
                              : "secondary"
                          }
                          className="text-[11px] capitalize"
                        >
                          {t.status.replace(/_/g, " ").toLowerCase()}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-slate-600">
                        {t.assignee_name ? (
                          <span className="inline-flex items-center gap-1">
                            <User className="h-3 w-3 text-slate-400" />
                            {t.assignee_name}
                          </span>
                        ) : (
                          <span className="text-slate-400 italic">Unassigned</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right text-xs text-slate-500 font-mono">
                        {new Date(t.updated_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell>
                        <ChevronRight className="h-4 w-4 text-slate-400" />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>

        {/* ------------------------------------------------------------- */}
        {/* TAB 3: RISK MANAGEMENT & IMPACTMIND                          */}
        {/* ------------------------------------------------------------- */}
        <TabsContent value="risk">
          {loading ? (
            <div className="p-12 text-center text-slate-400 bg-white rounded-xl border border-slate-200">
              <RefreshCw className="h-6 w-6 animate-spin mx-auto mb-2 text-blue-600" />
              <p className="text-xs">Aggregating ImpactMind structural exposure scores...</p>
            </div>
          ) : !riskOverview || !riskOverview.has_assessment_data ? (
            <div className="space-y-4">
              <div className="bg-amber-50 border border-amber-200 text-amber-900 p-4 rounded-xl flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
                <div>
                  <h4 className="font-semibold text-sm">No ImpactMind Risk Data Available</h4>
                  <p className="text-xs text-amber-800 mt-1">
                    Risk assessment data is not yet available for this workspace. To evaluate structural exposure scores,
                    breaking changes, and AST regression blast radius, trigger an analysis from ImpactMind.
                  </p>
                  <Link href="/impact">
                    <Button size="sm" variant="outline" className="text-xs h-7 mt-3 border-amber-300">
                      Go to ImpactMind Engine
                    </Button>
                  </Link>
                </div>
              </div>

              {/* Zero-state KPI Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
                <div className="bg-white p-4 rounded-xl border border-slate-200">
                  <span className="text-xs text-slate-500 font-medium">Structural Exposure Score</span>
                  <div className="text-2xl font-bold text-slate-400 mt-1">—</div>
                  <span className="text-[11px] text-slate-400">Unavailable</span>
                </div>
                <div className="bg-white p-4 rounded-xl border border-slate-200">
                  <span className="text-xs text-slate-500 font-medium">Risk Tier</span>
                  <div className="text-2xl font-bold text-slate-400 mt-1">N/A</div>
                  <span className="text-[11px] text-slate-400">No assessments</span>
                </div>
                <div className="bg-white p-4 rounded-xl border border-slate-200">
                  <span className="text-xs text-slate-500 font-medium">Breaking Changes</span>
                  <div className="text-2xl font-bold text-slate-400 mt-1">0</div>
                  <span className="text-[11px] text-slate-400">Total detected</span>
                </div>
                <div className="bg-white p-4 rounded-xl border border-slate-200">
                  <span className="text-xs text-slate-500 font-medium">Change Assessments</span>
                  <div className="text-2xl font-bold text-slate-400 mt-1">0</div>
                  <span className="text-[11px] text-slate-400">Completed runs</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Top Level Risk KPI Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
                <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
                  <span className="text-xs text-slate-500 font-medium">Structural Exposure Score</span>
                  <div
                    className={`text-3xl font-extrabold mt-1 ${
                      riskOverview.latest_risk_score && riskOverview.latest_risk_score > 75
                        ? "text-rose-600"
                        : riskOverview.latest_risk_score && riskOverview.latest_risk_score > 40
                        ? "text-amber-600"
                        : "text-emerald-600"
                    }`}
                  >
                    {riskOverview.latest_risk_score?.toFixed(1) ?? "—"}
                  </div>
                  <span className="text-[11px] text-slate-400">Score range: 0.0 - 100.0</span>
                </div>

                <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
                  <span className="text-xs text-slate-500 font-medium">Latest Exposure Tier</span>
                  <div className="mt-1">
                    <span
                      className={`inline-block text-xl font-bold px-2.5 py-0.5 rounded-lg ${
                        riskOverview.latest_risk_tier === "CRITICAL"
                          ? "bg-rose-100 text-rose-800"
                          : riskOverview.latest_risk_tier === "HIGH"
                          ? "bg-amber-100 text-amber-800"
                          : riskOverview.latest_risk_tier === "MEDIUM"
                          ? "bg-blue-100 text-blue-800"
                          : "bg-emerald-100 text-emerald-800"
                      }`}
                    >
                      {riskOverview.latest_risk_tier}
                    </span>
                  </div>
                  <span className="text-[11px] text-slate-400 block mt-1">
                    {riskOverview.latest_assessment_at
                      ? `Evaluated ${new Date(riskOverview.latest_assessment_at).toLocaleDateString()}`
                      : "Recently evaluated"}
                  </span>
                </div>

                <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
                  <span className="text-xs text-slate-500 font-medium">Breaking Changes</span>
                  <div
                    className={`text-3xl font-extrabold mt-1 ${
                      riskOverview.breaking_changes_total > 0 ? "text-rose-600" : "text-emerald-600"
                    }`}
                  >
                    {riskOverview.breaking_changes_total}
                  </div>
                  <span className="text-[11px] text-slate-400">Downstream breaking contracts</span>
                </div>

                <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
                  <span className="text-xs text-slate-500 font-medium">Tier Distribution</span>
                  <div className="flex items-center gap-2 mt-2">
                    <span className="text-xs font-mono font-bold text-rose-600">
                      C:{riskOverview.tier_distribution.CRITICAL || 0}
                    </span>
                    <span className="text-xs font-mono font-bold text-amber-600">
                      H:{riskOverview.tier_distribution.HIGH || 0}
                    </span>
                    <span className="text-xs font-mono font-bold text-blue-600">
                      M:{riskOverview.tier_distribution.MEDIUM || 0}
                    </span>
                    <span className="text-xs font-mono font-bold text-emerald-600">
                      L:{riskOverview.tier_distribution.LOW || 0}
                    </span>
                  </div>
                  <span className="text-[11px] text-slate-400 block mt-1">
                    Across {riskOverview.total_assessments} assessments
                  </span>
                </div>
              </div>

              {/* Two Column Breakdown */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Top Exposed Files */}
                <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-xs">
                  <h3 className="font-semibold text-sm text-slate-900 mb-3 flex items-center justify-between">
                    <span>Top Exposed Files</span>
                    <span className="text-xs font-normal text-slate-500">AST Blast Radius</span>
                  </h3>
                  {riskOverview.top_exposed_files.length === 0 ? (
                    <p className="text-xs text-slate-400 py-6 text-center">No impacted files recorded.</p>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>File Path</TableHead>
                          <TableHead className="text-right">Impacts</TableHead>
                          <TableHead className="text-right">Severity</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {riskOverview.top_exposed_files.map((f) => (
                          <TableRow key={f.file_path}>
                            <TableCell className="font-mono text-xs text-slate-800">
                              {f.file_path}
                            </TableCell>
                            <TableCell className="text-right text-xs font-semibold text-slate-700">
                              {f.impact_count}
                            </TableCell>
                            <TableCell className="text-right">
                              <Badge
                                variant={
                                  f.highest_severity === "CRITICAL"
                                    ? "destructive"
                                    : f.highest_severity === "HIGH"
                                    ? "warning"
                                    : "secondary"
                                }
                                className="text-[10px]"
                              >
                                {f.highest_severity}
                              </Badge>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </div>

                {/* Recent Assessments */}
                <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-xs">
                  <h3 className="font-semibold text-sm text-slate-900 mb-3 flex items-center justify-between">
                    <span>Recent Impact Assessments</span>
                    <Link href="/impact">
                      <Button size="sm" variant="ghost" className="text-xs h-6 p-0 text-blue-600">
                        View All
                      </Button>
                    </Link>
                  </h3>
                  {riskOverview.recent_assessments.length === 0 ? (
                    <p className="text-xs text-slate-400 py-6 text-center">No recent assessments.</p>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Repository</TableHead>
                          <TableHead>Score</TableHead>
                          <TableHead>Tier</TableHead>
                          <TableHead>Breaking</TableHead>
                          <TableHead className="text-right">Date</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {riskOverview.recent_assessments.map((a) => (
                          <TableRow key={a.id}>
                            <TableCell className="font-mono text-xs text-slate-800">
                              {a.repository_name || a.repository_id.slice(0, 8)}
                            </TableCell>
                            <TableCell className="font-mono text-xs font-semibold text-slate-700">
                              {a.structural_exposure_score.toFixed(1)}
                            </TableCell>
                            <TableCell>
                              <Badge
                                variant={
                                  a.exposure_tier === "CRITICAL"
                                    ? "destructive"
                                    : a.exposure_tier === "HIGH"
                                    ? "warning"
                                    : "secondary"
                                }
                                className="text-[10px]"
                              >
                                {a.exposure_tier}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-xs">
                              {a.breaking_changes_count > 0 ? (
                                <span className="font-bold text-rose-600">
                                  {a.breaking_changes_count}
                                </span>
                              ) : (
                                <span className="text-slate-400">0</span>
                              )}
                            </TableCell>
                            <TableCell className="text-right text-xs text-slate-500 font-mono">
                              {new Date(a.created_at).toLocaleDateString()}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </div>
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* ------------------------------------------------------------- */}
      {/* MODAL: DISPATCH DEVPILOT TASK                                 */}
      {/* ------------------------------------------------------------- */}
      {showCreateTaskModal && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4 z-50 animate-in fade-in duration-150">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-xl border border-slate-200">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                <Bot className="h-5 w-5 text-blue-600" />
                Dispatch DevPilot Task
              </h3>
              <button
                onClick={() => setShowCreateTaskModal(false)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleCreateTask} className="space-y-4 mt-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Target Repository <span className="text-rose-500">*</span>
                </label>
                <select
                  value={taskFormRepo}
                  onChange={(e) => setTaskFormRepo(e.target.value)}
                  required
                  className="w-full h-9 text-xs border border-slate-300 rounded-lg px-2 bg-white text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {repositories.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name} ({r.default_branch})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Task Title <span className="text-rose-500">*</span>
                </label>
                <Input
                  placeholder="e.g. Implement resilient token refresh in Auth client"
                  value={taskFormTitle}
                  onChange={(e) => setTaskFormTitle(e.target.value)}
                  required
                  className="text-xs h-9"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Task Type
                </label>
                <select
                  value={taskFormType}
                  onChange={(e) => setTaskFormType(e.target.value as DevPilotTaskType)}
                  className="w-full h-9 text-xs border border-slate-300 rounded-lg px-2 bg-white text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="FEATURE">Feature (New Implementation)</option>
                  <option value="BUG_FIX">Bug Fix (Defect Correction)</option>
                  <option value="REFACTOR">Refactoring (Structural Improvement)</option>
                  <option value="TESTING">Testing (Test Suite Hardening)</option>
                  <option value="API_DEVELOPMENT">API Development (Endpoint Implementation)</option>
                  <option value="PERFORMANCE_OPTIMIZATION">Performance Optimization</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Prompt & Detailed Instructions
                </label>
                <textarea
                  rows={4}
                  placeholder="Specify architectural constraints, target files, and expected outcomes..."
                  value={taskFormPrompt}
                  onChange={(e) => setTaskFormPrompt(e.target.value)}
                  className="w-full text-xs border border-slate-300 rounded-lg p-2 text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setShowCreateTaskModal(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" size="sm" disabled={taskSubmitting}>
                  {taskSubmitting ? "Dispatching..." : "Dispatch Task"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* MODAL: CREATE WORKSPACE TICKET                                */}
      {/* ------------------------------------------------------------- */}
      {showCreateTicketModal && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4 z-50 animate-in fade-in duration-150">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-xl border border-slate-200">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                <TicketIcon className="h-5 w-5 text-blue-600" />
                Create Workspace Ticket
              </h3>
              <button
                onClick={() => setShowCreateTicketModal(false)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleCreateTicket} className="space-y-4 mt-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Ticket Title <span className="text-rose-500">*</span>
                </label>
                <Input
                  placeholder="e.g. Memory leak in worker connection pool"
                  value={ticketFormTitle}
                  onChange={(e) => setTicketFormTitle(e.target.value)}
                  required
                  className="text-xs h-9"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">
                    Priority
                  </label>
                  <select
                    value={ticketFormPriority}
                    onChange={(e) => setTicketFormPriority(e.target.value as TicketPriority)}
                    className="w-full h-9 text-xs border border-slate-300 rounded-lg px-2 bg-white text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="LOW">Low</option>
                    <option value="MEDIUM">Medium</option>
                    <option value="HIGH">High</option>
                    <option value="CRITICAL">Critical</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">
                    Repository Association
                  </label>
                  <select
                    value={ticketFormRepo}
                    onChange={(e) => setTicketFormRepo(e.target.value)}
                    className="w-full h-9 text-xs border border-slate-300 rounded-lg px-2 bg-white text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">None (Workspace Level)</option>
                    {repositories.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Description & Reproduction
                </label>
                <textarea
                  rows={3}
                  placeholder="Detailed breakdown of the issue or requirement..."
                  value={ticketFormDesc}
                  onChange={(e) => setTicketFormDesc(e.target.value)}
                  className="w-full text-xs border border-slate-300 rounded-lg p-2 text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Tags (comma separated)
                </label>
                <Input
                  placeholder="e.g. backend, performance, security"
                  value={ticketFormTags}
                  onChange={(e) => setTicketFormTags(e.target.value)}
                  className="text-xs h-9"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setShowCreateTicketModal(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" size="sm" disabled={ticketSubmitting}>
                  {ticketSubmitting ? "Creating..." : "Create Ticket"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* DRAWER: TICKET DETAILS & ACTIVITY TRAIL                       */}
      {/* ------------------------------------------------------------- */}
      {selectedTicket && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex justify-end z-50 animate-in fade-in duration-150">
          <div className="bg-white w-full max-w-xl h-full shadow-2xl border-l border-slate-200 flex flex-col p-6 overflow-hidden">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <div className="flex items-center gap-2">
                <TicketIcon className="h-5 w-5 text-blue-600" />
                <span className="font-mono text-xs text-slate-500">#{selectedTicket.id.slice(0, 8)}</span>
                <Badge
                  variant={
                    selectedTicket.status === "RESOLVED" || selectedTicket.status === "CLOSED"
                      ? "success"
                      : selectedTicket.status === "IN_PROGRESS"
                      ? "default"
                      : "secondary"
                  }
                  className="text-xs capitalize"
                >
                  {selectedTicket.status.replace(/_/g, " ").toLowerCase()}
                </Badge>
              </div>
              <button
                onClick={() => setSelectedTicket(null)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto py-4 space-y-4">
              <div>
                <h2 className="text-lg font-bold text-slate-900">{selectedTicket.title}</h2>
                <div className="flex items-center gap-3 text-xs text-slate-500 mt-1">
                  <span>Priority: <strong className="text-slate-800">{selectedTicket.priority}</strong></span>
                  <span>•</span>
                  <span>Repo: <strong className="text-slate-800">{selectedTicket.repository_name || "Workspace"}</strong></span>
                  <span>•</span>
                  <span>Created by: {selectedTicket.creator_name || "System"}</span>
                </div>
              </div>

              {selectedTicket.description && (
                <div className="bg-slate-50 border border-slate-200 rounded-xl p-3 text-xs text-slate-800 whitespace-pre-wrap">
                  {selectedTicket.description}
                </div>
              )}

              {/* Status Transition Buttons */}
              <div className="bg-white p-3 rounded-xl border border-slate-200">
                <span className="text-xs font-semibold text-slate-700 block mb-2">Transition Status:</span>
                <div className="flex items-center gap-2 flex-wrap">
                  {(["OPEN", "IN_PROGRESS", "UNDER_REVIEW", "RESOLVED", "CLOSED"] as TicketStatus[]).map((st) => (
                    <Button
                      key={st}
                      variant={selectedTicket.status === st ? "default" : "outline"}
                      size="sm"
                      onClick={() => handleStatusChange(selectedTicket.id, st)}
                      className="text-xs h-7 px-2 capitalize"
                    >
                      {st.replace(/_/g, " ").toLowerCase()}
                    </Button>
                  ))}
                </div>
              </div>

              {/* Activity Trail */}
              <div>
                <h4 className="text-xs font-bold text-slate-800 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                  <Clock className="h-3.5 w-3.5" />
                  Activity History & Audit Trail
                </h4>
                {selectedTicket.activities && selectedTicket.activities.length > 0 ? (
                  <div className="space-y-2 border-l-2 border-slate-200 pl-3 ml-2">
                    {selectedTicket.activities.map((a) => (
                      <div key={a.id} className="text-xs text-slate-600 relative">
                        <div className="absolute -left-[19px] top-1.5 w-2 h-2 rounded-full bg-blue-600 ring-4 ring-white" />
                        <div className="font-semibold text-slate-900 flex items-center justify-between">
                          <span>{a.actor_name || "System"}</span>
                          <span className="text-[10px] text-slate-400 font-mono">
                            {new Date(a.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                          </span>
                        </div>
                        <p className="text-slate-700 mt-0.5">{a.comment}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-slate-400 italic">No activity recorded yet.</p>
                )}
              </div>
            </div>

            {/* Comment Form */}
            <form onSubmit={handleAddComment} className="pt-3 border-t border-slate-200 flex gap-2">
              <Input
                placeholder="Write a comment or status note..."
                value={newCommentText}
                onChange={(e) => setNewCommentText(e.target.value)}
                className="text-xs h-9"
              />
              <Button type="submit" size="sm" className="h-9 px-3" disabled={commentSubmitting}>
                <Send className="h-3.5 w-3.5 mr-1" />
                Comment
              </Button>
            </form>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* DRAWER: DEVPILOT TASK DETAIL                                  */}
      {/* ------------------------------------------------------------- */}
      {selectedTask && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex justify-end z-50 animate-in fade-in duration-150">
          <div className="bg-white w-full max-w-xl h-full shadow-2xl border-l border-slate-200 flex flex-col p-6 overflow-hidden">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <div className="flex items-center gap-2">
                <Bot className="h-5 w-5 text-blue-600" />
                <span className="font-mono text-xs text-slate-500">{selectedTask.id.slice(0, 8)}</span>
                <Badge
                  variant={
                    selectedTask.status === "COMPLETED"
                      ? "success"
                      : selectedTask.status === "FAILED"
                      ? "destructive"
                      : "default"
                  }
                  className="text-xs capitalize"
                >
                  {selectedTask.status.replace(/_/g, " ").toLowerCase()}
                </Badge>
              </div>
              <button
                onClick={() => setSelectedTask(null)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto py-4 space-y-4">
              <div>
                <h2 className="text-lg font-bold text-slate-900">{selectedTask.title}</h2>
                <div className="flex items-center gap-3 text-xs text-slate-500 mt-1">
                  <span>Type: <strong className="text-slate-800">{selectedTask.task_type}</strong></span>
                  <span>•</span>
                  <span>Mode: {selectedTask.execution_mode}</span>
                  <span>•</span>
                  <span>Created: {new Date(selectedTask.created_at).toLocaleDateString()}</span>
                </div>
              </div>

              {selectedTask.prompt && (
                <div>
                  <h4 className="text-xs font-semibold text-slate-700 mb-1">Instruction Prompt:</h4>
                  <div className="bg-slate-50 border border-slate-200 rounded-xl p-3 text-xs text-slate-800 whitespace-pre-wrap font-mono">
                    {selectedTask.prompt}
                  </div>
                </div>
              )}

              {selectedTask.latest_plan ? (
                <div>
                  <h4 className="text-xs font-semibold text-slate-700 mb-1 flex items-center justify-between">
                    <span>Generated Implementation Plan</span>
                    <Badge variant="outline" className="text-[10px]">
                      {selectedTask.latest_plan.status}
                    </Badge>
                  </h4>
                  <p className="text-xs text-slate-600 mb-3">{selectedTask.latest_plan.summary}</p>

                  <div className="space-y-2">
                    {selectedTask.latest_plan.steps.map((s) => (
                      <div
                        key={s.id || s.step_number}
                        className="p-3 rounded-lg border border-slate-200 bg-white"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-bold text-slate-900">
                            Step {s.step_number}: {s.title}
                          </span>
                          <Badge variant="secondary" className="text-[10px]">
                            {s.action_type}
                          </Badge>
                        </div>
                        <p className="text-xs text-slate-600">{s.description}</p>
                        {s.target_files && s.target_files.length > 0 && (
                          <div className="flex items-center gap-1 mt-2 flex-wrap">
                            {s.target_files.map((f) => (
                              <span
                                key={f}
                                className="text-[10px] bg-slate-100 text-slate-700 font-mono px-1.5 py-0.5 rounded"
                              >
                                {f}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 text-center text-xs text-slate-500">
                  Plan generation in progress or not yet initiated.
                </div>
              )}

              {selectedTask.error_message && (
                <div className="bg-rose-50 border border-rose-200 rounded-xl p-3 text-xs text-rose-800">
                  <strong className="block mb-1">Error Failure Reason:</strong>
                  {selectedTask.error_message}
                </div>
              )}
            </div>

            <div className="pt-3 border-t border-slate-200 flex justify-end">
              <Button size="sm" variant="outline" onClick={() => setSelectedTask(null)}>
                Close
              </Button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
