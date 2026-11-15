"use client";

import * as React from "react";
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
  GripVertical,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { type WorkflowNodeType, NODE_TYPE_LABELS } from "@/lib/flowforge-graph";

interface NodePaletteItem {
  nodeType: WorkflowNodeType;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  description: string;
}

interface PaletteGroup {
  group: string;
  items: NodePaletteItem[];
}

const PALETTE_GROUPS: PaletteGroup[] = [
  {
    group: "Entry",
    items: [
      {
        nodeType: "TRIGGER",
        label: NODE_TYPE_LABELS.TRIGGER,
        icon: Zap,
        color: "text-amber-600 bg-amber-50 border-amber-200",
        description: "Webhook, schedule, or event trigger",
      },
    ],
  },
  {
    group: "AI Agents",
    items: [
      {
        nodeType: "DEVPILOT",
        label: NODE_TYPE_LABELS.DEVPILOT,
        icon: Code2,
        color: "text-blue-600 bg-blue-50 border-blue-200",
        description: "AI code engineering task",
      },
      {
        nodeType: "IMPACTMIND",
        label: NODE_TYPE_LABELS.IMPACTMIND,
        icon: Network,
        color: "text-purple-600 bg-purple-50 border-purple-200",
        description: "Change impact analysis",
      },
      {
        nodeType: "TESTPILOT",
        label: NODE_TYPE_LABELS.TESTPILOT,
        icon: FlaskConical,
        color: "text-emerald-600 bg-emerald-50 border-emerald-200",
        description: "Autonomous test generation",
      },
      {
        nodeType: "SECUREFLOW",
        label: NODE_TYPE_LABELS.SECUREFLOW,
        icon: Shield,
        color: "text-red-600 bg-red-50 border-red-200",
        description: "Security vulnerability scan",
      },
    ],
  },
  {
    group: "Logic",
    items: [
      {
        nodeType: "CONDITION",
        label: NODE_TYPE_LABELS.CONDITION,
        icon: GitFork,
        color: "text-orange-600 bg-orange-50 border-orange-200",
        description: "Branch on a condition expression",
      },
      {
        nodeType: "PARALLEL",
        label: NODE_TYPE_LABELS.PARALLEL,
        icon: Split,
        color: "text-cyan-600 bg-cyan-50 border-cyan-200",
        description: "Fan out to parallel branches",
      },
      {
        nodeType: "MERGE",
        label: NODE_TYPE_LABELS.MERGE,
        icon: GitMerge,
        color: "text-teal-600 bg-teal-50 border-teal-200",
        description: "Merge parallel branches",
      },
    ],
  },
  {
    group: "Control",
    items: [
      {
        nodeType: "APPROVAL",
        label: NODE_TYPE_LABELS.APPROVAL,
        icon: UserCheck,
        color: "text-indigo-600 bg-indigo-50 border-indigo-200",
        description: "Human approval gate (ADMIN/OWNER)",
      },
      {
        nodeType: "NOTIFICATION",
        label: NODE_TYPE_LABELS.NOTIFICATION,
        icon: Bell,
        color: "text-sky-600 bg-sky-50 border-sky-200",
        description: "Send notification or webhook",
      },
      {
        nodeType: "END",
        label: NODE_TYPE_LABELS.END,
        icon: StopCircle,
        color: "text-slate-600 bg-slate-50 border-slate-200",
        description: "Terminal node",
      },
    ],
  },
];

interface NodePaletteProps {
  onDragStart?: (nodeType: WorkflowNodeType, event: React.DragEvent) => void;
  disabled?: boolean;
}

export function NodePalette({ onDragStart, disabled }: NodePaletteProps) {
  const handleDragStart = (
    nodeType: WorkflowNodeType,
    e: React.DragEvent
  ) => {
    e.dataTransfer.setData("application/flowforge-node-type", nodeType);
    e.dataTransfer.effectAllowed = "move";
    onDragStart?.(nodeType, e);
  };

  return (
    <div className="flex flex-col h-full bg-white border-r border-slate-200 overflow-y-auto">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-slate-100 shrink-0">
        <p className="text-xs font-semibold text-slate-700">Node Palette</p>
        <p className="text-[10px] text-slate-400 mt-0.5">Drag nodes onto the canvas</p>
      </div>

      {/* Groups */}
      <div className="flex-1 p-2 space-y-3 overflow-y-auto">
        {PALETTE_GROUPS.map((group) => (
          <div key={group.group}>
            <p className="px-1 text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">
              {group.group}
            </p>
            <div className="space-y-1">
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <div
                    key={item.nodeType}
                    draggable={!disabled}
                    onDragStart={(e) => handleDragStart(item.nodeType, e)}
                    title={item.description}
                    className={cn(
                      "flex items-center gap-2 px-2 py-1.5 rounded-md border text-xs font-medium transition-all select-none",
                      item.color,
                      disabled
                        ? "opacity-40 cursor-not-allowed"
                        : "cursor-grab hover:shadow-sm active:cursor-grabbing"
                    )}
                  >
                    <GripVertical className="h-3 w-3 text-current opacity-30 shrink-0" />
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">{item.label}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
