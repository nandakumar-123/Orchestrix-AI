import * as React from "react";
import {
  Activity,
  AlertCircle,
  Bot,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Code2,
  Cpu,
  ExternalLink,
  FileCode,
  FlaskConical,
  FolderGit2,
  GitBranch,
  Layers,
  Network,
  Play,
  RotateCw,
  Search,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  Workflow,
  Zap,
} from "lucide-react";

interface DynamicIconProps {
  name: string;
  className?: string;
}

export function DynamicIcon({ name, className = "h-4 w-4" }: DynamicIconProps) {
  switch (name) {
    case "Bot":
      return <Bot className={className} />;
    case "Code2":
      return <Code2 className={className} />;
    case "Network":
      return <Network className={className} />;
    case "FlaskConical":
      return <FlaskConical className={className} />;
    case "ShieldCheck":
      return <ShieldCheck className={className} />;
    case "ShieldAlert":
      return <ShieldAlert className={className} />;
    case "Workflow":
      return <Workflow className={className} />;
    case "BrainCircuit":
      return <BrainCircuit className={className} />;
    case "GitBranch":
      return <GitBranch className={className} />;
    case "Cpu":
      return <Cpu className={className} />;
    case "Activity":
      return <Activity className={className} />;
    case "Terminal":
      return <Terminal className={className} />;
    case "Layers":
      return <Layers className={className} />;
    case "FolderGit2":
      return <FolderGit2 className={className} />;
    case "FileCode":
      return <FileCode className={className} />;
    case "Zap":
      return <Zap className={className} />;
    case "Clock":
      return <Clock className={className} />;
    case "CheckCircle2":
      return <CheckCircle2 className={className} />;
    case "AlertCircle":
      return <AlertCircle className={className} />;
    case "Play":
      return <Play className={className} />;
    case "RotateCw":
      return <RotateCw className={className} />;
    case "Search":
      return <Search className={className} />;
    case "ExternalLink":
      return <ExternalLink className={className} />;
    case "ChevronDown":
      return <ChevronDown className={className} />;
    case "ChevronRight":
      return <ChevronRight className={className} />;
    case "Settings":
      return <Settings className={className} />;
    default:
      return <Activity className={className} />;
  }
}

