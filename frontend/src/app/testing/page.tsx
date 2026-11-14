"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { SAMPLE_TEST_EXECUTIONS } from "@/lib/mock-data";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FlaskConical, Play } from "lucide-react";

export default function TestingPage() {
  return (
    <AppShell>
      <PageHeader
        title="Automated Software Testing"
        subtitle="Powered by TestPilot: Autonomous test synthesis, fuzzing, and regression guards."
        actions={
          <Button size="sm" className="text-xs h-8">
            <Play className="h-3.5 w-3.5 mr-1" />
            Synthesize New Tests
          </Button>
        }
      />

      {/* Test Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <Card className="border-slate-200 bg-white">
          <CardContent className="p-4">
            <span className="text-xs text-slate-500 font-mono">Test Pass Rate</span>
            <p className="text-2xl font-bold text-emerald-600 mt-1">100%</p>
            <span className="text-[11px] text-slate-400 mt-0.5 block">98 total tests run</span>
          </CardContent>
        </Card>

        <Card className="border-slate-200 bg-white">
          <CardContent className="p-4">
            <span className="text-xs text-slate-500 font-mono">Coverage Achieved</span>
            <p className="text-2xl font-bold text-blue-600 mt-1">94.8%</p>
            <span className="text-[11px] text-slate-400 mt-0.5 block">+3.2% from last cycle</span>
          </CardContent>
        </Card>

        <Card className="border-slate-200 bg-white">
          <CardContent className="p-4">
            <span className="text-xs text-slate-500 font-mono">Edge Cases Generated</span>
            <p className="text-2xl font-bold text-slate-900 mt-1">324</p>
            <span className="text-[11px] text-slate-400 mt-0.5 block">Synthesized by TestPilot</span>
          </CardContent>
        </Card>

        <Card className="border-slate-200 bg-white">
          <CardContent className="p-4">
            <span className="text-xs text-slate-500 font-mono">Regression Flakiness</span>
            <p className="text-2xl font-bold text-slate-900 mt-1">0.0%</p>
            <span className="text-[11px] text-emerald-600 mt-0.5 block">Zero flaky assertions</span>
          </CardContent>
        </Card>
      </div>

      {/* Test Run History */}
      <Card className="border-slate-200 bg-white">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-blue-600" />
            Recent Automated Test Executions
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run ID</TableHead>
                <TableHead>Test Suite</TableHead>
                <TableHead>Passed</TableHead>
                <TableHead>Failed</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Executed</TableHead>
                <TableHead className="text-right">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {SAMPLE_TEST_EXECUTIONS.map((run) => (
                <TableRow key={run.id}>
                  <TableCell className="font-mono text-xs text-slate-500">
                    {run.id}
                  </TableCell>
                  <TableCell className="font-medium text-slate-900 text-xs sm:text-sm">
                    {run.suite}
                  </TableCell>
                  <TableCell>
                    <span className="text-emerald-600 font-semibold font-mono text-xs">
                      {run.passed}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-rose-600 font-semibold font-mono text-xs">
                      {run.failed}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-slate-500">
                    {run.duration}
                  </TableCell>
                  <TableCell className="text-xs text-slate-400">
                    {run.executedAt}
                  </TableCell>
                  <TableCell className="text-right">
                    <Badge variant="success" className="text-[11px]">
                      {run.status}
                    </Badge>
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
