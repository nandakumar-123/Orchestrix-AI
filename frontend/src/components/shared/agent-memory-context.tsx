"use client";

import * as React from "react";
import Link from "next/link";
import { BrainCircuit, CheckCircle2, AlertTriangle, ExternalLink, ChevronDown, ChevronUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  getMemoryContext,
  type MemoryContextResponse,
  type MemoryConsumerAgent,
} from "@/lib/devmemory";

interface AgentMemoryContextProps {
  agent: MemoryConsumerAgent;
  query: string;
  workspaceId: string | null;
  repositoryId?: string | null;
  title?: string;
  className?: string;
}

export function AgentMemoryContext({
  agent,
  query,
  workspaceId,
  repositoryId,
  title = "Institutional Knowledge (DevMemory)",
  className = "",
}: AgentMemoryContextProps) {
  const [context, setContext] = React.useState<MemoryContextResponse | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const [isExpanded, setIsExpanded] = React.useState(false);
  const [, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let ignore = false;
    async function load() {
      if (!workspaceId || !query) return;
      setIsLoading(true);
      setError(null);
      try {
        const res = await getMemoryContext(workspaceId, {
          agent,
          query,
          repository_id: repositoryId,
          include_unverified: true,
          limit: 3,
        });
        if (!ignore) {
          setContext(res);
        }
      } catch (e) {
        if (!ignore) {
          setError(e instanceof Error ? e.message : "Failed to load memory context");
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }
    load();
    return () => {
      ignore = true;
    };
  }, [agent, query, workspaceId, repositoryId]);

  if (!workspaceId || (!isLoading && (!context || context.memories_used === 0))) {
    return null;
  }

  return (
    <div className={`rounded-xl border border-indigo-100 bg-indigo-50/40 p-3 text-xs ${className}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BrainCircuit className="h-4 w-4 text-indigo-600 shrink-0" />
          <span className="font-semibold text-slate-800">{title}</span>
          {context && (
            <div className="flex items-center gap-1.5 ml-2">
              <Badge variant="outline" className="text-[10px] bg-white text-indigo-700 border-indigo-200">
                {context.memories_used} active context{context.memories_used !== 1 ? "s" : ""}
              </Badge>
              {context.verified_count > 0 && (
                <span className="text-[10px] text-emerald-700 font-mono flex items-center gap-0.5">
                  <CheckCircle2 className="h-3 w-3" /> {context.verified_count} verified
                </span>
              )}
              {context.unverified_count > 0 && (
                <span className="text-[10px] text-amber-700 font-mono flex items-center gap-0.5">
                  <AlertTriangle className="h-3 w-3" /> {context.unverified_count} unverified
                </span>
              )}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => setIsExpanded(!isExpanded)}
          className="text-indigo-600 hover:text-indigo-800 p-1"
          title={isExpanded ? "Collapse" : "Expand"}
        >
          {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
      </div>

      {isExpanded && context && (
        <div className="mt-2.5 pt-2 border-t border-indigo-100/70 space-y-2">
          <div className="bg-white/80 border border-indigo-100 rounded-md p-2.5 font-mono text-[11px] text-slate-700 whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
            {context.context_markdown}
          </div>
          {context.citations && context.citations.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 pt-1 text-[10px]">
              <span className="text-slate-400 font-medium">Memory Citations:</span>
              {context.citations.map((cid) => (
                <Link
                  key={cid}
                  href={`/memory/${cid}`}
                  className="font-mono text-blue-600 hover:underline inline-flex items-center gap-0.5 bg-white px-1.5 py-0.5 rounded border border-indigo-100"
                >
                  {cid.slice(0, 8)}… <ExternalLink className="h-2 w-2" />
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
