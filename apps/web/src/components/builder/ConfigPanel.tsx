"use client";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ModelPicker, useModels } from "@/components/common";
import { Badge, Button, Field, Icon, Input, Select, Textarea, Toggle, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { badReferences, keyError, variableSuggestions } from "@/lib/graph";
import { CATEGORY_TINT, SPEC } from "@/lib/nodes";
import { useWorkspace } from "@/lib/session";
import type { Issue, ModelRef, WFNode } from "@/lib/types";
import { useBuilder } from "@/store/builder";
import { ContextPanel, ContractPanel, HarnessPanel, TestsPanel } from "./HarnessPanels";
import VarInput, { VarChips } from "./VarInput";

const OPERATORS = ["==", "!=", ">", ">=", "<", "<=", "contains", "exists", "not_exists"];
const TOOLS = [
  { id: "web_search", label: "Web search" }, { id: "http_request", label: "HTTP request" }, { id: "python", label: "Python sandbox" },
  { id: "calculator", label: "Calculator" }, { id: "file_reader", label: "File reader" }, { id: "json_processor", label: "JSON processor" },
  { id: "vector_search", label: "Knowledge search" },
];
const PARAM_META: Record<string, { label: string; min?: number; max?: number; step?: number; hint?: string }> = {
  temperature: { label: "Temperature", min: 0, max: 2, step: 0.1, hint: "Lower is more deterministic" },
  top_p: { label: "Top P", min: 0, max: 1, step: 0.05 }, top_k: { label: "Top K", min: 1, step: 1 },
  max_tokens: { label: "Max output tokens", min: 1, step: 1 }, seed: { label: "Seed", step: 1, hint: "Same seed helps reproducibility where supported" },
  frequency_penalty: { label: "Frequency penalty", min: -2, max: 2, step: 0.1 }, presence_penalty: { label: "Presence penalty", min: -2, max: 2, step: 0.1 },
};

export default function ConfigPanel({ projectId, workflowId, issues }: { projectId: string; workflowId: string; issues: Issue[] }) {
  const { nodes, edges, settings, selection, selectedEdge } = useBuilder();
  const node = selection.length === 1 ? nodes.find((n) => n.id === selection[0]) : undefined;
  if (selectedEdge) return <EdgePanel workflowId={workflowId} />;
  if (selection.length > 1) return <MultiPanel count={selection.length} />;
  if (!node) return <SettingsPanel projectId={projectId} />;
  return <NodePanel key={node.id} node={node} projectId={projectId} workflowId={workflowId} issues={issues.filter((i) => i.node_id === node.id)} graph={{ schema_version: "2.0", nodes, edges, settings }} />;
}

function Section({ title, children, defaultOpen = true }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="border-b border-line">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between px-4 py-2.5 text-left text-xs font-semibold text-ink-700 hover:bg-canvas/60" aria-expanded={open}>
        {title}<Icon name={open ? "ChevronUp" : "ChevronDown"} size={14} className="text-ink-400" />
      </button>
      {open && <div className="space-y-3 px-4 pb-4">{children}</div>}
    </section>
  );
}

type PanelTab = "configure" | "contract" | "context" | "harness" | "tests";

