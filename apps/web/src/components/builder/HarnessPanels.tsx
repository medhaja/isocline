"use client";
import clsx from "clsx";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Code, Empty, ErrorBox, Field, Icon, Input, Select, Spinner, StatusBadge, Textarea, Toggle, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useWorkspace } from "@/lib/session";
import type { Contract, Harness, WFNode } from "@/lib/types";
import { useBuilder } from "@/store/builder";
import { routes } from "@/lib/routes";

const CAPS = ["vision", "tool_calling", "structured_output", "reasoning", "large_context", "coding"];
const BUILTIN = ["Any", "Text", "Number", "Boolean", "JSON", "Table", "File", "Image", "Audio", "Video", "Document", "Message", "Message[]", "Artifact", "Error"];
const ERRORS = ["any", "rate_limit", "timeout", "unavailable", "model_unavailable", "structured_output", "context_limit", "tool_error", "contract_violation"];
const ACTIONS = ["retry", "fallback", "switch_provider", "repair", "reduce_context", "route_error", "human", "degrade", "fail"];
const ACTION_LABEL: Record<string, string> = { retry: "Retry", fallback: "Fallback model", switch_provider: "Switch provider", repair: "Repair output",
  reduce_context: "Reduce context", route_error: "Error branch", human: "Ask a human", degrade: "Continue degraded", fail: "Fail" };

export function useTypes() {
  const { workspace } = useWorkspace();
  return useQuery({ queryKey: ["types", workspace?.id], enabled: !!workspace, queryFn: () => api<{ builtin: string[]; custom: any[] }>(`/workspaces/${workspace!.id}/types`) });
}

function TypeSelect({ value, onChange, ariaLabel }: { value: string; onChange: (v: string) => void; ariaLabel: string }) {
  const types = useTypes();
  const custom = (types.data?.custom || []).map((t) => t.name);
  const known = [...BUILTIN, ...custom.map((c) => `JSON<${c}>`)];
  return (
    <Select aria-label={ariaLabel} value={known.includes(value) ? value : "__custom"} onChange={(e) => onChange(e.target.value === "__custom" ? value : e.target.value)}>
      {BUILTIN.map((t) => <option key={t} value={t}>{t}</option>)}
      {custom.length > 0 && <optgroup label="Custom types">{custom.map((c) => <option key={c} value={`JSON<${c}>`}>{`JSON<${c}>`}</option>)}</optgroup>}
      {!known.includes(value) && <option value="__custom">{value}</option>}
    </Select>
  );
}

const emptyContract = (): Contract => ({ inputs: [], output: { name: "out", type: "Any" }, capabilities: [], side_effects: "none", max_cost: null, timeout_seconds: null });

