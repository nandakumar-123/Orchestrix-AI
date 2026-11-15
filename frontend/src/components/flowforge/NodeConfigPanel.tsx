"use client";

import * as React from "react";
import { type WorkflowReactFlowNode } from "@/lib/flowforge-graph";
import { type WorkflowNodeType } from "@/lib/flowforge-api";
import { Input } from "@/components/ui/input";

interface NodeConfigPanelProps {
  node: WorkflowReactFlowNode | null;
  onUpdate: (nodeId: string, updates: Partial<WorkflowReactFlowNode["data"]>) => void;
  readOnly?: boolean;
}

// Generic config field renderer
function ConfigField({
  label,
  field,
  value,
  placeholder,
  onChange,
  readOnly,
}: {
  label: string;
  field: string;
  value: string;
  placeholder?: string;
  onChange: (field: string, value: string) => void;
  readOnly?: boolean;
}) {
  return (
    <div className="space-y-1">
      <label className="text-[11px] font-medium text-slate-600 block">{label}</label>
      <Input
        value={value}
        placeholder={placeholder}
        readOnly={readOnly}
        onChange={(e) => onChange(field, e.target.value)}
        className="h-7 text-xs font-mono"
      />
    </div>
  );
}

function NodeTypeConfig({
  nodeType,
  config,
  onChange,
  readOnly,
}: {
  nodeType: WorkflowNodeType;
  config: Record<string, unknown>;
  onChange: (field: string, value: string) => void;
  readOnly?: boolean;
}) {
  const str = (k: string) => String(config[k] ?? "");

  switch (nodeType) {
    case "TRIGGER":
      return (
        <>
          <ConfigField label="Trigger Type" field="trigger_type" value={str("trigger_type")} placeholder="WEBHOOK / SCHEDULE / EVENT / MANUAL" onChange={onChange} readOnly={readOnly} />
          <ConfigField label="Schedule (cron)" field="cron_expression" value={str("cron_expression")} placeholder="*/15 * * * *" onChange={onChange} readOnly={readOnly} />
          <ConfigField label="Event Filter" field="event_filter" value={str("event_filter")} placeholder="pull_request.opened" onChange={onChange} readOnly={readOnly} />
        </>
      );
    case "DEVPILOT":
      return (
        <>
          <ConfigField label="Task Title" field="task_title" value={str("task_title")} placeholder="Implement feature..." onChange={onChange} readOnly={readOnly} />
          <ConfigField label="Task Type" field="task_type" value={str("task_type")} placeholder="FEATURE / BUG_FIX / REFACTOR" onChange={onChange} readOnly={readOnly} />
          <ConfigField label="Repository Slug" field="repository_slug" value={str("repository_slug")} placeholder="owner/repo" onChange={onChange} readOnly={readOnly} />
        </>
      );
    case "IMPACTMIND":
      return (
        <>
          <ConfigField label="Analysis Mode" field="analysis_mode" value={str("analysis_mode")} placeholder="FULL / QUICK" onChange={onChange} readOnly={readOnly} />
          <ConfigField label="Target Branch" field="target_branch" value={str("target_branch")} placeholder="main" onChange={onChange} readOnly={readOnly} />
        </>
      );
    case "TESTPILOT":
      return (
        <>
          <ConfigField label="Test Framework" field="framework" value={str("framework")} placeholder="pytest / jest / vitest" onChange={onChange} readOnly={readOnly} />
          <ConfigField label="Test Type" field="test_type" value={str("test_type")} placeholder="unit / integration / e2e" onChange={onChange} readOnly={readOnly} />
          <ConfigField label="Target Files" field="target_files" value={str("target_files")} placeholder="app/core.py, src/utils.ts" onChange={onChange} readOnly={readOnly} />
        </>
      );
    case "SECUREFLOW":
      return (
        <>
          <ConfigField label="Scan Type" field="scan_type" value={str("scan_type")} placeholder="FULL / QUICK / SECRETS" onChange={onChange} readOnly={readOnly} />
          <ConfigField label="Risk Threshold" field="risk_threshold" value={str("risk_threshold")} placeholder="LOW / MEDIUM / HIGH / CRITICAL" onChange={onChange} readOnly={readOnly} />
        </>
      );
    case "CONDITION":
      return (
        <>
          <ConfigField label="Condition Expression" field="expression" value={str("expression")} placeholder="context.test_passed == true" onChange={onChange} readOnly={readOnly} />
        </>
      );
    case "APPROVAL":
      return (
        <>
          <ConfigField label="Approval Title" field="approval_title" value={str("approval_title")} placeholder="Deploy to production?" onChange={onChange} readOnly={readOnly} />
          <ConfigField label="Timeout (seconds)" field="timeout_seconds" value={str("timeout_seconds")} placeholder="3600" onChange={onChange} readOnly={readOnly} />
        </>
      );
    case "PARALLEL":
      return (
        <>
          <ConfigField label="Branch Count" field="branch_count" value={str("branch_count")} placeholder="2" onChange={onChange} readOnly={readOnly} />
        </>
      );
    case "NOTIFICATION":
      return (
        <>
          <ConfigField label="Channel" field="channel" value={str("channel")} placeholder="slack / email / webhook" onChange={onChange} readOnly={readOnly} />
          <ConfigField label="Message Template" field="message" value={str("message")} placeholder="Workflow {{status}}" onChange={onChange} readOnly={readOnly} />
          <ConfigField label="Webhook URL" field="webhook_url" value={str("webhook_url")} placeholder="https://hooks.slack.com/..." onChange={onChange} readOnly={readOnly} />
        </>
      );
    default:
      return (
        <p className="text-xs text-slate-400 italic">No configuration required.</p>
      );
  }
}