function NodePanel({ node, projectId, workflowId, issues, graph }: { node: WFNode; projectId: string; workflowId: string; issues: Issue[]; graph: any }) {
  const { updateNode, updateConfig, removeSelected, duplicateSelected } = useBuilder();
  const [tab, setTab] = useState<PanelTab>("configure");
  const annotation = node.type === "note" || node.type === "group";
  const tabs: { id: PanelTab; label: string }[] = annotation ? [] : [
    { id: "configure", label: "Configure" }, { id: "contract", label: "Contract" },
    ...(node.type === "agent" ? [{ id: "context" as PanelTab, label: "Context" }] : []),
    ...(!node.type.startsWith("input_") && !node.type.startsWith("trigger_") && !node.type.startsWith("output_") ? [{ id: "harness" as PanelTab, label: "Harness" }] : []),
    ...(!node.type.startsWith("input_") && !node.type.startsWith("trigger_") ? [{ id: "tests" as PanelTab, label: "Test" }] : []),
  ];
  const spec = SPEC[node.type];
  const [key, setKey] = useState(node.key);
  const kErr = keyError(key, graph.nodes, node.id);
  const vars = useMemo(() => variableSuggestions(graph, node.id), [graph, node.id]);
  const refs = useMemo(() => badReferences(graph, node), [graph, node]);
  const set = (patch: Record<string, any>, k?: string) => updateConfig(node.id, patch, k ? `${node.id}:${k}` : undefined);
  const c = node.config;

  return (
    <div className="text-sm">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <span style={{ color: CATEGORY_TINT[spec.category] }}><Icon name={spec.icon} /></span>
        <span className="flex-1 text-xs text-ink-400">{spec.label}</span>
        <button title="Duplicate (⌘D)" aria-label="Duplicate" onClick={duplicateSelected} className="rounded p-1 text-ink-400 hover:bg-canvas hover:text-ink-900"><Icon name="Copy" size={14} /></button>
        <button title="Delete (Del)" aria-label="Delete" onClick={removeSelected} className="rounded p-1 text-ink-400 hover:bg-canvas hover:text-state-failed"><Icon name="Trash2" size={14} /></button>
      </div>
      {tabs.length > 0 && (
        <div className="flex gap-0.5 border-b border-line px-2" role="tablist">
          {tabs.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
              className={`-mb-px border-b-2 px-2 py-2 text-xs font-medium ${tab === t.id ? "border-accent-500 text-ink-900" : "border-transparent text-ink-400 hover:text-ink-700"}`}>
              {t.label}{t.id === "contract" && node.contract ? " ●" : ""}</button>
          ))}
        </div>
      )}
      {tab === "contract" && <ContractPanel node={node} />}
      {tab === "context" && <ContextPanel node={node} workflowId={workflowId} />}
      {tab === "harness" && <HarnessPanel node={node} />}
      {tab === "tests" && <TestsPanel node={node} workflowId={workflowId} />}
      {tab === "configure" && <>
      {(issues.length > 0 || refs.length > 0) && (
        <div className="space-y-1 border-b border-line bg-state-failed/5 px-4 py-2.5">
          {issues.map((i, k) => <p key={k} className={`flex gap-1.5 text-xs ${i.severity === "error" ? "text-state-failed" : "text-warn"}`}><Icon name={i.severity === "error" ? "CircleAlert" : "TriangleAlert"} size={13} className="mt-0.5 shrink-0" />{i.message}</p>)}
          {refs.map((r) => <p key={r} className="flex gap-1.5 text-xs text-state-failed"><Icon name="CircleAlert" size={13} className="mt-0.5 shrink-0" />{r}</p>)}
        </div>
      )}
      <Section title="General">
        <Field label="Name"><Input value={node.name} onChange={(e) => updateNode(node.id, { name: e.target.value }, `${node.id}:name`)} /></Field>
        {node.type !== "note" && node.type !== "group" && (
          <Field label="Variable key" error={kErr} hint={<>Other nodes reference this as <code className="font-mono">{`{{${node.key}.output}}`}</code></>}>
            <Input className="font-mono text-xs" value={key} onChange={(e) => setKey(e.target.value)} onBlur={() => { if (!kErr && key !== node.key) updateNode(node.id, { key }); else setKey(node.key); }} />
          </Field>
        )}
      </Section>
      {node.type === "agent" && <AgentFields node={node} set={set} vars={vars} projectId={projectId} />}
      {node.type.startsWith("input_") && (
        <Section title="Input">
          <Field label="Run input field" hint={<>Value comes from <code className="font-mono">{`input.${c.field}`}</code> when the run starts</>}><Input className="font-mono text-xs" value={c.field || ""} onChange={(e) => set({ field: e.target.value.replace(/[^\w]/g, "") }, "field")} /></Field>
          <Field label="Label shown in the run form"><Input value={c.label || ""} onChange={(e) => set({ label: e.target.value }, "label")} /></Field>
          <Toggle checked={c.required !== false} onChange={(v) => set({ required: v })} label="Required" />
          <Field label="Default value"><Input value={c.default ?? ""} onChange={(e) => set({ default: e.target.value || null }, "default")} /></Field>
          {node.type === "input_json" && <JsonField label="JSON schema (optional)" value={c.json_schema} onChange={(v) => set({ json_schema: v })} placeholder='{"company": "string", "year": "integer"}' />}
          {node.type === "input_file" && <p className="text-xs text-ink-400">Pass a project document id (upload under Knowledge → Project files). The text is extracted server-side.</p>}
        </Section>
      )}
      {node.type === "condition" && (
        <Section title="Rule">
          <RuleEditor rule={c.rule || {}} onChange={(rule) => set({ rule }, "rule")} vars={vars} />
          <p className="text-xs text-ink-400">Connect the green handle for true and the red one for false. Rules are compared as values, never executed as code.</p>
        </Section>
      )}
      {node.type === "router" && (
        <Section title="Routes">
          <p className="text-xs text-ink-400">The first matching route wins; otherwise the default handle is used.</p>
          {(c.routes || []).map((r: any, i: number) => (
            <div key={i} className="space-y-2 rounded-md border border-line p-2.5">
              <div className="flex gap-2"><Input className="font-mono text-xs" value={r.name} onChange={(e) => set({ routes: c.routes.map((x: any, k: number) => (k === i ? { ...x, name: e.target.value.replace(/[^\w]/g, "_") } : x)) }, `route${i}`)} />
                <Button size="sm" variant="ghost" icon="Trash2" aria-label="Remove route" onClick={() => set({ routes: c.routes.filter((_: any, k: number) => k !== i) })} /></div>
              <RuleEditor rule={r} vars={vars} onChange={(rule) => set({ routes: c.routes.map((x: any, k: number) => (k === i ? { ...x, ...rule } : x)) }, `route${i}`)} />
            </div>
          ))}
          <Button size="sm" icon="Plus" onClick={() => set({ routes: [...(c.routes || []), { name: `route_${(c.routes?.length || 0) + 1}`, left: "", operator: "contains", right: "" }] })}>Add route</Button>
        </Section>
      )}
      {node.type === "merge" && (
        <Section title="Merge">
          <Field label="Combine outputs as"><Select value={c.strategy} onChange={(e) => set({ strategy: e.target.value })}>
            <option value="named">Object keyed by node (research: …, risk: …)</option><option value="object">Single object (fields merged)</option><option value="array">List</option></Select></Field>
          <p className="text-xs text-ink-400">Waits for every active incoming branch. Branches skipped by a condition are not waited for.</p>
        </Section>
      )}
      {(node.type === "loop" || node.type === "retry") && (
        <Section title={node.type === "loop" ? "Loop" : "Retry until"}>
          {node.type === "loop" && <Field label="Collection" hint="Expression resolving to a list. Leave empty to repeat a fixed number of times.">
            <VarInput multiline={false} mono value={c.collection || ""} onChange={(v) => set({ collection: v }, "coll")} suggestions={vars} placeholder="{{research.output.companies}}" /></Field>}
          <Field label="Maximum iterations" hint={`Also capped by the workflow limit (${graph.settings.max_loop_iterations ?? 10}).`}><Input type="number" min={1} value={c.max_iterations} onChange={(e) => set({ max_iterations: Math.max(1, +e.target.value) }, "max")} /></Field>
          <Field label={node.type === "retry" ? "Success condition" : "Stop early when (optional)"}>
            {c.stop_condition ? <RuleEditor rule={c.stop_condition} vars={[...vars, { expr: "{{loop.result}}", label: "loop.result", detail: "This iteration's result" }]} onChange={(r) => set({ stop_condition: r }, "stop")} />
              : <Button size="sm" onClick={() => set({ stop_condition: { left: "{{loop.result}}", operator: "exists", right: null } })}>Add condition</Button>}
          </Field>
          <p className="text-xs text-ink-400">Connect the “each” handle to the loop body, and “done” to what runs afterwards. Inside the body use {"{{loop.item}}"} and {"{{loop.index}}"}.</p>
        </Section>
      )}
      {node.type === "transform" && (
        <Section title="Transform">
          <Field label="Mode"><Select value={c.mode} onChange={(e) => set({ mode: e.target.value })}>
            <option value="template">Text template</option><option value="select">Select a value</option><option value="mapping">Build an object</option><option value="json_parse">Parse JSON</option><option value="to_text">Convert to text</option></Select></Field>
          {c.mode === "template" && <Field label="Template"><VarInput value={c.template || ""} onChange={(v) => set({ template: v }, "tpl")} suggestions={vars} /></Field>}
          {["select", "json_parse", "to_text"].includes(c.mode) && <Field label="Value"><VarInput multiline={false} mono value={c.path || ""} onChange={(v) => set({ path: v }, "path")} suggestions={vars} placeholder="{{research.output.summary}}" /></Field>}
          {c.mode === "mapping" && <KeyValueEditor value={c.mapping || {}} onChange={(m) => set({ mapping: m }, "map")} vars={vars} />}
        </Section>
      )}
      {node.type === "human_approval" && (
        <Section title="Approval">
          <Field label="Title"><Input value={c.title || ""} onChange={(e) => set({ title: e.target.value }, "title")} /></Field>
          <Field label="Instructions for the reviewer"><Textarea value={c.instructions || ""} onChange={(e) => set({ instructions: e.target.value }, "instr")} /></Field>
          <Field label="Content to review" hint="Empty = the upstream output"><VarInput value={c.content || ""} onChange={(v) => set({ content: v }, "content")} suggestions={vars} rows={3} /></Field>
          <Toggle checked={c.allow_edit !== false} onChange={(v) => set({ allow_edit: v })} label="Reviewer can edit the content before approving" />
        </Section>
      )}
      {node.type.startsWith("tool_") && <ToolFields node={node} set={set} vars={vars} projectId={projectId} />}
      {node.type.startsWith("output_") && (
        <Section title="Output">
          <Field label="Template" hint="Empty = pass the upstream output through unchanged"><VarInput value={c.template || ""} onChange={(v) => set({ template: v }, "tpl")} suggestions={vars} rows={5} /></Field>
          <VarChips suggestions={vars} onPick={(s) => set({ template: (c.template || "") + s.expr })} />
          {node.type === "output_file" && <Field label="File name"><Input value={c.filename || ""} onChange={(e) => set({ filename: e.target.value }, "fn")} /></Field>}
          {node.type === "output_json" && <JsonField label="Output schema (optional)" value={c.json_schema} onChange={(v) => set({ json_schema: v })} placeholder='{"company": "string", "risk_score": "number"}' />}
        </Section>
      )}
      {node.type === "note" && <Section title="Note"><Textarea rows={6} value={c.text || ""} onChange={(e) => set({ text: e.target.value }, "text")} /></Section>}
      {node.type.startsWith("trigger_") && (
        <Section title="Trigger">
          <p className="text-xs text-ink-500">An entry point. The trigger&apos;s payload becomes this node&apos;s output ({"{{" + node.key + ".output}}"}) and the run input. Create the webhook, schedule, event or file trigger itself under the project&apos;s Triggers tab; triggers always run a published version.</p>
          <JsonField label="Payload schema (optional)" value={c.payload_schema} onChange={(v) => set({ payload_schema: v })} placeholder='{"email": "string", "amount": "number"}' />
        </Section>
      )}
      {(node.type === "wait_timer" || node.type === "wait_webhook" || node.type === "wait_event") && (
        <Section title="Durable wait">
          <p className="text-xs text-ink-500">The run pauses here without holding a worker and resumes from the database — across restarts.</p>
          {node.type === "wait_timer" && <>
            <Field label="Wait for (seconds)"><Input type="number" min={1} value={c.duration_seconds ?? ""} onChange={(e) => set({ duration_seconds: e.target.value ? +e.target.value : null }, "dur")} /></Field>
            <Field label="…or until (ISO time or expression)"><VarInput multiline={false} mono value={c.until || ""} onChange={(v) => set({ until: v }, "until")} suggestions={vars} placeholder="2026-12-01T09:00:00Z" /></Field>
          </>}
          {node.type === "wait_webhook" && <p className="rounded-md bg-canvas p-2 text-xs">Give the external system <code className="font-mono">{`{{run.callbacks.${node.key}}}`}</code> (e.g. in an HTTP request before this node). A POST to that URL resumes the run with the posted JSON as this node&apos;s output.</p>}
          {node.type === "wait_event" && <>
            <Field label="Event name"><Input value={c.event_name || ""} placeholder="order.paid" onChange={(e) => set({ event_name: e.target.value }, "ev")} /></Field>
            <Field label="Correlation key" hint="Only events with this key resume this run"><VarInput multiline={false} mono value={c.correlation || ""} onChange={(v) => set({ correlation: v }, "corr")} suggestions={vars} placeholder="{{input.order_id}}" /></Field>
          </>}
          <div className="grid grid-cols-2 gap-2">
            <Field label="Give up after (seconds)"><Input type="number" min={1} value={c.max_wait_seconds ?? ""} placeholder="never" onChange={(e) => set({ max_wait_seconds: e.target.value ? +e.target.value : null }, "max")} /></Field>
            <Field label="On timeout"><Select value={c.timeout_action || "edge"} onChange={(e) => set({ timeout_action: e.target.value })}>
              <option value="edge">Take the timeout branch</option><option value="continue">Continue</option><option value="fail">Fail the run</option></Select></Field>
          </div>
        </Section>
      )}
      {node.type === "human_approval" && (
        <Section title="Timeout" defaultOpen={!!c.max_wait_seconds}>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Expire after (seconds)"><Input type="number" min={1} value={c.max_wait_seconds ?? ""} placeholder="never" onChange={(e) => set({ max_wait_seconds: e.target.value ? +e.target.value : null }, "max")} /></Field>
            <Field label="On expiry"><Select value={c.timeout_action || "edge"} onChange={(e) => set({ timeout_action: e.target.value })}>
              <option value="edge">Take the timeout branch</option><option value="continue">Continue</option><option value="fail">Fail the run</option></Select></Field>
          </div>
        </Section>
      )}
      {node.type === "subworkflow" && <SubworkflowFields node={node} set={set} vars={vars} projectId={projectId} />}
      </>}
    </div>
  );
}

