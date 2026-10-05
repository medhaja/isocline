"use client";
import clsx from "clsx";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ModelPicker, useProviders } from "@/components/common";
import { Badge, Button, Dialog, ErrorBox, Field, Icon, Input, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import type { ModelRef, Workflow } from "@/lib/types";
import { routes } from "@/lib/routes";

type Mode = "blank" | "template" | "ai" | "import";
interface Template { id: string; name: string; category: string; description: string; node_count: number; agents: string[] }

export function useDefaultModel(): ModelRef {
  const providers = useProviders();
  const hosted = providers.data?.find((p) => p.has_credential && !p.is_test);
  if (hosted) return { provider: hosted.id, model: "" };
  const test = providers.data?.find((p) => p.is_test);
  return { provider: test?.id || "", model: test ? "echo" : "" };
}

export default function NewWorkflowDialog({ open, onClose, projectId, initialMode = "blank", initialTemplate }: {
  open: boolean; onClose: () => void; projectId: string; initialMode?: Mode; initialTemplate?: string;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [name, setName] = useState("");
  const [template, setTemplate] = useState<string | undefined>(initialTemplate);
  const [description, setDescription] = useState("");
  const def = useDefaultModel();
  const [model, setModel] = useState<ModelRef>({ provider: "", model: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<any>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const templates = useQuery({ queryKey: ["templates"], queryFn: () => api<Template[]>("/templates"), enabled: open });

  useEffect(() => { if (open) { setMode(initialMode); setTemplate(initialTemplate); setError(null); setPreview(null); } }, [open, initialMode, initialTemplate]);
  useEffect(() => { if (!model.provider && def.provider) setModel(def); }, [def.provider]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create(body: any) {
    setBusy(true); setError(null);
    try {
      const wf = await api<Workflow>(`/projects/${projectId}/workflows`, { body });
      router.push(routes.workflow(wf.id));
    } catch (e) { setError(e); setBusy(false); }
  }

  async function generate() {
    setBusy(true); setError(null); setPreview(null);
    try { setPreview(await api(`/projects/${projectId}/generate-workflow`, { body: { description, model } })); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }

  async function importFile(f: File) {
    setBusy(true); setError(null);
    try {
      const doc = JSON.parse(await f.text());
      const wf = await api<Workflow & { issues: any[] }>(`/projects/${projectId}/workflows/import`, { body: { document: doc } });
      router.push(routes.workflow(wf.id));
    } catch (e) { setError(e instanceof SyntaxError ? new Error("That file isn't valid JSON") : e); setBusy(false); }
  }

  const tpl = templates.data?.find((t) => t.id === template);
  const modes: { id: Mode; label: string; icon: string }[] = [
    { id: "blank", label: "Blank canvas", icon: "Square" }, { id: "template", label: "From a template", icon: "Blocks" },
    { id: "ai", label: "Describe it", icon: "Sparkles" }, { id: "import", label: "Import JSON", icon: "FileUp" },
  ];
  const errs = preview?.issues?.filter((i: any) => i.severity === "error") || [];

  return (
    <Dialog open={open} onClose={onClose} title="New workflow" wide
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        {mode === "blank" && <Button variant="primary" loading={busy} disabled={!name.trim()} onClick={() => create({ name })}>Create workflow</Button>}
        {mode === "template" && <Button variant="primary" loading={busy} disabled={!tpl || !model.model} onClick={() => create({ name: name || tpl!.name, template_id: template, model })}>Use template</Button>}
        {mode === "ai" && !preview && <Button variant="primary" icon="Sparkles" loading={busy} disabled={description.trim().length < 10 || !model.model} onClick={generate}>Generate</Button>}
        {mode === "ai" && preview && <>
          <Button onClick={() => setPreview(null)}>Edit description</Button>
          <Button variant="primary" loading={busy} onClick={() => create({ name: name || preview.name, description: preview.description, graph: preview.graph })}>Open in builder</Button>
        </>}
      </>}>
      <div className="mb-5 grid grid-cols-4 gap-2">
        {modes.map((m) => (
          <button key={m.id} onClick={() => { setMode(m.id); setError(null); }}
            className={clsx("flex flex-col items-start gap-2 rounded-md border px-3 py-2.5 text-left text-[13px] transition-colors",
              mode === m.id ? "border-accent-500 bg-accent-50 text-ink-900" : "border-line text-ink-600 hover:border-ink-300")}>
            <Icon name={m.icon} className={mode === m.id ? "text-accent-500" : ""} />{m.label}
          </button>
        ))}
      </div>
      <div className="space-y-4">
        <ErrorBox error={error} />
        {mode !== "import" && (
          <Field label="Name" htmlFor="wfname"><Input id="wfname" value={name} placeholder={mode === "template" ? tpl?.name : mode === "ai" ? preview?.name : "Company research"} onChange={(e) => setName(e.target.value)} /></Field>
        )}
        {mode === "template" && (
          <>
            <div className="grid grid-cols-2 gap-2">
              {templates.data?.map((t) => (
                <button key={t.id} onClick={() => setTemplate(t.id)}
                  className={clsx("rounded-md border p-3 text-left", template === t.id ? "border-accent-500 bg-accent-50" : "border-line hover:border-ink-300")}>
                  <div className="flex items-center gap-2 text-sm font-medium text-ink-900">{t.name}{t.category === "Flagship" && <Badge tone="blue">Flagship</Badge>}</div>
                  <p className="mt-1 text-xs leading-relaxed text-ink-400">{t.description}</p>
                </button>
              ))}
            </div>
            <Field label="Model for every agent" hint="You can change the model per agent afterwards."><ModelPicker value={model} onChange={setModel} compact /></Field>
          </>
        )}
        {mode === "ai" && !preview && (
          <>
            <Field label="What should the agents do?" htmlFor="desc" hint="Mention the roles, what can run in parallel, and whether a person should approve anything.">
              <Textarea id="desc" rows={4} value={description} onChange={(e) => setDescription(e.target.value)}
                placeholder="Research a company, have a financial analyst and a risk analyst work in parallel, ask me to approve, then a manager writes the final report." />
            </Field>
            <Field label="Model that designs the workflow (also used for the agents)"><ModelPicker value={model} onChange={setModel} compact /></Field>
          </>
        )}
        {mode === "ai" && preview && (
          <div className="space-y-3">
            {preview.note && <Badge tone="warn">{preview.note}</Badge>}
            <div className="rounded-md border border-line p-3">
              <div className="mb-2 text-xs text-ink-400">{preview.graph.nodes.length} nodes · {preview.graph.edges.length} connections</div>
              <ol className="space-y-1 text-sm">
                {preview.graph.nodes.map((n: any) => <li key={n.id} className="flex gap-2"><span className="w-28 shrink-0 text-xs text-ink-400">{n.type.replace("_", " ")}</span><span className="text-ink-900">{n.name}</span></li>)}
              </ol>
            </div>
            {errs.length > 0 && <ErrorBox error={new Error("The draft has issues you can fix in the builder")} />}
            {errs.length > 0 && <ul className="list-disc pl-5 text-xs text-ink-600">{errs.map((i: any, k: number) => <li key={k}>{i.message}</li>)}</ul>}
          </div>
        )}
        {mode === "import" && (
          <div className="rounded-md border border-dashed border-line p-6 text-center">
            <p className="text-sm text-ink-600">Choose a <code className="font-mono text-xs">.workflow.json</code> file exported from Isocline.</p>
            <p className="mt-1 text-xs text-ink-400">It's validated and saved as a draft. Nothing runs until you start it. Credentials are never included in exports, so reconnect models afterwards.</p>
            <input ref={fileRef} type="file" accept="application/json,.json" className="hidden" onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
            <Button className="mt-4" icon="FileUp" loading={busy} onClick={() => fileRef.current?.click()}>Choose file</Button>
          </div>
        )}
      </div>
    </Dialog>
  );
}
