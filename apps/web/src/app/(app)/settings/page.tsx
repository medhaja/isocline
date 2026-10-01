"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/shell/AppShell";
import { Button, Dialog, Field, Input, Spinner, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { ago } from "@/lib/format";
import { useMe, useWorkspace } from "@/lib/session";

export default function Settings() {
  const { workspace, setWorkspace } = useWorkspace();
  const me = useMe();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [newWs, setNewWs] = useState("");
  const limits = useQuery({ queryKey: ["limits"], queryFn: () => api<any>("/settings/limits") });
  const members = useQuery({ queryKey: ["members", workspace?.id], enabled: !!workspace, queryFn: () => api<any[]>(`/workspaces/${workspace!.id}/members`) });
  const isAdmin = workspace && ["owner", "admin"].includes(workspace.role);
  const audit = useQuery({ queryKey: ["audit", workspace?.id], enabled: !!isAdmin, queryFn: () => api<any[]>(`/workspaces/${workspace!.id}/audit?limit=50`) });
  if (!workspace) return <Spinner />;
  return (
    <>
      <PageHeader title="Settings" />
      <div className="max-w-4xl space-y-8 px-8 py-6">
        <section className="space-y-3">
          <h2 className="text-sm font-semibold">Workspace</h2>
          <div className="flex items-end gap-2"><Field label="Name"><Input className="w-72" defaultValue={workspace.name} onChange={(e) => setName(e.target.value)} /></Field>
            <Button disabled={!name || !isAdmin} onClick={async () => { try { await api(`/workspaces/${workspace.id}`, { method: "PATCH", body: { name } }); qc.invalidateQueries({ queryKey: ["me"] }); toast("Workspace renamed"); } catch (e) { toast(errorMessage(e), "error"); } }}>Save</Button></div>
          <div className="flex items-end gap-2"><Field label="Create another workspace"><Input className="w-72" value={newWs} onChange={(e) => setNewWs(e.target.value)} placeholder="Team workspace" /></Field>
            <Button disabled={!newWs} onClick={async () => { const w = await api<any>("/workspaces", { body: { name: newWs } }); await qc.invalidateQueries({ queryKey: ["me"] }); setWorkspace(w.id); setNewWs(""); toast("Workspace created"); }}>Create</Button></div>
          <div><div className="mb-1 text-xs font-medium text-ink-700">Members</div>
            <ul className="divide-y divide-line rounded-lg border border-line bg-paper text-sm">{members.data?.map((m) => <li key={m.user_id} className="flex justify-between px-4 py-2"><span>{m.name} <span className="text-ink-400">{m.email}</span></span><span className="text-ink-600">{m.role}</span></li>)}</ul></div>
        </section>
        <section>
          <h2 className="mb-2 text-sm font-semibold">Server limits</h2>
          <p className="mb-2 text-xs text-ink-400">Workflow limits are capped at these values by the server.</p>
          {limits.data && <dl className="grid grid-cols-2 gap-2 rounded-lg border border-line bg-paper p-4 text-sm md:grid-cols-4">
            {Object.entries(limits.data.ceilings).map(([k, v]) => <div key={k}><dt className="text-xs text-ink-400">{k.replace("max_", "").replace(/_/g, " ")}</dt><dd className="tabular-nums">{String(v)}</dd></div>)}
            <div><dt className="text-xs text-ink-400">web search</dt><dd>{limits.data.search_provider}</dd></div><div><dt className="text-xs text-ink-400">embeddings</dt><dd>{limits.data.embedding_provider}</dd></div>
          </dl>}
        </section>
        <TokensSection />
        <TypesSection workspaceId={workspace.id} />
        <QuotaSection workspaceId={workspace.id} admin={!!me.data?.user.is_admin} />
        <section><h2 className="mb-2 text-sm font-semibold">Account</h2><p className="text-sm text-ink-600">{me.data?.user.email}{me.data?.user.email_verified ? " (verified)" : " (not verified)"}</p>
          {!me.data?.user.email_verified && <Button size="sm" className="mt-2" onClick={() => api("/auth/resend-verification", { method: "POST" }).then(() => toast("Verification email sent"))}>Resend verification email</Button>}</section>
        {isAdmin && (
          <section><h2 className="mb-2 text-sm font-semibold">Audit log</h2>
            <ul className="divide-y divide-line rounded-lg border border-line bg-paper text-sm">{audit.data?.map((a) => (
              <li key={a.id} className="grid grid-cols-[140px_1fr_120px] gap-3 px-4 py-2"><span className="font-mono text-xs">{a.action}</span><span className="truncate text-ink-600">{a.user || "system"} {a.target_type ? `· ${a.target_type}` : ""}</span><span className="text-right text-xs text-ink-400">{ago(a.created_at)}</span></li>))}</ul>
          </section>
        )}
      </div>
    </>
  );
}


function TokensSection() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["tokens"], queryFn: () => api<any[]>("/tokens") });
  const [created, setCreated] = useState<string | null>(null);
  async function create() {
    const name = prompt("Name this token (e.g. CI pipeline)");
    if (!name) return;
    const t = await api<any>("/tokens", { body: { name, expires_in_days: 90 } });
    setCreated(t.token); qc.invalidateQueries({ queryKey: ["tokens"] });
  }
  return (
    <section>
      <div className="mb-2 flex items-center justify-between"><h2 className="text-sm font-semibold">Access tokens</h2><Button size="sm" icon="KeyRound" onClick={create}>New token</Button></div>
      <p className="mb-2 text-xs text-ink-500">For the Python SDK and the <code className="font-mono">isocline</code> CLI. Tokens act as you; they expire after 90 days.</p>
      {created && <div className="mb-2 rounded-md border border-state-running/40 bg-state-running/10 p-3 text-sm"><div className="font-medium">Copy this token now — it won&apos;t be shown again.</div>
        <code className="mt-1 block break-all font-mono text-xs">{created}</code><button className="mt-1 text-xs underline" onClick={() => { navigator.clipboard.writeText(created); setCreated(null); }}>Copy and hide</button></div>}
      <ul className="divide-y divide-line rounded-lg border border-line bg-paper text-sm">
        {q.data?.length === 0 && <li className="px-4 py-3 text-ink-400">No tokens.</li>}
        {q.data?.map((t) => (
          <li key={t.id} className="flex items-center justify-between px-4 py-2">
            <span className={t.revoked_at ? "text-ink-400 line-through" : ""}>{t.name} <code className="font-mono text-xs text-ink-400">{t.prefix}…</code>
              <span className="block text-xs text-ink-400">last used {ago(t.last_used_at)}{t.expires_at && ` · expires ${new Date(t.expires_at).toLocaleDateString()}`}</span></span>
            {!t.revoked_at && <button className="text-xs text-state-failed" onClick={async () => { await api(`/tokens/${t.id}/revoke`, { method: "POST" }); qc.invalidateQueries({ queryKey: ["tokens"] }); }}>Revoke</button>}
          </li>))}
      </ul>
    </section>
  );
}

