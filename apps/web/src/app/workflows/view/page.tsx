"use client";
import clsx from "clsx";
import Link from "next/link";
import { ReactFlowProvider, useReactFlow } from "@xyflow/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import OptimizerPanel from "@/components/builder/OptimizerPanel";
import type { EdgeTypeInfo, HeatInfo } from "@/components/builder/Canvas";
import BottomPanel, { useRunData } from "@/components/builder/BottomPanel";
import Canvas, { NodeLibrary } from "@/components/builder/Canvas";
import ConfigPanel from "@/components/builder/ConfigPanel";
import { RunDialog, VersionsDialog } from "@/components/builder/Dialogs";
import { NodeInspector } from "@/components/run/RunParts";
import { Logo } from "@/components/shell/AuthShell";
import { Button, Icon, Spinner, StatusBadge, toast } from "@/components/ui";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useMe } from "@/lib/session";
import type { Issue, NodeType, Workflow, WorkflowGraph } from "@/lib/types";
import { useRunStream } from "@/lib/useRunStream";
import { useBuilder } from "@/store/builder";
import { IdPage, routes } from "@/lib/routes";

export default function BuilderPage() {
  return <IdPage render={(id) => <ReactFlowProvider><Builder id={id} /></ReactFlowProvider>} />;
}

