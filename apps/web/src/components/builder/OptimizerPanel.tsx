"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, ErrorBox, Icon, Select, Spinner, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { fmtCost } from "@/lib/format";
import { useBuilder } from "@/store/builder";

const KIND_ICON: Record<string, string> = { parallelize: "Columns3", deterministic_logic: "Split", remove_low_value: "Scissors", repeated_context: "Layers",
  cheaper_model: "Coins", checkpoint: "Flag", enable_cache: "DatabaseZap" };

export default function OptimizerPanel({ workflowId, projectId, onClose, onApplied }: { workflowId: string; projectId: string; onClose: () => void; onApplied: () => void }) {
  const qc = useQueryClient();
  const [opt, setOpt] = useState<any | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [candidate, setCandidate] = useState<any | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [dataset, setDataset] = useState("");
  const saveState = useBuilder((s) => s.saveState);
  const datasets = useQuery({ queryKey: ["datasets", projectId], queryFn: () => api<any[]>(`/projects/${projectId}/evaluation-datasets`) });
  const live = useQuery({ queryKey: ["opt", opt?.id], enabled: !!opt && opt.status === "evaluating", queryFn: () => api<any>(`/optimizations/${opt.id}`), refetchInterval: 2500 });
  const o = live.data || opt;

  async function analyze() {
    setBusy("analyze"); setErr(null); setCandidate(null);
    try { const r = await api<any>(`/workflows/${workflowId}/optimize`, { method: "POST" }); setOpt(r); setSelected(r.recommendations.filter((x: any) => x.patchable).map((x: any) => x.id)); }
    catch (e) { setErr(e); } finally { setBusy(null); }
  }
  async function build() {
    setBusy("candidate"); setErr(null);
    try { setCandidate(await api(`/optimizations/${o.id}/candidate`, { body: { recommendation_ids: selected } })); }
    catch (e) { setErr(e); } finally { setBusy(null); }
  }
  async function evaluate() {
    setBusy("evaluate");
    try { setOpt(await api(`/optimizations/${o.id}/evaluate`, { body: { dataset_id: dataset } })); } catch (e) { setErr(e); } finally { setBusy(null); }
  }
  async function apply() {
    if (!confirm("Write the candidate into the draft as a new revision? Published versions are not changed.")) return;
    setBusy("apply");
    try { await api(`/optimizations/${o.id}/apply`, { method: "POST" }); toast("Applied to the draft. Publish when ready."); qc.invalidateQueries({ queryKey: ["workflow", workflowId] }); onApplied(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }
  const cur = o?.current_metrics, proj = o?.projected_metrics;
  const ev = o?.evaluations || {};
  return (
    <div className="flex h-full flex-col bg-paper">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold"><Icon name="Gauge" className="text-accent-500" />Optimizer</h3>
        <button onClick={onClose} aria-label="Close optimizer" className="text-ink-400 hover:text-ink-900"><Icon name="X" /></button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-4 text-sm">
        <p className="text-xs text-ink-500">Analyzes this workflow&apos;s structure and recent runs. Changes are proposed as a candidate you can evaluate side by side; applying writes a draft revision — never production.</p>
        {saveState !== "saved" && <p className="text-2xs text-warn">Unsaved edits are not included until autosave finishes.</p>}
        <ErrorBox error={err} />
        <Button variant="primary" icon="ScanSearch" loading={busy === "analyze"} onClick={analyze}>{o ? "Analyze again" : "Analyze workflow"}</Button>
        {o && (
          <>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {[["Cost / run", "cost_per_run", (v: any) => fmtCost(v)], ["Latency", "latency_s", (v: any) => `${v}s`], ["Model calls", "llm_calls", (v: any) => v],
                ["Quality", "quality", (v: any) => (typeof v === "number" ? `${Math.round(v * 100)}%` : v ?? "—")]].map(([l, key, f]: any) => (
                <div key={key} className="rounded-md border border-line p-2">
                  <div className="text-ink-400">{l}</div>
                  <div className="tabular-nums"><span className="font-medium">{cur?.[key] == null ? "—" : f(cur[key])}</span>
                    {proj && proj[key] != null && proj[key] !== cur?.[key] && <span className="ml-1 text-state-completed">→ {f(proj[key])}</span>}</div>
                </div>
              ))}
            </div>
            <p className="text-2xs text-ink-400">Based on {cur?.runs_analyzed || 0} completed runs. Projections are estimates; quality is only known after evaluation.</p>
            {!o.recommendations.length ? <p className="text-sm text-ink-500">No recommendations — the workflow looks efficient for its recent runs.</p> : (
              <ul className="space-y-2">
                {o.recommendations.map((r: any) => (
                  <li key={r.id} className="rounded-md border border-line p-3">
                    <label className="flex cursor-pointer items-start gap-2">
                      <input type="checkbox" className="mt-1" disabled={!r.patchable} checked={selected.includes(r.id)}
                        onChange={(e) => setSelected(e.target.checked ? [...selected, r.id] : selected.filter((x) => x !== r.id))} />
                      <span className="flex-1">
                        <span className="flex items-center gap-1.5 font-medium"><Icon name={KIND_ICON[r.kind] || "Sparkles"} size={14} className="text-accent-500" />{r.title}</span>
                        <span className="mt-1 block text-xs text-ink-500">{r.detail}</span>
                        <span className="mt-1.5 flex flex-wrap gap-1">
                          {Object.entries(r.impact || {}).map(([k2, v]: any) => <Badge key={k2} tone={typeof v === "number" && v < 0 ? "blue" : "neutral"}>{k2.replace(/_/g, " ")}: {typeof v === "number" ? (k2.includes("cost") ? fmtCost(v) : v) : v}</Badge>)}
                          {!r.patchable && <Badge tone="warn">manual change</Badge>}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
            {!!selected.length && <Button icon="GitBranchPlus" loading={busy === "candidate"} onClick={build}>Build candidate ({selected.length})</Button>}
          </>
        )}
        {candidate && (
          <div className="space-y-3 rounded-md border border-accent-100 bg-accent-50/40 p-3">
            <div className="text-xs font-semibold">Candidate changes</div>
            <ul className="space-y-0.5 text-xs">
              {candidate.diff.added.map((n: any) => <li key={"a" + n.key} className="text-state-completed">+ {n.name || n.key} ({n.type})</li>)}
              {candidate.diff.removed.map((n: any) => <li key={"r" + n.key} className="text-state-failed">− {n.name || n.key}</li>)}
              {candidate.diff.changed.map((n: any) => <li key={"c" + n.key}>~ {n.name || n.key}: {n.fields.map((f: any) => f.field).join(", ")}</li>)}
              {candidate.diff.edges_added + candidate.diff.edges_removed > 0 && <li className="text-ink-500">{candidate.diff.edges_added} connections added, {candidate.diff.edges_removed} removed</li>}
            </ul>
            {candidate.issues.filter((i: any) => i.severity === "error").length > 0 && <ErrorBox error={new Error("The candidate has validation errors; fix them after applying.")} />}
            <div className="flex gap-2">
              <Select className="h-8 flex-1 text-xs" value={dataset} onChange={(e) => setDataset(e.target.value)} aria-label="Evaluation dataset">
                <option value="">Evaluation dataset…</option>{datasets.data?.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.case_count})</option>)}</Select>
              <Button size="sm" disabled={!dataset} loading={busy === "evaluate"} onClick={evaluate}>Evaluate</Button>
            </div>
            {(ev.baseline || ev.candidate) && (
              <table className="w-full text-xs">
                <thead className="text-left text-ink-400"><tr><th /><th className="font-medium">Current</th><th className="font-medium">Candidate</th></tr></thead>
                <tbody>
                  {[["Pass rate", "pass_rate", (v: number) => `${Math.round(v * 100)}%`], ["Avg cost", "avg_cost_usd", (v: number) => fmtCost(v)], ["P95 latency", "p95_latency_s", (v: number) => `${v}s`],
                    ["Failure rate", "failure_rate", (v: number) => `${Math.round(v * 100)}%`]].map(([l, key, f]: any) => (
                    <tr key={key}><td className="py-0.5 text-ink-500">{l}</td>
                      <td className="tabular-nums">{ev.baseline?.status !== "completed" ? <Spinner /> : ev.baseline?.[key] == null ? "—" : f(ev.baseline[key])}</td>
                      <td className="tabular-nums">{ev.candidate?.status !== "completed" ? <Spinner /> : ev.candidate?.[key] == null ? "—" : f(ev.candidate[key])}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
            <Button variant="primary" size="sm" icon="Check" loading={busy === "apply"} onClick={apply}>Apply to draft</Button>
            <p className="text-2xs text-ink-400">Applying never publishes. Review and publish it yourself.</p>
          </div>
        )}
      </div>
    </div>
  );
}
