"use client";

import * as React from "react";
import {
  Handle,
  Position,
  type NodeProps,
  type Node,
} from "@xyflow/react";
import {
  Zap,
  Code2,
  Network,
  FlaskConical,
  Shield,
  GitFork,
  UserCheck,
  Split,
  GitMerge,
  Bell,
  StopCircle,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  MinusCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  type WorkflowNodeData,
  NODE_TYPE_LABELS,
} from "@/lib/flowforge-graph";
import { type WorkflowNodeType, type WorkflowStepStatus } from "@/lib/flowforge-api";

// Icon map
const NODE_ICONS: Record<WorkflowNodeType, React.ComponentType<{ className?: string }>> = {
  TRIGGER: Zap,
  DEVPILOT: Code2,
  IMPACTMIND: Network,
  TESTPILOT: FlaskConical,
  SECUREFLOW: Shield,
  CONDITION: GitFork,
  APPROVAL: UserCheck,
  PARALLEL: Split,
  MERGE: GitMerge,
  NOTIFICATION: Bell,
  END: StopCircle,
};

// Color schemes per node type
const NODE_COLORS: Record<
  WorkflowNodeType,
  { ring: string; icon: string; bg: string; border: string }
> = {
  TRIGGER:      { ring: "ring-amber-400",   icon: "text-amber-600",   bg: "bg-amber-50",   border: "border-amber-200" },
  DEVPILOT:     { ring: "ring-blue-400",    icon: "text-blue-600",    bg: "bg-blue-50",    border: "border-blue-200" },
  IMPACTMIND:   { ring: "ring-purple-400",  icon: "text-purple-600",  bg: "bg-purple-50",  border: "border-purple-200" },
  TESTPILOT:    { ring: "ring-emerald-400", icon: "text-emerald-600", bg: "bg-emerald-50", border: "border-emerald-200" },
  SECUREFLOW:   { ring: "ring-red-400",     icon: "text-red-600",     bg: "bg-red-50",     border: "border-red-200" },
  CONDITION:    { ring: "ring-orange-400",  icon: "text-orange-600",  bg: "bg-orange-50",  border: "border-orange-200" },
  APPROVAL:     { ring: "ring-indigo-400",  icon: "text-indigo-600",  bg: "bg-indigo-50",  border: "border-indigo-200" },
  PARALLEL:     { ring: "ring-cyan-400",    icon: "text-cyan-600",    bg: "bg-cyan-50",    border: "border-cyan-200" },
  MERGE:        { ring: "ring-teal-400",    icon: "text-teal-600",    bg: "bg-teal-50",    border: "border-teal-200" },
  NOTIFICATION: { ring: "ring-sky-400",     icon: "text-sky-600",     bg: "bg-sky-50",     border: "border-sky-200" },
  END:          { ring: "ring-slate-400",   icon: "text-slate-600",   bg: "bg-slate-50",   border: "border-slate-200" },
};

function StatusIcon({ status }: { status: WorkflowStepStatus }) {
  switch (status) {
    case "COMPLETED":
      return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />;
    case "FAILED":
      return <XCircle className="h-3.5 w-3.5 text-red-500" />;
    case "RUNNING":
      return <Loader2 className="h-3.5 w-3.5 text-blue-500 animate-spin" />;
    case "CANCELLED":
    case "SKIPPED":
      return <MinusCircle className="h-3.5 w-3.5 text-slate-400" />;
    case "TIMED_OUT":
      return <Clock className="h-3.5 w-3.5 text-orange-500" />;
    default:
      return null;
  }
}

function statusBorderClass(status?: WorkflowStepStatus): string {
  if (!status) return "";
  switch (status) {
    case "COMPLETED": return "ring-2 ring-emerald-400";
    case "FAILED":    return "ring-2 ring-red-400";
    case "RUNNING":   return "ring-2 ring-blue-400 animate-pulse";
    case "TIMED_OUT": return "ring-2 ring-orange-400";
    default:          return "";
  }
}

export function WorkflowCustomNode({ data, selected }: NodeProps<Node<WorkflowNodeData>>) {
  const nodeType = data.nodeType;
  const colors = NODE_COLORS[nodeType] ?? NODE_COLORS.END;
  const Icon = NODE_ICONS[nodeType] ?? StopCircle;
  const isEnd = nodeType === "END";
  const isTrigger = nodeType === "TRIGGER";

  return (
    <div
      className={cn(
        "relative min-w-[140px] max-w-[200px] rounded-xl border-2 shadow-sm transition-all",
        colors.bg,
        colors.border,
        selected ? `${colors.ring} ring-2` : "",
        statusBorderClass(data.stepStatus)
      )}
    >
      {/* Input handle (top) */}
      {!isTrigger && (
        <Handle
          type="target"
          position={Position.Top}
          className="!w-3 !h-3 !bg-slate-400 !border-white !border-2"
        />
      )}

      {/* Node body */}
      <div className="px-3 py-2.5 flex items-center gap-2">
        <div
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
            colors.bg,
            "border",
            colors.border
          )}
        >
          <Icon className={cn("h-3.5 w-3.5", colors.icon)} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold text-slate-800 truncate leading-tight">
            {data.label}
          </p>
          <p className="text-[9px] text-slate-400 font-mono uppercase tracking-wider">
            {NODE_TYPE_LABELS[nodeType]}
          </p>
        </div>
        {data.stepStatus && (
          <StatusIcon status={data.stepStatus} />
        )}
      </div>

      {/* Condition branch handles */}
      {nodeType === "CONDITION" && (
        <>
          <Handle
            type="source"
            position={Position.Bottom}
            id="true"
            style={{ left: "30%" }}
            className="!w-3 !h-3 !bg-emerald-400 !border-white !border-2"
          />
          <Handle
            type="source"
            position={Position.Bottom}
            id="false"
            style={{ left: "70%" }}
            className="!w-3 !h-3 !bg-red-400 !border-white !border-2"
          />
          <div className="flex justify-between px-2 pb-1">
            <span className="text-[9px] text-emerald-600 font-mono">true</span>
            <span className="text-[9px] text-red-500 font-mono">false</span>
          </div>
        </>
      )}

      {/* Default output handle */}
      {nodeType !== "CONDITION" && !isEnd && (
        <Handle
          type="source"
          position={Position.Bottom}
          className="!w-3 !h-3 !bg-slate-400 !border-white !border-2"
        />
      )}

      {/* Error tooltip */}
      {data.stepStatus === "FAILED" && data.errorMessage && (
        <div className="absolute -bottom-8 left-0 right-0 z-10 px-2 py-1 bg-red-50 border border-red-200 rounded-md text-[9px] text-red-700 truncate">
          {data.errorMessage}
        </div>
      )}
    </div>
  );
}
