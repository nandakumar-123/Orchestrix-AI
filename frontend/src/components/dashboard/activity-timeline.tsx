import * as React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ActivityEventItem } from "@/lib/dashboard";
import { Clock, CheckCircle2, AlertCircle, RefreshCw, Activity } from "lucide-react";

interface ActivityTimelineProps {
  activities: ActivityEventItem[];
}

export function ActivityTimeline({ activities }: ActivityTimelineProps) {
  return (
    <Card className="border-slate-200/90 bg-white">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Clock className="h-4 w-4 text-blue-600" />
            Recent Engineering Activity
          </CardTitle>
          <span className="text-[11px] text-slate-400 font-mono">
            Audit Stream
          </span>
        </div>
      </CardHeader>

      <CardContent className="p-0">
        {activities.length === 0 ? (
          <div className="p-6 text-center text-xs text-slate-500">
            No recent activity recorded in this workspace.
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {activities.map((item) => {
              const isCompleted = item.status === "COMPLETED" || item.status === "PASSED" || item.status === "ACTIVE";
              const isInProgress = item.status === "RUNNING" || item.status === "INDEXING" || item.status === "PENDING";
              const isFailed = item.status === "FAILED";

              return (
                <div
                  key={item.id}
                  className="p-3.5 sm:px-5 hover:bg-slate-50/70 transition-colors flex items-start justify-between gap-3 text-xs"
                >
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5">
                      {isCompleted && <CheckCircle2 className="h-4 w-4 text-emerald-600" />}
                      {isInProgress && <RefreshCw className="h-4 w-4 text-blue-600 animate-spin" />}
                      {isFailed && <AlertCircle className="h-4 w-4 text-rose-600" />}
                      {!isCompleted && !isInProgress && !isFailed && (
                        <Activity className="h-4 w-4 text-slate-400" />
                      )}
                    </div>

                    <div className="space-y-1">
                      <p className="font-medium text-slate-900">{item.title}</p>
                      {item.description && (
                        <p className="text-slate-500 text-[11px] leading-relaxed max-w-xl">
                          {item.description}
                        </p>
                      )}
                      <div className="flex items-center gap-2 pt-0.5 text-[11px] text-slate-400">
                        {item.repository_name && (
                          <>
                            <span className="font-mono text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded">
                              {item.repository_name}
                            </span>
                            <span>&bull;</span>
                          </>
                        )}
                        {item.agent && (
                          <span className="font-semibold text-blue-600">
                            {item.agent}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <span className="text-[11px] text-slate-400 whitespace-nowrap shrink-0">
                    {new Date(item.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
