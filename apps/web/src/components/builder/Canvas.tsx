"use client";
import clsx from "clsx";
import { Background, BackgroundVariant, Controls, MiniMap, ReactFlow, useReactFlow, type Connection, type Edge, type Node, type NodeChange, type EdgeChange } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useMemo, useRef, useState } from "react";
import { Icon, toast } from "@/components/ui";
import { connectionError } from "@/lib/graph";
import { CATEGORY_LABEL, CATEGORY_TINT, NODE_SPECS, SPEC } from "@/lib/nodes";
import type { NodeType, WFEdge, WFNode } from "@/lib/types";
import type { LiveNode } from "@/lib/useRunStream";
import { useBuilder } from "@/store/builder";
import FlowNode, { type FlowData } from "./FlowNode";

const nodeTypes = { wf: FlowNode };
export const DND_TYPE = "application/isocline-node";

function edgeClass(e: WFEdge, live?: Record<string, LiveNode>) {
  if (!live || !Object.keys(live).length) return "";
  const s = live[e.source], t = live[e.target];
  if (t?.status === "running" && s?.status === "completed") return "isc-active";
  if (s?.status === "completed" && t && ["completed", "running", "waiting", "failed"].includes(t.status)) {
    // a branch that was not taken stays dim
    if (s.handle && (e.source_handle ?? null) !== s.handle && !(s.handle === "done" && !e.source_handle)) return "isc-dim";
    return "isc-done";
  }
  if (t?.status === "skipped") return "isc-dim";
  return "";
}

export interface EdgeTypeInfo { source_type: string; target_type?: string; ok: boolean; note?: string; suggestion?: { transform: string; label: string } | null }
export interface HeatInfo { value: number; label: string; level: number }

export function toFlow(nodes: WFNode[], edges: WFEdge[], opts: { live?: Record<string, LiveNode>; selection?: string[]; selectedEdge?: string | null; issues?: Record<string, number>; readOnly?: boolean;
  edgeTypes?: Record<string, EdgeTypeInfo>; heat?: Record<string, HeatInfo> }) {
  const rfNodes: Node[] = nodes.map((n) => ({
    id: n.id, type: "wf", position: n.position, selected: opts.selection?.includes(n.id) ?? false,
    data: { node: n, live: opts.live?.[n.id], issues: opts.issues?.[n.id], readOnly: opts.readOnly, heat: opts.heat?.[n.id] } satisfies FlowData,
    ...(n.type === "group" ? { style: { width: n.config.width || 520, height: n.config.height || 320 }, zIndex: -1 } : {}),
    draggable: !opts.readOnly, connectable: !opts.readOnly,
  }));
  const rfEdges: Edge[] = edges.map((e) => {
    const t = opts.edgeTypes?.[e.id];
    const typed = t && t.target_type;
    return {
      id: e.id, source: e.source, target: e.target, sourceHandle: e.source_handle ?? null, targetHandle: e.target_handle ?? null,
      className: clsx(edgeClass(e, opts.live), t && !t.ok && "isc-bad"), selected: opts.selectedEdge === e.id,
      // typed connections show their data type; mismatches are red with the reason on hover
      label: typed ? (t.ok ? t.source_type : `${t.source_type} ≠ ${t.target_type}`) : (e.target_handle || undefined),
      labelShowBg: true, labelBgPadding: [4, 2] as [number, number], labelBgBorderRadius: 4,
      labelStyle: t && !t.ok ? { fill: "rgb(var(--state-failed))" } : undefined,
      data: { type: t },
    };
  });
  return { rfNodes, rfEdges };
}

export function ReadOnlyCanvas({ nodes, edges, live, onSelect, selected, heat }: { nodes: WFNode[]; edges: WFEdge[]; live: Record<string, LiveNode>; onSelect: (id: string | null) => void; selected: string | null; heat?: Record<string, HeatInfo> }) {
  const { rfNodes, rfEdges } = useMemo(() => toFlow(nodes, edges, { live, selection: selected ? [selected] : [], readOnly: true, heat }), [nodes, edges, live, selected, heat]);
  return (
    <ReactFlow nodes={rfNodes} edges={rfEdges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.08, maxZoom: 1, minZoom: 0.55 }} nodesDraggable={false} nodesConnectable={false}
      onNodeClick={(_, n) => onSelect(n.id)} onPaneClick={() => onSelect(null)} minZoom={0.2} proOptions={{ hideAttribution: true }}>
      <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} color="rgb(var(--ink-300) / .6)" />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

