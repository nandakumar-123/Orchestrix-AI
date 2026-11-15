"use client";

import * as React from "react";
import { Sidebar } from "@/components/navigation/sidebar";
import { Header } from "@/components/navigation/header";

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const [collapsed, setCollapsed] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);

  return (
    <div className="flex h-screen w-full overflow-hidden bg-slate-50">
      {/* Sidebar Navigation */}
      <React.Suspense fallback={<div className="w-64 border-r border-slate-200 bg-white" />}>
        <Sidebar
          collapsed={collapsed}
          onToggleCollapse={() => setCollapsed(!collapsed)}
          mobileOpen={mobileOpen}
          onCloseMobile={() => setMobileOpen(false)}
        />
      </React.Suspense>

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <React.Suspense fallback={<div className="h-14 border-b border-slate-200 bg-white" />}>
          <Header onOpenMobileSidebar={() => setMobileOpen(true)} />
        </React.Suspense>
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <div className="mx-auto max-w-7xl space-y-6">{children}</div>
        </main>
      </div>
    </div>
  );
}

