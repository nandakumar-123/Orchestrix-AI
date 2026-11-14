"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Menu,
  Search,
  Bell,
  GitBranch,
  ChevronRight,
  ShieldCheck,
  User,
  LogOut,
  LogIn,
  Building,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CurrentUser, fetchCurrentUser, logout } from "@/lib/auth";

interface HeaderProps {
  onOpenMobileSidebar: () => void;
}

const ROUTE_LABELS: Record<string, { title: string; category: string }> = {
  "/dashboard": { title: "Engineering Overview", category: "Overview" },
  "/repositories": { title: "Connected Repositories", category: "Engineering" },
  "/agents": { title: "AI Agent Mesh", category: "Engineering" },
  "/tasks": { title: "Tasks & Ticket Pipeline", category: "Engineering" },
  "/impact": { title: "Change Impact Intelligence", category: "Engineering" },
  "/testing": { title: "Automated Software Testing", category: "Engineering" },
  "/security": { title: "Security & Vulnerability Analysis", category: "Engineering" },
  "/workflows": { title: "Visual Workflow Builder", category: "Automation" },
  "/executions": { title: "Execution Runs & Audit Log", category: "Automation" },
  "/memory": { title: "Engineering Memory & ADRs", category: "Knowledge" },
  "/knowledge-graph": { title: "Knowledge Graph Workspace", category: "Knowledge" },
  "/notifications": { title: "Notifications & Alerts", category: "System" },
  "/settings": { title: "Workspace & Agent Settings", category: "System" },
};

