import * as React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ActivityEvent } from "@/types";
import { Clock, CheckCircle2, AlertCircle, RefreshCw } from "lucide-react";

interface ActivityTimelineProps {
  activities: ActivityEvent[];
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
            Live Stream
          </span>
        </div>
      </CardHeader>

      <CardContent className="p-0">
        <div className="divide-y divide-slate-100">
          {activities.map((item) => (
            <div
              key={item.id}
              className="p-3.5 sm:px-5 hover:bg-slate-50/70 transition-colors flex items-start justify-between gap-3 text-xs"
            >
              <div className="flex items-start gap-3">
                <div className="mt-0.5">
                  {item.status === "completed" && (
                    <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                  )}
                  {item.status === "in_progress" && (
                    <RefreshCw className="h-4 w-4 text-blue-600 animate-spin" />
                  )}
                  {item.status === "failed" && (
                    <AlertCircle className="h-4 w-4 text-rose-600" />
                  )}
                  {item.status === "queued" && (
                    <Clock className="h-4 w-4 text-slate-400" />
                  )}
                </div>

                <div className="space-y-1">
                  <p className="font-medium text-slate-900">{item.eventName}</p>
                  {item.description && (
                    <p className="text-slate-500 text-[11px] leading-relaxed max-w-xl">
                      {item.description}
                    </p>
                  )}
                  <div className="flex items-center gap-2 pt-0.5 text-[11px] text-slate-400">
                    <span className="font-mono text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded">
                      {item.repository}
                    </span>
                    <span>&bull;</span>
                    <span className="font-semibold text-blue-600">
                      {item.agent}
                    </span>
                  </div>
                </div>
              </div>

              <span className="text-[11px] text-slate-400 whitespace-nowrap shrink-0">
                {item.timestamp}
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
