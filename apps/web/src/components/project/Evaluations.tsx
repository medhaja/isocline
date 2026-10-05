"use client";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ModelPicker } from "@/components/common";
import { Badge, Button, Dialog, Empty, ErrorBox, Field, Input, Select, Spinner, StatusBadge, Textarea, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { ago, fmtCost } from "@/lib/format";
import type { Workflow } from "@/lib/types";
import { routes } from "@/lib/routes";

interface Dataset { id: string; name: string; description: string; case_count: number }
interface Case { id?: string; name: string; input: any; expected: any; evaluators: any[] }

const EVAL_TYPES = [
  { type: "contains", label: "Contains" }, { type: "exact", label: "Exact match" }, { type: "json_schema", label: "JSON schema" },
  { type: "numeric", label: "Numeric tolerance" }, { type: "semantic", label: "Semantic similarity" },
  { type: "custom_python", label: "Custom Python" }, { type: "llm_judge", label: "LLM judge (model-based)" },
];

export function Evaluations({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const ds = useQuery({ queryKey: ["datasets", projectId], queryFn: () => api<Dataset[]>(`/projects/${projectId}/evaluation-datasets`) });
  const runs = useQuery({ queryKey: ["evals", projectId], queryFn: () => api<any[]>(`/projects/${projectId}/evaluations`),
    refetchInterval: (q) => (q.state.data?.some((e) => e.status === "running") ? 3000 : false) });
  const wfs = useQuery({ queryKey: ["workflows", projectId, false], queryFn: () => api<Workflow[]>(`/projects/${projectId}/workflows`) });
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [runFor, setRunFor] = useState<Dataset | null>(null);
  const [wfId, setWfId] = useState("");
  const [version, setVersion] = useState("");

  async function start() {
    try {
      await api(`/workflows/${wfId}/evaluate`, { body: { dataset_id: runFor!.id, version: version ? +version : null } });
      setRunFor(null); toast("Evaluation started"); qc.invalidateQueries({ queryKey: ["evals", projectId] });
    } catch (e) { toast(errorMessage(e), "error"); }
  }

  if (ds.isLoading) return <Spinner />;
  return (
    <div className="space-y-8">
      <section>
        <div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold">Test datasets</h2>
          <Button variant="primary" icon="Plus" onClick={() => setEditing("new")}>New dataset</Button></div>
        {!ds.data?.length ? <Empty icon="FlaskConical" title="No test datasets" body="A dataset is a list of inputs with expected results. Run it against a workflow version to measure quality before you publish." /> : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {ds.data.map((d) => (
              <div key={d.id} className="rounded-lg border border-line bg-paper p-4">
                <div className="font-medium">{d.name}</div><div className="text-xs text-ink-400">{d.case_count} test cases</div>
                <div className="mt-3 flex gap-2"><Button size="sm" onClick={() => setEditing(d.id)}>Edit cases</Button>
                  <Button size="sm" variant="primary" icon="Play" onClick={() => setRunFor(d)} disabled={!d.case_count}>Run evaluation</Button></div>
              </div>
            ))}
          </div>
        )}
      </section>
      <section>
        <h2 className="mb-3 text-sm font-semibold">Evaluation runs</h2>
        {!runs.data?.length ? <p className="text-sm text-ink-400">No evaluations yet.</p> : (
          <div className="overflow-hidden rounded-lg border border-line bg-paper">
            <table className="w-full text-sm">
              <thead className="border-b border-line text-left text-xs text-ink-400"><tr><th className="px-4 py-2 font-medium">Workflow</th><th className="px-4 py-2 font-medium">Dataset</th><th className="px-4 py-2 font-medium">Status</th><th className="px-4 py-2 font-medium">Pass rate</th><th className="px-4 py-2 font-medium">Cost (est.)</th><th className="px-4 py-2 font-medium">Started</th></tr></thead>
              <tbody>{runs.data.map((e) => (
                <tr key={e.id} className="border-b border-line last:border-0 hover:bg-canvas/60">
                  <td className="px-4 py-2"><Link className="font-medium hover:text-accent-600" href={routes.evaluation(e.id)}>{e.workflow_name}</Link></td>
                  <td className="px-4 py-2 text-ink-600">{e.dataset_name}</td><td className="px-4 py-2"><StatusBadge status={e.status} /></td>
                  <td className="px-4 py-2 tabular-nums">{e.summary?.pass_rate !== undefined ? `${Math.round(e.summary.pass_rate * 100)}% (${e.summary.passed}/${e.summary.cases})` : "—"}</td>
                  <td className="px-4 py-2 tabular-nums text-ink-600">{fmtCost(e.summary?.total_cost_usd)}</td>
                  <td className="px-4 py-2 text-ink-600">{ago(e.created_at)}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
      </section>
      {editing && <DatasetEditor projectId={projectId} id={editing === "new" ? null : editing} onClose={() => { setEditing(null); qc.invalidateQueries({ queryKey: ["datasets", projectId] }); }} />}
      <Dialog open={!!runFor} onClose={() => setRunFor(null)} title={`Evaluate with “${runFor?.name}”`}
        footer={<><Button variant="ghost" onClick={() => setRunFor(null)}>Cancel</Button><Button variant="primary" disabled={!wfId} onClick={start}>Start evaluation</Button></>}>
        <div className="space-y-4">
          <Field label="Workflow"><Select value={wfId} onChange={(e) => setWfId(e.target.value)}><option value="">Choose…</option>{wfs.data?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</Select></Field>
          <Field label="Version" hint="Empty = current draft. Compare versions by running the same dataset against each."><Input type="number" min={1} value={version} onChange={(e) => setVersion(e.target.value)} /></Field>
          <p className="text-xs text-ink-400">Each case runs the real workflow, so it uses model calls and incurs cost. Workflows that pause for approval will report those cases as errors.</p>
        </div>
      </Dialog>
    </div>
  );
}

function DatasetEditor({ projectId, id, onClose }: { projectId: string; id: string | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ["dataset", id], enabled: !!id, queryFn: () => api<Dataset & { cases: Case[] }>(`/evaluation-datasets/${id}`) });
  const [name, setName] = useState("");
  const [draft, setDraft] = useState<Case | null>(null);
  const [inputText, setInputText] = useState("{}");
  const [expectedText, setExpectedText] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const qc = useQueryClient();

  function edit(c: Case) { setDraft(c); setInputText(JSON.stringify(c.input, null, 2)); setExpectedText(c.expected === null || c.expected === undefined ? "" : typeof c.expected === "string" ? c.expected : JSON.stringify(c.expected, null, 2)); setErr(null); }
  async function saveDataset() {
    try { const d = await api<Dataset>(`/projects/${projectId}/evaluation-datasets`, { body: { name } }); qc.setQueryData(["dataset", d.id], { ...d, cases: [] }); onClose(); toast("Dataset created. Open it again to add cases."); }
    catch (e) { setErr(e); }
  }
  async function saveCase() {
    setErr(null);
    let input: any, expected: any = null;
    try { input = JSON.parse(inputText || "{}"); } catch { return setErr(new Error("Input must be valid JSON, e.g. {\"company\": \"Acme\"}")); }
    if (expectedText.trim()) { try { expected = JSON.parse(expectedText); } catch { expected = expectedText; } }
    const body = { name: draft!.name, input, expected, evaluators: draft!.evaluators };
    try {
      if (draft!.id) await api(`/evaluation-cases/${draft!.id}`, { method: "PUT", body });
      else await api(`/evaluation-datasets/${id}/cases`, { body });
      setDraft(null); qc.invalidateQueries({ queryKey: ["dataset", id] });
    } catch (e) { setErr(e); }
  }
  const setEv = (i: number, patch: any) => setDraft({ ...draft!, evaluators: draft!.evaluators.map((e, k) => (k === i ? { ...e, ...patch } : e)) });

  if (!id) {
    return (
      <Dialog open onClose={onClose} title="New dataset" footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!name} onClick={saveDataset}>Create</Button></>}>
        <ErrorBox error={err} /><Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Smoke tests" /></Field>
      </Dialog>
    );
  }
  return (
    <Dialog open onClose={onClose} title={q.data?.name || "Dataset"} wide footer={<Button onClick={onClose}>Done</Button>}>
      {draft ? (
        <div className="space-y-4">
          <ErrorBox error={err} />
          <Field label="Case name"><Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></Field>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Run input (JSON)"><Textarea mono rows={6} value={inputText} onChange={(e) => setInputText(e.target.value)} /></Field>
            <Field label="Expected result" hint="Text or JSON. Used by exact, numeric and semantic evaluators."><Textarea mono rows={6} value={expectedText} onChange={(e) => setExpectedText(e.target.value)} /></Field>
          </div>
          <div>
            <div className="mb-2 flex items-center justify-between"><span className="text-xs font-medium text-ink-700">Evaluators</span>
              <Select className="w-56" value="" onChange={(e) => e.target.value && setDraft({ ...draft, evaluators: [...draft.evaluators, { type: e.target.value }] })}>
                <option value="">Add evaluator…</option>{EVAL_TYPES.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}</Select></div>
            <div className="space-y-2">
              {draft.evaluators.map((ev, i) => (
                <div key={i} className="rounded-md border border-line p-3">
                  <div className="mb-2 flex items-center justify-between text-sm font-medium">{EVAL_TYPES.find((t) => t.type === ev.type)?.label}
                    {ev.type === "llm_judge" && <Badge tone="warn">model-based, not objective truth</Badge>}
                    <button className="text-xs text-state-failed" onClick={() => setDraft({ ...draft, evaluators: draft.evaluators.filter((_, k) => k !== i) })}>Remove</button></div>
                  <div className="grid gap-2 md:grid-cols-2">
                    <Input placeholder="Output path (optional), e.g. risk_score" value={ev.path || ""} onChange={(e) => setEv(i, { path: e.target.value })} />
                    {ev.type === "contains" && <Input placeholder="Required phrases, comma-separated" value={(ev.values || []).join(", ")} onChange={(e) => setEv(i, { values: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />}
                    {ev.type === "numeric" && <Input type="number" step="any" placeholder="Tolerance" value={ev.tolerance ?? ""} onChange={(e) => setEv(i, { tolerance: +e.target.value })} />}
                    {ev.type === "semantic" && <Input type="number" step="0.05" placeholder="Threshold (0–1)" value={ev.threshold ?? 0.8} onChange={(e) => setEv(i, { threshold: +e.target.value })} />}
                  </div>
                  {ev.type === "json_schema" && <Textarea mono className="mt-2" placeholder='{"company": "string", "risk_score": "number"}' defaultValue={ev.schema ? JSON.stringify(ev.schema) : ""} onBlur={(e) => { try { setEv(i, { schema: JSON.parse(e.target.value) }); } catch { toast("Schema must be JSON", "error"); } }} />}
                  {ev.type === "custom_python" && <Textarea mono rows={5} className="mt-2" value={ev.code || "def evaluate(output, expected):\n    return str(expected).lower() in str(output).lower()\n"} onChange={(e) => setEv(i, { code: e.target.value })} />}
                  {ev.type === "llm_judge" && <div className="mt-2 space-y-2"><Textarea placeholder="Criteria, e.g. The report cites sources and states risks" value={ev.criteria || ""} onChange={(e) => setEv(i, { criteria: e.target.value })} />
                    <ModelPicker compact value={ev.model || { provider: "", model: "" }} onChange={(m) => setEv(i, { model: m })} /></div>}
                </div>
              ))}
              {!draft.evaluators.length && <p className="text-xs text-ink-400">Without evaluators, a case with an expected result is checked by exact match.</p>}
            </div>
          </div>
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setDraft(null)}>Cancel</Button><Button variant="primary" onClick={saveCase}>Save case</Button></div>
        </div>
      ) : (
        <div className="space-y-2">
          {q.data?.cases.map((c) => (
            <div key={c.id} className="flex items-center justify-between rounded-md border border-line px-3 py-2 text-sm">
              <span><span className="font-medium">{c.name || "Untitled case"}</span> <span className="text-xs text-ink-400">{c.evaluators.map((e) => e.type).join(", ") || "exact"}</span></span>
              <span className="flex gap-3 text-xs"><button className="text-accent-600" onClick={() => edit(c)}>Edit</button>
                <button className="text-state-failed" onClick={async () => { await api(`/evaluation-cases/${c.id}`, { method: "DELETE" }); qc.invalidateQueries({ queryKey: ["dataset", id] }); }}>Delete</button></span>
            </div>
          ))}
          <Button icon="Plus" onClick={() => edit({ name: "", input: {}, expected: null, evaluators: [{ type: "contains", values: [] }] })}>Add test case</Button>
        </div>
      )}
    </Dialog>
  );
}
