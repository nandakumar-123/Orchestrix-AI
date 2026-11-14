import * as React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TaskItem } from "@/types";
import { CheckSquare, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

interface RecentTasksProps {
  tasks: TaskItem[];
}

export function RecentTasks({ tasks }: RecentTasksProps) {
  return (
    <Card className="border-slate-200/90 bg-white">
      <CardHeader className="pb-3 flex flex-row items-center justify-between">
        <CardTitle className="text-sm font-semibold flex items-center gap-2">
          <CheckSquare className="h-4 w-4 text-blue-600" />
          Active Tasks & Queue
        </CardTitle>
        <Link href="/tasks">
          <Button variant="ghost" size="sm" className="h-7 text-xs text-blue-600">
            All tasks
            <ArrowUpRight className="h-3 w-3 ml-1" />
          </Button>
        </Link>
      </CardHeader>

      <CardContent className="p-0">
        <div className="divide-y divide-slate-100">
          {tasks.map((task) => (
            <div
              key={task.id}
              className="p-3.5 sm:px-5 hover:bg-slate-50/70 transition-colors flex items-center justify-between gap-3 text-xs"
            >
              <div className="space-y-1 min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[11px] text-slate-400">
                    {task.id}
                  </span>
                  <p className="font-medium text-slate-900 truncate">
                    {task.title}
                  </p>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-slate-400">
                  <span className="font-mono text-slate-600 bg-slate-100 px-1 rounded">
                    {task.repository}
                  </span>
                  <span>&bull;</span>
                  <span className="text-blue-600 font-medium">
                    {task.assignedAgent}
                  </span>
                  {task.branch && (
                    <>
                      <span>&bull;</span>
                      <span className="font-mono truncate">{task.branch}</span>
                    </>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
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
                <span className="text-[11px] text-slate-400 hidden sm:inline">
                  {task.updatedAt}
                </span>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

