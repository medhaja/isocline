"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/shell/AppShell";
import { Button, Dialog, Empty, ErrorBox, Field, Input, Spinner, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { useWorkspace } from "@/lib/session";
import type { Project } from "@/lib/types";
import { routes } from "@/lib/routes";

export default function Projects() {
  const { workspace } = useWorkspace();
  const router = useRouter();
  const q = useQuery({ queryKey: ["projects", workspace?.id], enabled: !!workspace, queryFn: () => api<Project[]>(`/workspaces/${workspace!.id}/projects`) });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", description: "" });
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function create() {
    setBusy(true); setErr(null);
    try { const p = await api<Project>(`/workspaces/${workspace!.id}/projects`, { body: form }); router.push(routes.project(p.id)); }
    catch (e) { setErr(e); setBusy(false); }
  }
  return (
    <>
      <PageHeader title="Projects" description="Group related workflows with their runs, evaluations, knowledge bases and triggers."
        actions={<Button variant="primary" icon="Plus" onClick={() => setOpen(true)}>New project</Button>} />
      <div className="px-8 py-6">
        {q.isLoading ? <Spinner /> : !q.data?.length ? (
          <Empty icon="FolderKanban" title="Create your first project" body="A project is where your workflows live, e.g. “Equity research” or “Support triage”."
            action={<Button variant="primary" icon="Plus" onClick={() => setOpen(true)}>New project</Button>} />
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {q.data.map((p) => (
              <Link key={p.id} href={routes.project(p.id)} className="rounded-lg border border-line bg-paper p-4 hover:border-ink-300">
                <div className="font-medium text-ink-900">{p.name}</div>
                {p.description && <p className="mt-1 line-clamp-2 text-sm text-ink-400">{p.description}</p>}
                <div className="mt-3 flex gap-4 text-xs text-ink-400">
                  <span>{p.workflow_count} workflows</span><span>{p.run_count} runs</span><span>created {ago(p.created_at)}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
      <Dialog open={open} onClose={() => setOpen(false)} title="New project"
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" loading={busy} disabled={!form.name.trim()} onClick={create}>Create project</Button></>}>
        <div className="space-y-4">
          <ErrorBox error={err} />
          <Field label="Name" htmlFor="pn"><Input id="pn" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Description (optional)" htmlFor="pd"><Textarea id="pd" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        </div>
      </Dialog>
    </>
  );
}
