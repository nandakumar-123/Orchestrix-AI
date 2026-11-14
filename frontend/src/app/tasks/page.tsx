"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { SAMPLE_TASKS } from "@/lib/mock-data";
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
import { EmptyState } from "@/components/shared/empty-state";
import { Search, Plus, CheckSquare } from "lucide-react";

export default function TasksPage() {
  const [searchTerm, setSearchTerm] = React.useState("");
  const [statusFilter, setStatusFilter] = React.useState<string>("all");

  const filteredTasks = SAMPLE_TASKS.filter((task) => {
    const matchesSearch =
      task.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      task.repository.toLowerCase().includes(searchTerm.toLowerCase()) ||
      task.assignedAgent.toLowerCase().includes(searchTerm.toLowerCase());

    const matchesStatus =
      statusFilter === "all" || task.status === statusFilter;

    return matchesSearch && matchesStatus;
  });

  return (
    <AppShell>
      <PageHeader
        title="Tasks & Ticket Pipeline"
        subtitle="Track autonomous engineering tasks dispatched to specialized AI agents."
        actions={
          <Button size="sm" className="text-xs h-8">
            <Plus className="h-3.5 w-3.5 mr-1" />
            Create Task
          </Button>
        }
      />

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-white p-3 rounded-xl border border-slate-200">
        <div className="w-full sm:max-w-md">
          <Input
            placeholder="Search tasks, repos, or assigned agents..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            icon={<Search className="h-3.5 w-3.5" />}
            className="h-8 text-xs"
          />
        </div>

        <div className="flex items-center gap-1.5 w-full sm:w-auto justify-end">
          {["all", "running", "completed", "pending"].map((status) => (
            <Button
              key={status}
              variant={statusFilter === status ? "default" : "outline"}
              size="sm"
              onClick={() => setStatusFilter(status)}
              className="capitalize text-xs h-7 px-2.5"
            >
              {status}
            </Button>
          ))}
        </div>
      </div>

      {filteredTasks.length === 0 ? (
        <EmptyState
          icon={CheckSquare}
          title="No tasks match filter"
          description="Try adjusting your search criteria or clear status filters."
          actionLabel="Reset filters"
          onAction={() => {
            setSearchTerm("");
            setStatusFilter("all");
          }}
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[100px]">Task ID</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Repository</TableHead>
              <TableHead>Assigned Agent</TableHead>
              <TableHead>Priority</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredTasks.map((task) => (
              <TableRow key={task.id}>
                <TableCell className="font-mono text-xs text-slate-500">
                  {task.id}
                </TableCell>
                <TableCell>
                  <div className="font-medium text-slate-900 text-xs sm:text-sm">
                    {task.title}
                  </div>
                  {task.branch && (
                    <div className="text-[11px] font-mono text-slate-400 mt-0.5">
                      {task.branch}
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <span className="font-mono text-xs bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded">
                    {task.repository}
                  </span>
                </TableCell>
                <TableCell>
                  <Badge variant="agent">{task.assignedAgent}</Badge>
                </TableCell>
                <TableCell>
                  <span
                    className={`inline-flex items-center text-xs font-semibold capitalize ${
                      task.priority === "critical"
                        ? "text-rose-600"
                        : task.priority === "high"
                        ? "text-amber-600"
                        : "text-slate-600"
                    }`}
                  >
                    {task.priority}
                  </span>
                </TableCell>
                <TableCell>
                  <Badge
                    variant={
                      task.status === "running"
                        ? "default"
                        : task.status === "completed"
                        ? "success"
                        : "secondary"
                    }
                    className="capitalize text-[11px]"
                  >
                    {task.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-right text-xs text-slate-400 font-mono">
                  {task.updatedAt}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </AppShell>
  );
}