export function NodeConfigPanel({ node, onUpdate, readOnly }: NodeConfigPanelProps) {
  if (!node) {
    return (
      <div className="flex flex-col h-full bg-white border-l border-slate-200 items-center justify-center p-4">
        <p className="text-xs text-slate-400 text-center">
          Select a node on the canvas to configure it.
        </p>
      </div>
    );
  }

  const handleLabelChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onUpdate(node.id, { label: e.target.value });
  };

  const handleConfigChange = (field: string, value: string) => {
    onUpdate(node.id, {
      config: { ...node.data.config, [field]: value },
    });
  };

  const handleRetryChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = parseInt(e.target.value, 10);
    if (!isNaN(v)) onUpdate(node.id, { retryLimit: v });
  };

  const handleTimeoutChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = parseInt(e.target.value, 10);
    if (!isNaN(v)) onUpdate(node.id, { timeoutSeconds: v });
  };

  return (
    <div className="flex flex-col h-full bg-white border-l border-slate-200 overflow-y-auto">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-slate-100 shrink-0">
        <p className="text-xs font-semibold text-slate-700">Node Configuration</p>
        <p className="text-[10px] text-slate-400 font-mono uppercase tracking-wider mt-0.5">
          {node.data.nodeType}
        </p>
      </div>

      <div className="flex-1 p-3 space-y-4 overflow-y-auto">
        {/* Label */}
        <div className="space-y-1">
          <label className="text-[11px] font-medium text-slate-600 block">Node Label</label>
          <Input
            value={node.data.label}
            readOnly={readOnly}
            onChange={handleLabelChange}
            className="h-7 text-xs"
            placeholder="Node name..."
          />
        </div>

        {/* Type-specific config */}
        <div className="space-y-3 border-t border-slate-100 pt-3">
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
            Configuration
          </p>
          <NodeTypeConfig
            nodeType={node.data.nodeType}
            config={node.data.config}
            onChange={handleConfigChange}
            readOnly={readOnly}
          />
        </div>

        {/* Execution settings */}
        <div className="space-y-3 border-t border-slate-100 pt-3">
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
            Execution Settings
          </p>
          <div className="space-y-1">
            <label className="text-[11px] font-medium text-slate-600 block">Retry Limit</label>
            <Input
              type="number"
              min={0}
              max={5}
              value={node.data.retryLimit ?? 0}
              readOnly={readOnly}
              onChange={handleRetryChange}
              className="h-7 text-xs"
            />
          </div>
          <div className="space-y-1">
            <label className="text-[11px] font-medium text-slate-600 block">Timeout (seconds)</label>
            <Input
              type="number"
              min={1}
              max={86400}
              value={node.data.timeoutSeconds ?? 300}
              readOnly={readOnly}
              onChange={handleTimeoutChange}
              className="h-7 text-xs"
            />
          </div>
        </div>

        {/* Execution status (read-only overlay info) */}
        {node.data.stepStatus && (
          <div className="border-t border-slate-100 pt-3">
            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
              Execution Status
            </p>
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-slate-100 text-slate-700">
                {node.data.stepStatus}
              </span>
            </div>
            {node.data.errorMessage && (
              <p className="mt-1 text-[10px] text-red-600 font-mono break-all">
                {node.data.errorMessage}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
