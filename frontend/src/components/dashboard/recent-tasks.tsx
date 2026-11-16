import * as React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TaskSummaryItem } from "@/lib/dashboard";
import { CheckSquare, ArrowUpRight, PlayCircle, CheckCircle2, AlertCircle, Clock } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

interface RecentTasksProps {
  tasks: TaskSummaryItem[];
}

export function RecentTasks({ tasks }: RecentTasksProps) {
  return (
    <Card className="border-slate-200/90 bg-white">
      <CardHeader className="pb-3 flex flex-row items-center justify-between">
        <CardTitle className="text-sm font-semibold flex items-center gap-2">
          <CheckSquare className="h-4 w-4 text-blue-600" />
          Active Tasks & Queue
        </CardTitle>
        <Link href="/devpilot">
          <Button variant="ghost" size="sm" className="h-7 text-xs text-blue-600">
            DevPilot Tasks
            <ArrowUpRight className="h-3 w-3 ml-1" />
          </Button>
        </Link>
      </CardHeader>

      <CardContent className="p-0">
        {tasks.length === 0 ? (
          <div className="p-6 text-center text-xs text-slate-500">
            No active or recent tasks found in this workspace.
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {tasks.map((task) => {
              const isRunning =
                task.status === "RUNNING" ||
                task.status === "IN_PROGRESS" ||
                task.status === "ANALYZING" ||
                task.status === "APPLYING";
              const isCompleted = task.status === "COMPLETED";
              const isFailed = task.status === "FAILED";

              return (
                <div
                  key={task.id}
                  className="p-3.5 sm:px-5 hover:bg-slate-50/70 transition-colors flex items-center justify-between gap-3 text-xs"
                >
                  <div className="space-y-1 min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11px] text-slate-400">
                        {task.id.slice(0, 8)}
                      </span>
                      <p className="font-medium text-slate-900 truncate">
                        {task.title}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 text-[11px] text-slate-400">
                      {task.repository_name && (
                        <span className="font-mono text-slate-600 bg-slate-100 px-1 rounded truncate max-w-[120px]">
                          {task.repository_name}
                        </span>
                      )}
                      {task.repository_name && <span>&bull;</span>}
                      <span className="text-blue-600 font-medium">
                        {task.assigned_agent || task.task_type}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <Badge
                      variant={
                        isRunning
                          ? "default"
                          : isCompleted
                          ? "success"
                          : isFailed
                          ? "destructive"
                          : "secondary"
                      }
                      className="capitalize text-[11px] flex items-center gap-1"
                    >
                      {isRunning && <PlayCircle className="h-3 w-3 animate-pulse" />}
                      {isCompleted && <CheckCircle2 className="h-3 w-3" />}
                      {isFailed && <AlertCircle className="h-3 w-3" />}
                      {!isRunning && !isCompleted && !isFailed && <Clock className="h-3 w-3" />}
                      <span>{task.status.toLowerCase().replace(/_/g, " ")}</span>
                    </Badge>
                    <span className="text-[11px] text-slate-400 hidden sm:inline">
                      {new Date(task.updated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
