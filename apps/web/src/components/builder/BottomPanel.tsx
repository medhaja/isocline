"use client";
import clsx from "clsx";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import ApprovalCard from "@/components/run/ApprovalCard";
import { EventLog, OutputView, RunError, RunSummary, Timeline, UsageTable } from "@/components/run/RunParts";
import { Button, Icon, StatusBadge, Tabs, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { NodeRun, Run, RunEvent, WFNode } from "@/lib/types";
import { routes } from "@/lib/routes";

type Tab = "run" | "output" | "trace" | "logs" | "tokens" | "cost" | "errors";

export function useRunData(runId: string | null, events: RunEvent[]) {
  const qc = useQueryClient();
  const run = useQuery({ queryKey: ["run", runId], enabled: !!runId, queryFn: () => api<Run>(`/runs/${runId}`) });
  const nodes = useQuery({ queryKey: ["run-nodes", runId], enabled: !!runId, queryFn: () => api<NodeRun[]>(`/runs/${runId}/nodes`) });
  const last = useRef(0);
  // Refresh persisted details when meaningful events arrive (throttled).
  useEffect(() => {
    const ev = events[events.length - 1];
    if (!ev || !runId) return;
    const important = /COMPLETED|FAILED|WAITING|SKIPPED|CANCELLED|TOOL_COMPLETED|RESUMED/.test(ev.type);
    if (!important) return;
    const now = Date.now();
    const delay = now - last.current > 800 ? 0 : 800;
    last.current = now + delay;
    const t = setTimeout(() => { qc.invalidateQueries({ queryKey: ["run", runId] }); qc.invalidateQueries({ queryKey: ["run-nodes", runId] }); }, delay);
    return () => clearTimeout(t);
  }, [events, runId, qc]);
  return { run: run.data, nodeRuns: nodes.data || [], refetch: () => { run.refetch(); nodes.refetch(); } };
}

export default function BottomPanel({ runId, events, graphNodes, open, setOpen, onSelectNode, selectedNode, onReplay }: {
  runId: string | null; events: RunEvent[]; graphNodes: WFNode[]; open: boolean; setOpen: (v: boolean) => void;
  onSelectNode: (id: string) => void; selectedNode: string | null; onReplay: (nodeId: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("run");
  const { run, nodeRuns, refetch } = useRunData(runId, events);
  const failed = nodeRuns.filter((n) => n.status === "failed");
  const pending = run?.approvals?.filter((a) => a.status === "pending") || [];
  useEffect(() => { setTab("run"); }, [runId]);  // every new run starts on Progress
  useEffect(() => {
    if (run?.status === "completed") setTab((t) => (t === "run" ? "output" : t));
    if (run?.status === "failed") setTab((t) => (t === "run" ? "errors" : t));
  }, [run?.status]);
  useEffect(() => { if (pending.length) { setTab("run"); setOpen(true); } }, [pending.length]); // a decision is needed: show it

  async function cancel() {
    try { await api(`/runs/${runId}/cancel`, { method: "POST" }); toast("Cancelling…", "info"); refetch(); } catch (e) { toast(errorMessage(e), "error"); }
  }
  return (
    <div className={clsx("flex flex-col border-t border-line bg-paper transition-[height]", open ? "h-[38vh]" : "h-10")}>
      <div className="flex items-center gap-3 px-3">
        <button onClick={() => setOpen(!open)} className="flex h-10 items-center gap-2 text-xs font-medium text-ink-700" aria-expanded={open}>
          <Icon name={open ? "ChevronDown" : "ChevronUp"} size={14} />{runId ? "Run" : "Run panel"}
        </button>
        {run && <StatusBadge status={run.status} />}
        {run && open && <div className="flex-1"><Tabs<Tab> value={tab} onChange={setTab} tabs={[
          { id: "run", label: "Progress" }, { id: "output", label: "Output" }, { id: "trace", label: "Trace" }, { id: "logs", label: "Logs", count: events.length },
          { id: "tokens", label: "Tokens" }, { id: "cost", label: "Cost" }, { id: "errors", label: "Errors", count: failed.length + (run.error ? 1 : 0) || undefined }]} /></div>}
        {!open && <div className="flex-1" />}
        {run && ["queued", "running", "waiting", "resuming"].includes(run.status) && <Button size="sm" icon="Square" onClick={cancel}>Stop</Button>}
        {run && <Link href={routes.run(run.id)} className="text-xs text-accent-600 hover:underline">Open run page</Link>}
      </div>
      {open && (
        <div className="flex-1 overflow-y-auto border-t border-line px-4 py-3">
          {!runId ? <p className="text-sm text-ink-400">Press Run (⌘↵) to execute the workflow. Nodes light up as they work; results, traces and costs appear here.</p>
            : !run ? <p className="text-sm text-ink-400">Starting…</p> : (
              <>
                {tab === "run" && (
                  <div className="space-y-4">
                    <RunSummary run={run} />
                    {pending.map((a) => <ApprovalCard key={a.id} approval={a} onDecided={refetch} />)}
                    <RunError run={run} nodes={graphNodes} />
                    <Timeline nodeRuns={nodeRuns} graph={graphNodes} onSelect={onSelectNode} selected={selectedNode} />
                  </div>
                )}
                {tab === "output" && (run.output ? (
                  Object.keys(run.output.outputs || {}).length > 1
                    ? Object.entries(run.output.outputs).map(([k, v]) => <div key={k} className="mb-4"><div className="mb-1 font-mono text-xs text-ink-400">{k}</div><OutputView value={v} /></div>)
                    : <OutputView value={run.output.result} />
                ) : <p className="text-sm text-ink-400">{run.status === "waiting" ? "Waiting for approval before the final output." : "No output yet."}</p>)}
                {tab === "trace" && <Timeline nodeRuns={nodeRuns} graph={graphNodes} onSelect={onSelectNode} selected={selectedNode} />}
                {tab === "logs" && <EventLog events={events} />}
                {tab === "tokens" && <UsageTable nodeRuns={nodeRuns} graph={graphNodes} mode="tokens" />}
                {tab === "cost" && <><UsageTable nodeRuns={nodeRuns} graph={graphNodes} mode="cost" /><p className="mt-3 text-xs text-ink-400">Costs are estimates from the server pricing table; your provider's invoice is authoritative.</p></>}
                {tab === "errors" && (
                  <div className="space-y-3">
                    <RunError run={run} nodes={graphNodes} />
                    {failed.map((n) => (
                      <div key={n.id} className="rounded-md border border-line p-3 text-sm">
                        <div className="flex items-center justify-between"><button className="font-medium hover:text-accent-600" onClick={() => onSelectNode(n.node_id)}>{graphNodes.find((g) => g.id === n.node_id)?.name || n.node_key}</button>
                          <Button size="sm" icon="RotateCcw" onClick={() => onReplay(n.node_id)}>Re-run from here</Button></div>
                        <p className="mt-1 text-state-failed">{n.error?.message}</p>
                        <p className="text-xs text-ink-400">{(n.attempts || []).filter((a: any) => a.status === "failed").length} failed attempt(s)</p>
                      </div>
                    ))}
                    {!failed.length && !run.error && <p className="text-sm text-ink-400">No errors.</p>}
                  </div>
                )}
              </>
            )}
        </div>
      )}
    </div>
  );
}
