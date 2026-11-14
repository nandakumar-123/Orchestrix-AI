"use client";

import * as React from "react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/shared/page-header";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Save, Check } from "lucide-react";

export default function SettingsPage() {
  const [saved, setSaved] = React.useState(false);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <AppShell>
      <PageHeader
        title="Workspace & Agent Settings"
        subtitle="Manage platform parameters, LLM model providers, GitHub App bindings, and memory stores."
        actions={
          <Button size="sm" onClick={handleSave} className="text-xs h-8">
            {saved ? (
              <>
                <Check className="h-3.5 w-3.5 mr-1" />
                Saved
              </>
            ) : (
              <>
                <Save className="h-3.5 w-3.5 mr-1" />
                Save Changes
              </>
            )}
          </Button>
        }
      />

      <Tabs defaultValue="general">
        <TabsList>
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="models">AI Models & Keys</TabsTrigger>
          <TabsTrigger value="github">GitHub Integration</TabsTrigger>
          <TabsTrigger value="infrastructure">Database & Storage</TabsTrigger>
        </TabsList>

        <TabsContent value="general" className="space-y-4 pt-2">
          <Card className="border-slate-200 bg-white">
            <CardHeader>
              <CardTitle className="text-sm font-semibold">Workspace Configuration</CardTitle>
              <CardDescription>Primary organization and default environment properties.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 max-w-xl text-xs">
              <div className="space-y-1.5">
                <label className="font-medium text-slate-700">Workspace Name</label>
                <Input defaultValue="Orchestrix Core Workspace" className="h-8 text-xs" />
              </div>
              <div className="space-y-1.5">
                <label className="font-medium text-slate-700">Default Target Branch</label>
                <Input defaultValue="main" className="h-8 text-xs font-mono" />
              </div>
              <div className="space-y-1.5">
                <label className="font-medium text-slate-700">Autonomous Cycle Frequency</label>
                <Input defaultValue="Event-Driven (PR / Commit webhook)" className="h-8 text-xs" />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="models" className="space-y-4 pt-2">
          <Card className="border-slate-200 bg-white">
            <CardHeader>
              <CardTitle className="text-sm font-semibold">LLM Agent Routing</CardTitle>
              <CardDescription>Configure reasoning engines for code synthesis and AST review.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 max-w-xl text-xs">
              <div className="space-y-1.5">
                <label className="font-medium text-slate-700">Code Synthesis Model (DevPilot)</label>
                <Input defaultValue="gemini-2.5-pro" className="h-8 text-xs font-mono" />
              </div>
              <div className="space-y-1.5">
                <label className="font-medium text-slate-700">Impact & Verification Engine (ImpactMind)</label>
                <Input defaultValue="mistral-large-latest" className="h-8 text-xs font-mono" />
              </div>
              <div className="p-3 rounded-lg bg-blue-50/70 border border-blue-100 text-slate-600 text-[11px] leading-relaxed">
                Keys and credentials are securely read from system environment variables (<code className="font-mono text-blue-700">.env</code>) and are never exposed in client bundles.
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="github" className="space-y-4 pt-2">
          <Card className="border-slate-200 bg-white">
            <CardHeader>
              <CardTitle className="text-sm font-semibold">GitHub App Connection</CardTitle>
              <CardDescription>Autonomous read/write permissions for PRs, issues, and checks.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 max-w-xl text-xs">
              <div className="space-y-1.5">
                <label className="font-medium text-slate-700">GitHub App Slug</label>
                <Input defaultValue="orchestrix-ai" className="h-8 text-xs font-mono" disabled />
              </div>
              <div className="space-y-1.5">
                <label className="font-medium text-slate-700">Webhook Status</label>
                <div className="flex items-center gap-2">
                  <Badge variant="success">Active</Badge>
                  <span className="text-slate-400 font-mono text-[11px]">https://api.orchestrix.ai/api/v1/webhooks/github</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="infrastructure" className="space-y-4 pt-2">
          <Card className="border-slate-200 bg-white">
            <CardHeader>
              <CardTitle className="text-sm font-semibold">State & Graph Persistence</CardTitle>
              <CardDescription>Knowledge graph and task queue infrastructure.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 max-w-xl text-xs">
              <div className="space-y-1.5">
                <label className="font-medium text-slate-700">Neo4j Knowledge Graph Store</label>
                <Input defaultValue="bolt://localhost:7687 (Active)" className="h-8 text-xs font-mono" disabled />
              </div>
              <div className="space-y-1.5">
                <label className="font-medium text-slate-700">Redis Distributed Mesh Bus</label>
                <Input defaultValue="redis://localhost:6379/0 (Active)" className="h-8 text-xs font-mono" disabled />
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </AppShell>
  );
}