function TypesSection({ workspaceId }: { workspaceId: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["types", workspaceId], queryFn: () => api<any>(`/workspaces/${workspaceId}/types`) });
  const [form, setForm] = useState({ name: "", schema: '{"company": "string", "revenue_growth": "number"}' });
  async function save() {
    try { await api(`/workspaces/${workspaceId}/types`, { body: { name: form.name, json_schema: JSON.parse(form.schema) } }); toast("Type saved"); setForm({ ...form, name: "" }); qc.invalidateQueries({ queryKey: ["types"] }); }
    catch (e) { toast(e instanceof SyntaxError ? "Schema must be JSON" : errorMessage(e), "error"); }
  }
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold">Custom types</h2>
      <p className="mb-2 text-xs text-ink-500">JSON Schemas usable in contracts as <code className="font-mono">JSON&lt;Name&gt;</code>. Connections are checked structurally; agents with such an output contract produce matching JSON.</p>
      <ul className="mb-3 space-y-1">{q.data?.custom.map((t: any) => (
        <li key={t.id} className="flex items-center justify-between rounded-md border border-line bg-paper px-3 py-1.5 text-xs"><span><code className="font-mono font-medium">{`JSON<${t.name}>`}</code> <span className="text-ink-400">{JSON.stringify(t.json_schema).slice(0, 90)}</span></span>
          <button className="text-state-failed" onClick={async () => { await api(`/types/${t.id}`, { method: "DELETE" }); qc.invalidateQueries({ queryKey: ["types"] }); }}>Delete</button></li>))}</ul>
      <div className="grid grid-cols-[180px_1fr_auto] items-end gap-2">
        <Field label="Name"><Input value={form.name} placeholder="FinancialReport" onChange={(e) => setForm({ ...form, name: e.target.value.replace(/[^A-Za-z0-9_]/g, "") })} /></Field>
        <Field label="Schema (simple fields or JSON Schema)"><Input className="font-mono text-xs" value={form.schema} onChange={(e) => setForm({ ...form, schema: e.target.value })} /></Field>
        <Button onClick={save} disabled={!/^[A-Z]/.test(form.name)}>Save type</Button>
      </div>
    </section>
  );
}