function SubworkflowFields({ node, set, vars, projectId }: { node: WFNode; set: (p: Record<string, any>, k?: string) => void; vars: any[]; projectId: string }) {
  const c = node.config;
  const wfs = useQuery({ queryKey: ["workflows", projectId, false], queryFn: () => api<any[]>(`/projects/${projectId}/workflows`) });
  const versions = useQuery({ queryKey: ["versions", c.workflow_id], enabled: !!c.workflow_id, queryFn: () => api<any[]>(`/workflows/${c.workflow_id}/versions`) });
  const published = (wfs.data || []).filter((w) => w.latest_version > 0);
  return (
    <Section title="Sub-workflow">
      <p className="text-xs text-ink-500">Runs a published, immutable version of another workflow as one step (its own trace, budget carved from this run&apos;s remaining budget).</p>
      <Field label="Workflow"><Select value={c.workflow_id || ""} onChange={(e) => set({ workflow_id: e.target.value, version: null })}>
        <option value="">Choose a published workflow…</option>{published.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</Select></Field>
      {c.workflow_id && <Field label="Pinned version" hint="Pinning keeps this step stable when the other workflow changes."><Select value={c.version ?? ""} onChange={(e) => set({ version: e.target.value ? +e.target.value : null })}>
        <option value="">Latest published at run time</option>{versions.data?.map((v) => <option key={v.id} value={v.version}>v{v.version}{v.notes ? ` — ${v.notes}` : ""}</option>)}</Select></Field>}
      <KeyValueEditor label="Input mapping (child input field → value)" value={c.input_mapping || {}} onChange={(m) => set({ input_mapping: m }, "map")} vars={vars} />
      <FailureSelect value={c.on_failure} onChange={(v) => set({ on_failure: v })} />
    </Section>
  );
}

function AgentFields({ node, set, vars, projectId }: { node: WFNode; set: (p: Record<string, any>, k?: string) => void; vars: any[]; projectId: string }) {
  const c = node.config;
  const { workspace } = useWorkspace();
  const templates = useQuery({ queryKey: ["agent-templates"], queryFn: () => api<any[]>("/agent-templates") });
  const library = useQuery({ queryKey: ["agents", workspace?.id], enabled: !!workspace, queryFn: () => api<any[]>(`/workspaces/${workspace!.id}/agents`) });
  const kbs = useQuery({ queryKey: ["kbs", projectId], queryFn: () => api<any[]>(`/projects/${projectId}/knowledge-bases`) });
  const models = useModels(c.model?.provider || undefined, c.model?.credential_id);
  const supported = models.data?.models.find((m) => m.id === c.model?.model)?.supported_params
    ?? (c.model?.provider ? ["temperature", "max_tokens"] : []);
  const params = c.params || {};
  const unsupportedSet = Object.keys(params).filter((p) => params[p] !== null && params[p] !== undefined && !supported.includes(p));

  function applyTemplate(id: string) {
    const t = templates.data?.find((x) => x.id === id);
    if (!t) return;
    set({ template: id, role: t.role, instructions: t.instructions, tools: t.tools });
  }
  async function saveToLibrary() {
    const name = prompt("Save this agent to the library as:", node.name);
    if (!name) return;
    try {
      const { library_agent_id: _omit, ...cfg } = c;
      await api(`/workspaces/${workspace!.id}/agents`, { body: { name, template: c.template || "custom", config: cfg } });
      toast("Saved to agent library");
      library.refetch();
    } catch (e) { toast(errorMessage(e), "error"); }
  }


  return (
    <>
      <Section title="Role">
        <div className="grid grid-cols-2 gap-2">
          <Field label="Template"><Select value={c.template || "general"} onChange={(e) => applyTemplate(e.target.value)}>
            {templates.data?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select></Field>
          <Field label="From library"><Select value={c.library_agent_id || ""} onChange={(e) => set({ library_agent_id: e.target.value || null })}>
            <option value="">None</option>{library.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
        </div>
        {c.library_agent_id && <p className="text-xs text-ink-400">Library settings apply where fields here are empty. Runs snapshot the library agent, so later edits don't change past runs.</p>}
        <Field label="Role"><Input value={c.role || ""} onChange={(e) => set({ role: e.target.value }, "role")} placeholder="Research analyst" /></Field>
        <Field label="Instructions"><Textarea rows={5} value={c.instructions || ""} onChange={(e) => set({ instructions: e.target.value }, "instr")} /></Field>
        <Field label="Task prompt" hint="Type {{ to insert run inputs or upstream outputs">
          <VarInput value={c.prompt || ""} onChange={(v) => set({ prompt: v }, "prompt")} suggestions={vars} rows={4} placeholder="Analyze {{input.company}} using {{research.output}}" />
        </Field>
        <VarChips suggestions={vars} onPick={(s) => set({ prompt: (c.prompt || "") + s.expr })} />
        <Button size="sm" variant="ghost" icon="BookmarkPlus" onClick={saveToLibrary}>Save to agent library</Button>
      </Section>
      <Section title="Model">
        <ModelPicker value={c.model || { provider: "", model: "" }} onChange={(m) => set({ model: m })} allowAuto />
        {c.model?.provider === "auto" && <RoutingFields routing={c.routing || {}} onChange={(r) => set({ routing: r }, "routing")} />}
        {c.model?.model && c.model?.provider !== "auto" && (
          <div className="space-y-3 pt-1">
            {Object.entries(PARAM_META).filter(([p]) => supported.includes(p)).map(([p, m]) => (
              <Field key={p} label={m.label} hint={m.hint}>
                <div className="flex items-center gap-2">
                  {m.max !== undefined ? <input type="range" className="flex-1 accent-accent-500" min={m.min} max={m.max} step={m.step} value={params[p] ?? (p === "temperature" ? 0.7 : m.min)}
                    onChange={(e) => set({ params: { ...params, [p]: +e.target.value } }, p)} aria-label={m.label} /> : null}
                  <Input type="number" className="w-24" min={m.min} max={m.max} step={m.step} value={params[p] ?? ""} placeholder="default"
                    onChange={(e) => set({ params: { ...params, [p]: e.target.value === "" ? null : +e.target.value } }, p)} />
                </div>
              </Field>
            ))}
            {supported.includes("reasoning_effort") && (
              <Field label="Reasoning effort"><Select value={params.reasoning_effort || ""} onChange={(e) => set({ params: { ...params, reasoning_effort: e.target.value || null } })}>
                <option value="">Model default</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></Select></Field>
            )}
            {supported.includes("stop") && <Field label="Stop sequences" hint="Comma-separated"><Input value={(params.stop || []).join(", ")} onChange={(e) => set({ params: { ...params, stop: e.target.value ? e.target.value.split(",").map((s) => s.trim()) : null } }, "stop")} /></Field>}
            {unsupportedSet.length > 0 && (
              <p className="text-xs text-warn">This model doesn't support {unsupportedSet.join(", ")}; those values won't be sent.
                <button className="ml-1 underline" onClick={() => set({ params: Object.fromEntries(Object.entries(params).filter(([k]) => supported.includes(k))) })}>Remove them</button></p>
            )}
          </div>
        )}
      </Section>
      <Section title="Tools and knowledge" defaultOpen={false}>
        <p className="text-xs text-ink-400">The agent can only use the tools checked here.</p>
        <div className="grid grid-cols-2 gap-1.5">
          {TOOLS.map((t) => (
            <label key={t.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={(c.tools || []).includes(t.id)}
              onChange={(e) => set({ tools: e.target.checked ? [...(c.tools || []), t.id] : (c.tools || []).filter((x: string) => x !== t.id) })} />{t.label}</label>
          ))}
        </div>
        <Field label="Knowledge bases" hint={(c.tools || []).includes("vector_search") ? "The agent searches these itself." : "Relevant passages are retrieved automatically before the call."}>
          {kbs.data?.length ? kbs.data.map((k) => (
            <label key={k.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={(c.knowledge_base_ids || []).includes(k.id)}
              onChange={(e) => set({ knowledge_base_ids: e.target.checked ? [...(c.knowledge_base_ids || []), k.id] : c.knowledge_base_ids.filter((x: string) => x !== k.id) })} />{k.name}</label>
          )) : <p className="text-xs text-ink-400">No knowledge bases in this project yet.</p>}
        </Field>
        <Field label="Max tool calls per run of this agent"><Input type="number" min={0} max={50} value={c.max_tool_iterations ?? 8} onChange={(e) => set({ max_tool_iterations: +e.target.value }, "mti")} /></Field>
      </Section>
      <Section title="Structured output" defaultOpen={!!c.output_schema}>
        <SchemaEditor value={c.output_schema} onChange={(v) => set({ output_schema: v })} />
      </Section>
      <Section title="Context and memory" defaultOpen={false}>
        <Toggle checked={c.context?.include_run_input !== false} onChange={(v) => set({ context: { ...c.context, include_run_input: v } })} label="Include the run input" />
        <Toggle checked={c.context?.include_direct_upstream !== false} onChange={(v) => set({ context: { ...c.context, include_direct_upstream: v } })} label="Include outputs of directly connected nodes" hint="Only immediate predecessors, never the whole history" />
        <Field label="Context limit (tokens)" hint="Empty = derived from the model's context window"><Input type="number" value={c.context?.max_context_tokens ?? ""} onChange={(e) => set({ context: { ...c.context, max_context_tokens: e.target.value ? +e.target.value : null } }, "ctx")} /></Field>
        <Field label="When context is too long"><Select value={c.context?.truncation || "truncate_middle"} onChange={(e) => set({ context: { ...c.context, truncation: e.target.value } })}>
          <option value="truncate_middle">Trim the middle</option><option value="truncate_end">Trim the end</option><option value="error">Fail the node</option></Select></Field>
        <Toggle checked={!!c.memory?.read_workflow_memory} onChange={(v) => set({ memory: { ...c.memory, read_workflow_memory: v } })} label="Read workflow memory" hint="Requires workflow memory to be enabled in workflow settings" />
        <Toggle checked={!!c.memory?.write_workflow_memory} onChange={(v) => set({ memory: { ...c.memory, write_workflow_memory: v } })} label="Save output to workflow memory" />
      </Section>
      <Section title="Reliability" defaultOpen={false}>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Timeout (s)"><Input type="number" min={1} value={c.timeout_seconds ?? 120} onChange={(e) => set({ timeout_seconds: +e.target.value }, "to")} /></Field>
          <Field label="Retries"><Input type="number" min={0} max={10} value={c.retry?.retries ?? 0} onChange={(e) => set({ retry: { ...c.retry, retries: +e.target.value } }, "rt")} /></Field>
        </div>
        <Field label="Backoff"><Select value={c.retry?.backoff || "exponential"} onChange={(e) => set({ retry: { ...c.retry, backoff: e.target.value } })}>
          <option value="exponential">Exponential</option><option value="fixed">Fixed</option><option value="none">None</option></Select></Field>
        <FailureSelect value={c.on_failure} onChange={(v) => set({ on_failure: v })} />
        <Field label="Fallback models" hint="Tried in order when the primary model is unavailable, rate-limited or times out. The model actually used is recorded.">
          <div className="space-y-2">
            {(c.fallbacks || []).map((f: ModelRef, i: number) => (
              <div key={i} className="flex items-start gap-1"><div className="flex-1"><ModelPicker compact value={f} onChange={(m) => set({ fallbacks: c.fallbacks.map((x: any, k: number) => (k === i ? m : x)) })} /></div>
                <Button size="sm" variant="ghost" icon="X" aria-label="Remove fallback" onClick={() => set({ fallbacks: c.fallbacks.filter((_: any, k: number) => k !== i) })} /></div>
            ))}
            <Button size="sm" icon="Plus" onClick={() => set({ fallbacks: [...(c.fallbacks || []), { provider: "", model: "" }] })}>Add fallback</Button>
          </div>
        </Field>
        <Toggle checked={!!c.reasoning_summary} onChange={(v) => set({ reasoning_summary: v })} label="Ask for a short reasoning summary" hint="A brief explanation, not the model's hidden reasoning" />
      </Section>
    </>
  );
}

function RoutingFields({ routing, onChange }: { routing: any; onChange: (r: any) => void }) {
  const providers = useQuery({ queryKey: ["providers-all"], queryFn: () => api<any[]>("/providers") });
  const objectives = [["balanced", "Balanced"], ["quality", "Highest quality"], ["cost", "Lowest cost"], ["latency", "Lowest latency"]];
  const allowed: string[] = routing.allowed_providers || [];
  return (
    <div className="space-y-3 rounded-md border border-accent-100 bg-accent-50/40 p-3">
      <p className="text-xs text-ink-600">The harness picks a configured model that satisfies this agent&apos;s capabilities, context size and policies, ranked by measured quality, cost and latency. Every decision and its reasons are recorded on the run.</p>
      <div className="grid grid-cols-2 gap-1">
        {objectives.map(([v, l]) => (
          <label key={v} className="flex items-center gap-1.5 text-xs"><input type="radio" name="objective" checked={(routing.objective || "balanced") === v} onChange={() => onChange({ ...routing, objective: v })} />{l}</label>
        ))}
      </div>
      <Field label="Allowed providers" hint="None selected = any provider with a key (the test provider needs to be selected explicitly)">
        <div className="flex flex-wrap gap-1.5">{providers.data?.map((p) => (
          <button key={p.id} type="button" onClick={() => onChange({ ...routing, allowed_providers: allowed.includes(p.id) ? allowed.filter((x) => x !== p.id) : [...allowed, p.id] })}
            className={`rounded-full border px-2 py-0.5 text-xs ${allowed.includes(p.id) ? "border-accent-500 bg-paper text-accent-700" : "border-line bg-paper text-ink-600"}`}>{p.name}</button>))}</div>
      </Field>
      <div className="grid grid-cols-3 gap-2">
        <Field label="Max $/call"><Input type="number" step="0.01" value={routing.max_cost_per_call ?? ""} onChange={(e) => onChange({ ...routing, max_cost_per_call: e.target.value ? +e.target.value : null })} /></Field>
        <Field label="Max latency (s)"><Input type="number" value={routing.max_latency_seconds ?? ""} onChange={(e) => onChange({ ...routing, max_latency_seconds: e.target.value ? +e.target.value : null })} /></Field>
        <Field label="Min eval score"><Input type="number" step="0.05" min={0} max={1} value={routing.min_eval_score ?? ""} onChange={(e) => onChange({ ...routing, min_eval_score: e.target.value ? +e.target.value : null })} /></Field>
      </div>
    </div>
  );
}

function ToolFields({ node, set, vars, projectId }: { node: WFNode; set: (p: Record<string, any>, k?: string) => void; vars: any[]; projectId: string }) {
  const c = node.config;
  const a = c.arguments || {};
  const arg = (patch: Record<string, any>, k: string) => set({ arguments: { ...a, ...patch } }, k);
  const kbs = useQuery({ queryKey: ["kbs", projectId], enabled: node.type === "tool_vector_search", queryFn: () => api<any[]>(`/projects/${projectId}/knowledge-bases`) });
  return (
    <>
      <Section title="Arguments">
        {node.type === "tool_web_search" && <>
          <Field label="Query"><VarInput multiline={false} value={a.query || ""} onChange={(v) => arg({ query: v }, "q")} suggestions={vars} /></Field>
          <Field label="Results"><Input type="number" min={1} max={10} value={a.max_results ?? 5} onChange={(e) => arg({ max_results: +e.target.value }, "n")} /></Field></>}
        {node.type === "tool_http" && <>
          <div className="grid grid-cols-[90px_1fr] gap-2"><Select value={a.method || "GET"} onChange={(e) => arg({ method: e.target.value }, "m")}>{["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m}>{m}</option>)}</Select>
            <VarInput multiline={false} value={a.url || ""} onChange={(v) => arg({ url: v }, "url")} suggestions={vars} placeholder="https://api.example.com/items" /></div>
          <JsonField label="Headers" value={a.headers} onChange={(v) => arg({ headers: v || {} }, "h")} placeholder='{"Authorization": "Bearer {{secret:MY_API_KEY}}"}' />
          <p className="text-xs text-ink-400">Reference secrets as {"{{secret:NAME}}"} — they're resolved on the server and never shown to models or logs. Localhost, private networks and cloud metadata addresses are blocked.</p>
          {a.method !== "GET" && <Field label="Body"><VarInput mono value={typeof a.body === "string" ? a.body : a.body ? JSON.stringify(a.body, null, 2) : ""} onChange={(v) => arg({ body: v }, "b")} suggestions={vars} /></Field>}</>}
        {node.type === "tool_python" && <>
          <Field label="Code" hint="Runs in an isolated sandbox with no network. INPUTS holds the inputs below; print results or write files to ./out.">
            <Textarea mono rows={10} value={a.code || ""} onChange={(e) => arg({ code: e.target.value }, "code")} /></Field>
          <KeyValueEditor label="Inputs" value={a.inputs || {}} onChange={(m) => arg({ inputs: m }, "in")} vars={vars} /></>}
        {node.type === "tool_calculator" && <Field label="Expression" hint="Arithmetic, sqrt, log, round, min, max… no code execution"><VarInput multiline={false} mono value={a.expression || ""} onChange={(v) => arg({ expression: v }, "e")} suggestions={vars} placeholder="({{financial.output.revenue}} - 100) / 100" /></Field>}
        {node.type === "tool_file_reader" && <Field label="Document id"><VarInput multiline={false} mono value={a.document_id || ""} onChange={(v) => arg({ document_id: v }, "d")} suggestions={vars} placeholder="{{input.file}}" /></Field>}
        {node.type === "tool_json" && <>
          <Field label="Operation"><Select value={a.operation || "parse"} onChange={(e) => arg({ operation: e.target.value }, "op")}>{["parse", "get", "pick", "filter", "count", "sort"].map((o) => <option key={o}>{o}</option>)}</Select></Field>
          <Field label="Data"><VarInput multiline={false} mono value={a.data || ""} onChange={(v) => arg({ data: v }, "data")} suggestions={vars} /></Field>
          {["get", "sort"].includes(a.operation) && <Field label="Path"><Input className="font-mono text-xs" value={a.path || ""} onChange={(e) => arg({ path: e.target.value }, "p")} placeholder="items[0].name" /></Field>}</>}
        {node.type === "tool_vector_search" && <>
          <Field label="Query"><VarInput multiline={false} value={a.query || ""} onChange={(v) => arg({ query: v }, "q")} suggestions={vars} /></Field>
          <Field label="Knowledge bases">{kbs.data?.map((k) => (
            <label key={k.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={(c.knowledge_base_ids || []).includes(k.id)}
              onChange={(e) => set({ knowledge_base_ids: e.target.checked ? [...(c.knowledge_base_ids || []), k.id] : (c.knowledge_base_ids || []).filter((x: string) => x !== k.id) })} />{k.name}</label>))}
            {!kbs.data?.length && <p className="text-xs text-ink-400">Create a knowledge base in this project first.</p>}</Field></>}
      </Section>
      <Section title="Reliability" defaultOpen={false}>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Timeout (s)"><Input type="number" min={1} value={c.timeout_seconds ?? 60} onChange={(e) => set({ timeout_seconds: +e.target.value }, "to")} /></Field>
          <Field label="Retries"><Input type="number" min={0} max={10} value={c.retry?.retries ?? 0} onChange={(e) => set({ retry: { ...c.retry, retries: +e.target.value } }, "rt")} /></Field>
        </div>
        <FailureSelect value={c.on_failure} onChange={(v) => set({ on_failure: v })} />
      </Section>
    </>
  );
}

function FailureSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Field label="If it still fails" hint={value === "route_error" ? "An “error” handle appears on the node; connect it to handle the failure." : undefined}>
      <Select value={value || "stop"} onChange={(e) => onChange(e.target.value)}>
        <option value="stop">Stop the workflow</option><option value="continue">Continue with no output</option>
        <option value="skip">Skip this node and its dependents</option><option value="route_error">Send to an error branch</option>
      </Select>
    </Field>
  );
}

function RuleEditor({ rule, onChange, vars }: { rule: any; onChange: (r: any) => void; vars: any[] }) {
  const unary = rule.operator === "exists" || rule.operator === "not_exists";
  return (
    <div className="space-y-2">
      <VarInput multiline={false} mono value={rule.left || ""} onChange={(v) => onChange({ ...rule, left: v })} suggestions={vars} placeholder="{{risk.output.risk_score}}" ariaLabel="Left value" />
      <div className="grid grid-cols-[110px_1fr] gap-2">
        <Select aria-label="Operator" value={rule.operator || "=="} onChange={(e) => onChange({ ...rule, operator: e.target.value })}>{OPERATORS.map((o) => <option key={o}>{o}</option>)}</Select>
        {!unary && <VarInput multiline={false} mono value={rule.right === null || rule.right === undefined ? "" : String(rule.right)} onChange={(v) => onChange({ ...rule, right: v })} suggestions={vars} placeholder="0.8" ariaLabel="Right value" />}
      </div>
    </div>
  );
}

function KeyValueEditor({ value, onChange, vars, label = "Fields" }: { value: Record<string, string>; onChange: (v: Record<string, string>) => void; vars: any[]; label?: string }) {
  const rows = Object.entries(value);
  return (
    <Field label={label}>
      <div className="space-y-2">
        {rows.map(([k, v], i) => (
          <div key={i} className="grid grid-cols-[100px_1fr_auto] gap-1.5">
            <Input className="font-mono text-xs" value={k} onChange={(e) => { const n = [...rows]; n[i] = [e.target.value, v]; onChange(Object.fromEntries(n)); }} />
            <VarInput multiline={false} mono value={String(v ?? "")} onChange={(nv) => { const n = [...rows]; n[i] = [k, nv]; onChange(Object.fromEntries(n)); }} suggestions={vars} />
            <Button size="sm" variant="ghost" icon="X" aria-label="Remove" onClick={() => onChange(Object.fromEntries(rows.filter((_, j) => j !== i)))} />
          </div>
        ))}
        <Button size="sm" icon="Plus" onClick={() => onChange({ ...value, [`field_${rows.length + 1}`]: "" })}>Add field</Button>
      </div>
    </Field>
  );
}

function JsonField({ label, value, onChange, placeholder }: { label: string; value: any; onChange: (v: any) => void; placeholder?: string }) {
  const [text, setText] = useState(value ? JSON.stringify(value, null, 2) : "");
  const [err, setErr] = useState<string | null>(null);
  return (
    <Field label={label} error={err}>
      <Textarea mono rows={4} value={text} placeholder={placeholder} onChange={(e) => setText(e.target.value)}
        onBlur={() => { if (!text.trim()) { setErr(null); return onChange(null); } try { onChange(JSON.parse(text)); setErr(null); } catch { setErr("Not valid JSON"); } }} />
    </Field>
  );
}

const TYPES = ["string", "number", "integer", "boolean", "array", "object"];
function SchemaEditor({ value, onChange }: { value: any; onChange: (v: any) => void }) {
  const simple = value && !value.properties && !value.type ? value : null;
  const [raw, setRaw] = useState(!!value && !simple);
  if (!value) return (
    <div className="space-y-2"><p className="text-xs text-ink-400">Require this agent to return JSON with specific fields. Output is validated; invalid JSON is repaired or the node fails — never passed on silently.</p>
      <Button size="sm" icon="Braces" onClick={() => onChange({ summary: "string" })}>Add output fields</Button></div>
  );
  if (raw) return <><JsonField label="JSON schema" value={value} onChange={onChange} /><Button size="sm" variant="ghost" onClick={() => onChange(null)}>Remove structured output</Button></>;
  const rows = Object.entries(simple || {});
  return (
    <div className="space-y-2">
      {rows.map(([k, t], i) => (
        <div key={i} className="grid grid-cols-[1fr_110px_auto] gap-1.5">
          <Input className="font-mono text-xs" value={k} onChange={(e) => { const n = [...rows]; n[i] = [e.target.value.replace(/[^\w]/g, "_"), t]; onChange(Object.fromEntries(n)); }} />
          <Select value={String(t)} onChange={(e) => { const n = [...rows]; n[i] = [k, e.target.value]; onChange(Object.fromEntries(n)); }}>{TYPES.map((x) => <option key={x}>{x}</option>)}</Select>
          <Button size="sm" variant="ghost" icon="X" aria-label="Remove field" onClick={() => { const n = rows.filter((_, j) => j !== i); onChange(n.length ? Object.fromEntries(n) : null); }} />
        </div>
      ))}
      <div className="flex gap-2"><Button size="sm" icon="Plus" onClick={() => onChange({ ...simple, [`field_${rows.length + 1}`]: "string" })}>Add field</Button>
        <Button size="sm" variant="ghost" onClick={() => setRaw(true)}>Edit as JSON schema</Button></div>
    </div>
  );
}

function EdgePanel({ workflowId }: { workflowId: string }) {
  const { edges, nodes, selectedEdge, removeEdges, select, commit } = useBuilder();
  const graph = useBuilder((st) => st.graph);
  const e = edges.find((x) => x.id === selectedEdge);
  const types = useQuery({ queryKey: ["edge-type", workflowId, selectedEdge, JSON.stringify(nodes.map((n) => [n.id, n.contract, n.config?.output_schema, n.config?.mode]))],
    enabled: !!e, queryFn: () => api<Record<string, any>>(`/workflows/${workflowId}/edge-types`, { body: { graph: graph() } }) });
  if (!e) return null;
  const s = nodes.find((n) => n.id === e.source), t = nodes.find((n) => n.id === e.target);
  const info = types.data?.[e.id];
  const ports = t?.contract?.inputs || [];
  function insertTransform(mode: string) {
    if (!s || !t) return;
    const id = `n_${Math.random().toString(36).slice(2, 10)}`;
    const key = `${mode}_${s.key}`.slice(0, 40);
    commit((st) => ({
      nodes: [...st.nodes, { id, key, type: "transform", name: mode === "csv_to_table" ? "CSV → Table" : mode === "json_parse" ? "Parse JSON" : "To text",
        position: { x: (s.position.x + t.position.x) / 2, y: (s.position.y + t.position.y) / 2 + 60 }, config: { mode, path: "" } }],
      edges: [...st.edges.filter((x) => x.id !== e!.id),
        { id: `e_${Math.random().toString(36).slice(2, 10)}`, source: e!.source, target: id, source_handle: e!.source_handle, target_handle: null },
        { id: `e_${Math.random().toString(36).slice(2, 10)}`, source: id, target: e!.target, source_handle: null, target_handle: e!.target_handle }],
    }));
    select([id]);
    toast("Transform inserted. Review it, then re-check the connection types.", "info");
  }
  return (
    <div className="space-y-3 p-4 text-sm">
      <h3 className="text-xs font-semibold text-ink-700">Connection</h3>
      <p>{s?.name} {e.source_handle && <Badge>{e.source_handle}</Badge>} → {t?.name}</p>
      {info && (
        <div className={`rounded-md border p-2.5 text-xs ${info.ok ? "border-line" : "border-state-failed/40 bg-state-failed/5"}`}>
          <div className="flex justify-between"><span className="text-ink-500">Carries</span><code className="font-mono">{info.source_type}</code></div>
          {info.target_type && <div className="flex justify-between"><span className="text-ink-500">Port expects</span><code className="font-mono">{info.target_type}</code></div>}
          <div className="mt-1 text-ink-500">Source: <code className="font-mono">{info.source}</code> → target: <code className="font-mono">{info.target}</code></div>
          {info.note && <p className={`mt-1 ${info.ok ? "text-ink-500" : "text-state-failed"}`}>{info.note}</p>}
          {info.suggestion && <Button size="sm" className="mt-2" icon="Wand2" onClick={() => insertTransform(info.suggestion.transform)}>{info.suggestion.label}?</Button>}
        </div>
      )}
      {ports.length > 1 && (
        <Field label="Target port"><Select value={e.target_handle || ""} onChange={(ev) => commit((st) => ({ edges: st.edges.map((x) => (x.id === e.id ? { ...x, target_handle: ev.target.value || null } : x)) }))}>
          <option value="">Choose a port…</option>{ports.map((p) => <option key={p.name} value={p.name}>{p.name} ({p.type})</option>)}</Select></Field>
      )}
      <p className="text-xs text-ink-400">{t?.name} receives {s?.name}&apos;s output as <code className="font-mono">{`{{${s?.key}.output}}`}</code>. Data is never converted silently.</p>
      <Button size="sm" variant="danger" icon="Trash2" onClick={() => { removeEdges([e.id]); select([]); }}>Delete connection</Button>
    </div>
  );
}

function MultiPanel({ count }: { count: number }) {
  const { duplicateSelected, removeSelected } = useBuilder();
  return (
    <div className="space-y-3 p-4 text-sm">
      <p>{count} nodes selected</p>
      <div className="flex gap-2"><Button size="sm" icon="Copy" onClick={duplicateSelected}>Duplicate</Button><Button size="sm" variant="danger" icon="Trash2" onClick={removeSelected}>Delete</Button></div>
      <p className="text-xs text-ink-400">Shift-drag on the canvas to box-select; ⌘/Ctrl-click to add to the selection.</p>
    </div>
  );
}

const GOAL_AGENTS = ["research", "financial_analyst", "critic", "data_analyst", "python", "writer", "reviewer", "summarizer", "planner", "manager", "developer"];
const GOAL_TOOLS = ["web_search", "python", "calculator", "vector_search", "json_processor", "file_reader"];

function GoalFields({ goal, onChange }: { goal: any; onChange: (g: any) => void }) {
  const set = (p: any) => onChange({ ...goal, ...p });
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  return (
    <div className="space-y-3 pt-1">
      <Field label="Goal"><Textarea rows={3} value={goal.goal} onChange={(e) => set({ goal: e.target.value })} placeholder="Research Acme Corp and produce an investment risk report." /></Field>
      <Field label="Constraints"><Textarea rows={2} value={goal.constraints || ""} onChange={(e) => set({ constraints: e.target.value })} placeholder="Cite sources. Keep the report under 800 words." /></Field>
      <Field label="Agents the planner may use">
        <div className="flex flex-wrap gap-1">{GOAL_AGENTS.map((a) => <button key={a} type="button" onClick={() => set({ agents: toggle(goal.agents, a) })}
          className={`rounded-full border px-2 py-0.5 text-xs ${goal.agents.includes(a) ? "border-accent-500 bg-accent-50 text-accent-700" : "border-line text-ink-600"}`}>{a.replace("_", " ")}</button>)}</div>
      </Field>
      <Field label="Tools the planner may grant">
        <div className="flex flex-wrap gap-1">{GOAL_TOOLS.map((a) => <button key={a} type="button" onClick={() => set({ tools: toggle(goal.tools, a) })}
          className={`rounded-full border px-2 py-0.5 text-xs ${goal.tools.includes(a) ? "border-accent-500 bg-accent-50 text-accent-700" : "border-line text-ink-600"}`}>{a.replace("_", " ")}</button>)}</div>
      </Field>
      <Field label="Planner model"><ModelPicker compact value={goal.planner_model} onChange={(m) => set({ planner_model: m })} /></Field>
      <Field label="Model for planned agents"><ModelPicker compact allowAuto value={goal.agent_model} onChange={(m) => set({ agent_model: m })} /></Field>
      <div className="grid grid-cols-3 gap-2">
        <Field label="Agent calls"><Input type="number" min={1} max={100} value={goal.max_agent_calls} onChange={(e) => set({ max_agent_calls: +e.target.value })} /></Field>
        <Field label="Plan depth"><Input type="number" min={1} max={30} value={goal.max_planning_depth} onChange={(e) => set({ max_planning_depth: +e.target.value })} /></Field>
        <Field label="Replans"><Input type="number" min={0} max={5} value={goal.max_replans} onChange={(e) => set({ max_replans: +e.target.value })} /></Field>
      </div>
      <JsonField label="Required output contract (optional)" value={goal.output_schema} onChange={(v) => set({ output_schema: v })} placeholder='{"risk_score": "number", "summary": "string"}' />
      <p className="text-2xs text-ink-400">Bounded autonomy: the planner can only use what is listed here, cannot exceed the budgets above, and every plan version is recorded. The canvas is ignored in Goal Mode.</p>
    </div>
  );
}

function SettingsPanel({ projectId }: { projectId: string }) {
  const { settings, setSettings } = useBuilder();
  const limits = useQuery({ queryKey: ["limits"], queryFn: () => api<any>("/settings/limits") });
  const ceil = limits.data?.ceilings || {};
  const num = (k: keyof typeof settings, label: string, def: number | null, hint?: string, step = 1) => (
    <Field label={label} hint={hint ?? (ceil[k] ? `Server maximum: ${ceil[k]}` : undefined)}>
      <Input type="number" step={step} min={0} value={(settings[k] as any) ?? def ?? ""} placeholder={def === null ? "No limit" : undefined}
        onChange={(e) => setSettings({ [k]: e.target.value === "" ? null : +e.target.value } as any)} />
    </Field>
  );
  const vars = settings.variables || {};
  return (
    <div className="text-sm">
      <div className="border-b border-line px-4 py-3"><h3 className="text-xs font-semibold text-ink-700">Workflow settings</h3>
        <p className="mt-0.5 text-xs text-ink-400">Select a node to configure it. These limits stop runaway runs.</p></div>
      <Section title="Budgets and limits">
        {num("max_cost", "Maximum cost (USD, estimated)", null, "Checked before every model call", 0.1)}
        {num("max_total_tokens", "Maximum tokens", null)}
        <div className="grid grid-cols-2 gap-2">{num("max_llm_calls", "Model calls", 50)}{num("max_tool_calls", "Tool calls", 100)}</div>
        <div className="grid grid-cols-2 gap-2">{num("max_runtime_seconds", "Runtime (s)", 600)}{num("max_parallel_nodes", "Parallel nodes", 10)}</div>
        <div className="grid grid-cols-2 gap-2">{num("max_loop_iterations", "Loop iterations", 10)}{num("max_retries_per_node", "Retries per node", 3)}</div>
      </Section>
      <Section title="Variables">
        <p className="text-xs text-ink-400">Constants available as {"{{vars.name}}"}.</p>
        <KeyValueEditor value={vars} onChange={(v) => setSettings({ variables: v })} vars={[]} label="" />
      </Section>
      <Section title="Execution mode" defaultOpen={settings.mode === "goal"}>
        <div className="grid grid-cols-2 gap-1 rounded-md bg-canvas p-1">
          {(["graph", "goal"] as const).map((m) => (
            <button key={m} onClick={() => setSettings({ mode: m, ...(m === "goal" && !settings.goal ? { goal: { goal: "", agents: ["research", "financial_analyst", "critic", "manager"], tools: ["web_search"],
              planner_model: { provider: "", model: "" }, agent_model: { provider: "", model: "" }, max_agent_calls: 12, max_planning_depth: 8, max_replans: 1 } } : {}) })}
              className={`rounded px-2 py-1 text-xs ${(settings.mode || "graph") === m ? "bg-paper font-medium shadow-card" : "text-ink-500"}`}>{m === "graph" ? "Graph (you design it)" : "Goal (harness plans it)"}</button>
          ))}
        </div>
        {settings.mode === "goal" && settings.goal && <GoalFields goal={settings.goal} onChange={(g) => setSettings({ goal: g })} />}
      </Section>
      <Section title="Compensation" defaultOpen={false}>
        <Toggle checked={!!settings.compensation_enabled} onChange={(v) => setSettings({ compensation_enabled: v })} label="Run compensating actions automatically when a run fails"
          hint="Off by default. Compensations registered by tool nodes run in reverse order and still pass the policy engine." />
      </Section>
      <Section title="Memory" defaultOpen={false}>
        <Toggle checked={!!settings.workflow_memory_enabled} onChange={(v) => setSettings({ workflow_memory_enabled: v })} label="Enable workflow memory"
          hint="Agents that opt in can save values that later runs of this workflow can read. Clear it any time from the toolbar menu." />
      </Section>
    </div>
  );
}

