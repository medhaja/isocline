"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { PageHeader } from "@/components/shell/AppShell";
import { Badge, Icon, Input, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/session";

const CAPS = [["vision", "Vision"], ["tool_calling", "Tools"], ["structured_output", "Structured"], ["reasoning", "Reasoning"]];

export default function Models() {
  const { workspace } = useWorkspace();
  const [q, setQ] = useState("");
  const [onlyConfigured, setOnly] = useState(true);
  const m = useQuery({ queryKey: ["capabilities", workspace?.id], enabled: !!workspace, queryFn: () => api<any[]>(`/workspaces/${workspace!.id}/models/capabilities`) });
  const rows = (m.data || []).filter((r) => (!onlyConfigured || r.configured) && `${r.provider}/${r.model}`.includes(q.toLowerCase()));
  return (
    <>
      <PageHeader title="Models" description="The capability registry AUTO routing and contracts use. Measured metrics come from this workspace's runs and experiments; everything else is registry metadata." />
      <div className="space-y-4 px-8 py-6">
        <div className="flex items-center gap-3">
          <Input className="max-w-xs" placeholder="Filter models" value={q} onChange={(e) => setQ(e.target.value)} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={onlyConfigured} onChange={(e) => setOnly(e.target.checked)} />Only models with a key</label>
          <div className="flex-1" /><Link href="/providers" className="text-sm text-accent-600">Keys, secrets & pricing →</Link>
        </div>
        {m.isLoading ? <Spinner /> : (
          <div className="overflow-x-auto rounded-lg border border-line bg-paper shadow-card">
            <table className="w-full text-sm">
              <thead className="border-b border-line text-left text-xs text-ink-500"><tr>
                <th className="px-4 py-2.5 font-medium">Model</th>{CAPS.map(([, l]) => <th key={l} className="px-2 py-2.5 text-center font-medium">{l}</th>)}
                <th className="px-3 py-2.5 font-medium">Coding</th><th className="px-3 py-2.5 font-medium">Context</th><th className="px-3 py-2.5 font-medium">$ / 1M in · out</th>
                <th className="px-3 py-2.5 font-medium">Measured (7d)</th><th className="px-3 py-2.5 font-medium">Eval score</th></tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.provider + r.model} className="border-b border-line last:border-0">
                  <td className="px-4 py-2"><div className="font-medium">{r.model}</div><div className="text-xs text-ink-400">{r.provider}{!r.configured && " · no key"}{r.provider === "local_test" && " · test only"}</div></td>
                  {CAPS.map(([k]) => <td key={k} className="px-2 py-2 text-center">{r.capabilities[k] === true ? <Icon name="Check" className="inline text-state-completed" /> : r.capabilities[k] === false ? <span className="text-ink-300">—</span> : <span className="text-2xs text-ink-400">?</span>}</td>)}
                  <td className="px-3 py-2 text-xs">{r.capabilities.coding || "—"}</td>
                  <td className="px-3 py-2 tabular-nums">{r.context_window ? `${Math.round(r.context_window / 1000)}K` : "—"}</td>
                  <td className="px-3 py-2 tabular-nums text-xs">{r.pricing ? `$${r.pricing.input_per_mtok} · $${r.pricing.output_per_mtok}` : "—"}</td>
                  <td className="px-3 py-2 text-xs">{r.metrics.calls ? <>{r.metrics.calls} calls · {Math.round((r.metrics.success_rate || 0) * 100)}% ok · {(r.metrics.p50_latency_ms / 1000).toFixed(1)}s</> : <span className="text-ink-400">no runs yet (prior: {r.capabilities.latency_s ?? "?"}s)</span>}</td>
                  <td className="px-3 py-2 text-xs">{r.metrics.eval_score != null ? <Badge tone="blue">{Math.round(r.metrics.eval_score * 100)}%</Badge> : <span className="text-ink-400">prior tier {r.capabilities.quality_tier ?? "?"}</span>}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-ink-400">“?” means the registry doesn&apos;t confirm the capability: AUTO won&apos;t pick that model when the capability is required. Administrators can edit capabilities and prices under Keys & secrets → Model pricing. Evaluation scores come from experiments.</p>
      </div>
    </>
  );
}
