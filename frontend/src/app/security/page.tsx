"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { SAMPLE_SECURITY_FINDINGS } from "@/lib/mock-data";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ShieldAlert, ShieldCheck } from "lucide-react";

export default function SecurityPage() {
  return (
    <AppShell>
      <PageHeader
        title="Security & Vulnerability Analysis"
        subtitle="Powered by SecureFlow: Continuous SAST scans, secret detection, and taint tracking."
        actions={
          <Button size="sm" className="text-xs h-8">
            <ShieldAlert className="h-3.5 w-3.5 mr-1" />
            Trigger Full Security Audit
          </Button>
        }
      />

      {/* Security Severity Distribution */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <Card className="border-slate-200 bg-white">
          <CardContent className="p-4">
            <span className="text-xs text-rose-600 font-semibold uppercase tracking-wider">Critical</span>
            <p className="text-2xl font-bold text-slate-900 mt-1">0</p>
            <span className="text-[11px] text-slate-400 mt-0.5 block">No critical CVEs</span>
          </CardContent>
        </Card>

        <Card className="border-slate-200 bg-white">
          <CardContent className="p-4">
            <span className="text-xs text-amber-600 font-semibold uppercase tracking-wider">High</span>
            <p className="text-2xl font-bold text-slate-900 mt-1">0</p>
            <span className="text-[11px] text-slate-400 mt-0.5 block">Zero high vulnerabilities</span>
          </CardContent>
        </Card>

        <Card className="border-slate-200 bg-white">
          <CardContent className="p-4">
            <span className="text-xs text-blue-600 font-semibold uppercase tracking-wider">Medium</span>
            <p className="text-2xl font-bold text-slate-900 mt-1">1</p>
            <span className="text-[11px] text-slate-400 mt-0.5 block">Rate limiter advisory</span>
          </CardContent>
        </Card>

        <Card className="border-slate-200 bg-white">
          <CardContent className="p-4">
            <span className="text-xs text-slate-500 font-semibold uppercase tracking-wider">Low</span>
            <p className="text-2xl font-bold text-slate-900 mt-1">1</p>
            <span className="text-[11px] text-slate-400 mt-0.5 block">CORS header recommendation</span>
          </CardContent>
        </Card>
      </div>

      {/* Security Findings Table */}
      <Card className="border-slate-200 bg-white">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-blue-600" />
            Active Findings Log
          </CardTitle>
        </CardHeader>

        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Finding ID</TableHead>
                <TableHead>Advisory Title</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Code Location</TableHead>
                <TableHead>Detected By</TableHead>
                <TableHead className="text-right">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {SAMPLE_SECURITY_FINDINGS.map((finding) => (
                <TableRow key={finding.id}>
                  <TableCell className="font-mono text-xs text-slate-500">
                    {finding.id}
                  </TableCell>
                  <TableCell className="font-medium text-slate-900 text-xs sm:text-sm">
                    {finding.title}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        finding.severity === "critical" || finding.severity === "high"
                          ? "destructive"
                          : finding.severity === "medium"
                          ? "warning"
                          : "secondary"
                      }
                      className="capitalize text-[11px]"
                    >
                      {finding.severity}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-slate-600">
                    {finding.location}
                  </TableCell>
                  <TableCell>
                    <Badge variant="agent">{finding.agent}</Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <span className="text-xs font-medium text-slate-600 capitalize">
                      {finding.status.replace("_", " ")}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </AppShell>
  );
}