function Builder({ id }: { id: string }) {
  const me = useMe();
  const qc = useQueryClient();
  const rf = useReactFlow();
  const wfq = useQuery({ queryKey: ["workflow", id], queryFn: () => api<Workflow>(`/workflows/${id}`), staleTime: Infinity });
  const b = useBuilder();
  const [runId, setRunId] = useState<string | null>(null);
  const [runOpen, setRunOpen] = useState(false);
  const [runErr, setRunErr] = useState<unknown>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [optimizer, setOptimizer] = useState(false);
  const [edgeTypes, setEdgeTypes] = useState<Record<string, EdgeTypeInfo>>({});
  const [heatMode, setHeatMode] = useState<string>("");
  const [versions, setVersions] = useState(false);
  const [rightTab, setRightTab] = useState<"config" | "run">("config");
  const [editingName, setEditingName] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const loaded = useRef<string | null>(null);

  useEffect(() => {
    if (wfq.data && loaded.current !== wfq.data.id) {
      loaded.current = wfq.data.id;
      b.load(wfq.data.id, wfq.data.name, wfq.data.revision, wfq.data.graph as WorkflowGraph);
      setTimeout(() => rf.fitView({ padding: 0.12, maxZoom: 1, minZoom: 0.62 }), 50);
    }
  }, [wfq.data]); // eslint-disable-line react-hooks/exhaustive-deps

  // Latest run of this workflow is shown on load, so a refresh never loses a running execution.
  const latest = useQuery({ queryKey: ["wf-runs", id], queryFn: () => api<any[]>(`/workflows/${id}/runs?limit=1`) });
  useEffect(() => { if (!runId && latest.data?.[0]) setRunId(latest.data[0].id); }, [latest.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const stream = useRunStream(runId);
  const heatQ = useQuery({ queryKey: ["heat", id, heatMode], enabled: !!heatMode, queryFn: () => api<any>(`/workflows/${id}/heatmap?last=30`) });
  const heat = useMemo(() => {
    if (!heatMode || !heatQ.data) return undefined;
    const entries = Object.entries(heatQ.data.nodes as Record<string, any>).filter(([, v]) => v[heatMode] != null);
    const vals = entries.map(([, v]) => Number(v[heatMode]) || 0);
    const max = Math.max(...vals, 0);
    const fmt = (v: number) => heatMode === "cost" ? `~$${v.toFixed(4)} / run` : heatMode === "latency_ms" ? `${(v / 1000).toFixed(1)}s median`
      : heatMode === "tokens" ? `${v.toLocaleString()} tokens / run` : heatMode === "errors" ? `${v} failures` : heatMode === "evaluation" ? `${Math.round(v * 100)}% tests pass`
      : `${Math.round(v * 100)}% cache hits`;
    const out: Record<string, HeatInfo> = {};
    for (const [nid, v] of entries) {
      const x = Number(v[heatMode]) || 0;
      const rel = max ? x / max : 0;
      const lvl = heatMode === "evaluation" ? Math.round((1 - x) * 5) : Math.round(rel * 5);
      out[nid] = { value: x, label: fmt(x), level: Math.max(0, Math.min(5, lvl)) };
    }
    return out;
  }, [heatMode, heatQ.data]);
  useEffect(() => { const t = setTimeout(() => rf.fitView({ padding: 0.12, maxZoom: 1, minZoom: 0.62, duration: 200 }), 220); return () => clearTimeout(t); }, [panelOpen, optimizer]); // eslint-disable-line react-hooks/exhaustive-deps
  const { nodeRuns } = useRunData(runId, stream.events);

  // ------------------------------------------------------------------ autosave
  useEffect(() => {
    if (b.saveState !== "dirty" || !b.workflowId) return;
    const t = setTimeout(async () => {
      const s = useBuilder.getState();
      const snap = { nodes: s.nodes, edges: s.edges, settings: s.settings, name: s.name };
      s.setSave("saving");
      try {
        const r = await api<Workflow>(`/workflows/${s.workflowId}`, { method: "PUT", body: { graph: s.graph(), name: s.name, revision: s.revision } });
        const now = useBuilder.getState();
        const same = now.nodes === snap.nodes && now.edges === snap.edges && now.settings === snap.settings && now.name === snap.name;
        now.setSave(same ? "saved" : "dirty", null, r.revision);
      } catch (e) {
        if (e instanceof ApiError && e.code === "revision_conflict") useBuilder.getState().setSave("conflict", e.message);
        else useBuilder.getState().setSave("error", errorMessage(e));
      }
    }, 900);
    return () => clearTimeout(t);
  }, [b.saveState, b.nodes, b.edges, b.settings, b.name, b.workflowId]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { const s = useBuilder.getState().saveState; if (s === "dirty" || s === "saving" || s === "error") { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  // ------------------------------------------------------------------ server validation (debounced)
  useEffect(() => {
    if (!b.workflowId) return;
    const t = setTimeout(async () => {
      const g = useBuilder.getState().graph();
      try { const r = await api<{ issues: Issue[] }>(`/workflows/${id}/validate`, { body: { graph: g } }); useBuilder.getState().setIssues(r.issues); } catch { /* shown on run */ }
      try { setEdgeTypes(await api<Record<string, EdgeTypeInfo>>(`/workflows/${id}/edge-types`, { body: { graph: g } })); } catch { /* optional */ }
    }, 1200);
    return () => clearTimeout(t);
  }, [b.nodes, b.edges, b.settings, b.workflowId, id]);
  const issuesByNode = useMemo(() => {
    const m: Record<string, number> = {};
    for (const i of b.issues) if (i.node_id && i.severity === "error") m[i.node_id] = (m[i.node_id] || 0) + 1;
    return m;
  }, [b.issues]);
  const errors = b.issues.filter((i) => i.severity === "error");
  const warnings = b.issues.filter((i) => i.severity === "warning");

  // ------------------------------------------------------------------ run
  const startRun = useCallback(async (input: Record<string, any>) => {
    setRunErr(null);
    const s = useBuilder.getState();
    try {
      if (s.saveState !== "saved") {
        const r = await api<Workflow>(`/workflows/${id}`, { method: "PUT", body: { graph: s.graph(), name: s.name, revision: s.revision } });
        s.setSave("saved", null, r.revision);
      }
      const r = await api<{ run_id: string }>(`/workflows/${id}/run`, { body: { input } });
      setRunId(r.run_id); setRunOpen(false); setPanelOpen(true); setRightTab("run");
      qc.invalidateQueries({ queryKey: ["wf-runs", id] });
    } catch (e) { setRunErr(e); }
  }, [id, qc]);

  async function replay(nodeId: string) {
    if (!runId) return;
    try {
      const useDraft = confirm("Use your current draft for the re-run?\n\nOK = current draft (includes your edits)\nCancel = the exact graph of the original run");
      const r = await api<{ run_id: string }>(`/runs/${runId}/replay`, { body: { node_id: nodeId, use_current_draft: useDraft } });
      setRunId(r.run_id); setPanelOpen(true);
      toast("Re-running from the selected node; earlier outputs are reused");
    } catch (e) { toast(errorMessage(e), "error"); }
  }

  // ------------------------------------------------------------------ keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      const typing = el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable;
      const mod = e.metaKey || e.ctrlKey;
      const s = useBuilder.getState();
      if (mod && e.key === "Enter") { e.preventDefault(); setRunOpen(true); return; }
      if (mod && e.key === "s") { e.preventDefault(); if (s.saveState === "saved") toast("All changes saved", "info"); return; }
      if (typing) return;
      if (mod && e.key === "z" && !e.shiftKey) { e.preventDefault(); s.undo(); }
      else if (mod && (e.key === "y" || (e.key === "z" && e.shiftKey) || e.key === "Z")) { e.preventDefault(); s.redo(); }
      else if (mod && e.key === "c") s.copy();
      else if (mod && e.key === "v") s.paste();
      else if (mod && e.key === "d") { e.preventDefault(); s.duplicateSelected(); }
      else if (mod && e.key === "a") { e.preventDefault(); s.select(s.nodes.map((n) => n.id)); }
      else if (e.key === "Delete" || e.key === "Backspace") s.removeSelected();
      else if (e.shiftKey && (e.key === "L" || e.key === "l")) { s.layout(); setTimeout(() => rf.fitView({ padding: 0.25 }), 50); }
      else if (e.key === "Escape") s.select([]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rf]);

  function addAtCenter(t: NodeType) {
    const bounds = document.querySelector(".react-flow")?.getBoundingClientRect();
    const p = rf.screenToFlowPosition({ x: (bounds?.left || 0) + (bounds?.width || 800) / 2, y: (bounds?.top || 0) + (bounds?.height || 600) / 2 });
    b.addNode(t, { x: Math.round(p.x - 120), y: Math.round(p.y - 40) });
  }

  async function importIntoCanvas(f: File) {
    try {
      const doc = JSON.parse(await f.text());
      if (!["1.0", "2.0"].includes(doc.schema_version) || !doc.graph?.nodes) throw new Error("Not an Isocline workflow (schema 1.0 or 2.0)");
      const r = await api<{ issues: Issue[] }>(`/workflows/${id}/validate`, { body: { graph: doc.graph } });
      if (!confirm(`Replace the canvas with “${doc.name}”? ${r.issues.filter((i) => i.severity === "error").length} validation error(s). You can undo this.`)) return;
      b.replaceGraph(doc.graph);
      setTimeout(() => rf.fitView({ padding: 0.25 }), 50);
    } catch (e) { toast(errorMessage(e), "error"); }
  }

  if (wfq.isLoading || me.isLoading) return <div className="flex h-screen items-center justify-center"><Spinner /></div>;
  if (!wfq.data) return <div className="p-8 text-sm">Workflow not found. <Link className="text-accent-600" href="/projects">Back to projects</Link></div>;
  const wf = wfq.data;
  const selectedId = b.selection.length === 1 ? b.selection[0] : null;
  const selectedNode = b.nodes.find((n) => n.id === selectedId);
  const nr = nodeRuns.filter((n) => n.node_id === selectedId).sort((a, c) => (a.scope ? 1 : 0) - (c.scope ? 1 : 0))[0];
  const inputs = b.nodes.filter((n) => n.type.startsWith("input_") || n.type.startsWith("trigger_"));
  // Live stream state first; persisted node states as a fallback (e.g. before the stream replays).
  const live = Object.keys(stream.nodes).length ? stream.nodes : Object.fromEntries(nodeRuns.filter((n) => !n.scope).map((n) => [n.node_id,
    { status: n.status, tokens: n.input_tokens + n.output_tokens, cost: n.cost_usd, handle: n.handle, fallback: n.fallback_used, model: n.model || undefined }]));
  const running = stream.status === "running";

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-canvas">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-paper px-3 text-ink-700">
        <Link href={routes.project(wf.project_id)} className="flex items-center gap-2 rounded p-1 hover:bg-canvas" title="Back to project"><Logo /></Link>
        <Link href={routes.project(wf.project_id)} className="text-xs text-ink-400 hover:text-ink-800">{wf.project_name}</Link>
        <span className="text-ink-300">/</span>
        {editingName ? (
          <input autoFocus className="h-7 rounded border border-line bg-paper px-2 text-sm text-ink-900 focus:border-accent-500 focus:outline-none" defaultValue={b.name}
            onBlur={(e) => { if (e.target.value.trim()) b.setName(e.target.value.trim()); setEditingName(false); }} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
        ) : <button onClick={() => setEditingName(true)} className="rounded px-1 text-sm font-semibold text-ink-900 hover:bg-canvas" title="Rename">{b.name}</button>}
        <StatusBadge status={wf.status} className="ml-1" />
        <SaveIndicator />
        <div className="ml-2 flex items-center">
          <IconBtn icon="Undo2" label="Undo (⌘Z)" onClick={b.undo} disabled={!b.past.length} />
          <IconBtn icon="Redo2" label="Redo (⇧⌘Z)" onClick={b.redo} disabled={!b.future.length} />
          <IconBtn icon="Network" label="Auto layout (⇧L)" onClick={() => { b.layout(); setTimeout(() => rf.fitView({ padding: 0.25 }), 50); }} />
          <IconBtn icon="Download" label="Export JSON" onClick={() => { window.location.href = `/api/v1/workflows/${id}/export`; }} />
          <IconBtn icon="Upload" label="Import JSON into this canvas" onClick={() => fileRef.current?.click()} />
          <input ref={fileRef} type="file" accept=".json,application/json" className="hidden" onChange={(e) => { if (e.target.files?.[0]) importIntoCanvas(e.target.files[0]); e.target.value = ""; }} />
        </div>
        <div className="flex-1" />
        <button onClick={() => { b.select([]); setRightTab("config"); }} className={clsx("flex items-center gap-1 rounded px-2 py-1 text-xs", errors.length ? "text-state-failed" : "text-state-completed")}
          title={[...errors, ...warnings].map((i) => i.message).join("\n") || "No issues"}>
          <Icon name={errors.length ? "CircleAlert" : "CircleCheck"} size={14} />{errors.length ? `${errors.length} to fix` : "Valid"}{warnings.length ? ` · ${warnings.length} warnings` : ""}
        </button>
        <Button size="sm" variant="dark" icon="Flame" onClick={() => setHeatMode(heatMode ? "" : "cost")} aria-pressed={!!heatMode}>Heatmap</Button>
        <Button size="sm" variant="dark" icon="Gauge" onClick={() => setOptimizer(!optimizer)}>Optimize</Button>
        <Button size="sm" variant="dark" icon="History" onClick={() => setVersions(true)}>Versions{wf.latest_version ? ` (v${wf.latest_version})` : ""}</Button>
        <Button size="sm" variant="primary" icon={running ? "LoaderCircle" : "Play"} onClick={() => setRunOpen(true)} title="Run (⌘↵)">{running ? "Running" : "Run"}</Button>
      </header>
      {b.saveState === "conflict" && (
        <div className="flex items-center gap-3 bg-state-running/15 px-4 py-2 text-sm text-ink-900" role="alert">
          <Icon name="TriangleAlert" />This workflow was changed in another tab or by someone else. Your edits are not saved.
          <Button size="sm" onClick={() => { loaded.current = null; qc.invalidateQueries({ queryKey: ["workflow", id] }); wfq.refetch(); }}>Load latest (discard mine)</Button>
          <Button size="sm" onClick={() => { const blob = new Blob([JSON.stringify({ schema_version: "2.0", name: b.name, graph: b.graph() }, null, 2)]); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "my-edits.workflow.json"; a.click(); }}>Download my edits</Button>
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <aside className="w-56 shrink-0 border-r border-line bg-paper" aria-label="Node library"><NodeLibrary onAdd={addAtCenter} /></aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="relative min-h-0 flex-1">
            <Canvas live={heat ? {} : live} issues={issuesByNode} edgeTypes={edgeTypes} heat={heat} />
            {heatMode && (
              <div className="absolute left-3 top-3 z-10 w-64 rounded-lg border border-line bg-paper/95 p-3 text-xs shadow-pop">
                <div className="mb-2 flex items-center justify-between font-semibold">Heatmap · last {heatQ.data?.runs_analyzed ?? "…"} runs
                  <button aria-label="Close heatmap" onClick={() => setHeatMode("")} className="text-ink-400 hover:text-ink-900"><Icon name="X" size={14} /></button></div>
                <div className="mb-2 flex flex-wrap gap-1">
                  {[["cost", "Cost"], ["latency_ms", "Latency"], ["tokens", "Tokens"], ["errors", "Errors"], ["cache_hit_rate", "Cache"], ["evaluation", "Tests"]].map(([m, l]) => (
                    <button key={m} onClick={() => setHeatMode(m)} className={clsx("rounded-full border px-2 py-0.5", heatMode === m ? "border-accent-500 bg-accent-50 text-accent-700" : "border-line")}>{l}</button>))}
                </div>
                {heatQ.data?.runs_analyzed === 0 && <p className="text-ink-500">Run the workflow to collect measurements.</p>}
                {!!heatQ.data?.bottlenecks?.length && <div className="space-y-0.5 border-t border-line pt-2">
                  <div className="font-medium text-ink-700">Bottlenecks</div>
                  {heatQ.data.bottlenecks.map((b: any) => <button key={b.metric} onClick={() => b.node_id && useBuilder.getState().select([b.node_id])} className="flex w-full justify-between text-left text-ink-600 hover:text-accent-600"><span>{b.label}</span><span className="font-mono">{b.key}</span></button>)}
                </div>}
              </div>
            )}
          </div>
          <BottomPanel runId={runId} events={stream.events} graphNodes={b.nodes} open={panelOpen} setOpen={setPanelOpen}
            onSelectNode={(nid) => { b.select([nid]); setRightTab("run"); }} selectedNode={selectedId} onReplay={replay} />
        </div>
        <aside className="flex w-[360px] shrink-0 flex-col border-l border-line bg-paper" aria-label="Configuration">
          {optimizer ? <OptimizerPanel workflowId={id} projectId={wf.project_id} onClose={() => setOptimizer(false)}
              onApplied={() => { loaded.current = null; wfq.refetch(); }} /> : (
            <>
              {selectedNode && runId && (
                <div className="flex border-b border-line text-xs">
                  {(["config", "run"] as const).map((t) => <button key={t} onClick={() => setRightTab(t)} className={clsx("flex-1 py-2 font-medium", rightTab === t ? "border-b-2 border-accent-500 text-ink-900" : "text-ink-400")}>{t === "config" ? "Design" : "Last run"}</button>)}
                </div>
              )}
              <div className="min-h-0 flex-1 overflow-y-auto">
                {selectedNode && runId && rightTab === "run" ? <NodeInspector nr={nr} node={selectedNode} onReplay={replay} /> : <ConfigPanel projectId={wf.project_id} workflowId={id} issues={b.issues} />}
              </div>
            </>
          )}
        </aside>
      </div>
      <RunDialog open={runOpen} onClose={() => setRunOpen(false)} workflowId={id} projectId={wf.project_id} inputs={inputs} onStart={startRun} error={runErr}
        goalMode={b.settings.mode === "goal"} />
      <VersionsDialog open={versions} onClose={() => setVersions(false)} workflowId={id} latest={wf.latest_version}
        onRestored={(g, rev) => { b.replaceGraph(g); useBuilder.getState().setSave("saved", null, rev); wfq.refetch(); }} />
    </div>
  );
}

function IconBtn({ icon, label, onClick, disabled }: { icon: string; label: string; onClick: () => void; disabled?: boolean }) {
  return <button onClick={onClick} disabled={disabled} title={label} aria-label={label} className="rounded p-1.5 text-ink-500 hover:bg-canvas hover:text-ink-900 disabled:opacity-30"><Icon name={icon} /></button>;
}

function SaveIndicator() {
  const { saveState, saveError } = useBuilder();
  const map = { saved: ["Check", "Saved", "text-ink-400"], dirty: ["Circle", "Unsaved", "text-ink-400"], saving: ["LoaderCircle", "Saving…", "text-ink-400"],
    error: ["CircleAlert", "Save failed — retrying on next edit", "text-state-failed"], conflict: ["TriangleAlert", "Conflict", "text-state-running"] } as const;
  const [icon, label, cls] = map[saveState];
  return <span className={clsx("ml-2 flex items-center gap-1 text-xs", cls)} title={saveError || undefined} aria-live="polite"><Icon name={icon} size={13} className={saveState === "saving" ? "animate-spin" : ""} />{label}</span>;
}
