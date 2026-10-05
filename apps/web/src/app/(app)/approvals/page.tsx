"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import ApprovalCard from "@/components/run/ApprovalCard";
import { PageHeader } from "@/components/shell/AppShell";
import { Empty, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/session";
import type { Approval } from "@/lib/types";
import { routes } from "@/lib/routes";

export default function Approvals() {
  const { workspace } = useWorkspace();
  const q = useQuery({ queryKey: ["approvals", workspace?.id], enabled: !!workspace, queryFn: () => api<Approval[]>(`/workspaces/${workspace!.id}/approvals`), refetchInterval: 10_000 });
  return (
    <>
      <PageHeader title="Approvals" description="Runs paused at a human approval step. They resume as soon as you decide." />
      <div className="max-w-3xl space-y-4 px-8 py-6">
        {q.isLoading ? <Spinner /> : !q.data?.length ? <Empty icon="UserCheck" title="Nothing waiting for you" body="When a workflow reaches a Human approval node, it appears here." /> :
          q.data.map((a) => <div key={a.id}><ApprovalCard approval={a} onDecided={() => q.refetch()} /><Link className="mt-1 inline-block text-xs text-accent-600" href={routes.run(a.run_id)}>Open run</Link></div>)}
      </div>
    </>
  );
}
