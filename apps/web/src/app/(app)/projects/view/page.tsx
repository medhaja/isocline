"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/shell/AppShell";
import { Artifacts } from "@/components/project/Artifacts";
import { Experiments } from "@/components/project/Experiments";
import { Monitoring } from "@/components/project/Monitoring";
import { Triggers } from "@/components/project/Triggers";
import { Evaluations } from "@/components/project/Evaluations";
import { Knowledge } from "@/components/project/Knowledge";
import { ProjectRuns, Workflows } from "@/components/project/Workflows";
import { Spinner, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { IdPage, routes } from "@/lib/routes";

type Tab = "workflows" | "runs" | "evaluations" | "experiments" | "artifacts" | "knowledge" | "triggers" | "monitoring";

function ProjectPage({ id }: { id: string }) {
  const params = useSearchParams();
  const router = useRouter();
  const tab = (params.get("tab") as Tab) || "workflows";
  const p = useQuery({ queryKey: ["project", id], queryFn: () => api<Project>(`/projects/${id}`) });
  if (p.isLoading) return <div className="p-8"><Spinner /></div>;
  if (!p.data) return <div className="p-8 text-sm text-ink-400">Project not found.</div>;
  return (
    <>
      <PageHeader title={p.data.name} description={p.data.description} back={{ href: "/projects", label: "Projects" }} />
      <div className="bg-paper px-8">
        <Tabs<Tab> value={tab} onChange={(t) => router.replace(routes.project(id, t))}
          tabs={[{ id: "workflows", label: "Workflows" }, { id: "runs", label: "Runs" }, { id: "evaluations", label: "Evaluations" },
            { id: "experiments", label: "Experiments" }, { id: "artifacts", label: "Artifacts" }, { id: "knowledge", label: "Knowledge" },
            { id: "triggers", label: "Triggers" }, { id: "monitoring", label: "Monitoring" }]} />
      </div>
      <div className="px-8 py-6">
        {tab === "workflows" && <Workflows projectId={id} />}
        {tab === "runs" && <ProjectRuns projectId={id} />}
        {tab === "evaluations" && <Evaluations projectId={id} />}
        {tab === "knowledge" && <Knowledge projectId={id} />}
        {tab === "experiments" && <Experiments projectId={id} />}
        {tab === "artifacts" && <Artifacts projectId={id} />}
        {tab === "triggers" && <Triggers projectId={id} />}
        {tab === "monitoring" && <Monitoring projectId={id} />}
      </div>
    </>
  );
}

export default function Page() { return <IdPage render={(id) => <ProjectPage id={id} />} />; }