function QuotaSection({ workspaceId, admin }: { workspaceId: string; admin: boolean }) {
  const q = useQuery({ queryKey: ["quota", workspaceId], queryFn: () => api<any>(`/workspaces/${workspaceId}/quota`) });
  const [edit, setEdit] = useState<any | null>(null);
  if (!q.data) return null;
  const l = q.data.limits, u = q.data.usage;
  const rows: [string, string, any, any][] = [["max_concurrent_runs", "Concurrent runs", u.running_runs, l.max_concurrent_runs], ["max_concurrent_nodes", "Parallel nodes per run", "", l.max_concurrent_nodes],
    ["monthly_token_quota", "Tokens this month", u.month_tokens.toLocaleString(), l.monthly_token_quota ?? "no limit"], ["monthly_cost_quota", "Cost this month (est.)", `$${u.month_cost_usd}`, l.monthly_cost_quota ?? "no limit"],
    ["sandbox_concurrency", "Sandbox executions at once", "", l.sandbox_concurrency], ["artifact_storage_bytes", "Artifact storage", `${(u.artifact_bytes / 1024 ** 2).toFixed(1)} MB`, `${(l.artifact_storage_bytes / 1024 ** 3).toFixed(1)} GB`]];
  return (
    <section>
      <div className="mb-2 flex items-center justify-between"><h2 className="text-sm font-semibold">Quotas</h2>{admin && <Button size="sm" onClick={() => setEdit({ ...l })}>Edit</Button>}</div>
      <p className="mb-2 text-xs text-ink-500">Keeps one workspace from exhausting shared workers: runs over the concurrency quota wait in the queue instead of occupying workers.</p>
      <dl className="grid grid-cols-2 gap-2 rounded-lg border border-line bg-paper p-4 text-sm md:grid-cols-3">
        {rows.map(([k, label, used, lim]) => <div key={k}><dt className="text-xs text-ink-400">{label}</dt><dd className="tabular-nums">{used !== "" ? `${used} / ` : ""}{lim}</dd></div>)}
      </dl>
      {edit && (
        <Dialog open onClose={() => setEdit(null)} title="Workspace quotas" footer={<><Button variant="ghost" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { try { await api(`/workspaces/${workspaceId}/quota`, { method: "PUT", body: edit }); setEdit(null); q.refetch(); toast("Quotas saved"); } catch (e) { toast(errorMessage(e), "error"); } }}>Save</Button></>}>
          <div className="grid grid-cols-2 gap-3">
            {Object.keys(edit).map((k) => <Field key={k} label={k.replace(/_/g, " ")}><Input type="number" value={edit[k] ?? ""} onChange={(e) => setEdit({ ...edit, [k]: e.target.value === "" ? null : +e.target.value })} /></Field>)}
          </div>
        </Dialog>
      )}
    </section>
  );
}

