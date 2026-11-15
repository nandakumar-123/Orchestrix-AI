"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import {
  ArrowLeft,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Archive,
  ShieldCheck,
  Network,
  ExternalLink,
  Plus,
  Loader2,
} from "lucide-react";
import { fetchCurrentUser, type CurrentUser } from "@/lib/auth";
import {
  getMemory,
  listEvidence,
  listRelationships,
  verifyMemory,
  outdateMemory,
  archiveMemory,
  attachEvidence,
  type MemoryResponse,
  type MemoryEvidenceResponse,
  type MemoryRelationshipResponse,
  type MemoryVerificationStatus,
  type EvidenceType,
} from "@/lib/devmemory";

const STATUS_CONFIG: Record<
  MemoryVerificationStatus,
  { label: string; className: string; icon: React.ComponentType<{ className?: string }> }
> = {
  VERIFIED: {
    label: "Verified Fact",
    className: "bg-emerald-50 text-emerald-700 border-emerald-200",
    icon: CheckCircle2,
  },
  UNVERIFIED: {
    label: "Unverified Claim",
    className: "bg-amber-50 text-amber-700 border-amber-200",
    icon: AlertTriangle,
  },
  OUTDATED: {
    label: "Outdated Knowledge",
    className: "bg-orange-50 text-orange-700 border-orange-200",
    icon: Clock,
  },
  ARCHIVED: {
    label: "Archived Memory",
    className: "bg-slate-100 text-slate-600 border-slate-200",
    icon: Archive,
  },
};

