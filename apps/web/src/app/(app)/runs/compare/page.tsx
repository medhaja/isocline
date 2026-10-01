"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Suspense, useState } from "react";
import { PageHeader } from "@/components/shell/AppShell";
import { Badge, Code, Spinner, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, fmtCost, fmtMs, fmtTokens, toText } from "@/lib/format";

function Compare() {
  const p = useSearchParams();
  const a = p.get("a"), b = p.get("b");
  const q = useQuery({ queryKey: ["compare", a, b], enabled: !!a && !!b, queryFn: () => api<any>(`/runs/compare/${a}/${b}`) });
  const [onlyChanged, setOnlyChanged] = useState(true);
  if (!a || !b) return <p className="p-8 text-sm">Choose two runs from a project's Runs tab.</p>;
  if (q.isLoading || !q.data) return <div className="p-8"><Spinner /></div>;
  const d = q.data;
  const rows = d.nodes.filter((r: any) => !onlyChanged || r.output_changed || r.config_changed || r.a?.status !== r.b?.status);
  const Side = ({ run, label }: { run: any; label: string }) => (
    <div className="rounded-lg border border-line bg-paper p-4 text-sm">
      <div className="flex items-center justify-between"><Link href={`/runs/${run.id}`} className="font-medium text-accent-600">{label}: {ago(run.created_at)}</Link><StatusBadge status={run.status} /></div>
      <div className="mt-2 grid grid-cols-4 gap-2 text-xs text-ink-600"><span>{fmtMs(run.duration_ms)}</span><span>{fmtTokens(run.input_tokens + run.output_tokens)} tokens</span><span>{fmtCost(run.cost_usd)}</span><span>{run.llm_calls} calls</span></div>
    </div>
  );
  return (
    <>
      <PageHeader title="Compare runs" description={d.input_changed ? "The two runs had different inputs." : "Both runs had the same input."} />
      <div className="space-y-4 px-8 py-6">
        <div className="grid grid-cols-2 gap-4"><Side run={d.a} label="A" /><Side run={d.b} label="B" /></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} /> Only show nodes that differ</label>
        {rows.length === 0 && <p className="text-sm text-ink-400">No differences.</p>}
        {rows.map((r: any) => (
          <section key={r.node_id + r.scope} className="rounded-lg border border-line bg-paper">
            <header className="flex items-center gap-2 border-b border-line px-4 py-2 text-sm font-medium">{r.name}<span className="font-mono text-xs text-ink-400">{r.key}{r.scope && ` @ ${r.scope}`}</span>
              {r.config_changed && <Badge tone="warn">configuration changed</Badge>}{r.output_changed && <Badge tone="blue">output changed</Badge>}</header>
            <div className="grid grid-cols-2 divide-x divide-line">
              {[r.a, r.b].map((s: any, i: number) => (
                <div key={i} className="space-y-2 p-4 text-sm">
                  {!s ? <p className="text-ink-400">Did not run</p> : <>
                    <div className="flex flex-wrap gap-3 text-xs text-ink-600"><StatusBadge status={s.status} />{s.model && <span>{s.provider}/{s.model}</span>}<span>{fmtMs(s.latency_ms)}</span><span>{fmtTokens(s.input_tokens + s.output_tokens)} tok</span><span>{fmtCost(s.cost_usd)}</span></div>
                    {r.config_changed && s.prompt !== undefined && <div><div className="text-xs text-ink-400">Prompt</div><Code value={s.prompt || "—"} maxH="max-h-32" /></div>}
                    {r.config_changed && s.params && <div><div className="text-xs text-ink-400">Parameters</div><Code value={s.params} maxH="max-h-24" /></div>}
                    <div><div className="text-xs text-ink-400">Output</div><Code value={s.error ? s.error.message : toText(s.output)} maxH="max-h-64" /></div>
                  </>}
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}

export default function Page() { return <Suspense><Compare /></Suspense>; }
