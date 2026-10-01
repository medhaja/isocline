"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/shell/AppShell";
import { Badge, Button, Dialog, Empty, ErrorBox, Field, Icon, Input, Select, Spinner, Toggle, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useWorkspace } from "@/lib/session";
import type { Project } from "@/lib/types";

const KIND_HELP: Record<string, string> = {
  tool: "Allow, deny or require approval for tool calls (built-in or MCP).", model: "Deny specific models (glob, e.g. openai/gpt-4*).",
  model_allowlist: "Only these models may run (globs, e.g. anthropic/*).", budget: "Lower a limit (never raises).",
  approval: "Pause the whole run for approval when a projected metric is exceeded.",
};
const BUDGETS = ["max_run_cost", "max_total_tokens", "max_llm_calls", "max_tool_calls", "max_parallel_nodes", "max_runtime_seconds"];

const blankRule = () => ({ kind: "tool", subject: "*", action: "external_write", effect: "require_approval", condition: {}, value: null, mandatory: false });

function describe(r: any) {
  if (r.kind === "tool") return `${r.effect.replace("_", " ")} ${r.subject === "*" ? "any tool" : r.subject}${r.action !== "*" ? ` (${r.action.replace("_", " ")})` : ""}`
    + (r.condition?.agent_template_not_in ? ` unless agent is ${r.condition.agent_template_not_in.join("/")}` : r.condition?.arg ? ` when ${r.condition.arg} ${r.condition.op} ${r.condition.value}` : "");
  if (r.kind === "model") return `deny model ${r.subject}`;
  if (r.kind === "model_allowlist") return `only models: ${(r.value || []).join(", ")}`;
  if (r.kind === "budget") return `${r.subject.replace(/_/g, " ")} ≤ ${r.value}`;
  if (r.kind === "approval") return `require run approval when ${r.condition?.metric?.replace(/_/g, " ")} ${r.condition?.op || ">"} ${r.condition?.value}`;
  return r.kind;
}

