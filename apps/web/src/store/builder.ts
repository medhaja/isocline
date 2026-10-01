"use client";
import { create } from "zustand";
import { autoLayout, makeNode, uid, uniqueKey } from "@/lib/graph";
import type { Issue, NodeStatus, NodeType, WFEdge, WFNode, WFSettings, WorkflowGraph } from "@/lib/types";

type Snapshot = { nodes: WFNode[]; edges: WFEdge[]; settings: WFSettings };
export type SaveState = "saved" | "dirty" | "saving" | "error" | "conflict";

export interface NodeLive { status: NodeStatus; tokens?: number; cost?: number | null; model?: string; attempt?: number; fallback?: boolean; iterations?: number; handle?: string | null }

interface BuilderState extends Snapshot {
  workflowId: string | null;
  name: string;
  revision: number;
  selection: string[];
  selectedEdge: string | null;
  past: Snapshot[];
  future: Snapshot[];
  lastCoalesce: { key: string; at: number } | null;
  clipboard: { nodes: WFNode[]; edges: WFEdge[] } | null;
  saveState: SaveState;
  saveError: string | null;
  issues: Issue[];
  live: Record<string, NodeLive>;
  liveRunId: string | null;

  load: (id: string, name: string, revision: number, g: WorkflowGraph) => void;
  commit: (fn: (s: Snapshot) => Partial<Snapshot>, coalesceKey?: string) => void;
  setPositions: (pos: Record<string, { x: number; y: number }>) => void;
  addNode: (type: NodeType, position: { x: number; y: number }, overrides?: Partial<WFNode>) => WFNode;
  updateNode: (id: string, patch: Partial<WFNode>, coalesceKey?: string) => void;
  updateConfig: (id: string, patch: Record<string, any>, coalesceKey?: string) => void;
  updateHarness: (id: string, patch: Record<string, any>, coalesceKey?: string) => void;
  setContract: (id: string, contract: any, coalesceKey?: string) => void;
  connect: (e: Omit<WFEdge, "id">) => void;
  removeEdges: (ids: string[]) => void;
  removeSelected: () => void;
  duplicateSelected: () => void;
  copy: () => void;
  paste: () => void;
  select: (ids: string[], edge?: string | null) => void;
  undo: () => void;
  redo: () => void;
  layout: () => void;
  replaceGraph: (g: WorkflowGraph, label?: string) => void;
  setSettings: (patch: Partial<WFSettings>) => void;
  setName: (name: string) => void;
  setSave: (s: SaveState, err?: string | null, revision?: number) => void;
  setIssues: (i: Issue[]) => void;
  resetLive: (runId: string | null) => void;
  patchLive: (nodeId: string, patch: Partial<NodeLive>) => void;
  graph: () => WorkflowGraph;
}

const HISTORY = 100;
const snap = (s: Snapshot): Snapshot => ({ nodes: s.nodes, edges: s.edges, settings: s.settings });