export default function Canvas({ live, issues, edgeTypes, heat }: { live: Record<string, LiveNode>; issues: Record<string, number>;
  edgeTypes?: Record<string, EdgeTypeInfo>; heat?: Record<string, HeatInfo> }) {
  const { nodes, edges, selection, selectedEdge } = useBuilder();
  const store = useBuilder;
  const rf = useReactFlow();
  const lastError = useRef<string | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; nodeId?: string; flow: { x: number; y: number } } | null>(null);
  const { rfNodes, rfEdges } = useMemo(() => toFlow(nodes, edges, { live, selection, selectedEdge, issues, edgeTypes, heat }),
    [nodes, edges, live, selection, selectedEdge, issues, edgeTypes, heat]);

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    const pos: Record<string, { x: number; y: number }> = {};
    let sel: string[] | null = null;
    for (const c of changes) {
      if (c.type === "position" && c.position) pos[c.id] = { x: Math.round(c.position.x), y: Math.round(c.position.y) };
      if (c.type === "select") {
        sel = sel ?? [...store.getState().selection];
        sel = c.selected ? [...new Set([...sel, c.id])] : sel.filter((x) => x !== c.id);
      }
    }
    if (Object.keys(pos).length) store.getState().setPositions(pos);
    if (sel) store.getState().select(sel, null);
  }, [store]);

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    for (const c of changes) if (c.type === "select" && c.selected) store.getState().select([], c.id);
  }, [store]);

  const isValidConnection = useCallback((c: Connection | Edge) => {
    const err = connectionError(store.getState(), c.source!, c.target!, (c.sourceHandle as string) ?? null);
    lastError.current = err;
    return !err;
  }, [store]);

  const onConnect = useCallback((c: Connection) => {
    const err = connectionError(store.getState(), c.source!, c.target!, c.sourceHandle ?? null);
    if (err) return toast(err, "error");
    store.getState().connect({ source: c.source!, target: c.target!, source_handle: c.sourceHandle ?? null, target_handle: null });
  }, [store]);

  const onConnectEnd = useCallback((_: any, state: any) => {
    if (state && !state.isValid && state.toNode && lastError.current) toast(lastError.current, "error");
    lastError.current = null;
  }, []);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const type = e.dataTransfer.getData(DND_TYPE) as NodeType;
    if (!type || !SPEC[type]) return;
    const p = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    store.getState().addNode(type, { x: Math.round(p.x - 120), y: Math.round(p.y - 30) });
  }, [rf, store]);

  const add = (type: NodeType) => { if (menu) store.getState().addNode(type, menu.flow); setMenu(null); };

  return (
    <div className="relative h-full w-full" onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }} onDrop={onDrop}>
      <ReactFlow nodes={rfNodes} edges={rfEdges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
        onConnect={onConnect} onConnectEnd={onConnectEnd} isValidConnection={isValidConnection}
        onNodeDragStart={() => store.getState().commit(() => ({}))}
        onPaneClick={() => { store.getState().select([]); setMenu(null); }}
        onNodeContextMenu={(e, n) => { e.preventDefault(); if (!store.getState().selection.includes(n.id)) store.getState().select([n.id]); setMenu({ x: e.clientX, y: e.clientY, nodeId: n.id, flow: n.position }); }}
        onPaneContextMenu={(e) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, flow: rf.screenToFlowPosition({ x: e.clientX, y: e.clientY }) }); }}
        deleteKeyCode={null} selectionKeyCode="Shift" multiSelectionKeyCode={["Meta", "Control"]} selectionOnDrag={false} panOnDrag
        fitView fitViewOptions={{ padding: 0.12, maxZoom: 1, minZoom: 0.62 }} minZoom={0.15} maxZoom={2} snapToGrid snapGrid={[10, 10]}
        defaultEdgeOptions={{ type: "default" }} proOptions={{ hideAttribution: true }}>
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} color="rgb(var(--ink-300) / .6)" />
        <MiniMap pannable zoomable nodeColor={(n) => CATEGORY_TINT[SPEC[(n.data as FlowData).node.type]?.category || "annotation"]} maskColor="rgb(var(--canvas) / .7)" />
        <Controls />
      </ReactFlow>
      {nodes.length === 0 && (
        <div className="contour-backdrop pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="max-w-xs rounded-lg bg-canvas/80 px-5 py-4 text-center backdrop-blur-[2px]">
            <p className="text-sm font-medium text-ink-700">Drag a node from the left to start</p>
            <p className="mt-1 text-xs text-ink-400">A minimal workflow is Text input → Agent → Text output. Or start from a template.</p>
          </div>
        </div>
      )}
      {menu && (
        <div className="fixed z-40 w-52 rounded-md border border-line bg-paper py-1 text-sm shadow-pop" style={{ left: menu.x, top: menu.y }} onMouseLeave={() => setMenu(null)}>
          {menu.nodeId ? (
            <>
              <MenuItem icon="Copy" label="Duplicate" kbd="⌘D" onClick={() => { store.getState().duplicateSelected(); setMenu(null); }} />
              <MenuItem icon="Clipboard" label="Copy" kbd="⌘C" onClick={() => { store.getState().copy(); setMenu(null); }} />
              <MenuItem icon="Trash2" label="Delete" kbd="Del" danger onClick={() => { store.getState().removeSelected(); setMenu(null); }} />
            </>
          ) : (
            <>
              <div className="px-3 pb-1 pt-1.5 text-2xs text-ink-400">Add here</div>
              {(["agent", "input_text", "condition", "merge", "human_approval", "output_text", "note"] as NodeType[]).map((t) => (
                <MenuItem key={t} icon={SPEC[t].icon} label={SPEC[t].label} onClick={() => add(t)} />
              ))}
              <div className="my-1 border-t border-line" />
              <MenuItem icon="ClipboardPaste" label="Paste" kbd="⌘V" onClick={() => { store.getState().paste(); setMenu(null); }} />
              <MenuItem icon="Network" label="Auto layout" kbd="⇧L" onClick={() => { store.getState().layout(); setMenu(null); setTimeout(() => rf.fitView({ padding: 0.25 }), 50); }} />
            </>
          )}
        </div>
      )}
    </div>
  );
}