export function ContractPanel({ node }: { node: WFNode }) {
  const { setContract } = useBuilder();
  const c = node.contract;
  const set = (patch: Partial<Contract>) => setContract(node.id, { ...(c || emptyContract()), ...patch }, `${node.id}:contract`);
  if (!c) {
    return (
      <div className="space-y-3 p-4">
        <p className="text-xs leading-relaxed text-ink-500">A contract declares what this node accepts and produces, which model capabilities it needs and what it may cost.
          Connections are type-checked before a run and outputs are checked at runtime. Without a contract, ports are <code className="font-mono">Any</code>.</p>
        <Button size="sm" icon="FileCheck2" onClick={() => setContract(node.id, emptyContract())}>Add a contract</Button>
      </div>
    );
  }
  return (
    <div className="space-y-4 p-4 text-sm">
      <div>
        <div className="mb-1.5 flex items-center justify-between"><span className="text-xs font-medium text-ink-700">Input ports</span>
          <Button size="sm" variant="ghost" icon="Plus" onClick={() => set({ inputs: [...c.inputs, { name: c.inputs.length ? `in_${c.inputs.length + 1}` : "in", type: "Any", required: true }] })}>Port</Button></div>
        {!c.inputs.length && <p className="text-2xs text-ink-400">No declared inputs (anything connected is accepted).</p>}
        <div className="space-y-1.5">
          {c.inputs.map((p, i) => (
            <div key={i} className="grid grid-cols-[1fr_1.2fr_auto_auto] items-center gap-1.5">
              <Input className="font-mono text-xs" value={p.name} aria-label="Port name"
                onChange={(e) => set({ inputs: c.inputs.map((x, k) => (k === i ? { ...x, name: e.target.value.replace(/[^a-z0-9_]/g, "") } : x)) })} />
              <TypeSelect ariaLabel="Port type" value={p.type} onChange={(t) => set({ inputs: c.inputs.map((x, k) => (k === i ? { ...x, type: t } : x)) })} />
              <label className="flex items-center gap-1 text-2xs text-ink-500"><input type="checkbox" checked={p.required !== false}
                onChange={(e) => set({ inputs: c.inputs.map((x, k) => (k === i ? { ...x, required: e.target.checked } : x)) })} />req.</label>
              <button aria-label="Remove port" className="text-ink-400 hover:text-state-failed" onClick={() => set({ inputs: c.inputs.filter((_, k) => k !== i) })}><Icon name="X" size={14} /></button>
            </div>
          ))}
        </div>
        {c.inputs.length > 1 && <p className="mt-1 text-2xs text-ink-400">With several ports, pick the port on each incoming connection (select the connection).</p>}
      </div>
      <Field label="Output type"><TypeSelect ariaLabel="Output type" value={c.output.type} onChange={(t) => set({ output: { ...c.output, type: t } })} /></Field>
      {node.type === "agent" && (
        <Field label="Required model capabilities" hint="Only models with these capabilities can run this agent (AUTO filters by them).">
          <div className="flex flex-wrap gap-1.5">
            {CAPS.map((cap) => (
              <button key={cap} onClick={() => set({ capabilities: c.capabilities.includes(cap) ? c.capabilities.filter((x) => x !== cap) : [...c.capabilities, cap] })}
                className={clsx("rounded-full border px-2 py-0.5 text-xs", c.capabilities.includes(cap) ? "border-accent-500 bg-accent-50 text-accent-700" : "border-line text-ink-600 hover:border-ink-300")}>
                {cap.replace("_", " ")}</button>
            ))}
          </div>
        </Field>
      )}
      <div className="grid grid-cols-2 gap-2">
        <Field label="Side effects"><Select value={c.side_effects} onChange={(e) => set({ side_effects: e.target.value as Contract["side_effects"] })}>
          <option value="none">None</option><option value="read">Reads external data</option><option value="write">Writes internal data</option><option value="external_write">Writes to external systems</option></Select></Field>
        <Field label="Min context (tokens)"><Input type="number" value={c.min_context_tokens ?? ""} onChange={(e) => set({ min_context_tokens: e.target.value ? +e.target.value : null })} /></Field>
        <Field label="Max cost (USD)"><Input type="number" step="0.01" value={c.max_cost ?? ""} onChange={(e) => set({ max_cost: e.target.value ? +e.target.value : null })} /></Field>
        <Field label="Timeout (s)"><Input type="number" value={c.timeout_seconds ?? ""} onChange={(e) => set({ timeout_seconds: e.target.value ? +e.target.value : null })} /></Field>
      </div>
      {node.type === "agent" && (
        <Toggle checked={c.allowed_tools != null} onChange={(v) => set({ allowed_tools: v ? (node.config.tools || []) : null })}
          label="Lock the tool list" hint={c.allowed_tools ? `Only ${c.allowed_tools.join(", ") || "no tools"} may ever be granted` : "Tools can be granted freely in Configure"} />
      )}
      <p className="text-2xs text-ink-400">Side effects other than “None” exclude this node from caching. Define reusable JSON types under Settings → Types.</p>
      <Button size="sm" variant="ghost" icon="Trash2" onClick={() => setContract(node.id, null)}>Remove contract</Button>
    </div>
  );
}

