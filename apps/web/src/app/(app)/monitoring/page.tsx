"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { PageHeader } from "@/components/shell/AppShell";
import { Empty, Icon, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { useWorkspace } from "@/lib/session";
import type { Project } from "@/lib/types";

export default function MonitoringHome() {
  const { workspace } = useWorkspace();
  const alerts = useQuery({ queryKey: ["alerts", workspace?.id], enabled: !!workspace, queryFn: () => api<any[]>(`/workspaces/${workspace!.id}/alerts`) });
  const projects = useQuery({ queryKey: ["projects", workspace?.id], enabled: !!workspace, queryFn: () => api<Project[]>(`/workspaces/${workspace!.id}/projects`) });
  return (
    <>
      <PageHeader title="Monitoring" description="Open production alerts across the workspace. Metrics, trends and drift checks live in each project's Monitoring tab." />
      <div className="grid gap-6 px-8 py-6 lg:grid-cols-[2fr_1fr]">
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Open alerts</h2>
          {alerts.isLoading ? <Spinner /> : !alerts.data?.length ? <Empty icon="CheckCheck" title="No open alerts" body="Drift detection compares production against the baseline after each release." /> :
            alerts.data.map((a) => (
              <div key={a.id} className="flex items-start gap-3 rounded-lg border border-line bg-paper p-3 shadow-card">
                <Icon name={a.severity === "critical" ? "Siren" : "TriangleAlert"} className={a.severity === "critical" ? "text-state-failed" : "text-warn"} />
                <div className="text-sm"><div className="font-medium">{a.workflow_name}: {a.message}</div>
                  <div className="text-xs text-ink-500">{a.metric.replace(/_/g, " ")}{a.primary_node_key && ` · primary source ${a.primary_node_key}`} · {ago(a.created_at)}</div></div>
              </div>))}
        </section>
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Projects</h2>
          <ul className="divide-y divide-line rounded-lg border border-line bg-paper shadow-card">
            {projects.data?.map((p) => <li key={p.id}><Link href={`/projects/${p.id}?tab=monitoring`} className="flex justify-between px-4 py-2.5 text-sm hover:bg-canvas/60">{p.name}<Icon name="ChevronRight" className="text-ink-300" /></Link></li>)}
          </ul>
        </section>
      </div>
    </>
  );
}