export function Header({ onOpenMobileSidebar }: HeaderProps) {
  const pathname = usePathname();
  const router = useRouter();
  const currentRoute = ROUTE_LABELS[pathname] || {
    title: "Engineering Workspace",
    category: "Platform",
  };

  const [notificationOpen, setNotificationOpen] = React.useState(false);
  const [profileOpen, setProfileOpen] = React.useState(false);
  const [searchQuery, setSearchQuery] = React.useState("");
  const [currentUser, setCurrentUser] = React.useState<CurrentUser | null>(null);
  const [loadingAuth, setLoadingAuth] = React.useState(true);

  React.useEffect(() => {
    let mounted = true;
    fetchCurrentUser().then((user) => {
      if (mounted) {
        setCurrentUser(user);
        setLoadingAuth(false);
      }
    });
    return () => {
      mounted = false;
    };
  }, []);

  const handleLogout = async () => {
    await logout();
    setCurrentUser(null);
    router.push("/login");
    router.refresh();
  };

  const initials = React.useMemo(() => {
    if (!currentUser) return "NK";
    if (currentUser.full_name) {
      const parts = currentUser.full_name.trim().split(/\s+/);
      if (parts.length >= 2) {
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
      }
      return parts[0].slice(0, 2).toUpperCase();
    }
    return currentUser.email.slice(0, 2).toUpperCase();
  }, [currentUser]);

  return (
    <header className="sticky top-0 z-30 flex h-14 w-full items-center justify-between border-b border-slate-200 bg-white/95 px-4 backdrop-blur-xs">
      {/* Left: Mobile trigger & Breadcrumbs */}
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon"
          onClick={onOpenMobileSidebar}
          className="md:hidden text-slate-500"
          aria-label="Open navigation drawer"
        >
          <Menu className="h-5 w-5" />
        </Button>

        <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-xs">
          <span className="text-slate-400 font-medium">{currentRoute.category}</span>
          <ChevronRight className="h-3.5 w-3.5 text-slate-300" />
          <span className="font-semibold text-slate-900 truncate">
            {currentRoute.title}
          </span>
        </nav>
      </div>

      {/* Middle: Global Search */}
      <div className="hidden lg:flex items-center max-w-sm w-full mx-4">
        <Input
          placeholder="Search agents, tasks, PRs, or commits (Ctrl+K)..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          icon={<Search className="h-3.5 w-3.5" />}
          className="h-8 text-xs bg-slate-50 border-slate-200 focus:bg-white"
        />
      </div>

      {/* Right Controls */}
      <div className="flex items-center gap-2">
        {/* Repo Badge */}
        <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-slate-100 text-slate-700 text-xs border border-slate-200/60 font-mono">
          <GitBranch className="h-3.5 w-3.5 text-blue-600" />
          <span className="truncate max-w-[120px]">Orchestrix-AI</span>
        </div>

        {/* Notification Bell Dropdown */}
        <div className="relative">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => {
              setNotificationOpen(!notificationOpen);
              setProfileOpen(false);
            }}
            className="relative text-slate-600 hover:text-slate-900"
            aria-label="View notifications"
          >
            <Bell className="h-4 w-4" />
            <span className="absolute top-1.5 right-1.5 flex h-2 w-2 rounded-full bg-blue-600 ring-2 ring-white" />
          </Button>

          {notificationOpen && (
            <div className="absolute right-0 mt-2 w-80 rounded-xl border border-slate-200 bg-white p-3 shadow-lg z-50">
              <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-100">
                <span className="font-semibold text-xs text-slate-900">
                  Engineering Notifications
                </span>
                <Badge variant="default" className="text-[10px]">
                  2 new
                </Badge>
              </div>
              <div className="space-y-2 text-xs">
                <div className="p-2 rounded-lg bg-blue-50/70 border border-blue-100">
                  <p className="font-medium text-blue-900">
                    DevPilot opened PR #104
                  </p>
                  <p className="text-[11px] text-blue-700 mt-0.5">
                    Auth refactoring with 100% test coverage synthesized.
                  </p>
                  <span className="text-[10px] text-blue-500 mt-1 block">
                    3m ago
                  </span>
                </div>
                <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
                  <p className="font-medium text-slate-800">
                    TestPilot verified test suites
                  </p>
                  <p className="text-[11px] text-slate-600 mt-0.5">
                    All 64 property-based tests passed with zero regression.
                  </p>
                  <span className="text-[10px] text-slate-400 mt-1 block">
                    18m ago
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* User Profile / Auth Action */}
        {loadingAuth ? (
          <div className="h-8 w-8 animate-pulse rounded-full bg-slate-200" />
        ) : currentUser ? (
          <div className="relative">
            <button
              type="button"
              onClick={() => {
                setProfileOpen(!profileOpen);
                setNotificationOpen(false);
              }}
              className="flex items-center gap-2 rounded-full focus:outline-none focus:ring-2 focus:ring-blue-600 focus:ring-offset-1"
              aria-label="User account menu"
            >
              {currentUser.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={currentUser.avatar_url}
                  alt={currentUser.full_name || currentUser.email}
                  className="h-8 w-8 rounded-full object-cover border border-slate-200"
                />
              ) : (
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-600 text-white font-semibold text-xs shadow-xs">
                  {initials}
                </div>
              )}
            </button>

            {profileOpen && (
              <div className="absolute right-0 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-2 shadow-xl z-50 text-xs">
                <div className="px-2 py-2 border-b border-slate-100">
                  <p className="font-semibold text-slate-900 truncate">
                    {currentUser.full_name || currentUser.email}
                  </p>
                  <p className="text-[11px] text-slate-500 font-mono truncate">
                    {currentUser.email}
                  </p>
                  {currentUser.workspaces.length > 0 && (
                    <div className="mt-1.5 flex items-center justify-between pt-1 border-t border-slate-50">
                      <span className="text-[10px] text-slate-400 flex items-center gap-1 truncate max-w-[140px]">
                        <Building className="h-2.5 w-2.5" />
                        {currentUser.workspaces[0].name}
                      </span>
                      <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider bg-blue-50 text-blue-700 border border-blue-100">
                        {currentUser.workspaces[0].role}
                      </span>
                    </div>
                  )}
                </div>
                <div className="pt-1 space-y-0.5">
                  <Link
                    href="/settings"
                    onClick={() => setProfileOpen(false)}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-slate-600 hover:bg-slate-50 transition"
                  >
                    <User className="h-3.5 w-3.5" />
                    <span>Workspace Settings</span>
                  </Link>
                  <Link
                    href="/security"
                    onClick={() => setProfileOpen(false)}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-slate-600 hover:bg-slate-50 transition"
                  >
                    <ShieldCheck className="h-3.5 w-3.5" />
                    <span>Security & Audits</span>
                  </Link>
                  <div className="my-1 border-t border-slate-100" />
                  <button
                    type="button"
                    onClick={handleLogout}
                    className="flex w-full items-center gap-2 px-2 py-1.5 rounded-lg text-red-600 hover:bg-red-50 transition text-left"
                  >
                    <LogOut className="h-3.5 w-3.5" />
                    <span>Sign Out</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <Link
            href="/login"
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-blue-700 transition active:scale-[0.98]"
          >
            <LogIn className="h-3.5 w-3.5" />
            <span>Sign In</span>
          </Link>
        )}
      </div>
    </header>
  );
}