export function ContextPanel({ node, workflowId }: { node: WFNode; workflowId: string }) {
  const { graph } = useBuilder();
  const [mocks, setMocks] = useState("");
  const q = useQuery({
    queryKey: ["ctx-preview", workflowId, node.id, JSON.stringify(node.config), mocks], retry: false,
    queryFn: () => api<any>(`/workflows/${workflowId}/nodes/${node.id}/context-preview`, { body: { graph: graph(), mocks: safe(mocks) } }),
  });
  const { updateConfig } = useBuilder();
  const ctx = node.config.context || {};
  const setCtx = (patch: any) => updateConfig(node.id, { context: { ...ctx, ...patch } }, `${node.id}:ctx`);
  const src = (cat: string) => (ctx.sources || {})[cat] || {};
  const setSrc = (cat: string, patch: any) => setCtx({ sources: { ...(ctx.sources || {}), [cat]: { ...src(cat), ...patch } } });
  const d = q.data;
  const max = d ? Math.max(...(d.categories || []).map((c: any) => c.tokens_before || c.tokens || 1), 1) : 1;
  return (
    <div className="space-y-4 p-4 text-sm">
      <div className="rounded-lg border border-line p-3">
        <div className="mb-2 flex items-center justify-between"><span className="text-xs font-semibold text-ink-800">Model context preview</span>
          <button className="text-xs text-accent-600" onClick={() => q.refetch()}>Refresh</button></div>
        {q.isLoading ? <Spinner /> : q.error ? <ErrorBox error={q.error} /> : d && (
          <>
            <ul className="space-y-1.5">
              {(d.categories || []).filter((c: any) => c.tokens || c.tokens_after).map((c: any, i: number) => (
                <li key={i}>
                  <div className="flex justify-between text-xs"><span className="text-ink-700">{c.label}</span>
                    <span className="tabular-nums text-ink-500">{(c.tokens_after ?? c.tokens).toLocaleString()}{c.action !== "kept" && <span className="ml-1 text-warn">{c.action}</span>}</span></div>
                  <div className="mt-0.5 h-1.5 rounded-full bg-canvas"><div className="h-1.5 rounded-full bg-accent-500" style={{ width: `${((c.tokens_after ?? c.tokens) / max) * 100}%` }} /></div>
                </li>
              ))}
            </ul>
            <div className="mt-3 flex justify-between border-t border-line pt-2 text-xs font-medium"><span>Estimated total</span>
              <span className="tabular-nums">{(d.total_tokens || 0).toLocaleString()}{d.budget ? ` / ${d.budget.toLocaleString()} budget` : ""}</span></div>
            {d.over_budget && <p className="mt-2 text-2xs text-state-failed">{d.over_budget}</p>}
            <p className="mt-2 text-2xs text-ink-400">Upstream values: {Object.entries(d.upstream_sources || {}).map(([k, v]) => `${k} (${v})`).join(", ") || "none"}. {d.note}</p>
          </>
        )}
      </div>
      <Field label="Context budget (tokens)" hint="Lower-priority sources are reduced first when the estimate exceeds the budget.">
        <Input type="number" value={ctx.max_context_tokens ?? ""} placeholder="From the model's window" onChange={(e) => setCtx({ max_context_tokens: e.target.value ? +e.target.value : null })} />
      </Field>
      <div>
        <div className="mb-1 text-xs font-medium text-ink-700">Sources, highest priority first</div>
        <ul className="space-y-1">
          {(ctx.priority || ["system", "instructions", "user_input", "upstream", "knowledge", "artifacts", "memory", "history"]).map((cat: string, i: number, arr: string[]) => (
            <li key={cat} className="grid grid-cols-[18px_1fr_110px_70px] items-center gap-1.5">
              <span className="text-2xs tabular-nums text-ink-400">{i + 1}</span>
              <span className="flex items-center gap-1 text-xs">{cat.replace("_", " ")}
                {i > 0 && cat !== "system" && <button aria-label="Move up" className="text-ink-300 hover:text-ink-700" onClick={() => { const n = [...arr]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; setCtx({ priority: n }); }}><Icon name="ArrowUp" size={12} /></button>}</span>
              {cat === "system" ? <span className="text-2xs text-ink-400">never reduced</span> : (
                <Select aria-label={`${cat} strategy`} className="h-7 text-xs" value={src(cat).strategy || "truncate"} onChange={(e) => setSrc(cat, { strategy: e.target.value })}>
                  <option value="keep">Keep</option><option value="truncate">Truncate</option><option value="extract">Extract relevant</option><option value="summarize">Summarize</option><option value="drop">Drop</option></Select>)}
              {cat !== "system" && <Input aria-label={`${cat} max tokens`} className="h-7 text-xs" type="number" placeholder="max" value={src(cat).max_tokens ?? ""} onChange={(e) => setSrc(cat, { max_tokens: e.target.value ? +e.target.value : null })} />}
            </li>
          ))}
        </ul>
        <p className="mt-1 text-2xs text-ink-400">Summarize makes an extra model call (counted in the run budget). Every reduction is recorded in the node trace.</p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Retrieved passages"><Input type="number" min={0} max={50} value={ctx.retrieval_top_k ?? 5} onChange={(e) => setCtx({ retrieval_top_k: +e.target.value })} /></Field>
        <Field label="History window"><Input type="number" min={0} value={ctx.history_window ?? 10} onChange={(e) => setCtx({ history_window: +e.target.value })} /></Field>
      </div>
      <Field label="Artifacts" hint="Artifacts never enter prompts as bytes unless you choose extraction.">
        <Select value={ctx.artifact_mode || "reference"} onChange={(e) => setCtx({ artifact_mode: e.target.value })}>
          <option value="reference">Reference only (name, type, size)</option><option value="extract">Extract text (bounded)</option></Select>
      </Field>
      <Field label="Mock upstream values for the preview (JSON)"><Textarea mono rows={3} value={mocks} onChange={(e) => setMocks(e.target.value)} placeholder='{"research": "…"}' /></Field>
    </div>
  );
}

