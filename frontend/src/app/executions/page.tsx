"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { SAMPLE_ACTIVITIES } from "@/lib/mock-data";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RotateCw } from "lucide-react";

export default function ExecutionsPage() {
  return (
    <AppShell>
      <PageHeader
        title="Execution Runs & Audit Log"
        subtitle="Chronological execution trace of all multi-agent operations and state machine transitions."
        actions={
          <Button variant="outline" size="sm" className="text-xs h-8">
            <RotateCw className="h-3.5 w-3.5 mr-1.5 text-slate-500" />
            Refresh Logs
          </Button>
        }
      />

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Execution ID</TableHead>
            <TableHead>Operation / Event</TableHead>
            <TableHead>Repository</TableHead>
            <TableHead>Agent</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Timestamp</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {SAMPLE_ACTIVITIES.map((act) => (
            <TableRow key={act.id}>
              <TableCell className="font-mono text-xs text-slate-500">
                {act.id}
              </TableCell>
              <TableCell>
                <div className="font-medium text-slate-900 text-xs sm:text-sm">
                  {act.eventName}
                </div>
                {act.description && (
                  <div className="text-[11px] text-slate-500 mt-0.5">
                    {act.description}
                  </div>
                )}
              </TableCell>
              <TableCell>
                <span className="font-mono text-xs bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded">
                  {act.repository}
                </span>
              </TableCell>
              <TableCell>
                <Badge variant="agent">{act.agent}</Badge>
              </TableCell>
              <TableCell>
                <Badge
                  variant={
                    act.status === "completed"
                      ? "success"
                      : act.status === "in_progress"
                      ? "default"
                      : "secondary"
                  }
                  className="capitalize text-[11px]"
                >
                  {act.status.replace("_", " ")}
                </Badge>
              </TableCell>
              <TableCell className="text-right text-xs text-slate-400 font-mono">
                {act.timestamp}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </AppShell>
  );
}
