"use client";

import * as React from "react";
import {
  Save,
  CheckCircle2,
  Play,
  Zap,
  Pause,
  AlertCircle,
  Loader2,
  ChevronDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { type WorkflowStatus } from "@/lib/flowforge-api";
import { cn } from "@/lib/utils";

interface WorkflowToolbarProps {
  name: string;
  status: WorkflowStatus;
  isDirty: boolean;
  isSaving: boolean;
  isValidating: boolean;
  isExecuting: boolean;
  validationError?: string | null;
  canEdit: boolean; // MEMBER or above
  canActivate: boolean; // MEMBER or above
  canExecute: boolean; // MEMBER or above
  onNameChange: (name: string) => void;
  onSaveDraft: () => void;
  onValidate: () => void;
  onPublish: () => void;
  onExecute: () => void;
  onActivate: () => void;
  onPause: () => void;
}

const STATUS_BADGES: Record<WorkflowStatus, { label: string; className: string }> = {
  DRAFT:    { label: "Draft",    className: "bg-slate-100 text-slate-700" },
  ACTIVE:   { label: "Active",   className: "bg-emerald-100 text-emerald-700" },
  PAUSED:   { label: "Paused",   className: "bg-amber-100 text-amber-700" },
  ARCHIVED: { label: "Archived", className: "bg-red-100 text-red-700" },
};

export function WorkflowToolbar({
  name,
  status,
  isDirty,
  isSaving,
  isValidating,
  isExecuting,
  validationError,
  canEdit,
  canActivate,
  canExecute,
  onNameChange,
  onSaveDraft,
  onValidate,
  onPublish,
  onExecute,
  onActivate,
  onPause,
}: WorkflowToolbarProps) {
  const [isPublishOpen, setIsPublishOpen] = React.useState(false);
  const badge = STATUS_BADGES[status] ?? STATUS_BADGES.DRAFT;

  return (
    <div className="flex items-center gap-2 px-4 h-12 border-b border-slate-200 bg-white shrink-0">
      {/* Name */}
      <Input
        value={name}
        onChange={(e) => onNameChange(e.target.value)}
        readOnly={!canEdit}
        className="h-7 text-sm font-semibold w-56 border-transparent hover:border-slate-200 focus:border-blue-300 bg-transparent"
        placeholder="Workflow name..."
      />

      {/* Status badge */}
      <Badge className={cn("text-[10px] font-mono", badge.className)}>
        {badge.label}
      </Badge>

      {/* Unsaved indicator */}
      {isDirty && (
        <span className="text-[10px] text-amber-600 font-mono flex items-center gap-1">
          <AlertCircle className="h-3 w-3" /> unsaved
        </span>
      )}

      <div className="flex-1" />

      {/* Validation error summary */}
      {validationError && (
        <span className="text-[10px] text-red-600 font-mono max-w-xs truncate">
          {validationError}
        </span>
      )}

      {/* Actions */}
      {canEdit && (
        <>
          {/* Validate */}
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={onValidate}
            disabled={isValidating}
          >
            {isValidating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
            )}
            Validate
          </Button>

          {/* Save */}
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={onSaveDraft}
            disabled={isSaving || !isDirty}
          >
            {isSaving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
            ) : (
              <Save className="h-3.5 w-3.5 mr-1" />
            )}
            Save Draft
          </Button>

          {/* Publish dropdown */}
          <div className="relative">
            <div className="flex">
              <Button
                size="sm"
                className="h-7 text-xs rounded-r-none"
                onClick={onPublish}
                disabled={isSaving}
              >
                <Zap className="h-3.5 w-3.5 mr-1" />
                Publish Version
              </Button>
              <Button
                size="sm"
                variant="default"
                className="h-7 w-6 px-0 rounded-l-none border-l border-blue-500"
                onClick={() => setIsPublishOpen((o) => !o)}
              >
                <ChevronDown className="h-3 w-3" />
              </Button>
            </div>
            {isPublishOpen && (
              <div className="absolute right-0 top-9 bg-white border border-slate-200 rounded-lg shadow-lg z-20 w-40 py-1">
                {canActivate && status === "DRAFT" && (
                  <button
                    className="w-full text-left px-3 py-1.5 text-xs hover:bg-slate-50 text-slate-700"
                    onClick={() => { onActivate(); setIsPublishOpen(false); }}
                  >
                    Activate Workflow
                  </button>
                )}
                {status === "ACTIVE" && (
                  <button
                    className="w-full text-left px-3 py-1.5 text-xs hover:bg-slate-50 text-slate-700"
                    onClick={() => { onPause(); setIsPublishOpen(false); }}
                  >
                    <Pause className="h-3 w-3 inline mr-1" />
                    Pause Workflow
                  </button>
                )}
              </div>
            )}
          </div>
        </>
      )}

      {/* Execute */}
      {canExecute && (
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs text-emerald-700 border-emerald-200 hover:bg-emerald-50"
          onClick={onExecute}
          disabled={isExecuting || status === "ARCHIVED"}
        >
          {isExecuting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
          ) : (
            <Play className="h-3.5 w-3.5 mr-1" />
          )}
          Execute
        </Button>
      )}
    </div>
  );
}
