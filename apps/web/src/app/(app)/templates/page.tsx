"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import NewWorkflowDialog from "@/components/NewWorkflow";
import { PageHeader } from "@/components/shell/AppShell";
import { Badge, Input, Button, Dialog, Field, Select, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/session";
import type { Project } from "@/lib/types";

export default function Templates() {
  const { workspace } = useWorkspace();
  const t = useQuery({ queryKey: ["templates"], queryFn: () => api<any[]>("/templates") });
  const projects = useQuery({ queryKey: ["projects", workspace?.id], enabled: !!workspace, queryFn: () => api<Project[]>(`/workspaces/${workspace!.id}/projects`) });
  const [pick, setPick] = useState<string | null>(null);
  const [project, setProject] = useState("");
  const [go, setGo] = useState(false);
  const [cat, setCat] = useState("All");
  const [q, setQ] = useState("");
  const cats = ["All", ...Array.from(new Set((t.data || []).map((x) => x.category as string)))];
  const shown = (t.data || []).filter((x) => (cat === "All" || x.category === cat)
    && (!q || `${x.name} ${x.description} ${x.category}`.toLowerCase().includes(q.toLowerCase())));
  return (
    <>
      <PageHeader title="Templates" description={`${t.data?.length || ""} working multi-agent workflows for students, job seekers, recruiters, creators, managers, investors, founders and engineers. Pick a model when you create one; every part stays editable.`} />
      <div className="space-y-3 px-8 pt-6">
        <Input aria-label="Search templates" placeholder="Search templates (e.g. resume, YouTube, board update)" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-md" />
        <div className="flex flex-wrap gap-1.5">
          {cats.map((c) => (
            <button key={c} onClick={() => setCat(c)} className={`rounded-full border px-3 py-1 text-xs ${cat === c ? "border-accent-500 bg-accent-50 font-medium text-accent-700" : "border-line bg-paper text-ink-600 hover:border-ink-300"}`}>{c}</button>
          ))}
        </div>
      </div>
      <div className="grid gap-4 px-8 py-6 md:grid-cols-2 xl:grid-cols-3">
        {t.isLoading && <Spinner />}
        {!t.isLoading && !shown.length && <p className="text-sm text-ink-500">No templates match.</p>}
        {shown.map((x) => (
          <article key={x.id} className="flex flex-col rounded-lg border border-line bg-paper p-5">
            <div className="flex items-center gap-2"><h2 className="font-semibold">{x.name}</h2>{x.category === "Flagship" ? <Badge tone="blue">Flagship</Badge> : <Badge>{x.category}</Badge>}</div>
            <p className="mt-1 text-sm text-ink-600">{x.description}</p>
            <p className="mt-3 text-xs text-ink-400">{x.node_count} steps · {x.agents.length} agents: {x.agents.join(", ")}</p>
            <div className="mt-4 flex-1" />
            <Button variant="primary" onClick={() => { setPick(x.id); setProject(projects.data?.[0]?.id || ""); }}>Use template</Button>
          </article>
        ))}
      </div>
      <Dialog open={!!pick && !go} onClose={() => setPick(null)} title="Choose a project"
        footer={<><Button variant="ghost" onClick={() => setPick(null)}>Cancel</Button><Button variant="primary" disabled={!project} onClick={() => setGo(true)}>Continue</Button></>}>
        {projects.data?.length ? <Field label="Project"><Select value={project} onChange={(e) => setProject(e.target.value)}>{projects.data.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
          : <p className="text-sm text-ink-600">Create a project first under Projects.</p>}
      </Dialog>
      {go && pick && <NewWorkflowDialog open onClose={() => { setGo(false); setPick(null); }} projectId={project} initialMode="template" initialTemplate={pick} />}
    </>
  );
}
