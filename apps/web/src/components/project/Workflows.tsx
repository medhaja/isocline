"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import NewWorkflowDialog from "@/components/NewWorkflow";
import { RunsTable } from "@/components/common";
import { Button, Empty, Icon, Select, Spinner, StatusBadge, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { ago } from "@/lib/format";
import type { Run, Workflow } from "@/lib/types";
import { routes } from "@/lib/routes";

export function Workflows({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [archived, setArchived] = useState(false);
  const [open, setOpen] = useState<null | "blank" | "template" | "ai" | "import">(null);
  const q = useQuery({ queryKey: ["workflows", projectId, archived], queryFn: () => api<Workflow[]>(`/projects/${projectId}/workflows?include_archived=${archived}`) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["workflows", projectId] });

  async function act(w: Workflow, what: "duplicate" | "archive" | "unarchive" | "delete") {
    try {
      if (what === "duplicate") await api(`/workflows/${w.id}/duplicate`, { method: "POST" });
      if (what === "archive") await api(`/workflows/${w.id}/status`, { method: "PATCH", body: { status: "archived" } });
      if (what === "unarchive") await api(`/workflows/${w.id}/status`, { method: "PATCH", body: { status: "draft" } });
      if (what === "delete") {
        if (!confirm(`Delete “${w.name}” and all of its runs? This can't be undone.`)) return;
        await api(`/workflows/${w.id}`, { method: "DELETE" });
      }
      toast(what === "duplicate" ? "Workflow duplicated" : what === "delete" ? "Workflow deleted" : what === "archive" ? "Workflow archived" : "Workflow restored");
      refresh();
    } catch (e) { toast(errorMessage(e), "error"); }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm text-ink-600"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived</label>
        <div className="flex gap-2">
          <Button icon="FileUp" onClick={() => setOpen("import")}>Import</Button>
          <Button icon="Sparkles" onClick={() => setOpen("ai")}>Create with AI</Button>
          <Button variant="primary" icon="Plus" onClick={() => setOpen("blank")}>New workflow</Button>
        </div>
      </div>
      {q.isLoading ? <Spinner /> : !q.data?.length ? (
        <Empty icon="Workflow" title="No workflows in this project" body="Start from a template to see a multi-agent team at work, or describe what you need."
          action={<div className="flex gap-2"><Button onClick={() => setOpen("template")}>Browse templates</Button><Button variant="primary" icon="Sparkles" onClick={() => setOpen("ai")}>Create with AI</Button></div>} />
      ) : (
        <div className="overflow-hidden rounded-lg border border-line bg-paper">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-xs text-ink-400"><tr>
              <th className="px-4 py-2 font-medium">Name</th><th className="px-4 py-2 font-medium">Status</th><th className="px-4 py-2 font-medium">Nodes</th>
              <th className="px-4 py-2 font-medium">Last run</th><th className="px-4 py-2 font-medium">Edited</th><th /></tr></thead>
            <tbody>
              {q.data.map((w) => (
                <tr key={w.id} className="border-b border-line last:border-0 hover:bg-canvas/60">
                  <td className="px-4 py-2.5"><Link className="font-medium text-ink-900 hover:text-accent-600" href={routes.workflow(w.id)}>{w.name}</Link>
                    {w.latest_version > 0 && <span className="ml-2 text-xs text-ink-400">v{w.latest_version}</span>}</td>
                  <td className="px-4 py-2.5"><StatusBadge status={w.status} /></td>
                  <td className="px-4 py-2.5 tabular-nums text-ink-600">{w.node_count}</td>
                  <td className="px-4 py-2.5 text-ink-600">{ago(w.last_run_at)}</td>
                  <td className="px-4 py-2.5 text-ink-600">{ago(w.updated_at)}</td>
                  <td className="px-4 py-2.5 text-right">
                    <RowMenu items={[
                      { label: "Duplicate", icon: "Copy", onClick: () => act(w, "duplicate") },
                      w.status === "archived" ? { label: "Restore", icon: "ArchiveRestore", onClick: () => act(w, "unarchive") } : { label: "Archive", icon: "Archive", onClick: () => act(w, "archive") },
                      { label: "Delete", icon: "Trash2", onClick: () => act(w, "delete"), danger: true },
                    ]} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <NewWorkflowDialog open={!!open} initialMode={open || "blank"} onClose={() => setOpen(null)} projectId={projectId} />
    </div>
  );
}

export function RowMenu({ items }: { items: { label: string; icon: string; onClick: () => void; danger?: boolean }[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative inline-block">
      <button aria-label="More actions" onClick={() => setOpen(!open)} onBlur={() => setTimeout(() => setOpen(false), 150)} className="rounded p-1 text-ink-400 hover:bg-canvas hover:text-ink-900"><Icon name="Ellipsis" /></button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-40 rounded-md border border-line bg-paper py-1 text-left shadow-pop">
          {items.map((i) => (
            <button key={i.label} onMouseDown={(e) => e.preventDefault()} onClick={() => { setOpen(false); i.onClick(); }}
              className={`flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-canvas ${i.danger ? "text-state-failed" : "text-ink-700"}`}>
              <Icon name={i.icon} size={14} />{i.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function ProjectRuns({ projectId }: { projectId: string }) {
  const [status, setStatus] = useState("");
  const [compareA, setCompareA] = useState<string | null>(null);
  const router = useRouter();
  const q = useQuery({ queryKey: ["project-runs", projectId, status], queryFn: () => api<Run[]>(`/projects/${projectId}/runs?limit=100${status ? `&status=${status}` : ""}`), refetchInterval: 10_000 });
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Select className="w-44" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
          <option value="">All statuses</option>
          {["running", "waiting", "completed", "failed", "cancelled", "queued"].map((s) => <option key={s}>{s}</option>)}
        </Select>
        {compareA && <span className="text-sm text-ink-600">Pick a second run to compare with. <button className="text-accent-600 underline" onClick={() => setCompareA(null)}>Cancel</button></span>}
      </div>
      {q.isLoading ? <Spinner /> : !q.data?.length ? <Empty icon="Play" title="No runs" body="Runs appear here when a workflow is started from the builder, the API or an evaluation." /> :
        <RunsTable runs={q.data} compareFrom={(id) => compareA ? router.push(`/runs/compare?a=${compareA}&b=${id}`) : setCompareA(id)} />}
    </div>
  );
}
