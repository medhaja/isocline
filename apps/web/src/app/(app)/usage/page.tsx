"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/shell/AppShell";
import { Select, Spinner, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtCost, fmtTokens } from "@/lib/format";
import { useWorkspace } from "@/lib/session";

export default function Usage() {
  const { workspace } = useWorkspace();
  const [days, setDays] = useState(30);
  const q = useQuery({ queryKey: ["usage", workspace?.id, days], enabled: !!workspace, queryFn: () => api<any>(`/workspaces/${workspace!.id}/usage?days=${days}`) });
  const d = q.data;
  const max = Math.max(1, ...(d?.daily || []).map((x: any) => x.input_tokens + x.output_tokens));
  const total = d ? d.by_model.reduce((s: number, m: any) => s + m.cost_usd, 0) : 0;
  const tokens = d ? d.by_model.reduce((s: number, m: any) => s + m.input_tokens + m.output_tokens, 0) : 0;
  const calls = d ? d.by_model.reduce((s: number, m: any) => s + m.calls, 0) : 0;
  return (
    <>
      <PageHeader title="Usage" description={d?.note}
        actions={<Select className="w-40" value={days} onChange={(e) => setDays(+e.target.value)} aria-label="Period"><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option></Select>} />
      {q.isLoading || !d ? <div className="p-8"><Spinner /></div> : (
        <div className="space-y-6 px-8 py-6">
          <div className="grid grid-cols-3 gap-3"><Stat label="Estimated spend" value={fmtCost(total)} /><Stat label="Tokens" value={fmtTokens(tokens)} /><Stat label="Model calls" value={calls.toLocaleString()} /></div>
          <section className="rounded-lg border border-line bg-paper p-4">
            <h2 className="mb-3 text-sm font-semibold">Tokens per day</h2>
            {d.daily.length === 0 ? <p className="text-sm text-ink-400">No usage in this period.</p> : (
              <div className="flex h-40 items-end gap-1" role="img" aria-label="Daily token usage">
                {d.daily.map((x: any) => (
                  <div key={x.date} className="group relative flex-1" title={`${x.date}: ${fmtTokens(x.input_tokens + x.output_tokens)} tokens, ${fmtCost(x.cost_usd)}`}>
                    <div className="w-full rounded-t bg-accent-500/80 group-hover:bg-accent-500" style={{ height: `${((x.input_tokens + x.output_tokens) / max) * 150}px` }} />
                  </div>
                ))}
              </div>
            )}
          </section>
          <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
            <section><h2 className="mb-2 text-sm font-semibold">By model</h2>
              <div className="overflow-hidden rounded-lg border border-line bg-paper"><table className="w-full text-sm">
                <thead className="border-b border-line text-left text-xs text-ink-400"><tr><th className="px-4 py-2 font-medium">Model</th><th className="px-4 py-2 text-right font-medium">Calls</th><th className="px-4 py-2 text-right font-medium">Input</th><th className="px-4 py-2 text-right font-medium">Output</th><th className="px-4 py-2 text-right font-medium">Cost (est.)</th></tr></thead>
                <tbody>{d.by_model.map((m: any) => (
                  <tr key={m.provider + m.model} className="border-b border-line last:border-0"><td className="px-4 py-2">{m.model} <span className="text-xs text-ink-400">{m.provider}</span>{m.unpriced_calls > 0 && <span className="block text-xs text-warn">{m.unpriced_calls} calls without a price in the pricing table</span>}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{m.calls}</td><td className="px-4 py-2 text-right tabular-nums">{fmtTokens(m.input_tokens)}</td><td className="px-4 py-2 text-right tabular-nums">{fmtTokens(m.output_tokens)}</td><td className="px-4 py-2 text-right tabular-nums">{fmtCost(m.cost_usd)}</td></tr>))}</tbody>
              </table></div></section>
            <section className="space-y-6">
              <div><h2 className="mb-2 text-sm font-semibold">By project</h2><ul className="divide-y divide-line rounded-lg border border-line bg-paper text-sm">{d.by_project.map((p: any) => <li key={p.project} className="flex justify-between px-4 py-2"><span>{p.project}</span><span className="tabular-nums text-ink-600">{fmtCost(p.cost_usd)}</span></li>)}
                {!d.by_project.length && <li className="px-4 py-2 text-ink-400">—</li>}</ul></div>
              <div><h2 className="mb-2 text-sm font-semibold">By purpose</h2><ul className="divide-y divide-line rounded-lg border border-line bg-paper text-sm">{d.by_purpose.map((p: any) => <li key={p.purpose} className="flex justify-between px-4 py-2"><span>{({ run: "Workflow runs", generator: "Create with AI", eval_judge: "LLM judge" } as any)[p.purpose] || p.purpose}</span><span className="tabular-nums text-ink-600">{p.calls} · {fmtCost(p.cost_usd)}</span></li>)}
                {!d.by_purpose.length && <li className="px-4 py-2 text-ink-400">—</li>}</ul></div>
            </section>
          </div>
        </div>
      )}
    </>
  );
}
