"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ModelPicker } from "@/components/common";
import { PageHeader } from "@/components/shell/AppShell";
import { Button, Dialog, Empty, ErrorBox, Field, Input, Select, Spinner, Textarea, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { ago } from "@/lib/format";
import { useWorkspace } from "@/lib/session";

const TOOLS = ["web_search", "http_request", "python", "calculator", "file_reader", "json_processor", "vector_search"];

export default function Agents() {
  const { workspace } = useWorkspace();
  const qc = useQueryClient();
  const agents = useQuery({ queryKey: ["agents", workspace?.id], enabled: !!workspace, queryFn: () => api<any[]>(`/workspaces/${workspace!.id}/agents`) });
  const templates = useQuery({ queryKey: ["agent-templates"], queryFn: () => api<any[]>("/agent-templates") });
  const [edit, setEdit] = useState<any | null>(null);
  const [err, setErr] = useState<unknown>(null);

  function fromTemplate(t: any) { setErr(null); setEdit({ name: t.name, description: t.description, template: t.id, config: { role: t.role, instructions: t.instructions, tools: t.tools, model: { provider: "", model: "" }, params: { temperature: 0.3 } } }); }
  async function save() {
    setErr(null);
    try {
      const body = { name: edit.name, description: edit.description, template: edit.template, config: edit.config };
      if (edit.id) { await api(`/agents/${edit.id}`, { method: "PUT", body }); setEdit(null); qc.invalidateQueries({ queryKey: ["agents", workspace?.id] }); toast("Agent saved"); }
      else { await api<any>(`/workspaces/${workspace!.id}/agents`, { body }); setEdit(null); qc.invalidateQueries({ queryKey: ["agents", workspace?.id] }); toast("Agent saved"); }
    } catch (e) { setErr(e); }
  }
  const c = edit?.config || {};
  const setC = (p: any) => setEdit({ ...edit, config: { ...edit.config, ...p } });
  return (
    <>
      <PageHeader title="Agents" description="Reusable agent configurations: role, instructions, model and tools. Drop one into any workflow from the builder's agent node." />
      <div className="space-y-8 px-8 py-6">
        <section>
          <h2 className="mb-3 text-sm font-semibold">Your agents</h2>
          {agents.isLoading ? <Spinner /> : !agents.data?.length ? <Empty icon="Bot" title="No saved agents" body="Start from a template below, or save an agent from the builder." /> : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {agents.data.map((a) => (
                <button key={a.id} onClick={() => { setErr(null); setEdit({ ...a }); }} className="block rounded-lg border border-line bg-paper p-4 text-left shadow-card hover:border-ink-300">
                  <div className="font-medium">{a.name}</div>
                  <p className="mt-2 line-clamp-2 text-sm text-ink-600">{a.config.role || a.description}</p>
                  <div className="mt-2 text-2xs text-ink-400">{a.config.model?.provider === "auto" ? "AUTO model" : a.config.model?.model || "No model"} · {(a.config.tools || []).length} tools · updated {ago(a.updated_at)}</div>
                </button>
              ))}
            </div>
          )}
        </section>
        <section>
          <h2 className="mb-3 text-sm font-semibold">Templates</h2>
          <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-5">
            {templates.data?.map((t) => (
              <button key={t.id} onClick={() => fromTemplate(t)} className="rounded-md border border-line bg-paper p-3 text-left hover:border-ink-300">
                <div className="text-sm font-medium">{t.name}</div><div className="mt-0.5 text-xs text-ink-400">{t.description}</div>
              </button>
            ))}
          </div>
        </section>
      </div>
      {edit && (
        <Dialog open onClose={() => setEdit(null)} title={edit.id ? `Edit ${edit.name}` : "New agent"} wide
          footer={<><Button variant="ghost" onClick={() => setEdit(null)}>Cancel</Button>{edit.id && <Button variant="ghost" onClick={async () => { await api(`/agents/${edit.id}`, { method: "DELETE" }); setEdit(null); qc.invalidateQueries({ queryKey: ["agents", workspace?.id] }); }}>Delete</Button>}<Button variant="primary" onClick={save} disabled={!edit.name}>{edit.id ? "Save" : "Create agent"}</Button></>}>
          <div className="space-y-4">
            <ErrorBox error={err} />
            <div className="grid grid-cols-2 gap-3"><Field label="Name"><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
              <Field label="Template"><Select value={edit.template} onChange={(e) => setEdit({ ...edit, template: e.target.value })}>{templates.data?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select></Field></div>
            <Field label="Role"><Input value={c.role || ""} onChange={(e) => setC({ role: e.target.value })} /></Field>
            <Field label="Instructions"><Textarea rows={5} value={c.instructions || ""} onChange={(e) => setC({ instructions: e.target.value })} /></Field>
            <Field label="Model"><ModelPicker value={c.model || { provider: "", model: "" }} onChange={(m) => setC({ model: m })} compact allowAuto /></Field>
            <Field label="Tools"><div className="grid grid-cols-3 gap-1.5">{TOOLS.map((t) => (
              <label key={t} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={(c.tools || []).includes(t)} onChange={(e) => setC({ tools: e.target.checked ? [...(c.tools || []), t] : c.tools.filter((x: string) => x !== t) })} />{t.replace("_", " ")}</label>))}</div></Field>
          </div>
        </Dialog>
      )}
    </>
  );
}
