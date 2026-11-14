"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CheckCircle2, AlertTriangle, Info, Check } from "lucide-react";

interface NotificationItem {
  id: string;
  title: string;
  message: string;
  timestamp: string;
  type: "info" | "warning" | "success";
  unread: boolean;
  agent: string;
}

const NOTIFICATIONS: NotificationItem[] = [
  {
    id: "notif-1",
    title: "PR #104 Ready for Review",
    message: "DevPilot has completed OAuth token introspection implementation with 100% test coverage.",
    timestamp: "3 minutes ago",
    type: "success",
    unread: true,
    agent: "DevPilot",
  },
  {
    id: "notif-2",
    title: "Dependency Rate-Limiter Advisory",
    message: "SecureFlow detected an unthrottled route in backend auth endpoint. Mitigation patch staged.",
    timestamp: "45 minutes ago",
    type: "warning",
    unread: true,
    agent: "SecureFlow",
  },
  {
    id: "notif-3",
    title: "Graph Indexing Complete",
    message: "DevMemory synchronized 14,280 AST entities into the Neo4j ontology store.",
    timestamp: "2 hours ago",
    type: "info",
    unread: false,
    agent: "DevMemory",
  },
];

export default function NotificationsPage() {
  const [items, setItems] = React.useState(NOTIFICATIONS);

  const markAllRead = () => {
    setItems(items.map((i) => ({ ...i, unread: false })));
  };

  return (
    <AppShell>
      <PageHeader
        title="Notifications & Alerts"
        subtitle="Operational event stream dispatched from the autonomous agent mesh."
        actions={
          <Button variant="outline" size="sm" onClick={markAllRead} className="text-xs h-8">
            <Check className="h-3.5 w-3.5 mr-1 text-slate-500" />
            Mark all as read
          </Button>
        }
      />

      <div className="space-y-3">
        {items.map((item) => (
          <Card
            key={item.id}
            className={`border-slate-200 bg-white transition-all ${
              item.unread ? "border-l-4 border-l-blue-600 bg-blue-50/20" : ""
            }`}
          >
            <CardContent className="p-4 flex items-start justify-between gap-3 text-xs">
              <div className="flex items-start gap-3">
                <div className="mt-0.5">
                  {item.type === "success" && <CheckCircle2 className="h-4 w-4 text-emerald-600" />}
                  {item.type === "warning" && <AlertTriangle className="h-4 w-4 text-amber-600" />}
                  {item.type === "info" && <Info className="h-4 w-4 text-blue-600" />}
                </div>

                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <h4 className="font-semibold text-slate-900 text-xs sm:text-sm">{item.title}</h4>
                    {item.unread && (
                      <Badge variant="default" className="text-[10px] py-0">New</Badge>
                    )}
                  </div>
                  <p className="text-slate-600 leading-relaxed max-w-2xl">{item.message}</p>
                  <div className="flex items-center gap-2 pt-1 text-[11px] text-slate-400 font-mono">
                    <Badge variant="agent">{item.agent}</Badge>
                    <span>&bull;</span>
                    <span>{item.timestamp}</span>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </AppShell>
  );
}
