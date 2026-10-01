"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ModelPicker } from "@/components/common";
import { Badge, Button, Dialog, Empty, ErrorBox, Field, Icon, Input, Select, Spinner, StatusBadge, Textarea, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { fmtCost } from "@/lib/format";
import type { ModelRef, Workflow } from "@/lib/types";

export function Experiments({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const wfs = useQuery({ queryKey: ["workflows", projectId, false], queryFn: () => api<Workflow[]>(`/projects/${projectId}/workflows`) });
  const [wf, setWf] = useState("");
  const wid = wf || wfs.data?.[0]?.id || "";
  const exps = useQuery({ queryKey: ["experiments", wid], enabled: !!wid, queryFn: () => api<any[]>(`/workflows/${wid}/experiments`),
    refetchInterval: (q) => (q.state.data?.some((e: any) => e.status === "running") ? 3000 : false) });
  const [open, setOpen] = useState(false);
  if (wfs.isLoading) return <Spinner />;
  if (!wfs.data?.length) return <Empty icon="FlaskConical" title="No workflows" body="Create a workflow first." />;
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Select className="w-72" value={wid} onChange={(e) => setWf(e.target.value)} aria-label="Workflow">{wfs.data.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</Select>
        <div className="flex-1" /><Button variant="primary" icon="Plus" onClick={() => setOpen(true)}>New experiment</Button>
      </div>
      {exps.isLoading ? <Spinner /> : !exps.data?.length ? (
        <Empty icon="FlaskConical" title="No experiments yet" body="Compare models, prompts or temperatures for a node on an evaluation dataset. Results show trade-offs — Isocline never labels one variant “best”." />
      ) : exps.data.map((e) => <ExperimentCard key={e.id} exp={e} onStarted={() => qc.invalidateQueries({ queryKey: ["experiments", wid] })} />)}
      {open && <NewExperiment projectId={projectId} workflow={wfs.data.find((w) => w.id === wid)!} onClose={() => { setOpen(false); qc.invalidateQueries({ queryKey: ["experiments", wid] }); }} />}
    </div>
  );
}

function ExperimentCard({ exp, onStarted }: { exp: any; onStarted: () => void }) {
  const [busy, setBusy] = useState(false);
  const pct = (x: any) => (x == null ? "—" : `${Math.round(x * 100)}%`);
  return (
    <section className="rounded-lg border border-line bg-paper shadow-card">
      <header className="flex items-center justify-between border-b border-line px-4 py-3">
        <div><div className="font-semibold">{exp.name}</div><div className="text-xs text-ink-500">{exp.variants.length} variants</div></div>
        <div className="flex items-center gap-2"><StatusBadge status={exp.status === "draft" ? "queued" : exp.status} />
          {exp.status === "draft" && <Button size="sm" variant="primary" icon="Play" loading={busy} onClick={async () => { setBusy(true); try { await api(`/experiments/${exp.id}/start`, { method: "POST" }); onStarted(); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); } }}>Run</Button>}</div>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-ink-500"><tr>
            <th className="px-4 py-2 font-medium">Variant</th><th className="px-3 py-2 font-medium">Quality</th><th className="px-3 py-2 font-medium">Avg cost</th>
            <th className="px-3 py-2 font-medium">P95 latency</th><th className="px-3 py-2 font-medium">Schema</th><th className="px-3 py-2 font-medium">Tool success</th>
            <th className="px-3 py-2 font-medium">Failures</th><th className="px-3 py-2 font-medium">Tokens</th><th /></tr></thead>
          <tbody>{exp.variants.map((v: any) => {
            const m = v.metrics || {};
            return (
              <tr key={v.id} className="border-t border-line">
                <td className="px-4 py-2"><span className="font-medium">{v.name}</span>{v.pareto && <Badge tone="blue" className="ml-2">Pareto-efficient</Badge>}</td>
                <td className="px-3 py-2 tabular-nums">{m.status && m.status !== "completed" ? <Spinner /> : pct(m.pass_rate)}</td>
                <td className="px-3 py-2 tabular-nums">{fmtCost(m.avg_cost_usd)}</td><td className="px-3 py-2 tabular-nums">{m.p95_latency_s != null ? `${m.p95_latency_s}s` : "—"}</td>
                <td className="px-3 py-2 tabular-nums">{pct(m.schema_compliance)}</td><td className="px-3 py-2 tabular-nums">{pct(m.tool_success)}</td>
                <td className="px-3 py-2 tabular-nums">{pct(m.failure_rate)}</td><td className="px-3 py-2 tabular-nums">{m.avg_tokens?.toLocaleString() ?? "—"}</td>
                <td className="px-3 py-2">{v.evaluation_run_id && <Link className="text-xs text-accent-600" href={`/evaluations/${v.evaluation_run_id}`}>cases</Link>}</td>
              </tr>);
          })}</tbody>
        </table>
      </div>
      <p className="px-4 py-2 text-2xs text-ink-400">{exp.note}{exp.variants.some((v: any) => v.metrics?.model_based_evaluators) ? " Quality includes model-based (LLM judge) scores." : ""}</p>
    </section>
  );
}

function NewExperiment({ projectId, workflow, onClose }: { projectId: string; workflow: Workflow; onClose: () => void }) {
  const wf = useQuery({ queryKey: ["workflow", workflow.id], queryFn: () => api<Workflow>(`/workflows/${workflow.id}`) });
  const ds = useQuery({ queryKey: ["datasets", projectId], queryFn: () => api<any[]>(`/projects/${projectId}/evaluation-datasets`) });
  const agents = (wf.data?.graph?.nodes || []).filter((n) => n.type === "agent");
  const [name, setName] = useState("Model comparison");
  const [node, setNode] = useState("");
  const [dataset, setDataset] = useState("");
  const [models, setModels] = useState<ModelRef[]>([{ provider: "", model: "" }, { provider: "", model: "" }]);
  const [prompts, setPrompts] = useState<string[]>([]);
  const [temps, setTemps] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const dims: any = {};
  if (models.some((m) => m.model)) dims.model = models.filter((m) => m.model);
  if (prompts.filter(Boolean).length) dims.prompt = prompts.filter(Boolean);
  if (temps.trim()) dims.params = temps.split(",").map((t) => ({ temperature: +t.trim() })).filter((p) => !isNaN(p.temperature));
  const count = Object.values(dims).reduce((n: number, v: any) => n * v.length, 1);
  async function create() {
    setErr(null);
    try { await api(`/workflows/${workflow.id}/experiments`, { body: { name, dataset_id: dataset, node_id: node || null, dimensions: dims } }); toast("Experiment created — press Run"); onClose(); }
    catch (e) { setErr(e); }
  }
  return (
    <Dialog open onClose={onClose} title="New experiment" wide
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" onClick={create} disabled={!dataset || !Object.keys(dims).length || count > 12}>Create {Object.keys(dims).length ? `${count} variants` : ""}</Button></>}>
      <div className="space-y-4">
        <ErrorBox error={err} />
        <div className="grid grid-cols-3 gap-3">
          <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Agent to vary"><Select value={node} onChange={(e) => setNode(e.target.value)}><option value="">All agents</option>{agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
          <Field label="Dataset"><Select value={dataset} onChange={(e) => setDataset(e.target.value)}><option value="">Choose…</option>{ds.data?.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.case_count})</option>)}</Select></Field>
        </div>
        <Field label="Models">
          <div className="space-y-2">{models.map((m, i) => (
            <div key={i} className="flex items-start gap-2"><div className="flex-1"><ModelPicker compact value={m} onChange={(v) => setModels(models.map((x, k) => (k === i ? v : x)))} /></div>
              <button aria-label="Remove model" className="pt-2 text-ink-400" onClick={() => setModels(models.filter((_, k) => k !== i))}><Icon name="X" size={14} /></button></div>))}
            <Button size="sm" variant="ghost" icon="Plus" onClick={() => setModels([...models, { provider: "", model: "" }])}>Model</Button></div>
        </Field>
        <Field label="Prompt variants (optional)">
          <div className="space-y-2">{prompts.map((p, i) => <Textarea key={i} rows={2} value={p} onChange={(e) => setPrompts(prompts.map((x, k) => (k === i ? e.target.value : x)))} />)}
            <Button size="sm" variant="ghost" icon="Plus" onClick={() => setPrompts([...prompts, ""])}>Prompt</Button></div>
        </Field>
        <Field label="Temperatures (optional, comma-separated)"><Input value={temps} onChange={(e) => setTemps(e.target.value)} placeholder="0, 0.7" /></Field>
        <p className="text-xs text-ink-500">{Object.keys(dims).length ? `${count} variants (every combination). Each runs the whole workflow on every case, so this costs ${count}× one evaluation.` : "Add at least one dimension."}{count > 12 && " At most 12 variants."}</p>
      </div>
    </Dialog>
  );
}
