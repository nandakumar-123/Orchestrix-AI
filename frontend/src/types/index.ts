export interface MetricItem {
  id: string;
  label: string;
  value: string | number;
  change?: string;
  trend?: "up" | "down" | "neutral";
  iconName: string;
  description?: string;
}

export type AgentStatus = "operational" | "busy" | "idle" | "error";

export interface AgentInfo {
  id: string;
  name: string;
  role: string;
  purpose: string;
  status: AgentStatus;
  currentTask?: string;
  completedTasks: number;
  lastActive: string;
  iconName: string;
  capabilities: string[];
}

export interface ActivityEvent {
  id: string;
  eventName: string;
  repository: string;
  agent: string;
  timestamp: string;
  status: "completed" | "in_progress" | "failed" | "queued";
  description?: string;
}

export interface TaskItem {
  id: string;
  title: string;
  repository: string;
  assignedAgent: string;
  status: "running" | "completed" | "pending" | "failed";
  updatedAt: string;
  priority: "low" | "medium" | "high" | "critical";
  branch?: string;
}

export interface RepositoryItem {
  id: string;
  name: string;
  owner: string;
  defaultBranch: string;
  lastIndexed: string;
  status: "synced" | "indexing" | "pending";
  agentCount: number;
  openIssues: number;
  visibility: "public" | "private";
}

export interface SecurityFinding {
  id: string;
  title: string;
  severity: "critical" | "high" | "medium" | "low";
  location: string;
  detectedAt: string;
  status: "open" | "resolved" | "in_review";
  agent: string;
}

export interface TestExecution {
  id: string;
  suite: string;
  passed: number;
  failed: number;
  skipped: number;
  duration: string;
  executedAt: string;
  status: "passed" | "failed" | "running";
}

export interface WorkflowItem {
  id: string;
  name: string;
  description: string;
  trigger: string;
  stepsCount: number;
  status: "active" | "draft" | "paused";
  lastRun: string;
}

export interface MemoryEntry {
  id: string;
  key: string;
  scope: "repository" | "architecture" | "decision" | "pattern";
  summary: string;
  updatedAt: string;
  relevanceScore: number;
}

