import * as React from "react";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RepositoryItem } from "@/types";
import { FolderGit2, Lock, Globe } from "lucide-react";

interface RepositoryOverviewProps {
  repositories: RepositoryItem[];
}

export function RepositoryOverview({ repositories }: RepositoryOverviewProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {repositories.map((repo) => (
        <Card
          key={repo.id}
          className="border-slate-200/90 bg-white hover:border-slate-300 transition-colors flex flex-col justify-between"
        >
          <CardHeader className="p-4 pb-2">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2">
                <FolderGit2 className="h-4 w-4 text-blue-600 shrink-0" />
                <h4 className="font-semibold text-xs text-slate-900 truncate">
                  {repo.name}
                </h4>
              </div>
              {repo.visibility === "private" ? (
                <Lock className="h-3 w-3 text-slate-400 shrink-0" />
              ) : (
                <Globe className="h-3 w-3 text-slate-400 shrink-0" />
              )}
            </div>
            <p className="text-[11px] text-slate-400 font-mono mt-1">
              {repo.owner} &bull; {repo.defaultBranch}
            </p>
          </CardHeader>

          <CardContent className="p-4 pt-1 space-y-3">
            <div className="flex items-center justify-between text-[11px] text-slate-500 pt-2 border-t border-slate-100">
              <Badge variant="outline" className="text-[10px] py-0">
                {repo.status}
              </Badge>
              <span>{repo.agentCount} agents attached</span>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
