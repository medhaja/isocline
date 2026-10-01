"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import PlanView from "@/components/builder/PlanView";
import { Badge, Button, Code, Icon, Input, Spinner, StatusBadge, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { ago } from "@/lib/format";

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold text-ink-800">{title}{count !== undefined && <span className="ml-1.5 font-normal text-ink-400">{count}</span>}</h3>
      {children}
    </section>
  );
}

export default function HarnessTab({ runId, active, nodeName }: { runId: string; active: boolean; nodeName: (id: string) => string }) {
  const router = useRouter();
  const q = useQuery({ queryKey: ["harness", runId], queryFn: () => api<any>(`/runs/${runId}/harness`), refetchInterval: active ? 3000 : false });
  const [openCand, setOpenCand] = useState<string | null>(null);
  if (q.isLoading || !q.data) return <Spinner />;
  const h = q.data;
  async function resume(cp: string) {
    try { const r = await api<{ run_id: string }>(`/runs/${runId}/resume`, { body: { checkpoint_id: cp } }); router.push(`/runs/${r.run_id}`); }
    catch (e) { toast(errorMessage(e), "error"); }
  }
  async function compensate() {
    if (!confirm("Run all available compensating actions for this run, newest first?")) return;
    try { const r = await api<any>(`/runs/${runId}/compensate`, { body: {} }); toast(`Compensation: ${r.succeeded} succeeded, ${r.failed} failed, ${r.skipped} skipped`); q.refetch(); }
    catch (e) { toast(errorMessage(e), "error"); }
  }
  return (
    <div className="space-y-6">
      {h.run_approval && <p className="rounded-md bg-state-waiting/10 p-2 text-xs text-state-waiting">Policy required approval before this run: {h.run_approval.reasons.join("; ")}</p>}
      {h.plan && <Section title="Execution plan (at start)"><PlanView plan={h.plan} compact /></Section>}
      {h.goal_plans.length > 0 && (
        <Section title="Goal plans" count={h.goal_plans.length}>
          <ol className="space-y-2">{h.goal_plans.map((p: any) => (
            <li key={p.id} className="rounded-md border border-line p-2.5 text-xs">
              <div className="flex items-center gap-2 font-medium">v{p.version}<Badge tone={p.method === "model" ? "blue" : "warn"}>{p.method === "model" ? "model planner" : "offline heuristic"}</Badge>
                <span className="font-normal text-ink-400">{ago(p.created_at)} · {p.graph.nodes.length} steps</span></div>
              <p className="mt-1 text-ink-600">{p.reason}</p>
              <p className="mt-1 text-ink-500">{p.graph.nodes.filter((n: any) => n.type === "agent").map((n: any) => n.name).join(" · ")}</p>
              {p.validation.map((v: any, i: number) => <p key={i} className="text-warn">Harness: {v.message}</p>)}
            </li>))}</ol>
        </Section>
      )}
      <Section title="Model routing" count={h.routing.length}>
        {!h.routing.length ? <p className="text-xs text-ink-400">No AUTO models in this run.</p> : h.routing.map((d: any) => (
          <div key={d.id} className="rounded-md border border-line p-2.5 text-xs">
            <div className="flex justify-between"><span className="font-medium">{nodeName(d.node_id)} → {d.selected_provider}/{d.selected_model}</span><span className="text-ink-400">{d.objective}</span></div>
            <ul className="mt-1 space-y-0.5 text-ink-600">{d.reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
            <button className="mt-1 text-accent-600" onClick={() => setOpenCand(openCand === d.id ? null : d.id)}>{openCand === d.id ? "Hide" : "Show"} {d.candidates.length} candidates</button>
            {openCand === d.id && (
              <table className="mt-1 w-full text-2xs"><tbody>{d.candidates.map((c: any, i: number) => (
                <tr key={i} className="border-t border-line"><td className="py-0.5">{c.provider}/{c.model}</td>
                  <td className="text-right tabular-nums">{c.score != null ? `score ${c.score}` : ""}</td>
                  <td className="pl-2 text-state-failed">{(c.rejected || []).join("; ")}</td></tr>))}</tbody></table>
            )}
          </div>
        ))}
      </Section>
      <Section title="Policy decisions" count={h.policy_decisions.length}>
        {!h.policy_decisions.length ? <p className="text-xs text-ink-400">No governed actions were evaluated.</p> : (
          <table className="w-full text-xs"><tbody>{h.policy_decisions.map((d: any) => (
            <tr key={d.id} className="border-b border-line last:border-0">
              <td className="py-1"><Badge tone={d.effect === "allow" ? "neutral" : d.effect === "deny" ? "warn" : "blue"}>{d.effect.replace("_", " ")}</Badge></td>
              <td className="py-1 font-mono">{d.subject}</td><td className="py-1 text-ink-500">{d.action}</td><td className="py-1 text-ink-500">{nodeName(d.node_id)}</td>
              <td className="py-1 text-ink-400">{d.reason}</td></tr>))}</tbody></table>
        )}
      </Section>
      <Section title="Checkpoints" count={h.checkpoints.length}>
        {!h.checkpoints.length ? <p className="text-xs text-ink-400">No checkpoints yet.</p> : (
          <ul className="space-y-1">{h.checkpoints.map((c: any) => (
            <li key={c.id} className="flex items-center justify-between rounded-md border border-line px-2.5 py-1.5 text-xs">
              <span><span className="font-medium">after {nodeName(c.node_id)}</span> <span className="text-ink-400">· {c.reason.replace(/_/g, " ")} · {c.nodes_complete} nodes complete · {ago(c.created_at)}</span></span>
              {!active && <Button size="sm" icon="RotateCcw" onClick={() => resume(c.id)}>Resume from here</Button>}
            </li>))}</ul>
        )}
        <p className="text-2xs text-ink-400">Resuming starts a new run that reuses every output completed at the checkpoint; this run is not changed.</p>
      </Section>
      {h.waits.length > 0 && (
        <Section title="Durable waits" count={h.waits.length}>
          {h.waits.map((w: any) => (
            <div key={w.id} className="rounded-md border border-line p-2.5 text-xs">
              <div className="flex items-center justify-between"><span className="font-medium">{nodeName(w.node_id)} · {w.kind}</span><StatusBadge status={w.status === "waiting" ? "waiting" : w.status === "resumed" ? "completed" : w.status === "timed_out" ? "failed" : w.status} /></div>
              <div className="mt-1 space-y-0.5 text-ink-500">
                {w.resume_at && <div>Resumes at {new Date(w.resume_at).toLocaleString()}</div>}
                {w.timeout_at && <div>Times out at {new Date(w.timeout_at).toLocaleString()} → {w.timeout_action}</div>}
                {w.event_name && <div>Event <code className="font-mono">{w.event_name}</code>{w.correlation_key ? ` · key ${w.correlation_key}` : ""}</div>}
                {w.child_run_id && <div>Sub-workflow run <Link className="text-accent-600" href={`/runs/${w.child_run_id}`}>{w.child_run_id.slice(0, 8)}</Link></div>}
                {w.callback_path && w.status === "waiting" && (
                  <div className="flex gap-1"><Input readOnly className="h-7 font-mono text-2xs" value={`${window.location.origin}${w.callback_path}`} />
                    <Button size="sm" icon="Copy" onClick={() => { navigator.clipboard.writeText(`${window.location.origin}${w.callback_path}`); toast("Callback URL copied"); }} /></div>)}
              </div>
            </div>
          ))}
          <p className="text-2xs text-ink-400">A waiting run holds no worker; it resumes from the database even after restarts.</p>
        </Section>
      )}
      {h.compensations.length > 0 && (
        <Section title="Compensation" count={h.compensations.length}>
          <ul className="space-y-1">{h.compensations.map((c: any) => (
            <li key={c.id} className="rounded-md border border-line p-2.5 text-xs">
              <div className="flex justify-between"><span className="font-medium">#{c.sequence} {c.node_key}</span><Badge tone={c.status === "succeeded" ? "blue" : c.status === "available" ? "neutral" : "warn"}>{c.status}</Badge></div>
              <div className="mt-1 font-mono text-2xs text-ink-500">undo: {c.compensation.arguments?.method} {c.compensation.arguments?.url}</div>
              {c.result?.reason && <div className="text-2xs text-warn">{c.result.reason}</div>}
            </li>))}</ul>
          {!active && h.compensations.some((c: any) => c.status === "available") && <Button size="sm" variant="danger" icon="Undo2" onClick={compensate}>Run compensation</Button>}
        </Section>
      )}
    </div>
  );
}

export function LineageTab({ runId, output }: { runId: string; output: any }) {
  const fields = output && typeof output === "object" && !Array.isArray(output) ? Object.keys(output) : [];
  const [field, setField] = useState<string>("");
  const q = useQuery({ queryKey: ["lineage", runId, field], queryFn: () => api<any>(`/runs/${runId}/lineage${field ? `?field=${encodeURIComponent(field)}` : ""}`) });
  if (!q.data) return <Spinner />;
  const d = q.data;
  const byId = Object.fromEntries(d.nodes.map((n: any) => [n.node_id, n]));
  return (
    <div className="space-y-4 text-sm">
      {fields.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs"><span className="text-ink-500">Trace an output field:</span>
          {fields.map((f) => <button key={f} onClick={() => setField(f === field ? "" : f)} className={`rounded-full border px-2 py-0.5 font-mono ${f === field ? "border-accent-500 bg-accent-50" : "border-line"}`}>{f}</button>)}</div>
      )}
      {d.field && (
        <div className="rounded-md border border-accent-100 bg-accent-50/40 p-3 text-xs">
          <div className="font-medium">{d.field.field}</div>
          <div>Produced by <strong>{d.field.produced_by || "unknown"}</strong> <Badge>{d.field.precision}</Badge></div>
          {d.field.mapping.map((m: any, i: number) => <div key={i} className="text-ink-600">via {m.via}{m.path ? ` (${m.path})` : ""}</div>)}
          {d.field.based_on.length > 0 && <div className="text-ink-600">Based on: {d.field.based_on.join(" ← ")}</div>}
        </div>
      )}
      <ol className="space-y-1.5">
        {d.nodes.map((n: any) => (
          <li key={n.node_id} className="rounded-md border border-line p-2.5 text-xs">
            <div className="flex justify-between"><span className="font-medium">{n.name}</span><span className="text-ink-400">{n.model || n.type}</span></div>
            {d.edges.filter((e: any) => e.target === n.node_id).length > 0 && <div className="text-ink-500">← {d.edges.filter((e: any) => e.target === n.node_id).map((e: any) => byId[e.source]?.name).join(", ")}</div>}
            {n.artifacts_produced.map((a: any) => <div key={a.id} className="text-ink-600">produced <Icon name="FileBox" size={11} className="inline" /> {a.name} <span className="text-ink-400">({a.type})</span></div>)}
            {n.sources.slice(0, 5).map((s: any, i: number) => <div key={i} className="truncate text-ink-500">source ({s.kind}): {s.url ? <a className="text-accent-600" href={s.url} target="_blank" rel="noopener noreferrer nofollow">{s.label}</a> : s.label}</div>)}
          </li>
        ))}
      </ol>
      <p className="text-2xs text-ink-400">{d.note}</p>
    </div>
  );
}
