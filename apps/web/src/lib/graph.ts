import dagre from "@dagrejs/dagre";
import { SPEC, hasTarget, isExecutable, sourceHandles } from "./nodes";
import type { NodeType, WFEdge, WFNode, WorkflowGraph } from "./types";

const RESERVED = new Set(["input", "vars", "loop", "memory", "run", "upstream", "env", "secrets"]);

export const uid = (p: string) => `${p}_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36).slice(-3)}`;

export function slugKey(s: string) {
  let k = s.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "node";
  if (!/^[a-z]/.test(k)) k = "n_" + k;
  if (RESERVED.has(k)) k += "_node";
  return k;
}

export function uniqueKey(base: string, nodes: WFNode[], except?: string) {
  const taken = new Set(nodes.filter((n) => n.id !== except).map((n) => n.key));
  let k = slugKey(base), i = 2;
  const root = k;
  while (taken.has(k)) k = `${root}_${i++}`;
  return k;
}

export function keyError(key: string, nodes: WFNode[], selfId: string): string | null {
  if (!/^[a-z][a-z0-9_]{0,47}$/.test(key)) return "Use lowercase letters, digits and underscores, starting with a letter";
  if (RESERVED.has(key)) return `"${key}" is reserved`;
  if (nodes.some((n) => n.key === key && n.id !== selfId)) return "Another node already uses this key";
  return null;
}

export function makeNode(type: NodeType, position: { x: number; y: number }, nodes: WFNode[], overrides: Partial<WFNode> = {}): WFNode {
  const spec = SPEC[type];
  return {
    id: uid("n"),
    key: uniqueKey(overrides.name ? slugKey(overrides.name) : spec.defaultKey, nodes),
    type, name: overrides.name || spec.label, position, config: spec.defaults(), ...overrides,
  };
}

/** Would adding this edge create a cycle? (loops are expressed with loop nodes, never cycles) */
export function createsCycle(edges: WFEdge[], source: string, target: string) {
  const out = new Map<string, string[]>();
  for (const e of edges) out.set(e.source, [...(out.get(e.source) || []), e.target]);
  const stack = [target];
  const seen = new Set<string>();
  while (stack.length) {
    const n = stack.pop()!;
    if (n === source) return true;
    if (seen.has(n)) continue;
    seen.add(n);
    stack.push(...(out.get(n) || []));
  }
  return false;
}

export function connectionError(g: { nodes: WFNode[]; edges: WFEdge[] }, source: string, target: string, handle: string | null): string | null {
  if (source === target) return "A node can't connect to itself";
  const s = g.nodes.find((n) => n.id === source), t = g.nodes.find((n) => n.id === target);
  if (!s || !t) return "Unknown node";
  if (!isExecutable(s.type) || !isExecutable(t.type)) return "Notes and groups can't be connected";
  if (!hasTarget(t)) return `${SPEC[t.type].label} nodes can't have inputs`;
  if (!sourceHandles(s).some((h) => (h.id ?? null) === (handle ?? null))) return "That output doesn't exist on this node";
  if (g.edges.some((e) => e.source === source && e.target === target && (e.source_handle ?? null) === (handle ?? null))) return "Already connected";
  if (createsCycle(g.edges, source, target)) return "That would create a cycle. Use a Loop node for repetition.";
  return null;
}

export function upstreamIds(edges: WFEdge[], nodeId: string): Set<string> {
  const inc = new Map<string, string[]>();
  for (const e of edges) inc.set(e.target, [...(inc.get(e.target) || []), e.source]);
  const seen = new Set<string>();
  const stack = [...(inc.get(nodeId) || [])];
  while (stack.length) {
    const n = stack.pop()!;
    if (seen.has(n)) continue;
    seen.add(n);
    stack.push(...(inc.get(n) || []));
  }
  return seen;
}

export interface VarSuggestion { expr: string; label: string; detail: string }

