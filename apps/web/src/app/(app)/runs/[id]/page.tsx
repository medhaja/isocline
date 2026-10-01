"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ReactFlowProvider } from "@xyflow/react";
import { useState } from "react";
import { useRunData } from "@/components/builder/BottomPanel";
import { ReadOnlyCanvas } from "@/components/builder/Canvas";
import ApprovalCard from "@/components/run/ApprovalCard";
import HarnessTab, { LineageTab } from "@/components/run/HarnessTab";
import { EventLog, NodeInspector, OutputView, RunError, RunSummary, Timeline, UsageTable } from "@/components/run/RunParts";
import { PageHeader } from "@/components/shell/AppShell";
import { Button, Code, Spinner, StatusBadge, Tabs, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { ago } from "@/lib/format";
import { useRunStream } from "@/lib/useRunStream";

type Tab = "output" | "trace" | "harness" | "lineage" | "tokens" | "logs" | "input";

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const stream = useRunStream(id);
  const { run, nodeRuns, refetch } = useRunData(id, stream.events);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("output");

  if (!run) return <div className="p-8"><Spinner /></div>;
  const graph = run.graph_snapshot!;
  const live = Object.keys(stream.nodes).length ? stream.nodes : Object.fromEntries(nodeRuns.filter((n) => !n.scope).map((n) => [n.node_id, { status: n.status, tokens: n.input_tokens + n.output_tokens, cost: n.cost_usd, handle: n.handle, fallback: n.fallback_used, model: n.model || undefined }]));
  const node = graph.nodes.find((n) => n.id === selected);
  const nr = nodeRuns.filter((n) => n.node_id === selected).sort((a, b) => (a.scope ? 1 : 0) - (b.scope ? 1 : 0))[0];
  const active = ["queued", "running", "waiting", "resuming"].includes(run.status);

  async function replay(nodeId: string) {
    try { const r = await api<{ run_id: string }>(`/runs/${id}/replay`, { body: { node_id: nodeId, use_current_draft: false } }); router.push(`/runs/${r.run_id}`); }
    catch (e) { toast(errorMessage(e), "error"); }
  }
  async function cancel() { try { await api(`/runs/${id}/cancel`, { method: "POST" }); refetch(); } catch (e) { toast(errorMessage(e), "error"); } }

  return (
    <div className="flex h-full flex-col">
      <PageHeader back={{ href: `/projects/${run.project_id}?tab=runs`, label: "Runs" }}
        title={<span className="flex items-center gap-3">{run.workflow_name} <StatusBadge status={run.status} /></span>}
        description={<>Started {ago(run.created_at)} by {run.trigger}{run.parent_run_id && <> · re-run of <Link className="text-accent-600" href={`/runs/${run.parent_run_id}`}>an earlier run</Link> from node {graph.nodes.find((n) => n.id === run.replay_from_node_id)?.name}</>}
          {run.workflow_version_id ? " · published version" : " · draft"}{run.recovery_attempts ? ` · resumed after ${run.recovery_attempts} worker interruption(s)` : ""}</>}
        actions={<>
          {active && <Button icon="Square" onClick={cancel}>Stop run</Button>}
          {run.parent_run_id && <Link href={`/runs/compare?a=${run.parent_run_id}&b=${run.id}`}><Button icon="GitCompare">Compare with original</Button></Link>}
          <Link href={`/workflows/${run.workflow_id}`}><Button icon="Pencil">Open workflow</Button></Link>
        </>} />
      <div className="border-b border-line bg-paper px-8 py-4"><RunSummary run={run} /></div>
      <div className="grid min-h-0 flex-1 grid-cols-[1fr_400px]">
        <div className="flex min-h-0 flex-col">
          <div className="h-[46%] min-h-[260px] border-b border-line"><ReactFlowProvider><ReadOnlyCanvas nodes={graph.nodes} edges={graph.edges} live={live} selected={selected} onSelect={setSelected} /></ReactFlowProvider></div>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
            <div className="space-y-4">
              {run.approvals?.filter((a) => a.status === "pending").map((a) => <ApprovalCard key={a.id} approval={a} onDecided={refetch} />)}
              <RunError run={run} nodes={graph.nodes} />
              <Tabs<Tab> value={tab} onChange={setTab} tabs={[{ id: "output", label: "Output" }, { id: "trace", label: "Timeline" }, { id: "harness", label: "Harness" }, { id: "lineage", label: "Lineage" },
                { id: "tokens", label: "Tokens & cost" }, { id: "logs", label: "Events", count: stream.events.length }, { id: "input", label: "Input" }]} />
              {tab === "output" && (run.output ? (Object.keys(run.output.outputs || {}).length > 1
                ? Object.entries(run.output.outputs).map(([k, v]) => <div key={k}><div className="mb-1 font-mono text-xs text-ink-400">{k}</div><OutputView value={v} /></div>)
                : <OutputView value={run.output.result} />) : <p className="text-sm text-ink-400">{active ? "The output appears when the run finishes." : "This run produced no output."}</p>)}
              {tab === "trace" && <Timeline nodeRuns={nodeRuns} graph={graph.nodes} onSelect={setSelected} selected={selected} />}
              {tab === "tokens" && <UsageTable nodeRuns={nodeRuns} graph={graph.nodes} mode="tokens" />}
              {tab === "logs" && <EventLog events={stream.events} />}
              {tab === "input" && <Code value={run.input} />}
              {tab === "harness" && <HarnessTab runId={id} active={active} nodeName={(nid) => graph.nodes.find((n) => n.id === nid)?.name || nid} />}
              {tab === "lineage" && <LineageTab runId={id} output={run.output?.result} />}
              {!!run.replays?.length && <div className="text-sm"><div className="mb-1 text-xs font-medium text-ink-700">Re-runs</div>
                {run.replays.map((r) => <Link key={r.id} href={`/runs/${r.id}`} className="mr-3 text-accent-600 hover:underline">{ago(r.created_at)} ({r.status})</Link>)}</div>}
            </div>
          </div>
        </div>
        <aside className="min-h-0 overflow-hidden border-l border-line bg-paper">
          {node ? <NodeInspector nr={nr} node={node} onReplay={active ? undefined : replay} onClose={() => setSelected(null)} />
            : <p className="p-5 text-sm text-ink-400">Select a node in the graph or timeline to inspect its resolved input, output, tool calls, tokens, cost and attempts. From there you can re-run the workflow from that node; upstream outputs are reused and this run stays unchanged.</p>}
        </aside>
      </div>
    </div>
  );
}
