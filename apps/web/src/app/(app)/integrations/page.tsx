"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useCredentials } from "@/components/common";
import { PageHeader } from "@/components/shell/AppShell";
import { Badge, Button, Dialog, Empty, ErrorBox, Field, Input, Select, Spinner, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { ago } from "@/lib/format";
import { useWorkspace } from "@/lib/session";

export default function Integrations() {
  const { workspace } = useWorkspace();
  const qc = useQueryClient();
  const creds = useCredentials();
  const list = useQuery({ queryKey: ["mcp", workspace?.id], enabled: !!workspace, queryFn: () => api<any[]>(`/workspaces/${workspace!.id}/mcp`) });
  const [form, setForm] = useState<any | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["mcp"] });
  async function create() {
    setErr(null);
    try { const m = await api<any>(`/workspaces/${workspace!.id}/mcp`, { body: { ...form, credential_id: form.credential_id || null } }); setForm(null); refresh(); await sync(m.id); }
    catch (e) { setErr(e); }
  }
  async function sync(id: string) {
    try { const m = await api<any>(`/mcp/${id}/sync`, { method: "POST" }); toast(m.status === "ok" ? `Found ${m.tools.length} tools` : `Sync failed: ${m.last_error}`, m.status === "ok" ? "ok" : "error"); refresh(); }
    catch (e) { toast(errorMessage(e), "error"); }
  }
  async function setAllowed(m: any, tools: string[]) {
    try { await api(`/mcp/${m.id}`, { method: "PUT", body: { ...m, allowed_tools: tools } }); refresh(); } catch (e) { toast(errorMessage(e), "error"); }
  }
  return (
    <>
      <PageHeader title="Integrations" description="MCP servers. Registering a server grants nothing: allowlist its tools here, then grant them per agent. Every call still passes policies, approvals, secret handling, rate limits and audit."
        actions={<Button variant="primary" icon="Plus" onClick={() => setForm({ name: "", endpoint: "https://", credential_id: "", rate_limit_per_minute: 60 })}>Add MCP server</Button>} />
      <div className="space-y-4 px-8 py-6">
        {list.isLoading ? <Spinner /> : !list.data?.length ? <Empty icon="Plug" title="No MCP servers" body="Connect remote MCP servers over HTTP(S) to give agents governed access to external tools." /> :
          list.data.map((m) => (
            <section key={m.id} className="rounded-lg border border-line bg-paper p-4 shadow-card">
              <div className="flex items-center justify-between">
                <div><div className="flex items-center gap-2 font-semibold">{m.name}<Badge tone={m.status === "ok" ? "blue" : m.status === "error" ? "warn" : "neutral"}>{m.status}</Badge></div>
                  <div className="font-mono text-xs text-ink-500">{m.endpoint}</div>{m.last_error && <div className="text-xs text-state-failed">{m.last_error}</div>}</div>
                <div className="flex gap-2"><Button size="sm" icon="RefreshCw" onClick={() => sync(m.id)}>Sync tools</Button>
                  <Button size="sm" variant="ghost" icon="Trash2" aria-label="Remove" onClick={async () => { if (confirm(`Remove ${m.name}?`)) { await api(`/mcp/${m.id}`, { method: "DELETE" }); refresh(); } }} /></div>
              </div>
              {m.tools.length > 0 && (
                <div className="mt-3">
                  <div className="mb-1 text-xs text-ink-500">Allowlist ({m.allowed_tools.length} of {m.tools.length}) {m.synced_at && `· synced ${ago(m.synced_at)}`}</div>
                  <ul className="grid gap-1 md:grid-cols-2">{m.tools.map((t: any) => {
                    const on = m.allowed_tools.includes(t.name);
                    const a = t.annotations || {};
                    return (
                      <li key={t.name}><label className="flex cursor-pointer items-start gap-2 rounded-md border border-line p-2 text-xs">
                        <input type="checkbox" className="mt-0.5" checked={on} onChange={(e) => setAllowed(m, e.target.checked ? [...m.allowed_tools, t.name] : m.allowed_tools.filter((x: string) => x !== t.name))} />
                        <span className="min-w-0"><span className="font-mono font-medium">{t.name}</span> {a.readOnlyHint ? <Badge>read-only</Badge> : a.destructiveHint ? <Badge tone="warn">destructive</Badge> : <Badge tone="warn">writes</Badge>}
                          <span className="block truncate text-ink-500">{t.description}</span>{on && <code className="text-2xs text-accent-700">mcp:{m.name}/{t.name}</code>}</span>
                      </label></li>);
                  })}</ul>
                  <p className="mt-2 text-2xs text-ink-400">Tools without a read-only annotation are treated as external writes by the policy engine.</p>
                </div>
              )}
            </section>
          ))}
      </div>
      {form && (
        <Dialog open onClose={() => setForm(null)} title="Add MCP server"
          footer={<><Button variant="ghost" onClick={() => setForm(null)}>Cancel</Button><Button variant="primary" onClick={create} disabled={!form.name || !form.endpoint}>Add and sync</Button></>}>
          <div className="space-y-4">
            <ErrorBox error={err} />
            <Field label="Name" hint="Lowercase; used in grants as mcp:<name>/<tool>"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "") })} placeholder="github" /></Field>
            <Field label="Endpoint (streamable HTTP)"><Input className="font-mono text-xs" value={form.endpoint} onChange={(e) => setForm({ ...form, endpoint: e.target.value })} /></Field>
            <Field label="Credential (sent as a bearer token)" hint="Store it under Keys & secrets → Other secrets first"><Select value={form.credential_id} onChange={(e) => setForm({ ...form, credential_id: e.target.value })}>
              <option value="">None</option>{creds.data?.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.provider})</option>)}</Select></Field>
            <Field label="Rate limit (calls/minute)"><Input type="number" value={form.rate_limit_per_minute} onChange={(e) => setForm({ ...form, rate_limit_per_minute: +e.target.value })} /></Field>
            <p className="text-xs text-ink-400">Local (stdio) MCP servers aren&apos;t supported: they would run commands on the Isocline host. Private network addresses are blocked unless the operator allows them.</p>
          </div>
        </Dialog>
      )}
    </>
  );
}
