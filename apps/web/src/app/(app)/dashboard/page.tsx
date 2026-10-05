"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/shell/AppShell";
import { RunsTable, useProviders } from "@/components/common";
import { Button, Empty, Icon, Spinner, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, fmtCost, fmtTokens } from "@/lib/format";
import { useWorkspace } from "@/lib/session";
import type { Project } from "@/lib/types";
import { routes } from "@/lib/routes";

export default function Dashboard() {
  const { workspace } = useWorkspace();
  const dash = useQuery({ queryKey: ["dashboard", workspace?.id], enabled: !!workspace, queryFn: () => api<any>(`/workspaces/${workspace!.id}/dashboard`), refetchInterval: 15_000 });
  const projects = useQuery({ queryKey: ["projects", workspace?.id], enabled: !!workspace, queryFn: () => api<Project[]>(`/workspaces/${workspace!.id}/projects`) });
  const providers = useProviders();
  const d = dash.data;
  const hasKey = providers.data?.some((p) => p.has_credential);
  const onboarding = !projects.isLoading && (!hasKey || !projects.data?.length || !d?.total_runs);

  return (
    <>
      <PageHeader title="Dashboard" description={`Activity in ${workspace?.name} over the last 30 days.`}
        actions={<Link href="/projects"><Button variant="primary" icon="Plus">New workflow</Button></Link>} />
      <div className="space-y-8 px-8 py-6">
        {onboarding && (
          <section className="rounded-lg border border-line bg-paper p-5">
            <h2 className="text-sm font-semibold">Get your first workflow running</h2>
            <ol className="mt-3 grid gap-3 md:grid-cols-3">
              <Step done={!!hasKey} href="/providers" title="Connect a model" body="Add an API key for OpenAI, Anthropic, Gemini, OpenRouter, or point at Ollama." />
              <Step done={!!projects.data?.length} href="/projects" title="Create a project" body="Projects hold workflows, runs, knowledge bases and triggers." />
              <Step done={!!d?.total_runs} href="/templates" title="Run a template" body="The Investment Research Team shows parallel agents, approval and a final report." />
            </ol>
          </section>
        )}
        {dash.isLoading ? <Spinner /> : d && (
          <>
            <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
              <Stat label="Runs" value={d.total_runs} sub={d.runs_by_status.running ? `${d.runs_by_status.running} running now` : undefined} />
              <Stat label="Success rate" value={d.success_rate === null ? "—" : `${Math.round(d.success_rate * 100)}%`} sub={d.runs_by_status.failed ? `${d.runs_by_status.failed} failed` : undefined} />
              <Stat label="Tokens" value={fmtTokens(d.tokens)} />
              <Stat label="Spend" value={fmtCost(d.estimated_spend_usd)} sub="Estimated from pricing table" />
              <Stat label="Avg. duration" value={d.avg_duration_seconds ? `${d.avg_duration_seconds}s` : "—"} />
            </section>
            <div className="grid gap-8 xl:grid-cols-[2fr_1fr]">
              <section>
                <h2 className="mb-3 text-sm font-semibold">Recent runs</h2>
                {d.recent_runs.length ? <RunsTable runs={d.recent_runs} /> : <Empty icon="Play" title="No runs yet" body="Open a workflow and press Run to see live execution here." />}
              </section>
              <section className="space-y-6">
                <div>
                  <h2 className="mb-3 text-sm font-semibold">Recent workflows</h2>
                  <ul className="divide-y divide-line rounded-lg border border-line bg-paper">
                    {d.recent_workflows.length === 0 && <li className="px-4 py-3 text-sm text-ink-400">No workflows yet.</li>}
                    {d.recent_workflows.map((w: any) => (
                      <li key={w.id}><Link href={routes.workflow(w.id)} className="flex items-center justify-between px-4 py-2.5 hover:bg-canvas/60">
                        <span><span className="block text-sm font-medium">{w.name}</span><span className="text-xs text-ink-400">{w.project_name} · edited {ago(w.updated_at)}</span></span>
                        <Icon name="ChevronRight" className="text-ink-300" />
                      </Link></li>
                    ))}
                  </ul>
                </div>
                {d.failed_workflows.length > 0 && (
                  <div>
                    <h2 className="mb-3 text-sm font-semibold">Failing workflows</h2>
                    <ul className="divide-y divide-line rounded-lg border border-line bg-paper">
                      {d.failed_workflows.map((w: any) => (
                        <li key={w.id}><Link href={routes.workflow(w.id)} className="flex justify-between px-4 py-2.5 text-sm hover:bg-canvas/60">
                          <span>{w.name}</span><span className="text-state-failed">{w.failures} failed</span></Link></li>
                      ))}
                    </ul>
                  </div>
                )}
                <div>
                  <h2 className="mb-3 text-sm font-semibold">Models in use</h2>
                  <ul className="divide-y divide-line rounded-lg border border-line bg-paper text-sm">
                    {d.model_usage.length === 0 && <li className="px-4 py-3 text-ink-400">No model calls yet.</li>}
                    {d.model_usage.map((m: any) => (
                      <li key={m.provider + m.model} className="flex justify-between px-4 py-2">
                        <span className="truncate">{m.model} <span className="text-ink-400">{m.provider}</span></span>
                        <span className="tabular-nums text-ink-600">{m.calls} calls · {fmtCost(m.cost_usd)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                {d.top_agents.length > 0 && (
                  <div>
                    <h2 className="mb-3 text-sm font-semibold">Most-used agents</h2>
                    <ul className="divide-y divide-line rounded-lg border border-line bg-paper text-sm">
                      {d.top_agents.map((a: any) => (
                        <li key={a.key + a.workflow} className="flex justify-between px-4 py-2"><span>{a.key} <span className="text-ink-400">in {a.workflow}</span></span><span className="tabular-nums text-ink-600">{a.runs}×</span></li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
            </div>
          </>
        )}
      </div>
    </>
  );
}

function Step({ done, href, title, body }: { done: boolean; href: string; title: string; body: string }) {
  return (
    <li>
      <Link href={href} className="flex h-full gap-3 rounded-md border border-line p-3 hover:border-ink-300">
        <span className={done ? "text-state-completed" : "text-ink-300"}><Icon name={done ? "CircleCheck" : "Circle"} size={18} /></span>
        <span><span className="block text-sm font-medium text-ink-900">{title}</span><span className="text-xs leading-relaxed text-ink-400">{body}</span></span>
      </Link>
    </li>
  );
}
