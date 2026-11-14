import {
  Activity,
  Bot,
  CheckCircle2,
  Cpu,
  Layers,
  Terminal,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function Home() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Bot className="h-7 w-7 text-indigo-400" />
            <h1 className="text-xl font-bold tracking-tight">Orchestrix AI</h1>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="border-indigo-500/40 text-indigo-300">
              Platform Foundation v0.1.0
            </Badge>
            <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <main className="flex-1 max-w-6xl mx-auto px-6 py-12 flex flex-col gap-10">
        <section className="space-y-4 max-w-3xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <Activity className="h-3.5 w-3.5" />
            Autonomous Multi-Agent Software Engineering Platform
          </div>
          <h2 className="text-4xl font-extrabold tracking-tight sm:text-5xl text-white">
            Engineering systems driven by autonomous agents.
          </h2>
          <p className="text-slate-400 text-base sm:text-lg leading-relaxed">
            Orchestrix AI unifies requirement analysis, architecture design, code synthesis,
            automated testing, CI/CD orchestration, and self-healing engineering loops.
          </p>
        </section>

        {/* Status & Architecture Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card className="bg-slate-900/60 border-slate-800 text-slate-100">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Terminal className="h-4 w-4 text-emerald-400" />
                  Backend Engine
                </CardTitle>
                <Badge variant="success">Operational</Badge>
              </div>
              <CardDescription className="text-slate-400">
                FastAPI, Pydantic & uv package runtime
              </CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-slate-300 space-y-2">
              <div className="flex items-center justify-between text-xs font-mono bg-slate-950/60 p-2.5 rounded border border-slate-800/80">
                <span className="text-slate-400">Endpoint:</span>
                <span className="text-emerald-400">GET /api/v1/health</span>
              </div>
              <p className="text-xs text-slate-400">
                Python 3.11 environment with strict type checking, ruff linting, and pytest suite.
              </p>
            </CardContent>
          </Card>

          <Card className="bg-slate-900/60 border-slate-800 text-slate-100">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Layers className="h-4 w-4 text-indigo-400" />
                  Frontend Console
                </CardTitle>
                <Badge variant="outline" className="border-indigo-500/50 text-indigo-300">
                  Ready
                </Badge>
              </div>
              <CardDescription className="text-slate-400">
                Next.js App Router, TypeScript & Tailwind CSS
              </CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-slate-300 space-y-2">
              <div className="flex items-center justify-between text-xs font-mono bg-slate-950/60 p-2.5 rounded border border-slate-800/80">
                <span className="text-slate-400">Components:</span>
                <span className="text-indigo-400">shadcn/ui & Lucide</span>
              </div>
              <p className="text-xs text-slate-400">
                Modern modular component architecture with client & server rendering capability.
              </p>
            </CardContent>
          </Card>

          <Card className="bg-slate-900/60 border-slate-800 text-slate-100">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Cpu className="h-4 w-4 text-violet-400" />
                  Agent Systems
                </CardTitle>
                <Badge variant="secondary" className="bg-slate-800 text-slate-300">
                  Foundation
                </Badge>
              </div>
              <CardDescription className="text-slate-400">
                Extensible architecture foundation
              </CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-slate-300 space-y-2">
              <div className="flex items-center justify-between text-xs font-mono bg-slate-950/60 p-2.5 rounded border border-slate-800/80">
                <span className="text-slate-400">Branch:</span>
                <span className="text-violet-300">feature/project-foundation</span>
              </div>
              <p className="text-xs text-slate-400">
                Ready for AI agents, Neo4j knowledge graph, Redis queue, and GitHub App integration.
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Foundation Checklist */}
        <section className="bg-slate-900/40 border border-slate-800 rounded-xl p-6">
          <h3 className="text-base font-semibold mb-4 text-white">Foundation Verification Checklist</h3>
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm text-slate-300">
            <li className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400 flex-shrink-0" />
              <span>Independent Next.js + FastAPI monorepo organization</span>
            </li>
            <li className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400 flex-shrink-0" />
              <span>Strict dependency management via uv (pyproject.toml & uv.lock)</span>
            </li>
            <li className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400 flex-shrink-0" />
              <span>Zero secret leaks (.gitignore protects .env and .pem keys)</span>
            </li>
            <li className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400 flex-shrink-0" />
              <span>Full automated CI/CD workflows and local test suites</span>
            </li>
          </ul>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800 py-6 text-center text-xs text-slate-500">
        Orchestrix AI &bull; Autonomous Multi-Agent Engineering Platform &bull; Phase 1 Initialized
      </footer>
    </div>
  );
}