function MemoryDetailContent() {
  const params = useParams<{ memoryId: string }>();
  const router = useRouter();
  const memoryId = params?.memoryId;

  const [user, setUser] = React.useState<CurrentUser | null>(null);
  const [memory, setMemory] = React.useState<MemoryResponse | null>(null);
  const [evidenceList, setEvidenceList] = React.useState<MemoryEvidenceResponse[]>([]);
  const [relationships, setRelationships] = React.useState<MemoryRelationshipResponse[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [actionLoading, setActionLoading] = React.useState(false);

  // Evidence modal/input state
  const [isAddingEvidence, setIsAddingEvidence] = React.useState(false);
  const [evidenceType, setEvidenceType] = React.useState<EvidenceType>("CODE_REFERENCE");
  const [evidenceContent, setEvidenceContent] = React.useState("");
  const [sourceReference, setSourceReference] = React.useState("");

  const workspaceId = user?.workspaces?.[0]?.workspace_id ?? null;
  const userRole = user?.workspaces?.[0]?.role;
  const canVerify = userRole === "OWNER" || userRole === "ADMIN" || userRole === "MEMBER";
  const canArchive = userRole === "OWNER" || userRole === "ADMIN";

  const [refreshTrigger, setRefreshTrigger] = React.useState(0);

  React.useEffect(() => {
    let ignore = false;
    async function init() {
      const u = await fetchCurrentUser();
      if (!ignore) {
        setUser(u);
      }
    }
    init();
    return () => {
      ignore = true;
    };
  }, []);

  React.useEffect(() => {
    if (!workspaceId || !memoryId) return;
    const activeWorkspaceId = workspaceId;
    const activeMemoryId = memoryId;
    let ignore = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const [memData, evData, relData] = await Promise.all([
          getMemory(activeMemoryId, activeWorkspaceId),
          listEvidence(activeMemoryId, activeWorkspaceId),
          listRelationships(activeMemoryId, activeWorkspaceId),
        ]);
        if (!ignore) {
          setMemory(memData);
          setEvidenceList(evData);
          setRelationships(relData);
        }
      } catch (e) {
        if (!ignore) {
          setError(e instanceof Error ? e.message : "Failed to load memory details");
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
  }, [workspaceId, memoryId, refreshTrigger]);

  const loadMemoryData = React.useCallback(async () => {
    setRefreshTrigger((prev) => prev + 1);
  }, []);

  // Lifecycle handlers
  const handleVerify = async () => {
    if (!workspaceId || !memoryId) return;
    setActionLoading(true);
    try {
      await verifyMemory(memoryId, workspaceId, {
        reason: "Verified by engineer in DevMemory studio",
      });
      await loadMemoryData();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Verification failed");
    } finally {
      setActionLoading(false);
    }
  };

  const handleOutdate = async () => {
    if (!workspaceId || !memoryId) return;
    const reason = prompt("Reason for marking this memory as outdated:");
    if (reason === null) return;
    setActionLoading(true);
    try {
      await outdateMemory(memoryId, workspaceId, reason || undefined);
      await loadMemoryData();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Outdate transition failed");
    } finally {
      setActionLoading(false);
    }
  };

  const handleArchive = async () => {
    if (!workspaceId || !memoryId) return;
    if (!confirm("Are you sure you want to archive this memory? It will be excluded from standard active agent retrieval.")) return;
    setActionLoading(true);
    try {
      await archiveMemory(memoryId, workspaceId, "Archived by user");
      await loadMemoryData();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Archival failed");
    } finally {
      setActionLoading(false);
    }
  };

  const handleAttachEvidence = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!workspaceId || !memoryId || !evidenceContent.trim()) return;
    setActionLoading(true);
    try {
      await attachEvidence(memoryId, workspaceId, {
        evidence_type: evidenceType,
        evidence_content: evidenceContent.trim(),
        source_reference: sourceReference.trim() || undefined,
      });
      setEvidenceContent("");
      setSourceReference("");
      setIsAddingEvidence(false);
      await loadMemoryData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to attach evidence");
    } finally {
      setActionLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  if (error || !memory) {
    return (
      <div className="p-6 space-y-4">
        <Button variant="outline" size="sm" onClick={() => router.push("/memory")} className="h-8 text-xs">
          <ArrowLeft className="h-3.5 w-3.5 mr-1" /> Back to Catalog
        </Button>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-xs text-red-700">
          {error || "Memory record not found in this workspace."}
        </div>
      </div>
    );
  }

  const statusCfg = STATUS_CONFIG[memory.verification_status] ?? STATUS_CONFIG.UNVERIFIED;
  const StatusIcon = statusCfg.icon;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Button
          variant="outline"
          size="sm"
          onClick={() => router.push("/memory")}
          className="h-8 text-xs"
        >
          <ArrowLeft className="h-3.5 w-3.5 mr-1" />
          Back to Memory Catalog
        </Button>
        <div className="flex items-center gap-2">
          {canVerify && memory.verification_status === "UNVERIFIED" && (
            <Button
              size="sm"
              className="h-8 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
              onClick={handleVerify}
              disabled={actionLoading}
            >
              <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
              Verify Memory
            </Button>
          )}
          {canVerify && memory.verification_status !== "OUTDATED" && memory.verification_status !== "ARCHIVED" && (
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-xs text-orange-700 border-orange-200 hover:bg-orange-50"
              onClick={handleOutdate}
              disabled={actionLoading}
            >
              <Clock className="h-3.5 w-3.5 mr-1" />
              Mark Outdated
            </Button>
          )}
          {canArchive && memory.verification_status !== "ARCHIVED" && (
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-xs text-slate-600 hover:bg-slate-50"
              onClick={handleArchive}
              disabled={actionLoading}
            >
              <Archive className="h-3.5 w-3.5 mr-1" />
              Archive
            </Button>
          )}
        </div>
      </div>

      {/* Main Memory Details Card */}
      <Card className="border-slate-200 bg-white">
        <CardHeader className="p-6 pb-4">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <Badge
              variant="outline"
              className={`text-xs font-semibold px-2.5 py-0.5 flex items-center gap-1.5 ${statusCfg.className}`}
            >
              <StatusIcon className="h-3.5 w-3.5" />
              {statusCfg.label}
            </Badge>
            <span className="font-mono text-xs text-slate-600 bg-slate-50 border border-slate-200 px-2.5 py-0.5 rounded">
              {memory.memory_type}
            </span>
            <span className="text-xs font-mono text-slate-400 ml-auto">
              Confidence: {(memory.confidence_score * 100).toFixed(0)}%
            </span>
          </div>
          <CardTitle className="text-lg font-bold text-slate-900 leading-snug">
            {memory.title}
          </CardTitle>
          {memory.summary && (
            <p className="text-xs text-slate-500 mt-2 font-medium">
              {memory.summary}
            </p>
          )}
        </CardHeader>

        <CardContent className="p-6 pt-0 space-y-4">
          {/* Detailed Content */}
          <div className="bg-slate-50/70 border border-slate-200 rounded-lg p-4 font-mono text-xs text-slate-800 whitespace-pre-wrap leading-relaxed">
            {memory.content}
          </div>

          {/* Metadata Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-3 border-t border-slate-100 text-xs">
            <div>
              <p className="text-[10px] text-slate-400 font-medium uppercase">Source Type</p>
              <p className="text-slate-700 font-mono mt-0.5">{memory.source_type}</p>
            </div>
            <div>
              <p className="text-[10px] text-slate-400 font-medium uppercase">Repository</p>
              <p className="text-slate-700 font-mono mt-0.5 truncate">
                {memory.repository_id ? memory.repository_id.slice(0, 16) : "Global / Workspace Scope"}
              </p>
            </div>
            <div>
              <p className="text-[10px] text-slate-400 font-medium uppercase">Recorded At</p>
              <p className="text-slate-700 font-mono mt-0.5">
                {new Date(memory.created_at).toLocaleString()}
              </p>
            </div>
            <div>
              <p className="text-[10px] text-slate-400 font-medium uppercase">Content Hash</p>
              <p className="text-slate-700 font-mono mt-0.5 truncate" title={memory.content_hash}>
                {memory.content_hash.slice(0, 14)}…
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Evidence & Relationships Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Evidence Section */}
        <Card className="border-slate-200 bg-white">
          <CardHeader className="p-4 pb-3 flex flex-row items-center justify-between border-b border-slate-100">
            <CardTitle className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-emerald-600" />
              Supporting Evidence ({evidenceList.length})
            </CardTitle>
            {canVerify && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs text-blue-600"
                onClick={() => setIsAddingEvidence(!isAddingEvidence)}
              >
                <Plus className="h-3 w-3 mr-1" />
                Attach Evidence
              </Button>
            )}
          </CardHeader>
          <CardContent className="p-4 space-y-3">
            {isAddingEvidence && (
              <form onSubmit={handleAttachEvidence} className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-2 mb-3">
                <p className="text-xs font-semibold text-slate-700">Add Concrete Verification Evidence</p>
                <div>
                  <label className="text-[10px] font-medium text-slate-500 uppercase">Evidence Type</label>
                  <select
                    value={evidenceType}
                    onChange={(e) => setEvidenceType(e.target.value as EvidenceType)}
                    className="w-full text-xs h-7 px-2 border rounded bg-white text-slate-700"
                  >
                    <option value="CODE_REFERENCE">Code Reference</option>
                    <option value="GIT_COMMIT">Git Commit</option>
                    <option value="CODE_DIFF">Code Diff</option>
                    <option value="TEST_RESULT">Test Result</option>
                  </select>
                </div>
                <div>
                  <label className="text-[10px] font-medium text-slate-500 uppercase">Source Reference (URL, Commit SHA, or File Path)</label>
                  <input
                    type="text"
                    value={sourceReference}
                    onChange={(e) => setSourceReference(e.target.value)}
                    placeholder="e.g. app/services/auth.py:45 or commit hash"
                    className="w-full text-xs h-7 px-2 border rounded bg-white text-slate-700"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-medium text-slate-500 uppercase">Evidence Content or Proof</label>
                  <textarea
                    rows={3}
                    value={evidenceContent}
                    onChange={(e) => setEvidenceContent(e.target.value)}
                    placeholder="Describe or paste verifying code snippet or output..."
                    className="w-full text-xs p-2 border rounded bg-white font-mono text-slate-700"
                    required
                  />
                </div>
                <div className="flex gap-2 justify-end">
                  <Button type="button" variant="ghost" size="sm" onClick={() => setIsAddingEvidence(false)} className="h-7 text-xs">
                    Cancel
                  </Button>
                  <Button type="submit" size="sm" className="h-7 text-xs bg-blue-600 text-white" disabled={actionLoading}>
                    Submit Evidence
                  </Button>
                </div>
              </form>
            )}

            {evidenceList.length === 0 ? (
              <p className="text-xs text-slate-400 italic py-4 text-center">
                No verified evidence artifacts recorded for this memory.
              </p>
            ) : (
              evidenceList.map((ev) => (
                <div key={ev.id} className="p-3 bg-slate-50/70 border border-slate-200 rounded-lg space-y-1.5 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-semibold text-slate-700 text-[11px] bg-white px-2 py-0.5 rounded border border-slate-200">
                      {ev.evidence_type}
                    </span>
                    <span className="text-[10px] text-slate-400">
                      {new Date(ev.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  {ev.source_reference && (
                    <p className="font-mono text-[11px] text-blue-600 break-all">
                      Source: {ev.source_reference}
                    </p>
                  )}
                  <p className="font-mono text-slate-600 whitespace-pre-wrap bg-white p-2 rounded border border-slate-100 text-[11px]">
                    {ev.evidence_content}
                  </p>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {/* Semantic Relationships Section */}
        <Card className="border-slate-200 bg-white">
          <CardHeader className="p-4 pb-3 flex flex-row items-center justify-between border-b border-slate-100">
            <CardTitle className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              <Network className="h-4 w-4 text-indigo-600" />
              Connected Memories & Graph ({relationships.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4 space-y-3">
            {relationships.length === 0 ? (
              <p className="text-xs text-slate-400 italic py-4 text-center">
                No semantic relationships linked to this memory node.
              </p>
            ) : (
              relationships.map((rel) => {
                const isSource = rel.source_memory_id === memory.id;
                const targetId = isSource ? rel.target_memory_id : rel.source_memory_id;
                return (
                  <div key={rel.id} className="p-3 bg-slate-50/70 border border-slate-200 rounded-lg space-y-1 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-semibold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-100 text-[11px]">
                        {rel.relationship_type}
                      </span>
                      <span className="text-[10px] font-mono text-slate-400">
                        Confidence: {(rel.confidence_score * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="flex items-center justify-between pt-1">
                      <span className="text-[11px] font-mono text-slate-600 truncate max-w-xs">
                        Target Node: {targetId.slice(0, 16)}…
                      </span>
                      <Link
                        href={`/memory/${targetId}`}
                        className="text-blue-600 hover:underline font-semibold text-[11px] flex items-center gap-0.5"
                      >
                        Inspect <ExternalLink className="h-2.5 w-2.5" />
                      </Link>
                    </div>
                  </div>
                );
              })
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default function MemoryDetailPage() {
  return (
    <AppShell>
      <React.Suspense
        fallback={
          <div className="flex items-center justify-center h-64">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        }
      >
        <MemoryDetailContent />
      </React.Suspense>
    </AppShell>
  );
}