/** Variables a node may reference: run input fields, workflow variables, loop vars, and UPSTREAM node outputs only. */
export function variableSuggestions(g: WorkflowGraph, nodeId: string): VarSuggestion[] {
  const out: VarSuggestion[] = [];
  const ups = upstreamIds(g.edges, nodeId);
  for (const n of g.nodes) {
    if (n.type.startsWith("input_")) out.push({ expr: `{{input.${n.config.field || n.key}}}`, label: `input.${n.config.field || n.key}`, detail: `Run input (${n.name})` });
    if (n.type.startsWith("trigger_")) out.push({ expr: `{{${n.key}.output}}`, label: `${n.key}.output`, detail: "Trigger payload" });
    if (n.type === "wait_webhook") out.push({ expr: `{{run.callbacks.${n.key}}}`, label: `run.callbacks.${n.key}`, detail: `Callback URL that resumes ${n.name}` });
  }
  for (const k of Object.keys(g.settings.variables || {})) out.push({ expr: `{{vars.${k}}}`, label: `vars.${k}`, detail: "Workflow variable" });
  const inLoop = g.edges.some((e) => e.target === nodeId && e.source_handle === "body") || [...ups].some((u) => g.nodes.find((n) => n.id === u && (n.type === "loop" || n.type === "retry")));
  if (inLoop) {
    out.push({ expr: "{{loop.item}}", label: "loop.item", detail: "Current loop item" }, { expr: "{{loop.index}}", label: "loop.index", detail: "Iteration number (0-based)" },
      { expr: "{{loop.previous}}", label: "loop.previous", detail: "Previous iteration result" });
  }
  for (const n of g.nodes) {
    if (!ups.has(n.id) || n.type.startsWith("input_") || n.type.startsWith("trigger_") || !isExecutable(n.type)) continue;
    out.push({ expr: `{{${n.key}.output}}`, label: `${n.key}.output`, detail: `Output of ${n.name}` });
    const props = n.config?.output_schema && typeof n.config.output_schema === "object"
      ? Object.keys(n.config.output_schema.properties || n.config.output_schema) : [];
    for (const p of props) if (p !== "type" && p !== "properties" && p !== "required") out.push({ expr: `{{${n.key}.output.${p}}}`, label: `${n.key}.output.${p}`, detail: `Field of ${n.name}` });
    if (n.type === "human_approval") out.push({ expr: `{{${n.key}.output.content}}`, label: `${n.key}.output.content`, detail: "Approved (possibly edited) content" },
      { expr: `{{${n.key}.output.comment}}`, label: `${n.key}.output.comment`, detail: "Reviewer comment" });
  }
  return out;
}

/** Nodes referenced in {{…}} that are not upstream: surfaced inline before the server validator runs. */
export function badReferences(g: WorkflowGraph, node: WFNode): string[] {
  const text = JSON.stringify(node.config);
  const ups = upstreamIds(g.edges, node.id);
  const bad: string[] = [];
  for (const m of text.matchAll(/\{\{\s*([a-zA-Z_]\w*)/g)) {
    const head = m[1];
    if (["input", "vars", "loop", "memory", "run", "secret", "this"].includes(head)) continue;
    const ref = g.nodes.find((n) => n.key === head);
    if (!ref) bad.push(`{{${head}}} doesn't match any node`);
    else if (ref.id === node.id) bad.push(`{{${head}}} refers to this node itself`);
    else if (!ups.has(ref.id)) bad.push(`{{${head}}} is not upstream of this node`);
  }
  return [...new Set(bad)];
}

export function autoLayout(nodes: WFNode[], edges: WFEdge[]): WFNode[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 50, ranksep: 90, marginx: 40, marginy: 40 });
  g.setDefaultEdgeLabel(() => ({}));
  const exec = nodes.filter((n) => isExecutable(n.type));
  for (const n of exec) g.setNode(n.id, { width: 240, height: n.type === "agent" ? 112 : 76 });
  for (const e of edges) if (g.hasNode(e.source) && g.hasNode(e.target)) g.setEdge(e.source, e.target);
  dagre.layout(g);
  return nodes.map((n) => {
    if (!isExecutable(n.type)) return n;
    const p = g.node(n.id);
    return p ? { ...n, position: { x: Math.round(p.x - p.width / 2), y: Math.round(p.y - p.height / 2) } } : n;
  });
}

export const emptyGraph = (): WorkflowGraph => ({ schema_version: "2.0", nodes: [], edges: [], settings: {} });