export default function Policies() {
  const { workspace } = useWorkspace();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["policies", workspace?.id], enabled: !!workspace, queryFn: () => api<any[]>(`/workspaces/${workspace!.id}/policies`) });
  const projects = useQuery({ queryKey: ["projects", workspace?.id], enabled: !!workspace, queryFn: () => api<Project[]>(`/workspaces/${workspace!.id}/projects`) });
  const [edit, setEdit] = useState<any | null>(null);
  const [err, setErr] = useState<unknown>(null);
  async function save() {
    setErr(null);
    try {
      const body = { ...edit, rules: edit.rules.map((r: any) => ({ ...r, value: r.kind === "budget" ? Number(r.value) : r.kind === "model_allowlist" && typeof r.value === "string" ? r.value.split(",").map((x: string) => x.trim()).filter(Boolean) : r.value })) };
      if (edit.id) await api(`/policies/${edit.id}`, { method: "PUT", body }); else await api("/policies", { body });
      setEdit(null); qc.invalidateQueries({ queryKey: ["policies"] }); toast("Policy saved");
    } catch (e) { setErr(e); }
  }
  const scopeName = (p: any) => p.scope_type === "workspace" ? "Workspace" : p.scope_type === "project" ? `Project · ${projects.data?.find((x) => x.id === p.scope_id)?.name || "…"}` : `${p.scope_type} · ${p.scope_id.slice(0, 8)}`;
  const setRule = (i: number, patch: any) => setEdit({ ...edit, rules: edit.rules.map((r: any, k: number) => (k === i ? { ...r, ...patch } : r)) });
  return (
    <>
      <PageHeader title="Policies" description="Rules enforced by the harness on every run — outside prompts, never delegated to a model. Mandatory rules can't be weakened by a more specific scope."
        actions={<Button variant="primary" icon="Plus" onClick={() => setEdit({ name: "", scope_type: "workspace", scope_id: workspace!.id, enabled: true, rules: [blankRule()] })}>New policy</Button>} />
      <div className="space-y-4 px-8 py-6">
        {list.isLoading ? <Spinner /> : !list.data?.length ? <Empty icon="ShieldCheck" title="No policies" body="Example: require approval for external writes, restrict production to approved models, cap run cost at $5." /> :
          list.data.map((p) => (
            <section key={p.id} className="rounded-lg border border-line bg-paper p-4 shadow-card">
              <div className="flex items-center justify-between">
                <div><div className="flex items-center gap-2 font-semibold">{p.name}{!p.enabled && <Badge tone="warn">disabled</Badge>}<Badge>{scopeName(p)}</Badge></div>
                  <div className="text-xs text-ink-400">version {p.version}</div></div>
                <div className="flex gap-2"><Button size="sm" onClick={() => setEdit({ ...p, rules: p.rules.map((r: any) => ({ ...r, value: r.kind === "model_allowlist" ? (r.value || []).join(", ") : r.value })) })}>Edit</Button>
                  <Button size="sm" variant="ghost" icon="Trash2" aria-label="Delete policy" onClick={async () => { if (confirm(`Delete ${p.name}?`)) { await api(`/policies/${p.id}`, { method: "DELETE" }); qc.invalidateQueries({ queryKey: ["policies"] }); } }} /></div>
              </div>
              <ul className="mt-3 space-y-1">{p.rules.map((r: any) => (
                <li key={r.id} className="flex items-center gap-2 text-sm"><Icon name={r.effect === "deny" ? "Ban" : r.effect === "require_approval" ? "UserCheck" : r.kind === "budget" ? "Gauge" : "Check"} size={14}
                  className={r.effect === "deny" ? "text-state-failed" : r.effect === "require_approval" ? "text-state-waiting" : "text-ink-400"} />{describe(r)}{r.mandatory && <Badge tone="warn">mandatory</Badge>}</li>))}</ul>
            </section>
          ))}
      </div>
      {edit && (
        <Dialog open onClose={() => setEdit(null)} title={edit.id ? "Edit policy" : "New policy"} wide
          footer={<><Button variant="ghost" onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" onClick={save} disabled={!edit.name}>Save policy</Button></>}>
          <div className="space-y-4">
            <ErrorBox error={err} />
            <div className="grid grid-cols-2 gap-3">
              <Field label="Name"><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} placeholder="Production policy" /></Field>
              <Field label="Applies to"><Select disabled={!!edit.id} value={edit.scope_type === "workspace" ? "workspace" : edit.scope_id} onChange={(e) => setEdit(e.target.value === "workspace"
                ? { ...edit, scope_type: "workspace", scope_id: workspace!.id } : { ...edit, scope_type: "project", scope_id: e.target.value })}>
                <option value="workspace">Whole workspace</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>Project: {p.name}</option>)}</Select></Field>
            </div>
            <Toggle checked={edit.enabled} onChange={(v) => setEdit({ ...edit, enabled: v })} label="Enabled" />
            <div className="space-y-2">
              {edit.rules.map((r: any, i: number) => (
                <div key={i} className="space-y-2 rounded-md border border-line p-3">
                  <div className="flex items-center gap-2">
                    <Select className="w-52" value={r.kind} onChange={(e) => {
                      const k = e.target.value;
                      setRule(i, k === "budget" ? { kind: k, subject: "max_run_cost", effect: "limit", action: "*", value: 5, condition: {} }
                        : k === "model_allowlist" ? { kind: k, subject: "*", effect: "allow", action: "*", value: "openai/*, anthropic/*", condition: {} }
                        : k === "approval" ? { kind: k, subject: "run", effect: "require_approval", action: "*", value: null, condition: { metric: "projected_cost", op: "gt", value: 2 } }
                        : k === "model" ? { kind: k, subject: "openai/gpt-4o", effect: "deny", action: "*", value: null, condition: {} } : blankRule());
                    }}>
                      <option value="tool">Tool permission</option><option value="model_allowlist">Approved models</option><option value="model">Blocked model</option>
                      <option value="budget">Budget limit</option><option value="approval">Run approval</option></Select>
                    <span className="flex-1 text-xs text-ink-500">{KIND_HELP[r.kind]}</span>
                    <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={r.mandatory} onChange={(e) => setRule(i, { mandatory: e.target.checked })} />Mandatory</label>
                    <button aria-label="Remove rule" className="text-ink-400 hover:text-state-failed" onClick={() => setEdit({ ...edit, rules: edit.rules.filter((_: any, k: number) => k !== i) })}><Icon name="X" /></button>
                  </div>
                  {r.kind === "tool" && (
                    <div className="grid grid-cols-4 gap-2">
                      <Field label="Tool"><Input className="font-mono text-xs" value={r.subject} onChange={(e) => setRule(i, { subject: e.target.value })} placeholder="* or http_request or mcp:github/*" /></Field>
                      <Field label="Action"><Select value={r.action} onChange={(e) => setRule(i, { action: e.target.value })}>
                        {[["*", "any"], ["read", "read"], ["compute", "compute"], ["write", "any write"], ["external_write", "external write"], ["destructive", "destructive"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>
                      <Field label="Effect"><Select value={r.effect} onChange={(e) => setRule(i, { effect: e.target.value })}>
                        <option value="allow">Allow</option><option value="require_approval">Require approval</option><option value="deny">Deny</option></Select></Field>
                      <Field label="Except agent types"><Input value={(r.condition?.agent_template_not_in || []).join(",")} placeholder="research"
                        onChange={(e) => setRule(i, { condition: e.target.value ? { agent_template_not_in: e.target.value.split(",").map((x) => x.trim()) } : {} })} /></Field>
                    </div>)}
                  {r.kind === "model_allowlist" && <Field label="Allowed models (comma-separated globs)"><Input className="font-mono text-xs" value={r.value} onChange={(e) => setRule(i, { value: e.target.value })} /></Field>}
                  {r.kind === "model" && <Field label="Model (glob)"><Input className="font-mono text-xs" value={r.subject} onChange={(e) => setRule(i, { subject: e.target.value })} /></Field>}
                  {r.kind === "budget" && <div className="grid grid-cols-2 gap-2"><Field label="Limit"><Select value={r.subject} onChange={(e) => setRule(i, { subject: e.target.value })}>{BUDGETS.map((b) => <option key={b} value={b}>{b.replace(/_/g, " ")}</option>)}</Select></Field>
                    <Field label="Value"><Input type="number" step="any" value={r.value} onChange={(e) => setRule(i, { value: e.target.value })} /></Field></div>}
                  {r.kind === "approval" && <div className="grid grid-cols-2 gap-2">
                    <Field label="When"><Select value={r.condition.metric} onChange={(e) => setRule(i, { condition: { ...r.condition, metric: e.target.value } })}>
                      <option value="projected_cost">projected cost (USD, worst case)</option><option value="projected_tokens">projected tokens</option><option value="projected_llm_calls">projected model calls</option></Select></Field>
                    <Field label="Exceeds"><Input type="number" step="any" value={r.condition.value} onChange={(e) => setRule(i, { condition: { ...r.condition, op: "gt", value: +e.target.value } })} /></Field></div>}
                </div>
              ))}
              <Button size="sm" icon="Plus" onClick={() => setEdit({ ...edit, rules: [...edit.rules, blankRule()] })}>Add rule</Button>
            </div>
            <p className="text-xs text-ink-400">Changes apply to new runs; each run keeps the policy snapshot it started with. Every change is audited.</p>
          </div>
        </Dialog>
      )}
    </>
  );
}
