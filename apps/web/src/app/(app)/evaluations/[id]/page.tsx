"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { PageHeader } from "@/components/shell/AppShell";
import { Badge, Code, Spinner, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtCost, fmtMs, fmtTokens, toText } from "@/lib/format";

export default function EvaluationPage() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({ queryKey: ["evaluation", id], queryFn: () => api<any>(`/evaluations/${id}`), refetchInterval: (x) => (x.state.data?.status === "running" ? 2500 : false) });
  const [open, setOpen] = useState<string | null>(null);
  if (!q.data) return <div className="p-8"><Spinner /></div>;
  const e = q.data, s = e.summary || {};
  return (
    <>
      <PageHeader title={`Evaluation of ${e.workflow_name}`} description={e.workflow_version_id ? "Published version" : "Draft at the time of the evaluation"}
        actions={<StatusBadge status={e.status} />} />
      <div className="space-y-6 px-8 py-6">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Stat label="Pass rate" value={s.pass_rate !== undefined && e.status === "completed" ? `${Math.round(s.pass_rate * 100)}%` : "…"} sub={`${s.passed ?? 0} of ${s.cases} passed`} />
          <Stat label="Failed" value={s.failed ?? "…"} /><Stat label="Errors" value={s.errors ?? "…"} />
          <Stat label="Avg. latency" value={fmtMs(s.avg_latency_ms)} /><Stat label="Cost" value={fmtCost(s.total_cost_usd)} sub={`${fmtTokens(s.total_tokens)} tokens`} />
        </div>
        {s.model_based_evaluators && <p className="text-xs text-warn">Some scores come from an LLM judge. They are model-based opinions, not objective truth.</p>}
        <div className="overflow-hidden rounded-lg border border-line bg-paper">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-xs text-ink-400"><tr><th className="px-4 py-2 font-medium">Case</th><th className="px-4 py-2 font-medium">Result</th><th className="px-4 py-2 font-medium">Scores</th><th className="px-4 py-2 font-medium">Latency</th><th className="px-4 py-2 font-medium">Cost</th><th /></tr></thead>
            <tbody>{e.results.map((r: any) => (
              <Fragment key={r.id}>
                <tr className="cursor-pointer border-b border-line hover:bg-canvas/60" onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <td className="px-4 py-2 font-medium">{r.case_name || "Untitled"}</td><td className="px-4 py-2"><StatusBadge status={r.status} /></td>
                  <td className="px-4 py-2">{r.scores.map((sc: any, i: number) => <Badge key={i} tone={sc.passed ? "blue" : "warn"} className="mr-1">{sc.label || sc.type} {typeof sc.score === "number" ? sc.score.toFixed(2) : ""}</Badge>)}</td>
                  <td className="px-4 py-2 tabular-nums text-ink-600">{fmtMs(r.latency_ms)}</td><td className="px-4 py-2 tabular-nums text-ink-600">{fmtCost(r.cost_usd)}</td>
                  <td className="px-4 py-2 text-right">{r.run_id && <Link onClick={(ev) => ev.stopPropagation()} href={`/runs/${r.run_id}`} className="text-xs text-accent-600">Open run</Link>}</td>
                </tr>
                {open === r.id && (
                  <tr className="border-b border-line bg-canvas/40"><td colSpan={6} className="px-4 py-3">
                    <div className="grid gap-3 md:grid-cols-3"><div><div className="text-xs text-ink-400">Input</div><Code value={r.input} maxH="max-h-40" /></div>
                      <div><div className="text-xs text-ink-400">Expected</div><Code value={toText(r.expected) || "—"} maxH="max-h-40" /></div>
                      <div><div className="text-xs text-ink-400">Output</div><Code value={toText(r.output) || "—"} maxH="max-h-40" /></div></div>
                    <ul className="mt-2 space-y-1 text-xs">{r.scores.map((sc: any, i: number) => <li key={i}><strong>{sc.label || sc.type}</strong>: {sc.passed ? "passed" : "failed"}{sc.reason && ` — ${sc.reason}`}{sc.error && <span className="text-state-failed"> — {sc.error}</span>}{sc.details?.method && ` (${sc.details.method})`}{sc.judge && ` · judge ${sc.judge}`}</li>)}</ul>
                  </td></tr>
                )}
              </Fragment>
            ))}</tbody>
          </table>
        </div>
      </div>
    </>
  );
}
