"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
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
  RefreshCw,
  Trash2,
  CheckCircle2,
  AlertCircle,
  X,
  Star,
  GitFork,
  ShieldCheck,
  Loader2,
  Building2,
  ArrowRightLeft,
} from "lucide-react";

function GitHubIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg
      role="img"
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
    </svg>
  );
}
import { CurrentUser, fetchCurrentUser } from "@/lib/auth";
import {
  AccessibleGitHubRepo,
  GitHubStatus,
  WorkspaceRepository,
  connectRepositoryToWorkspace,
  disconnectGitHub,
  disconnectWorkspaceRepository,
  fetchAccessibleGitHubRepos,
  fetchGitHubStatus,
  fetchWorkspaceRepositories,
  getGitHubConnectUrl,
  refreshWorkspaceRepository,
} from "@/lib/github";

export default function RepositoriesPage() {
  const [currentUser, setCurrentUser] = React.useState<CurrentUser | null>(null);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = React.useState<string | null>(null);
  const [githubStatus, setGithubStatus] = React.useState<GitHubStatus>({ connected: false });
  const [repositories, setRepositories] = React.useState<WorkspaceRepository[]>([]);
  const [accessibleRepos, setAccessibleRepos] = React.useState<AccessibleGitHubRepo[]>([]);

  const [loading, setLoading] = React.useState(true);
  const [loadingModal, setLoadingModal] = React.useState(false);
  const [isModalOpen, setIsModalOpen] = React.useState(false);
  const [isConnectModalOpen, setIsConnectModalOpen] = React.useState(false);
  const [isSwitchModalOpen, setIsSwitchModalOpen] = React.useState(false);
  const [isDisconnectModalOpen, setIsDisconnectModalOpen] = React.useState(false);
  const [actionLoadingId, setActionLoadingId] = React.useState<string | null>(null);
  const [connectingRepoId, setConnectingRepoId] = React.useState<number | null>(null);

  const [searchTerm, setSearchTerm] = React.useState("");
  const [modalSearchTerm, setModalSearchTerm] = React.useState("");
  const [notification, setNotification] = React.useState<{
    type: "success" | "error" | "info";
    message: string;
  } | null>(null);
  const [accountConfirmation, setAccountConfirmation] = React.useState<{
    login: string | null;
  } | null>(null);

  // Active workspace (derived from selectedWorkspaceId or first workspace)
  const activeWorkspace = React.useMemo(() => {
    if (!currentUser?.workspaces || currentUser.workspaces.length === 0) return null;
    if (selectedWorkspaceId) {
      const found = currentUser.workspaces.find((w) => w.workspace_id === selectedWorkspaceId);
      if (found) return found;
    }
    return currentUser.workspaces[0];
  }, [currentUser, selectedWorkspaceId]);

  const isWorkspaceAdminOrOwner =
    activeWorkspace?.role === "OWNER" || activeWorkspace?.role === "ADMIN";

  // Check URL query parameters on mount for OAuth callback feedback
  React.useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const gh = params.get("github");
      const login = params.get("login");
      const ghErr = params.get("github_error");
      if (gh === "connected") {
        queueMicrotask(() => {
          setAccountConfirmation({ login });
          setNotification({
            type: "success",
            message: `GitHub account connected successfully as @${login || "user"}!`,
          });
        });
        window.history.replaceState({}, document.title, window.location.pathname);
      } else if (ghErr) {
        queueMicrotask(() => {
          setNotification({
            type: "error",
            message: `GitHub connection failed: ${ghErr}. Please try again.`,
          });
        });
        window.history.replaceState({}, document.title, window.location.pathname);
      }
    }
  }, []);

  // Initial load
  React.useEffect(() => {
    let isMounted = true;

    async function initialize() {
      try {
        const user = await fetchCurrentUser();
        if (!isMounted) return;
        setCurrentUser(user);

        if (user && user.workspaces && user.workspaces.length > 0) {
          const initialWsId = user.workspaces[0].workspace_id;
          setSelectedWorkspaceId(initialWsId);
          const repos = await fetchWorkspaceRepositories(initialWsId);
          if (isMounted) {
            setRepositories(repos);
          }
        }

        const ghStatus = await fetchGitHubStatus();
        if (!isMounted) return;
        setGithubStatus(ghStatus);
      } catch {
        if (isMounted) {
          setNotification({
            type: "error",
            message: "Failed to load repository workspace data.",
          });
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }

    initialize();

    return () => {
      isMounted = false;
    };
  }, []);

  // Handle workspace change from dropdown
  const handleWorkspaceChange = async (newWorkspaceId: string) => {
    setSelectedWorkspaceId(newWorkspaceId);
    setLoading(true);
    try {
      const repos = await fetchWorkspaceRepositories(newWorkspaceId);
      setRepositories(repos);
    } catch {
      setNotification({
        type: "error",
        message: "Failed to load repositories for selected workspace.",
      });
    } finally {
      setLoading(false);
    }
  };

  // Open Connect Repository Drawer / Modal
  const handleOpenConnectModal = async () => {
    if (!githubStatus.connected) {
      setIsConnectModalOpen(true);
      return;
    }

    if (!activeWorkspace) {
      setNotification({
        type: "error",
        message: "No active workspace found to connect repositories.",
      });
      return;
    }

    setIsModalOpen(true);
    setLoadingModal(true);
    try {
      const repos = await fetchAccessibleGitHubRepos(activeWorkspace.workspace_id);
      setAccessibleRepos(repos);
    } catch {
      setNotification({
        type: "error",
        message: "Failed to load accessible repositories from GitHub.",
      });
    } finally {
      setLoadingModal(false);
    }
  };

  // Connect a repo from modal
  const handleConnectRepo = async (repo: AccessibleGitHubRepo) => {
    if (!activeWorkspace) return;
    setConnectingRepoId(repo.id);
    try {
      await connectRepositoryToWorkspace({
        workspace_id: activeWorkspace.workspace_id,
        github_repository_id: repo.id,
        name: repo.name,
        full_name: repo.full_name,
        owner_login: repo.owner_login,
        owner_avatar_url: repo.owner_avatar_url,
        description: repo.description,
        default_branch: repo.default_branch,
        html_url: repo.html_url,
        visibility: repo.visibility,
        language: repo.language,
      });

      // Update state locally
      setAccessibleRepos((prev) =>
        prev.map((r) => (r.id === repo.id ? { ...r, is_connected: true } : r))
      );

      // Refresh workspace repository list
      const updatedRepos = await fetchWorkspaceRepositories(activeWorkspace.workspace_id);
      setRepositories(updatedRepos);

      setNotification({
        type: "success",
        message: `Repository "${repo.full_name}" successfully connected to workspace.`,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to connect repository";
      setNotification({
        type: "error",
        message: msg,
      });
    } finally {
      setConnectingRepoId(null);
    }
  };

  // Disconnect a connected repository
  const handleDisconnectRepo = async (repo: WorkspaceRepository) => {
    if (!activeWorkspace) return;
    if (!confirm(`Are you sure you want to disconnect "${repo.full_name}" from this workspace?`)) {
      return;
    }

    setActionLoadingId(repo.id);
    try {
      const ok = await disconnectWorkspaceRepository(repo.id, activeWorkspace.workspace_id);
      if (ok) {
        setRepositories((prev) => prev.filter((r) => r.id !== repo.id));
        setAccessibleRepos((prev) =>
          prev.map((r) =>
            r.id === repo.github_repository_id ? { ...r, is_connected: false } : r
          )
        );
        setNotification({
          type: "success",
          message: `Repository "${repo.full_name}" disconnected from workspace.`,
        });
      } else {
        throw new Error("Disconnection failed");
      }
    } catch {
      setNotification({
        type: "error",
        message: `Failed to disconnect repository "${repo.full_name}".`,
      });
    } finally {
      setActionLoadingId(null);
    }
  };

  // Refresh repository metadata
  const handleRefreshRepo = async (repo: WorkspaceRepository) => {
    if (!activeWorkspace) return;
    setActionLoadingId(repo.id);
    try {
      const refreshed = await refreshWorkspaceRepository(repo.id, activeWorkspace.workspace_id);
      setRepositories((prev) => prev.map((r) => (r.id === repo.id ? refreshed : r)));
      setNotification({
        type: "success",
        message: `Metadata for "${repo.full_name}" refreshed from GitHub.`,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to refresh repository";
      setNotification({
        type: "error",
        message: msg,
      });
    } finally {
      setActionLoadingId(null);
    }
  };

  // Execute disconnect GitHub account
  const executeDisconnectGitHub = async () => {
    try {
      const ok = await disconnectGitHub();
      if (ok) {
        setGithubStatus({ connected: false });
        setNotification({
          type: "info",
          message: "GitHub account disconnected and stored credentials purged.",
        });
      }
    } catch {
      setNotification({
        type: "error",
        message: "Failed to disconnect GitHub account.",
      });
    }
  };

  // Filter connected repositories
  const filtered = repositories.filter(
    (r) =>
      r.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      r.owner_login.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Filter modal accessible repositories
  const filteredAccessible = accessibleRepos.filter(
    (r) =>
      r.name.toLowerCase().includes(modalSearchTerm.toLowerCase()) ||
      r.owner_login.toLowerCase().includes(modalSearchTerm.toLowerCase())
  );

  return (
    <AppShell>
      <PageHeader
        title="Connected Repositories"
        subtitle="Manage GitHub repositories connected to the Orchestrix AI agent mesh."
        actions={
          <div className="flex items-center gap-2">
            {githubStatus.connected ? (
              <Button
                size="sm"
                className="text-xs h-8 bg-blue-600 hover:bg-blue-700 text-white"
                onClick={handleOpenConnectModal}
                disabled={!isWorkspaceAdminOrOwner}
                title={
                  !isWorkspaceAdminOrOwner
                    ? "Only workspace Admins or Owners can connect repositories"
                    : ""
                }
              >
                <Plus className="h-3.5 w-3.5 mr-1" />
                Connect GitHub Repository
              </Button>
            ) : (
              <Button
                size="sm"
                className="text-xs h-8 bg-slate-900 hover:bg-slate-800 text-white"
                onClick={() => setIsConnectModalOpen(true)}
              >
                <GitHubIcon className="h-3.5 w-3.5 mr-1.5" />
                Connect GitHub Account
              </Button>
            )}
          </div>
        }
      />

      {/* Account Confirmation Banner (shown when returning from GitHub OAuth) */}
      {accountConfirmation && (
        <div
          data-testid="account-confirmation-banner"
          className="p-4 rounded-xl border border-blue-200 bg-blue-50/95 text-blue-900 shadow-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 animate-in fade-in"
        >
          <div className="flex items-center gap-3.5">
            {githubStatus.avatar_url ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                src={githubStatus.avatar_url}
                alt={githubStatus.github_login || "avatar"}
                className="h-11 w-11 rounded-full border border-blue-300 shadow-2xs shrink-0 object-cover"
              />
            ) : (
              <div className="h-11 w-11 rounded-full bg-blue-600 text-white flex items-center justify-center shrink-0">
                <GitHubIcon className="h-5 w-5" />
              </div>
            )}
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-xs text-blue-900">
                  GitHub account connected:
                </span>
                <span className="font-bold text-sm text-blue-950 font-mono">
                  @{accountConfirmation.login || githubStatus.github_login || "user"}
                </span>
                <Badge variant="success" className="text-[10px] py-0.5 px-2">
                  Verified Identity
                </Badge>
              </div>
              <p className="text-xs text-blue-700 mt-0.5">
                Please confirm that this is the intended GitHub identity for your Orchestrix workspace.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 self-end sm:self-auto shrink-0">
            <Button
              size="sm"
              variant="outline"
              className="text-xs h-8 bg-white border-blue-200 text-blue-700 hover:bg-blue-100"
              onClick={() => {
                setAccountConfirmation(null);
                setIsSwitchModalOpen(true);
              }}
            >
              <ArrowRightLeft className="h-3.5 w-3.5 mr-1" />
              Not your account? Switch
            </Button>
            <Button
              size="sm"
              className="text-xs h-8 bg-blue-600 hover:bg-blue-700 text-white shadow-xs"
              onClick={() => {
                setAccountConfirmation(null);
                setNotification({
                  type: "success",
                  message: `Confirmed active GitHub connection as @${
                    accountConfirmation.login || githubStatus.github_login || "user"
                  }`,
                });
              }}
            >
              <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
              Confirm & Continue
            </Button>
          </div>
        </div>
      )}

      {/* Notification Banner */}
      {notification && (
        <div
          className={`flex items-center justify-between p-3.5 rounded-xl border text-xs transition-all ${
            notification.type === "success"
              ? "bg-emerald-50/90 text-emerald-800 border-emerald-200"
              : notification.type === "error"
              ? "bg-rose-50/90 text-rose-800 border-rose-200"
              : "bg-blue-50/90 text-blue-800 border-blue-200"
          }`}
        >
          <div className="flex items-center gap-2.5">
            {notification.type === "success" ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
            ) : (
              <AlertCircle className="h-4 w-4 shrink-0" />
            )}
            <span className="font-medium">{notification.message}</span>
          </div>
          <button
            onClick={() => setNotification(null)}
            className="p-1 hover:bg-black/5 rounded-md transition-colors"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Workspace Selector & Tenant Header */}
      <div className="bg-white p-3.5 rounded-xl border border-slate-200/90 shadow-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-lg bg-indigo-50 border border-indigo-100 text-indigo-600 flex items-center justify-center shrink-0">
            <Building2 className="h-4 w-4" />
          </div>
          <div>
            <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block">
              Active Workspace
            </span>
            {currentUser && currentUser.workspaces && currentUser.workspaces.length > 1 ? (
              <div className="flex items-center gap-2 mt-0.5">
                <select
                  data-testid="workspace-selector"
                  value={selectedWorkspaceId || ""}
                  onChange={(e) => handleWorkspaceChange(e.target.value)}
                  className="text-xs font-semibold text-slate-900 bg-slate-50 border border-slate-300 rounded-md px-2.5 py-1 focus:outline-hidden focus:ring-2 focus:ring-blue-500 cursor-pointer"
                >
                  {currentUser.workspaces.map((ws) => (
                    <option key={ws.workspace_id} value={ws.workspace_id}>
                      {ws.name} ({ws.role})
                    </option>
                  ))}
                </select>
                <Badge
                  variant={isWorkspaceAdminOrOwner ? "success" : "secondary"}
                  className="text-[10px]"
                >
                  {activeWorkspace?.role}
                </Badge>
              </div>
            ) : activeWorkspace ? (
              <div className="flex items-center gap-2 mt-0.5">
                <span className="font-semibold text-sm text-slate-900">
                  {activeWorkspace.name}
                </span>
                <Badge
                  variant={isWorkspaceAdminOrOwner ? "success" : "secondary"}
                  className="text-[10px]"
                >
                  {activeWorkspace.role}
                </Badge>
              </div>
            ) : (
              <span className="text-xs text-slate-500">No workspace available</span>
            )}
          </div>
        </div>

        {!isWorkspaceAdminOrOwner && activeWorkspace && (
          <div className="flex items-center gap-1.5 text-xs text-amber-700 bg-amber-50 border border-amber-200/80 px-3 py-1.5 rounded-lg">
            <AlertCircle className="h-3.5 w-3.5 shrink-0 text-amber-600" />
            <span>
              Read-only ({activeWorkspace.role}): Connecting repositories requires ADMIN or OWNER role.
            </span>
          </div>
        )}
      </div>

      {/* GitHub Connection Status Header Banner */}
      <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-slate-900 text-white flex items-center justify-center shrink-0">
            <GitHubIcon className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-slate-900">GitHub Integration</span>
              {githubStatus.connected ? (
                <Badge variant="success" dotColor="bg-emerald-500" className="text-[11px]">
                  Connected
                </Badge>
              ) : (
                <Badge variant="secondary" className="text-[11px]">
                  Not Connected
                </Badge>
              )}
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              {githubStatus.connected
                ? `Authorized as @${githubStatus.github_login || "unknown"} (Scope: ${
                    githubStatus.scope || "repo, read:user"
                  })`
                : "Connect your GitHub account using OAuth 2.0 to import public and private repositories."}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5 shrink-0 flex-wrap">
          {githubStatus.connected ? (
            <>
              <div className="hidden sm:flex items-center gap-1.5 text-[11px] text-slate-500 bg-slate-50 border border-slate-200 px-2.5 py-1 rounded-md">
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
                <span>AES-128 Encrypted Credentials</span>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setIsSwitchModalOpen(true)}
                className="text-xs h-7.5 border-slate-200 text-slate-700 hover:text-blue-600 hover:border-blue-200"
              >
                <ArrowRightLeft className="h-3.5 w-3.5 mr-1" />
                Switch Account
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setIsDisconnectModalOpen(true)}
                className="text-xs h-7.5 border-slate-200 text-slate-600 hover:text-rose-600 hover:border-rose-200"
              >
                Disconnect Account
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              className="text-xs h-8 bg-slate-900 hover:bg-slate-800 text-white"
              onClick={() => setIsConnectModalOpen(true)}
            >
              <GitHubIcon className="h-3.5 w-3.5 mr-1.5" />
              Connect GitHub Account
            </Button>
          )}
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-white p-3 rounded-xl border border-slate-200">
        <div className="w-full sm:max-w-md">
          <Input
            placeholder="Filter connected repositories by name or owner..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            icon={<Search className="h-3.5 w-3.5" />}
            className="h-8 text-xs"
          />
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500 w-full sm:w-auto justify-end">
          <span>
            Showing {filtered.length} of {repositories.length} connected repositories in{" "}
            <strong>{activeWorkspace?.name || "workspace"}</strong>
          </span>
        </div>
      </div>

      {/* Main Content: Repositories List or Loading/Empty States */}
      {loading ? (
        <div className="flex flex-col items-center justify-center p-16 bg-white rounded-xl border border-slate-200">
          <Loader2 className="h-8 w-8 text-blue-600 animate-spin mb-3" />
          <p className="text-xs text-slate-500">Loading connected repositories...</p>
        </div>
      ) : repositories.length === 0 ? (
        <EmptyState
          icon={FolderGit2}
          title="No repositories connected"
          description={
            githubStatus.connected
              ? isWorkspaceAdminOrOwner
                ? `Your GitHub account is connected. Select repositories to connect them to "${
                    activeWorkspace?.name || "this workspace"
                  }".`
                : `No repositories connected to "${
                    activeWorkspace?.name || "this workspace"
                  }". Contact a workspace Admin or Owner to connect repositories.`
              : "Connect your GitHub account to import repositories and enable Orchestrix AI agents."
          }
          actionLabel={
            githubStatus.connected
              ? isWorkspaceAdminOrOwner
                ? "Connect GitHub Repository"
                : undefined
              : "Connect GitHub Account"
          }
          onAction={
            githubStatus.connected
              ? handleOpenConnectModal
              : () => setIsConnectModalOpen(true)
          }
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={FolderGit2}
          title="No matching repositories"
          description={`No repositories matched your search query "${searchTerm}".`}
          actionLabel="Clear search"
          onAction={() => setSearchTerm("")}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filtered.map((repo) => (
            <Card
              key={repo.id}
              className="border-slate-200/90 bg-white hover:border-slate-300 transition-colors shadow-xs"
            >
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
                          <span title="Private repository">
                            <Lock className="h-3 w-3 text-slate-400" />
                          </span>
                        ) : (
                          <span title="Public repository">
                            <Globe className="h-3 w-3 text-slate-400" />
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-400 font-mono mt-0.5">{repo.owner_login}</p>
                    </div>
                  </div>

                  <Badge
                    variant={repo.is_active ? "success" : "secondary"}
                    dotColor={repo.is_active ? "bg-emerald-500" : "bg-slate-400"}
                    className="capitalize text-[11px]"
                  >
                    {repo.is_active ? "Active" : "Inactive"}
                  </Badge>
                </div>
              </CardHeader>

              <CardContent className="p-5 pt-0 space-y-4">
                {repo.description && (
                  <p className="text-xs text-slate-600 line-clamp-2">{repo.description}</p>
                )}

                <div className="grid grid-cols-3 gap-2 p-2.5 rounded-lg bg-slate-50 text-xs text-slate-600 border border-slate-200/60 font-mono text-[11px]">
                  <div>
                    <span className="text-slate-400 block text-[10px]">Default Branch</span>
                    <span className="font-semibold text-slate-800 flex items-center gap-1 mt-0.5">
                      <GitBranch className="h-3 w-3 text-blue-600 shrink-0" />
                      <span className="truncate">{repo.default_branch}</span>
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">Language</span>
                    <span className="font-semibold text-slate-800 flex items-center gap-1 mt-0.5 truncate">
                      {repo.language || "Multi"}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px]">Connected</span>
                    <span className="font-semibold text-slate-800 flex items-center gap-1 mt-0.5">
                      <Clock className="h-3 w-3 text-slate-400 shrink-0" />
                      <span>{new Date(repo.created_at).toLocaleDateString()}</span>
                    </span>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-xs">
                  <a
                    href={repo.html_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center text-xs text-slate-500 hover:text-blue-600 transition-colors"
                  >
                    <span>View on GitHub</span>
                    <ExternalLink className="h-3 w-3 ml-1" />
                  </a>

                  <div className="flex items-center gap-1.5">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleRefreshRepo(repo)}
                      disabled={actionLoadingId === repo.id}
                      className="h-7 text-xs text-slate-600 hover:text-blue-600"
                      title="Sync latest metadata from GitHub"
                    >
                      <RefreshCw
                        className={`h-3 w-3 mr-1 ${
                          actionLoadingId === repo.id ? "animate-spin text-blue-600" : ""
                        }`}
                      />
                      Sync
                    </Button>

                    {isWorkspaceAdminOrOwner && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDisconnectRepo(repo)}
                        disabled={actionLoadingId === repo.id}
                        className="h-7 text-xs text-slate-500 hover:text-rose-600"
                        title="Disconnect from workspace"
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Professional Account Connection Dialog */}
      {isConnectModalOpen && (
        <div
          data-testid="connect-account-modal"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4 animate-in fade-in duration-150"
        >
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-xl w-full overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="h-9 w-9 rounded-lg bg-slate-900 text-white flex items-center justify-center">
                  <GitHubIcon className="h-5 w-5" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-slate-900">Connect GitHub to Orchestrix AI</h2>
                  <p className="text-xs text-slate-500">Choose which GitHub account you want to connect</p>
                </div>
              </div>
              <button
                onClick={() => setIsConnectModalOpen(false)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="p-5 space-y-4">
              {/* Option A: Use Current GitHub Account */}
              <div className="p-4 rounded-xl border border-blue-200 bg-blue-50/50 hover:bg-blue-50 transition-colors flex flex-col justify-between gap-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-xs text-slate-900">
                        Option A — Use Current GitHub Account
                      </span>
                      <Badge variant="secondary" className="text-[10px] bg-blue-100 text-blue-800 border-blue-200">
                        Default
                      </Badge>
                    </div>
                    <p className="text-xs text-slate-600 leading-relaxed">
                      GitHub will authorize the account currently signed in to <strong>github.com</strong> in this browser.
                    </p>
                  </div>
                </div>
                <Button
                  size="sm"
                  className="w-full text-xs h-8 bg-blue-600 hover:bg-blue-700 text-white"
                  onClick={() => {
                    setIsConnectModalOpen(false);
                    window.location.href = getGitHubConnectUrl();
                  }}
                >
                  <GitHubIcon className="h-3.5 w-3.5 mr-1.5" />
                  Connect Current Account
                </Button>
              </div>

              {/* Option B: Connect a Different GitHub Account */}
              <div className="p-4 rounded-xl border border-slate-200 bg-slate-50/70 hover:bg-slate-50 transition-colors flex flex-col justify-between gap-3">
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-xs text-slate-900">
                      Option B — Connect a Different GitHub Account
                    </span>
                    <Badge variant="secondary" className="text-[10px]">
                      Account Switch
                    </Badge>
                  </div>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    Because GitHub automatically uses your active session, to connect a different account:
                  </p>
                  <ol className="list-decimal list-inside text-xs text-slate-600 space-y-1 pl-1">
                    <li>
                      Open{" "}
                      <a
                        href="https://github.com/logout"
                        target="_blank"
                        rel="noreferrer"
                        className="text-blue-600 underline font-medium inline-flex items-center gap-0.5"
                      >
                        github.com/logout <ExternalLink className="h-3 w-3 inline" />
                      </a>{" "}
                      to sign out of your current account (or open Orchestrix in a separate private/incognito window).
                    </li>
                    <li>Sign in with your desired GitHub account.</li>
                    <li>Return here and proceed with authorization.</li>
                  </ol>
                </div>
                <div className="flex items-center gap-2 pt-1">
                  <a
                    href="https://github.com/logout"
                    target="_blank"
                    rel="noreferrer"
                    className="flex-1 text-center py-1.5 px-3 rounded-lg border border-slate-300 text-xs text-slate-700 bg-white hover:bg-slate-100 font-medium inline-flex items-center justify-center gap-1.5"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    Sign out of GitHub.com
                  </a>
                  <Button
                    size="sm"
                    className="flex-1 text-xs h-8 bg-slate-900 hover:bg-slate-800 text-white"
                    onClick={() => {
                      setIsConnectModalOpen(false);
                      window.location.href = getGitHubConnectUrl();
                    }}
                  >
                    Proceed to GitHub
                  </Button>
                </div>
              </div>
            </div>

            <div className="p-3.5 border-t border-slate-100 bg-slate-50 flex items-center justify-end">
              <Button
                variant="outline"
                size="sm"
                className="text-xs h-7.5"
                onClick={() => setIsConnectModalOpen(false)}
              >
                Close
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Account Switching Guidance Modal (When already connected) */}
      {isSwitchModalOpen && (
        <div
          data-testid="account-switch-modal"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4 animate-in fade-in duration-150"
        >
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-lg w-full overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="h-8 w-8 rounded-lg bg-slate-900 text-white flex items-center justify-center">
                  <GitHubIcon className="h-4 w-4" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-slate-900">Switch GitHub Account</h2>
                  <p className="text-xs text-slate-500">Connect a different GitHub identity to Orchestrix</p>
                </div>
              </div>
              <button
                onClick={() => setIsSwitchModalOpen(false)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="p-5 space-y-4 text-xs text-slate-600">
              <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-amber-800 space-y-1">
                <div className="flex items-center gap-1.5 font-semibold text-amber-900">
                  <AlertCircle className="h-4 w-4 shrink-0 text-amber-600" />
                  <span>Important: GitHub browser session reuse</span>
                </div>
                <p className="text-[11px] leading-relaxed">
                  GitHub OAuth 2.0 does not support account chooser prompts (such as Google&apos;s prompt parameter). GitHub will automatically authorize whatever account is currently signed in to <span className="font-mono font-semibold">github.com</span> in this browser.
                </p>
              </div>

              <div className="space-y-2">
                <p className="font-semibold text-slate-800">To switch to a different account:</p>
                <ol className="list-decimal list-inside space-y-1.5 text-slate-600 text-[11px] pl-1">
                  <li>
                    Open{" "}
                    <a
                      href="https://github.com/logout"
                      target="_blank"
                      rel="noreferrer"
                      className="text-blue-600 underline font-medium inline-flex items-center gap-0.5"
                    >
                      github.com/logout <ExternalLink className="h-3 w-3 inline" />
                    </a>{" "}
                    in a new tab to <strong>sign out</strong> of your current account (or use an <strong>Incognito / Private</strong> window).
                  </li>
                  <li>
                    Sign in to your target GitHub account on github.com.
                  </li>
                  <li>
                    Click <strong>&quot;Disconnect & Reconnect to GitHub&quot;</strong> below to authorize your target account.
                  </li>
                </ol>
              </div>

              <p className="text-[11px] text-slate-400 italic">
                Note: Existing repositories already imported into your workspace will remain connected and active.
              </p>
            </div>

            <div className="p-4 border-t border-slate-100 bg-slate-50 flex items-center justify-end gap-2.5">
              <Button
                variant="outline"
                size="sm"
                className="text-xs h-8"
                onClick={() => setIsSwitchModalOpen(false)}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                className="text-xs h-8 bg-slate-900 hover:bg-slate-800 text-white"
                onClick={async () => {
                  setIsSwitchModalOpen(false);
                  try {
                    await disconnectGitHub();
                  } catch {
                    // Ignore disconnect failure on switch
                  }
                  window.location.href = getGitHubConnectUrl();
                }}
              >
                Disconnect & Reconnect to GitHub
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Disconnect Confirmation Modal */}
      {isDisconnectModalOpen && (
        <div
          data-testid="disconnect-modal"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4 animate-in fade-in duration-150"
        >
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-md w-full overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="h-8 w-8 rounded-lg bg-rose-50 border border-rose-100 text-rose-600 flex items-center justify-center">
                  <Trash2 className="h-4 w-4" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-slate-900">Disconnect GitHub Account</h2>
                  <p className="text-xs text-slate-500">
                    Disconnect @{githubStatus.github_login || "account"} from Orchestrix
                  </p>
                </div>
              </div>
              <button
                onClick={() => setIsDisconnectModalOpen(false)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="p-5 space-y-3.5 text-xs text-slate-600">
              <p className="leading-relaxed">
                Are you sure you want to disconnect your GitHub identity?
              </p>

              <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-2 text-[11px]">
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 shrink-0 mt-0.5" />
                  <span>
                    <strong>Credentials purged:</strong> Stored OAuth tokens and credentials will be permanently removed from Orchestrix.
                  </span>
                </div>
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 shrink-0 mt-0.5" />
                  <span>
                    <strong>Repositories preserved:</strong> Repositories already connected to your workspace will remain connected and active.
                  </span>
                </div>
                <div className="flex items-start gap-2">
                  <AlertCircle className="h-3.5 w-3.5 text-amber-600 shrink-0 mt-0.5" />
                  <span>
                    <strong>GitHub session remains:</strong> Disconnecting Orchestrix does not sign you out of github.com in your browser.
                  </span>
                </div>
              </div>
            </div>

            <div className="p-4 border-t border-slate-100 bg-slate-50 flex items-center justify-end gap-2.5">
              <Button
                variant="outline"
                size="sm"
                className="text-xs h-8"
                onClick={() => setIsDisconnectModalOpen(false)}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                className="text-xs h-8 bg-rose-600 hover:bg-rose-700 text-white"
                onClick={async () => {
                  setIsDisconnectModalOpen(false);
                  await executeDisconnectGitHub();
                }}
              >
                Confirm Disconnect
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Connect GitHub Repository Modal / Dialog */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4 animate-in fade-in duration-150">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-2xl w-full max-h-[85vh] flex flex-col overflow-hidden">
            {/* Modal Header */}
            <div className="p-5 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold text-slate-900">
                  Connect GitHub Repositories
                </h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Select repositories accessible to your GitHub account to connect to{" "}
                  <span className="font-medium text-slate-800">
                    {activeWorkspace?.name || "your workspace"}
                  </span>
                  .
                </p>
              </div>
              <button
                onClick={() => setIsModalOpen(false)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Modal Search */}
            <div className="p-4 border-b border-slate-100 bg-slate-50/50">
              <Input
                placeholder="Search accessible repositories..."
                value={modalSearchTerm}
                onChange={(e) => setModalSearchTerm(e.target.value)}
                icon={<Search className="h-3.5 w-3.5" />}
                className="h-8.5 text-xs bg-white"
              />
            </div>

            {/* Modal Repository List */}
            <div className="flex-1 overflow-y-auto p-4 space-y-2.5">
              {loadingModal ? (
                <div className="flex flex-col items-center justify-center p-12">
                  <Loader2 className="h-6 w-6 text-blue-600 animate-spin mb-2" />
                  <p className="text-xs text-slate-500">
                    Fetching accessible repositories from GitHub...
                  </p>
                </div>
              ) : filteredAccessible.length === 0 ? (
                <div className="text-center p-8 text-xs text-slate-500">
                  No repositories found matching your search.
                </div>
              ) : (
                filteredAccessible.map((repo) => (
                  <div
                    key={repo.id}
                    className="flex items-center justify-between p-3.5 rounded-xl border border-slate-200 hover:border-slate-300 bg-white transition-colors"
                  >
                    <div className="min-w-0 pr-4">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-xs text-slate-900 truncate">
                          {repo.full_name}
                        </span>
                        {repo.visibility === "private" ? (
                          <Lock className="h-3 w-3 text-slate-400 shrink-0" />
                        ) : (
                          <Globe className="h-3 w-3 text-slate-400 shrink-0" />
                        )}
                      </div>
                      {repo.description && (
                        <p className="text-[11px] text-slate-500 truncate mt-0.5">
                          {repo.description}
                        </p>
                      )}
                      <div className="flex items-center gap-3 text-[10px] text-slate-400 mt-1 font-mono">
                        {repo.language && <span>{repo.language}</span>}
                        <span className="flex items-center gap-0.5">
                          <Star className="h-2.5 w-2.5" />
                          {repo.stargazers_count}
                        </span>
                        <span className="flex items-center gap-0.5">
                          <GitFork className="h-2.5 w-2.5" />
                          {repo.forks_count}
                        </span>
                        <span>branch: {repo.default_branch}</span>
                      </div>
                    </div>

                    <div className="shrink-0">
                      {repo.is_connected ? (
                        <Badge
                          variant="success"
                          dotColor="bg-emerald-500"
                          className="text-[10px] py-1 px-2"
                        >
                          Connected
                        </Badge>
                      ) : (
                        <Button
                          size="sm"
                          className="text-xs h-7.5 bg-blue-600 hover:bg-blue-700 text-white"
                          disabled={connectingRepoId === repo.id || !isWorkspaceAdminOrOwner}
                          onClick={() => handleConnectRepo(repo)}
                        >
                          {connectingRepoId === repo.id ? (
                            <>
                              <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                              Connecting...
                            </>
                          ) : (
                            "Connect"
                          )}
                        </Button>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Modal Footer */}
            <div className="p-3.5 border-t border-slate-100 bg-slate-50 flex items-center justify-between text-xs text-slate-500">
              <span>
                {filteredAccessible.length} repositories available to connect
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setIsModalOpen(false)}
                className="text-xs h-7.5"
              >
                Close
              </Button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