export const useBuilder = create<BuilderState>((set, get) => ({
  workflowId: null, name: "", revision: 0, nodes: [], edges: [], settings: {}, selection: [], selectedEdge: null,
  past: [], future: [], lastCoalesce: null, clipboard: null, saveState: "saved", saveError: null, issues: [], live: {}, liveRunId: null,

  load: (id, name, revision, g) => set({
    workflowId: id, name, revision, nodes: g.nodes, edges: g.edges, settings: g.settings || {}, past: [], future: [],
    selection: [], selectedEdge: null, saveState: "saved", saveError: null, live: {}, liveRunId: null, lastCoalesce: null,
  }),

  commit: (fn, coalesceKey) => set((s) => {
    const now = Date.now();
    const coalesce = coalesceKey && s.lastCoalesce?.key === coalesceKey && now - s.lastCoalesce.at < 1200;
    const next = fn(snap(s));
    return {
      ...next,
      past: coalesce ? s.past : [...s.past.slice(-HISTORY + 1), snap(s)],
      future: [],
      lastCoalesce: coalesceKey ? { key: coalesceKey, at: now } : null,
      saveState: s.saveState === "conflict" ? "conflict" : "dirty",
    };
  }),

  // Dragging updates positions without a history entry per frame; the drag-start commit captures undo.
  setPositions: (pos) => set((s) => ({
    nodes: s.nodes.map((n) => (pos[n.id] ? { ...n, position: pos[n.id] } : n)),
    saveState: s.saveState === "conflict" ? "conflict" : "dirty",
  })),

  addNode: (type, position, overrides) => {
    const node = makeNode(type, position, get().nodes, overrides);
    get().commit((s) => ({ nodes: [...s.nodes, node] }));
    set({ selection: [node.id], selectedEdge: null });
    return node;
  },

  updateNode: (id, patch, key) => get().commit((s) => ({ nodes: s.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)) }), key),

  updateConfig: (id, patch, key) => get().commit((s) => ({
    nodes: s.nodes.map((n) => (n.id === id ? { ...n, config: { ...n.config, ...patch } } : n)),
  }), key),

  updateHarness: (id, patch, key) => get().commit((s) => ({
    nodes: s.nodes.map((n) => (n.id === id ? { ...n, harness: { ...(n.harness || {}), ...patch } } : n)),
  }), key),

  setContract: (id, contract, key) => get().commit((s) => ({ nodes: s.nodes.map((n) => (n.id === id ? { ...n, contract } : n)) }), key),

  connect: (e) => get().commit((s) => ({ edges: [...s.edges, { ...e, id: uid("e") }] })),

  removeEdges: (ids) => get().commit((s) => ({ edges: s.edges.filter((e) => !ids.includes(e.id)) })),

  removeSelected: () => {
    const { selection, selectedEdge } = get();
    if (!selection.length && !selectedEdge) return;
    get().commit((s) => ({
      nodes: s.nodes.filter((n) => !selection.includes(n.id)),
      edges: s.edges.filter((e) => e.id !== selectedEdge && !selection.includes(e.source) && !selection.includes(e.target)),
    }));
    set({ selection: [], selectedEdge: null });
  },

  copy: () => {
    const { nodes, edges, selection } = get();
    const picked = nodes.filter((n) => selection.includes(n.id));
    if (!picked.length) return;
    set({ clipboard: { nodes: picked, edges: edges.filter((e) => selection.includes(e.source) && selection.includes(e.target)) } });
  },

  paste: () => {
    const clip = get().clipboard;
    if (!clip) return;
    const idMap: Record<string, string> = {};
    let all = [...get().nodes];
    const newNodes = clip.nodes.map((n) => {
      const id = uid("n");
      idMap[n.id] = id;
      const key = uniqueKey(n.key, all);
      const copy = { ...n, id, key, name: n.name, position: { x: n.position.x + 40, y: n.position.y + 40 }, config: structuredClone(n.config) };
      all = [...all, copy];
      return copy;
    });
    const newEdges = clip.edges.map((e) => ({ ...e, id: uid("e"), source: idMap[e.source], target: idMap[e.target] }));
    get().commit((s) => ({ nodes: [...s.nodes, ...newNodes], edges: [...s.edges, ...newEdges] }));
    set({ selection: newNodes.map((n) => n.id), clipboard: { nodes: newNodes, edges: newEdges } });
  },

  duplicateSelected: () => { get().copy(); get().paste(); },

  select: (ids, edge = null) => set({ selection: ids, selectedEdge: edge }),

  undo: () => set((s) => {
    if (!s.past.length) return s;
    const prev = s.past[s.past.length - 1];
    return { ...prev, past: s.past.slice(0, -1), future: [snap(s), ...s.future], saveState: "dirty", lastCoalesce: null };
  }),

  redo: () => set((s) => {
    if (!s.future.length) return s;
    const [next, ...rest] = s.future;
    return { ...next, past: [...s.past, snap(s)], future: rest, saveState: "dirty", lastCoalesce: null };
  }),

  layout: () => get().commit((s) => ({ nodes: autoLayout(s.nodes, s.edges) })),

  replaceGraph: (g) => get().commit(() => ({ nodes: g.nodes, edges: g.edges, settings: g.settings || {} })),

  setSettings: (patch) => get().commit((s) => ({ settings: { ...s.settings, ...patch } }), "settings"),

  setName: (name) => set({ name, saveState: "dirty" }),

  setSave: (saveState, saveError = null, revision) => set((s) => ({ saveState, saveError, revision: revision ?? s.revision })),

  setIssues: (issues) => set({ issues }),

  resetLive: (runId) => set({ live: {}, liveRunId: runId }),

  patchLive: (nodeId, patch) => set((s) => ({ live: { ...s.live, [nodeId]: { ...(s.live[nodeId] || { status: "queued" }), ...patch } } })),

  graph: () => {
    const s = get();
    return { schema_version: "2.0", nodes: s.nodes, edges: s.edges, settings: s.settings };
  },
}));