function MenuItem({ icon, label, kbd, onClick, danger }: { icon: string; label: string; kbd?: string; onClick: () => void; danger?: boolean }) {
  return (
    <button onClick={onClick} className={`flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-canvas ${danger ? "text-state-failed" : "text-ink-700"}`}>
      <Icon name={icon} size={14} /><span className="flex-1">{label}</span>{kbd && <span className="text-2xs text-ink-400">{kbd}</span>}
    </button>
  );
}

export function NodeLibrary({ onAdd }: { onAdd: (t: NodeType) => void }) {
  const [q, setQ] = useState("");
  const cats = ["trigger", "input", "agent", "logic", "wait", "tool", "output", "annotation"] as const;
  const labels = CATEGORY_LABEL;
  const match = (s: (typeof NODE_SPECS)[number]) => !q || `${s.label} ${s.description}`.toLowerCase().includes(q.toLowerCase());
  return (
    <div className="flex h-full flex-col">
      <div className="p-3"><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search nodes" aria-label="Search nodes"
        className="h-8 w-full rounded-md border border-line bg-canvas px-2.5 text-xs text-ink-900 placeholder:text-ink-400 focus:border-accent-500 focus:outline-none" /></div>
      <div className="flex-1 space-y-4 overflow-y-auto px-2 pb-4">
        {cats.map((c) => {
          const items = NODE_SPECS.filter((s) => s.category === c && match(s));
          if (!items.length) return null;
          return (
            <div key={c}>
              <div className="px-2 pb-1 text-2xs font-medium text-ink-400">{labels[c]}</div>
              {items.map((s) => (
                <div key={s.type} draggable onDragStart={(e) => { e.dataTransfer.setData(DND_TYPE, s.type); e.dataTransfer.effectAllowed = "move"; }}
                  onDoubleClick={() => onAdd(s.type)} onKeyDown={(e) => e.key === "Enter" && onAdd(s.type)} tabIndex={0} role="button"
                  title={`${s.description}. Drag onto the canvas, or double-click to add.`}
                  className="flex cursor-grab items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-ink-700 hover:bg-canvas active:cursor-grabbing">
                  <span style={{ color: CATEGORY_TINT[s.category] }}><Icon name={s.icon} size={15} /></span>{s.label}
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
