"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  GitBranch,
  Bot,
  CheckSquare,
  Network,
  FlaskConical,
  ShieldAlert,
  Workflow,
  History,
  BrainCircuit,
  Share2,
  Bell,
  Settings,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FolderGit2,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItem {
  title: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
}

interface NavGroup {
  group: string;
  items: NavItem[];
}

const NAVIGATION_GROUPS: NavGroup[] = [
  {
    group: "OVERVIEW",
    items: [
      { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
    ],
  },
  {
    group: "ENGINEERING",
    items: [
      { title: "Repositories", href: "/repositories", icon: GitBranch },
      { title: "AI Agents", href: "/agents", icon: Bot, badge: "6 Active" },
      { title: "Tasks & Tickets", href: "/tasks", icon: CheckSquare },
      { title: "Change Intelligence", href: "/impact", icon: Network },
      { title: "Testing", href: "/testing", icon: FlaskConical },
      { title: "Security", href: "/security", icon: ShieldAlert },
    ],
  },
  {
    group: "AUTOMATION",
    items: [
      { title: "Workflow Builder", href: "/workflows", icon: Workflow },
      { title: "Execution History", href: "/executions", icon: History },
    ],
  },
  {
    group: "KNOWLEDGE",
    items: [
      { title: "Engineering Memory", href: "/memory", icon: BrainCircuit },
      { title: "Knowledge Graph", href: "/knowledge-graph", icon: Share2 },
    ],
  },
  {
    group: "SYSTEM",
    items: [
      { title: "Notifications", href: "/notifications", icon: Bell, badge: "2" },
      { title: "Settings", href: "/settings", icon: Settings },
    ],
  },
];

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export function Sidebar({
  collapsed,
  onToggleCollapse,
  mobileOpen,
  onCloseMobile,
}: SidebarProps) {
  const pathname = usePathname();

  return (
    <>
      {/* Mobile Backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-xs md:hidden"
          onClick={onCloseMobile}
        />
      )}

      {/* Sidebar Container */}
      <aside
        className={cn(
          "fixed top-0 bottom-0 left-0 z-50 flex flex-col border-r border-slate-200 bg-white transition-all duration-300 md:static",
          collapsed ? "w-16" : "w-64",
          mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        )}
      >
        {/* Brand Header */}
        <div className="flex h-14 items-center justify-between border-b border-slate-200 px-4">
          <Link
            href="/dashboard"
            className="flex items-center gap-2.5 overflow-hidden"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-white font-bold text-sm shadow-xs">
              OX
            </div>
            {!collapsed && (
              <div className="flex flex-col">
                <span className="font-semibold text-sm tracking-tight text-slate-900">
                  Orchestrix AI
                </span>
                <span className="text-[10px] text-slate-400 font-mono tracking-wider uppercase">
                  Multi-Agent Platform
                </span>
              </div>
            )}
          </Link>

          {/* Desktop Collapse Toggle */}
          <button
            type="button"
            onClick={onToggleCollapse}
            className="hidden md:flex h-6 w-6 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronLeft className="h-4 w-4" />
            )}
          </button>
        </div>

        {/* Repository Context Switcher */}
        {!collapsed && (
          <div className="p-3 border-b border-slate-100">
            <div className="flex items-center justify-between p-2 rounded-lg bg-slate-50 border border-slate-200/80 text-xs cursor-pointer hover:bg-slate-100/70 transition-colors">
              <div className="flex items-center gap-2 min-w-0">
                <FolderGit2 className="h-4 w-4 text-blue-600 shrink-0" />
                <div className="truncate">
                  <p className="font-medium text-slate-800 truncate">
                    Orchestrix-AI
                  </p>
                  <p className="text-[10px] text-slate-500 font-mono">
                    main &bull; active
                  </p>
                </div>
              </div>
              <ChevronDown className="h-3.5 w-3.5 text-slate-400 shrink-0" />
            </div>
          </div>
        )}

        {/* Nav Items */}
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-5">
          {NAVIGATION_GROUPS.map((group) => (
            <div key={group.group} className="space-y-1">
              {!collapsed && (
                <div className="px-2 text-[10px] font-semibold text-slate-400 tracking-wider">
                  {group.group}
                </div>
              )}
              {group.items.map((item) => {
                const isActive =
                  pathname === item.href ||
                  (item.href !== "/dashboard" && pathname?.startsWith(item.href));
                const Icon = item.icon;

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={onCloseMobile}
                    className={cn(
                      "group flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors select-none",
                      isActive
                        ? "bg-blue-50 text-blue-700 font-semibold"
                        : "text-slate-600 hover:bg-slate-100/80 hover:text-slate-900"
                    )}
                    title={collapsed ? item.title : undefined}
                  >
                    <Icon
                      className={cn(
                        "h-4 w-4 shrink-0 transition-colors",
                        isActive
                          ? "text-blue-600"
                          : "text-slate-400 group-hover:text-slate-700"
                      )}
                    />
                    {!collapsed && (
                      <span className="truncate flex-1">{item.title}</span>
                    )}
                    {!collapsed && item.badge && (
                      <span
                        className={cn(
                          "rounded-md px-1.5 py-0.5 text-[10px] font-mono",
                          isActive
                            ? "bg-blue-100/80 text-blue-800 font-semibold"
                            : "bg-slate-100 text-slate-500"
                        )}
                      >
                        {item.badge}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          ))}
        </div>

        {/* System Footprint */}
        {!collapsed && (
          <div className="p-3 border-t border-slate-200 bg-slate-50/50">
            <div className="flex items-center gap-2.5">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
              </span>
              <div className="text-[11px] leading-tight text-slate-600">
                <span className="font-semibold text-slate-800">Mesh Status: </span>
                <span className="text-emerald-700">All Agents Ready</span>
              </div>
            </div>
          </div>
        )}
      </aside>
    </>
  );
}

