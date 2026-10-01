"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Empty, Icon, Spinner, toast } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, fmtCost } from "@/lib/format";

export function Spark({ values, color = "rgb(var(--accent-500))", height = 36 }: { values: (number | null)[]; color?: string; height?: number }) {
  const v = values.map((x) => x ?? 0);
  if (v.length < 2) return <div style={{ height }} className="text-2xs text-ink-300">not enough data</div>;
  const max = Math.max(...v, 1e-9);
  const pts = v.map((x, i) => `${(i / (v.length - 1)) * 100},${height - (x / max) * (height - 4) - 2}`).join(" ");
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="w-full" style={{ height }} role="img" aria-label="trend">
      <polyline points={`0,${height} ${pts} 100,${height}`} fill={color} opacity="0.08" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const pct = (x: number | null | undefined) => (x == null ? "—" : `${(x * 100).toFixed(x < 0.1 && x > 0 ? 1 : 0)}%`);

export function Monitoring({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["monitoring", projectId], queryFn: () => api<any>(`/projects/${projectId}/monitoring?hours=168`), refetchInterval: 30_000 });
  if (q.isLoading) return <Spinner />;
  const d = q.data;
  async function detect() {
    const r = await api<any>(`/projects/${projectId}/monitoring/detect`, { method: "POST" });
    toast(r.new_alerts ? `${r.new_alerts} new drift alert(s)` : "No drift detected", r.new_alerts ? "error" : "ok");
    qc.invalidateQueries({ queryKey: ["monitoring", projectId] });
  }
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-ink-500">Last 7 days of runs per workflow, with drift alerts against each workflow's published baseline.</p>
        <Button icon="Radar" onClick={detect}>Check for drift now</Button>
      </div>
      {!!d.alerts.length && (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold">Alerts</h3>
          {d.alerts.map((a: any) => (
            <div key={a.id} className={`flex items-start gap-3 rounded-lg border p-3 text-sm ${a.acknowledged_at ? "border-line opacity-60" : a.severity === "critical" ? "border-state-failed/40 bg-state-failed/5" : "border-state-running/40 bg-state-running/5"}`}>
              <Icon name={a.severity === "critical" ? "Siren" : "TriangleAlert"} className={a.severity === "critical" ? "text-state-failed" : "text-warn"} />
              <div className="flex-1">
                <div className="font-medium">{a.message}</div>
                <div className="text-xs text-ink-500">{a.metric.replace(/_/g, " ")}{a.primary_node_key && ` · primary source: ${a.primary_node_key}`} · {ago(a.created_at)}</div>
              </div>
              {!a.acknowledged_at && <Button size="sm" variant="ghost" onClick={async () => { await api(`/alerts/${a.id}/acknowledge`, { method: "POST" }); qc.invalidateQueries({ queryKey: ["monitoring", projectId] }); qc.invalidateQueries({ queryKey: ["alerts"] }); }}>Acknowledge</Button>}
            </div>
          ))}
        </section>
      )}
      {!d.targets.length ? <Empty icon="Activity" title="No runs in the last 7 days" body="Run a workflow and its metrics appear here." /> : (
        <div className="grid gap-4 xl:grid-cols-2">
          {d.targets.map((t: any) => {
            const m = t.metrics, s = m.series || [];
            return (
              <section key={t.kind + t.id + t.workflow_id} className="rounded-lg border border-line bg-paper p-4 shadow-card">
                <div className="flex items-center justify-between"><div><div className="font-semibold">{t.workflow_name}</div>
                  <div className="text-xs text-ink-500">{t.version ? `Published v${t.version}` : "Draft only"}</div></div>
                  <Badge tone={m.failure_rate > 0.05 ? "warn" : "blue"}>{pct(m.success_rate)} success</Badge></div>
                <dl className="mt-3 grid grid-cols-4 gap-3 text-xs">
                  {[["Requests", m.requests], ["P95 latency", m.latency_p95_s != null ? `${m.latency_p95_s}s` : "—"], ["Cost / run", fmtCost(m.cost_per_run)], ["Tokens", m.tokens.toLocaleString()],
                    ["Tool errors", pct(m.tool_error_rate)], ["Fallback rate", pct(m.fallback_rate)], ["Cache hits", pct(m.cache_hit_rate)], ["Approval rate", pct(m.approval_rate)]].map(([l, v]) => (
                    <div key={l as string}><dt className="text-ink-400">{l}</dt><dd className="font-medium tabular-nums">{v}</dd></div>))}
                </dl>
                <div className="mt-3 grid grid-cols-2 gap-4">
                  <div><div className="text-2xs text-ink-400">Requests</div><Spark values={s.map((x: any) => x.requests)} /></div>
                  <div><div className="text-2xs text-ink-400">P95 latency</div><Spark values={s.map((x: any) => x.latency_p95_s)} color="rgb(var(--state-waiting))" /></div>
                </div>
                {!!m.routing?.length && <div className="mt-2 text-2xs text-ink-500">AUTO routing: {m.routing.map((r: any) => `${r.model} ×${r.count}`).join(", ")}</div>}
                {m.cache_savings_usd > 0 && <div className="mt-1 text-2xs text-state-completed">Cache saved {fmtCost(m.cache_savings_usd)}</div>}
              </section>
            );
          })}
        </div>
      )}
      <p className="text-xs text-ink-400">Drift compares the last 24 hours with the first 7 days after the current release. Costs are estimates. Output-size drift is labelled as an evaluation proxy.</p>
    </div>
  );
}
