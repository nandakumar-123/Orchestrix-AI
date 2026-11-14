import * as React from "react";
import { Card, CardContent } from "@/components/ui/card";
import { MetricItem } from "@/types";
import { DynamicIcon } from "@/components/shared/icons";
import { ArrowUpRight, ArrowDownRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface MetricCardsProps {
  metrics: MetricItem[];
}

export function MetricCards({ metrics }: MetricCardsProps) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {metrics.map((item) => (
        <Card
          key={item.id}
          className="border-slate-200/80 bg-white hover:border-slate-300 transition-colors"
        >
          <CardContent className="p-4 sm:p-5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-500">
                {item.label}
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                <DynamicIcon name={item.iconName} className="h-4 w-4" />
              </div>
            </div>

            <div className="mt-2.5 flex items-baseline justify-between">
              <span className="text-2xl font-bold tracking-tight text-slate-900">
                {item.value}
              </span>
              {item.change && (
                <span
                  className={cn(
                    "inline-flex items-center gap-0.5 text-[11px] font-medium",
                    item.trend === "up" && "text-emerald-600",
                    item.trend === "down" && "text-rose-600",
                    item.trend === "neutral" && "text-slate-500"
                  )}
                >
                  {item.trend === "up" && <ArrowUpRight className="h-3 w-3" />}
                  {item.trend === "down" && <ArrowDownRight className="h-3 w-3" />}
                  {item.change}
                </span>
              )}
            </div>

            {item.description && (
              <p className="mt-1 text-[11px] text-slate-400 truncate">
                {item.description}
              </p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