function safe(s: string) { try { return s ? JSON.parse(s) : {}; } catch { return {}; } }

export function HarnessPanel({ node }: { node: WFNode }) {
  const { updateHarness } = useBuilder();
  const h: Harness = node.harness || {};
  const set = (patch: Partial<Harness>, k?: string) => updateHarness(node.id, patch, k ? `${node.id}:h:${k}` : undefined);
  const cache = h.cache || { mode: "disabled" };
  const sla = h.sla || {};
  const rules = h.recovery || [];
  const cacheable = ["agent", "tool_web_search", "tool_python", "tool_calculator", "tool_json", "tool_vector_search", "tool_file_reader", "tool_http"].includes(node.type);
  return (
    <div className="space-y-5 p-4 text-sm">
      {cacheable && (
        <section className="space-y-2">
          <h4 className="text-xs font-semibold text-ink-800">Cache</h4>
          <div className="grid grid-cols-3 gap-1 rounded-md bg-canvas p-1">
            {(["disabled", "exact", "semantic"] as const).map((m) => (
              <button key={m} onClick={() => set({ cache: { ...cache, mode: m } })} className={clsx("rounded px-2 py-1 text-xs capitalize", cache.mode === m ? "bg-paper font-medium shadow-card" : "text-ink-500")}>{m}</button>
            ))}
          </div>
          {cache.mode !== "disabled" && (
            <div className="grid grid-cols-2 gap-2">
              <Field label="Keep for (hours)"><Input type="number" min={1} value={Math.round((cache.ttl_seconds ?? 86400) / 3600)} onChange={(e) => set({ cache: { ...cache, ttl_seconds: Math.max(1, +e.target.value) * 3600 } }, "ttl")} /></Field>
              {cache.mode === "semantic" && <Field label="Similarity ≥"><Input type="number" step="0.01" min={0.5} max={1} value={cache.similarity_threshold ?? 0.95} onChange={(e) => set({ cache: { ...cache, similarity_threshold: +e.target.value } }, "sim")} /></Field>}
            </div>
          )}
          <p className="text-2xs text-ink-400">{cache.mode === "exact" ? "Reuses a result only when the full input, prompt, model, tools and knowledge are identical." : cache.mode === "semantic" ? "Reuses results for similar requests under an identical configuration. Opt-in; review for correctness." : "Every run executes this node."} Side-effecting nodes are never cached.</p>
        </section>
      )}
      <section className="space-y-2">
        <h4 className="text-xs font-semibold text-ink-800">Service level</h4>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Max latency (ms)"><Input type="number" value={sla.max_latency_ms ?? ""} onChange={(e) => set({ sla: { ...sla, max_latency_ms: e.target.value ? +e.target.value : null } }, "lat")} /></Field>
          <Field label="Max cost (USD)"><Input type="number" step="0.001" value={sla.max_cost ?? ""} onChange={(e) => set({ sla: { ...sla, max_cost: e.target.value ? +e.target.value : null } }, "cost")} /></Field>
          <Field label="Max tokens"><Input type="number" value={sla.max_tokens ?? ""} onChange={(e) => set({ sla: { ...sla, max_tokens: e.target.value ? +e.target.value : null } }, "tok")} /></Field>
          <Field label="Max attempts"><Input type="number" value={sla.max_attempts ?? ""} onChange={(e) => set({ sla: { ...sla, max_attempts: e.target.value ? +e.target.value : null } }, "att")} /></Field>
        </div>
        <Field label="When breached"><Select value={sla.on_breach || "fail"} onChange={(e) => set({ sla: { ...sla, on_breach: e.target.value } })}>
          <option value="fail">Fail the node</option><option value="fallback">Try the fallback model</option><option value="degrade">Continue, flagged as degraded</option><option value="alert">Continue and raise an alert</option></Select></Field>
      </section>
      <section className="space-y-2">
        <div className="flex items-center justify-between"><h4 className="text-xs font-semibold text-ink-800">Recovery rules</h4>
          <Button size="sm" variant="ghost" icon="Plus" onClick={() => set({ recovery: [...rules, { when: ["rate_limit"], actions: ["fallback"] }] })}>Rule</Button></div>
        {!rules.length && <p className="text-2xs text-ink-400">Without rules: retry transient errors (see Reliability in Configure), then fail.</p>}
        {rules.map((r, i) => (
          <div key={i} className="space-y-1.5 rounded-md border border-line p-2.5">
            <div className="flex items-center gap-1.5 text-xs">
              <span className="text-ink-500">When</span>
              <Select aria-label="Error kind" className="h-7 flex-1 text-xs" value={r.attempts_gte ? "__attempts" : r.when[0]} onChange={(e) => {
                const v = e.target.value;
                set({ recovery: rules.map((x, k) => (k === i ? (v === "__attempts" ? { ...x, when: ["any"], attempts_gte: 3 } : { ...x, when: [v], attempts_gte: null }) : x)) });
              }}>{ERRORS.map((x) => <option key={x} value={x}>{x === "any" ? "any error" : x.replace(/_/g, " ")}</option>)}<option value="__attempts">attempts reach…</option></Select>
              {r.attempts_gte ? <Input aria-label="Attempts" className="h-7 w-14 text-xs" type="number" min={1} value={r.attempts_gte}
                onChange={(e) => set({ recovery: rules.map((x, k) => (k === i ? { ...x, attempts_gte: +e.target.value } : x)) })} /> : null}
              <button aria-label="Remove rule" className="text-ink-400 hover:text-state-failed" onClick={() => set({ recovery: rules.filter((_, k) => k !== i) })}><Icon name="X" size={14} /></button>
            </div>
            <div className="flex flex-wrap items-center gap-1 text-xs">
              <span className="text-ink-500">then</span>
              {r.actions.map((a, j) => (
                <span key={j} className="inline-flex items-center gap-1 rounded-full bg-canvas px-2 py-0.5">{j > 0 && <Icon name="ArrowRight" size={10} className="text-ink-400" />}{ACTION_LABEL[a]}
                  <button aria-label="Remove action" onClick={() => set({ recovery: rules.map((x, k) => (k === i ? { ...x, actions: x.actions.filter((_, m) => m !== j) } : x)) })}><Icon name="X" size={10} /></button></span>
              ))}
              <select aria-label="Add action" className="h-6 rounded border border-line bg-paper text-2xs" value="" onChange={(e) => e.target.value && set({ recovery: rules.map((x, k) => (k === i ? { ...x, actions: [...x.actions, e.target.value] } : x)) })}>
                <option value="">+ step</option>{ACTIONS.map((a) => <option key={a} value={a}>{ACTION_LABEL[a]}</option>)}</select>
            </div>
          </div>
        ))}
        <p className="text-2xs text-ink-400">“Ask a human” pauses the run durably; approving retries the node, rejecting fails it.</p>
      </section>
      <section className="space-y-2">
        <h4 className="text-xs font-semibold text-ink-800">Durability</h4>
        <Toggle checked={!!h.checkpoint} onChange={(v) => set({ checkpoint: v })} label="Checkpoint after this node" hint="Checkpoints are also created automatically after expensive agents, before approvals and before side effects." />
        <Field label="Resource class"><Select value={h.resource_class || "standard"} onChange={(e) => set({ resource_class: e.target.value })}>
          {["standard", "cpu_heavy", "memory_heavy", "sandbox", "long_running"].map((r) => <option key={r} value={r}>{r.replace("_", " ")}</option>)}</Select></Field>
      </section>
      {node.type.startsWith("tool_") && (
        <section className="space-y-2">
          <h4 className="text-xs font-semibold text-ink-800">Compensation</h4>
          {h.compensation ? (
            <>
              <p className="text-2xs text-ink-400">An HTTP request that undoes this node's side effect. Runs only when the workflow enables automatic compensation, or when someone triggers it on the run page. Use {"{{this.output…}}"} for values from this node's result.</p>
              <div className="grid grid-cols-[90px_1fr] gap-2">
                <Select value={h.compensation.arguments.method || "DELETE"} onChange={(e) => set({ compensation: { ...h.compensation!, arguments: { ...h.compensation!.arguments, method: e.target.value } } })}>
                  {["DELETE", "POST", "PUT", "PATCH"].map((m) => <option key={m}>{m}</option>)}</Select>
                <Input className="font-mono text-xs" value={h.compensation.arguments.url || ""} placeholder="https://api.example.com/items/{{this.output.body.id}}"
                  onChange={(e) => set({ compensation: { ...h.compensation!, arguments: { ...h.compensation!.arguments, url: e.target.value } } }, "comp")} />
              </div>
              <Button size="sm" variant="ghost" onClick={() => set({ compensation: null })}>Remove compensation</Button>
            </>
          ) : <Button size="sm" icon="Undo2" onClick={() => set({ compensation: { tool: "http_request", arguments: { method: "DELETE", url: "" } } })}>Add compensating action</Button>}
        </section>
      )}
    </div>
  );
}

