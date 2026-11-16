import * as React from "react";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { RepositorySummary } from "@/lib/dashboard";
import { FolderGit2, Lock, Globe, Clock, CheckCircle2, AlertCircle, RefreshCw } from "lucide-react";
import Link from "next/link";

interface RepositoryOverviewProps {
  repositories: RepositorySummary[];
}

export function RepositoryOverview({ repositories }: RepositoryOverviewProps) {
  if (repositories.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 p-8 text-center bg-slate-50/50">
        <FolderGit2 className="mx-auto h-8 w-8 text-slate-400" />
        <h3 className="mt-2 text-sm font-semibold text-slate-900">No repositories connected</h3>
        <p className="mt-1 text-xs text-slate-500">
          Connect a GitHub repository to start indexing codebases and assigning AI agents.
        </p>
        <div className="mt-4">
          <Link
            href="/repositories"
            className="inline-flex items-center rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
          >
            Connect Repository
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {repositories.map((repo) => {
        const isIndexed = repo.indexing_status === "COMPLETED";
        const isIndexing = repo.indexing_status === "INDEXING" || repo.indexing_status === "RUNNING";
        const isFailed = repo.indexing_status === "FAILED";

        return (
          <Link key={repo.id} href={`/repositories?selected=${repo.id}`} className="block focus:outline-none">
            <Card className="h-full border-slate-200/90 bg-white hover:border-slate-300 hover:shadow-xs transition-all flex flex-col justify-between">
              <CardHeader className="p-4 pb-2">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2 min-w-0">
                    <FolderGit2 className="h-4 w-4 text-blue-600 shrink-0" />
                    <h4 className="font-semibold text-xs text-slate-900 truncate" title={repo.name}>
                      {repo.name}
                    </h4>
                  </div>
                  {repo.is_private ? (
                    <Lock className="h-3 w-3 text-slate-400 shrink-0 ml-1" />
                  ) : (
                    <Globe className="h-3 w-3 text-slate-400 shrink-0 ml-1" />
                  )}
                </div>
                <p className="text-[11px] text-slate-400 font-mono mt-1 truncate">
                  {repo.owner} &bull; {repo.default_branch}
                </p>
              </CardHeader>

              <CardContent className="p-4 pt-1 space-y-2">
                <div className="flex items-center justify-between text-[11px] text-slate-500 pt-2 border-t border-slate-100">
                  <div className="flex items-center gap-1.5">
                    {isIndexed && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />}
                    {isIndexing && <RefreshCw className="h-3.5 w-3.5 text-blue-600 animate-spin" />}
                    {isFailed && <AlertCircle className="h-3.5 w-3.5 text-rose-600" />}
                    {!isIndexed && !isIndexing && !isFailed && <Clock className="h-3.5 w-3.5 text-slate-400" />}
                    
                    <span className="font-medium text-slate-700">
                      {isIndexed ? "Indexed" : isIndexing ? "Indexing" : isFailed ? "Index Failed" : "Not Indexed"}
                    </span>
                  </div>

                  {repo.primary_language && (
                    <span className="font-mono text-[10px] text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded">
                      {repo.primary_language}
                    </span>
                  )}
                </div>

                {repo.last_indexed_at && (
                  <p className="text-[10px] text-slate-400">
                    Last indexed: {new Date(repo.last_indexed_at).toLocaleDateString()}
                  </p>
                )}
              </CardContent>
            </Card>
          </Link>
        );
      })}
    </div>
  );
}