export function TestsPanel({ node, workflowId }: { node: WFNode; workflowId: string }) {
  const qc = useQueryClient();
  const tests = useQuery({ queryKey: ["tests", workflowId], queryFn: () => api<any[]>(`/workflows/${workflowId}/tests`), refetchInterval: (q) => (q.state.data?.some((t: any) => t.last_status === "running") ? 2000 : false) });
  const mine = (tests.data || []).filter((t) => t.node_id === node.id);
  const { graph, nodes, edges } = useBuilder();
  const ups = edges.filter((e) => e.target === node.id).map((e) => nodes.find((n) => n.id === e.source)).filter(Boolean) as WFNode[];
  const [mocks, setMocks] = useState(() => JSON.stringify(Object.fromEntries(ups.filter((u) => !u.type.startsWith("input_")).map((u) => [u.key, "…"])), null, 2));
  const [input, setInput] = useState("{}");
  const [runId, setRunId] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const run = useQuery({ queryKey: ["pg-run", runId], enabled: !!runId, queryFn: () => api<any>(`/runs/${runId}`),
    refetchInterval: (q) => (["completed", "failed", "cancelled", "waiting"].includes(q.state.data?.status) ? false : 1000) });
  const nodesQ = useQuery({ queryKey: ["pg-nodes", runId, run.data?.status], enabled: !!runId && ["completed", "failed"].includes(run.data?.status),
    queryFn: () => api<any[]>(`/runs/${runId}/nodes`) });
  const out = nodesQ.data?.find((n) => n.node_id === node.id);
  const [assert, setAssert] = useState({ path: "", op: "exists", value: "" });

  async function play() {
    setErr(null);
    try { setRunId((await api<{ run_id: string }>(`/workflows/${workflowId}/nodes/${node.id}/playground`, { body: { input: JSON.parse(input || "{}"), mocks: JSON.parse(mocks || "{}"), graph: graph() } })).run_id); }
    catch (e) { setErr(e instanceof SyntaxError ? new Error("Mocks and input must be valid JSON") : e); }
  }
  async function saveTest() {
    const name = prompt("Name this test", `${node.name} contract`);
    if (!name) return;
    const assertions: any[] = [{ type: node.contract ? "schema_valid" : "not_empty" }];
    if (assert.path || assert.op !== "exists") assertions.push({ path: assert.path, op: assert.op, value: assert.op === "between" ? assert.value.split(",").map(Number) : isNaN(+assert.value) ? assert.value : +assert.value });
    try {
      await api(`/workflows/${workflowId}/tests`, { body: { node_id: node.id, name, run_input: JSON.parse(input || "{}"), mocks: JSON.parse(mocks || "{}"), assertions } });
      qc.invalidateQueries({ queryKey: ["tests", workflowId] }); toast("Contract test saved");
    } catch (e) { toast(errorMessage(e), "error"); }
  }
  async function runAll() {
    try { await api(`/workflows/${workflowId}/tests/run`, { method: "POST" }); qc.invalidateQueries({ queryKey: ["tests", workflowId] }); toast("Running contract tests", "info"); }
    catch (e) { toast(errorMessage(e), "error"); }
  }
  return (
    <div className="space-y-4 p-4 text-sm">
      <section className="space-y-2">
        <h4 className="text-xs font-semibold text-ink-800">Playground</h4>
        <p className="text-2xs text-ink-400">Run only this {node.type === "subworkflow" ? "sub-workflow" : "component"} with mocked upstream values. Unmocked upstream nodes execute normally.</p>
        <Field label="Mock upstream outputs (by node key)"><Textarea mono rows={4} value={mocks} onChange={(e) => setMocks(e.target.value)} /></Field>
        <Field label="Run input"><Textarea mono rows={2} value={input} onChange={(e) => setInput(e.target.value)} /></Field>
        <ErrorBox error={err} />
        <Button size="sm" variant="primary" icon="Play" onClick={play}>Run component</Button>
        {runId && (
          <div className="space-y-2 rounded-md border border-line p-2.5">
            <div className="flex items-center justify-between text-xs"><StatusBadge status={run.data?.status || "queued"} />
              <Link className="text-accent-600" href={routes.run(runId)}>Open run</Link></div>
            {out && <Code value={out.output ?? out.error} maxH="max-h-48" />}
          </div>
        )}
      </section>
      <section className="space-y-2">
        <div className="flex items-center justify-between"><h4 className="text-xs font-semibold text-ink-800">Contract tests</h4>
          {!!tests.data?.length && <Button size="sm" variant="ghost" icon="Play" onClick={runAll}>Run all</Button>}</div>
        <p className="text-2xs text-ink-400">Tests run against the current draft and must pass before this workflow can be published.</p>
        <div className="grid grid-cols-[1fr_90px_1fr] gap-1.5">
          <Input className="h-8 font-mono text-xs" placeholder="output path, e.g. risk_score" value={assert.path} onChange={(e) => setAssert({ ...assert, path: e.target.value })} />
          <Select className="h-8 text-xs" value={assert.op} onChange={(e) => setAssert({ ...assert, op: e.target.value })}>{["exists", "==", "contains", ">", "<", "between"].map((o) => <option key={o}>{o}</option>)}</Select>
          <Input className="h-8 text-xs" placeholder={assert.op === "between" ? "0,1" : "value"} value={assert.value} onChange={(e) => setAssert({ ...assert, value: e.target.value })} />
        </div>
        <Button size="sm" icon="FlaskConical" onClick={saveTest}>Save as contract test</Button>
        {tests.isLoading ? <Spinner /> : !mine.length ? <p className="text-2xs text-ink-400">No tests for this node yet.</p> : (
          <ul className="space-y-1.5">
            {mine.map((t) => (
              <li key={t.id} className="rounded-md border border-line p-2 text-xs">
                <div className="flex items-center justify-between"><span className="font-medium">{t.name}</span>
                  <span className="flex items-center gap-1.5">{!t.current && t.last_status && <Badge tone="warn">stale</Badge>}<StatusBadge status={t.last_status || "queued"} /></span></div>
                {(t.last_details || []).map((d: any, i: number) => <div key={i} className={d.passed ? "text-state-completed" : "text-state-failed"}>{d.passed ? "✓" : "✗"} {d.assertion}{d.detail ? ` — ${d.detail}` : ""}</div>)}
                <button className="mt-1 text-2xs text-state-failed" onClick={async () => { await api(`/tests/${t.id}`, { method: "DELETE" }); qc.invalidateQueries({ queryKey: ["tests", workflowId] }); }}>Delete</button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
