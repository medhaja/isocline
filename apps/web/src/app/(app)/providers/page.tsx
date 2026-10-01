"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useCredentials, useProviders } from "@/components/common";
import { PageHeader } from "@/components/shell/AppShell";
import { Badge, Button, Dialog, Empty, ErrorBox, Field, Input, Select, Spinner, Tabs, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { ago } from "@/lib/format";
import { useMe, useWorkspace } from "@/lib/session";

type Tab = "keys" | "pricing";
const SECRET_KINDS = [{ id: "custom", name: "Custom secret (for HTTP tool headers)" }, { id: "tavily", name: "Tavily (web search)" }, { id: "brave", name: "Brave Search (web search)" }];

export default function Providers() {
  const [tab, setTab] = useState<Tab>("keys");
  const me = useMe();
  return (
    <>
      <PageHeader title="Keys & secrets" description="Keys are encrypted at rest and resolved server-side inside model and tool calls. No API ever returns a value, and models never see them. Keys can also come from environment variables (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, OLLAMA_BASE_URL, …)." />
      <div className="bg-paper px-8"><Tabs<Tab> value={tab} onChange={setTab} tabs={[{ id: "keys", label: "Keys and secrets" }, { id: "pricing", label: "Model pricing" }]} /></div>
      <div className="px-8 py-6">{tab === "keys" ? <Keys /> : <Pricing admin={!!me.data?.user.is_admin} />}</div>
    </>
  );
}

function Keys() {
  const { workspace } = useWorkspace();
  const qc = useQueryClient();
  const providers = useProviders();
  const creds = useCredentials();
  const [form, setForm] = useState<{ provider: string; name: string; value: string; base_url: string } | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["credentials"] }); qc.invalidateQueries({ queryKey: ["providers"] }); qc.invalidateQueries({ queryKey: ["models"] }); };

  async function save() {
    setErr(null);
    try { await api(`/workspaces/${workspace!.id}/credentials`, { body: { ...form, value: form!.value || null, base_url: form!.base_url || null } }); setForm(null); refresh(); toast("Key saved"); }
    catch (e) { setErr(e); }
  }
  async function test(id: string) {
    setTesting(id);
    try { const r = await api<{ ok: boolean; message: string }>(`/credentials/${id}/test`, { method: "POST" }); toast(r.message, r.ok ? "ok" : "error"); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setTesting(null); }
  }
  async function rotate(id: string) {
    const value = prompt("Paste the new key. The old one is replaced immediately.");
    if (!value) return;
    try { await api(`/credentials/${id}`, { method: "PATCH", body: { value } }); refresh(); toast("Key rotated"); } catch (e) { toast(errorMessage(e), "error"); }
  }
  const prov = providers.data?.find((p) => p.id === form?.provider);
  if (providers.isLoading) return <Spinner />;
  return (
    <div className="space-y-6">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {providers.data?.map((p) => {
          const mine = creds.data?.filter((c) => c.provider === p.id) || [];
          return (
            <section key={p.id} className="rounded-lg border border-line bg-paper p-4">
              <div className="flex items-center justify-between"><h2 className="font-medium">{p.name}</h2>
                {p.is_test ? <Badge tone="warn">testing only</Badge> : p.has_credential ? <Badge tone="blue">connected</Badge> : !p.requires_key ? <Badge>no key needed</Badge> : <Badge>not connected</Badge>}</div>
              {p.is_test && <p className="mt-1 text-xs text-ink-400">Deterministic responses for trying workflows offline. Not an AI model. Disable with ISOCLINE_ENABLE_TEST_PROVIDER=false.</p>}
              {p.id === "ollama" && <p className="mt-1 text-xs text-ink-400">Add an entry with your Ollama base URL (for example http://host.docker.internal:11434).</p>}
              {p.id === "openai_compatible" && <p className="mt-1 text-xs text-ink-400">Any endpoint that implements the OpenAI chat completions API (vLLM, LM Studio, Together…).</p>}
              <ul className="mt-3 space-y-1.5 text-sm">
                {mine.map((c) => (
                  <li key={c.id} className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate">{c.name} {c.hint && <code className="font-mono text-xs text-ink-400">····{c.hint}</code>}{c.base_url && <span className="block truncate text-xs text-ink-400">{c.base_url}</span>}</span>
                    <span className="flex shrink-0 gap-2 text-xs">
                      <button className="text-accent-600" disabled={testing === c.id} onClick={() => test(c.id)}>{testing === c.id ? "Testing…" : "Test"}</button>
                      <button className="text-accent-600" onClick={() => rotate(c.id)}>Rotate</button>
                      <button className="text-state-failed" onClick={async () => { if (confirm(`Delete ${c.name}? Workflows using it will fail validation.`)) { await api(`/credentials/${c.id}`, { method: "DELETE" }); refresh(); } }}>Delete</button>
                    </span>
                  </li>
                ))}
              </ul>
              {!p.is_test && <Button size="sm" className="mt-3" icon="Plus" onClick={() => { setErr(null); setForm({ provider: p.id, name: p.name, value: "", base_url: p.id === "ollama" ? "http://host.docker.internal:11434" : "" }); }}>Add {p.requires_key ? "key" : "endpoint"}</Button>}
            </section>
          );
        })}
      </div>
      <section>
        <div className="mb-2 flex items-center justify-between"><h2 className="text-sm font-semibold">Other secrets</h2>
          <Button size="sm" icon="Plus" onClick={() => { setErr(null); setForm({ provider: "custom", name: "", value: "", base_url: "" }); }}>Add secret</Button></div>
        <p className="mb-2 text-xs text-ink-400">Web search keys and secrets for the HTTP tool. Reference a secret in HTTP headers as {"{{secret:NAME}}"}.</p>
        <ul className="divide-y divide-line rounded-lg border border-line bg-paper text-sm">
          {creds.data?.filter((c) => ["custom", "tavily", "brave", "search"].includes(c.provider)).map((c) => (
            <li key={c.id} className="flex items-center justify-between px-4 py-2"><span><code className="font-mono text-xs">{c.name}</code> <span className="text-xs text-ink-400">{c.provider} · ····{c.hint} · added {ago(c.created_at)}</span></span>
              <button className="text-xs text-state-failed" onClick={async () => { if (confirm(`Delete ${c.name}?`)) { await api(`/credentials/${c.id}`, { method: "DELETE" }); refresh(); } }}>Delete</button></li>
          ))}
          {!creds.data?.some((c) => ["custom", "tavily", "brave"].includes(c.provider)) && <li className="px-4 py-3 text-ink-400">None yet.</li>}
        </ul>
      </section>
      {form && (
        <Dialog open onClose={() => setForm(null)} title={prov ? `Connect ${prov.name}` : "Add secret"}
          footer={<><Button variant="ghost" onClick={() => setForm(null)}>Cancel</Button><Button variant="primary" onClick={save} disabled={!form.name || (prov?.requires_key && !form.value)}>Save</Button></>}>
          <div className="space-y-4">
            <ErrorBox error={err} />
            {!prov && <Field label="Type"><Select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value, name: e.target.value === "custom" ? form.name : e.target.value })}>{SECRET_KINDS.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}</Select></Field>}
            <Field label={prov ? "Label" : "Name"} hint={!prov ? "Letters, digits and underscores, e.g. MY_API_KEY" : "Useful when you keep several keys, e.g. “Team key”"}><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            {(prov?.requires_key !== false || form.provider === "openai_compatible") && <Field label={prov ? "API key" : "Value"}><Input type="password" autoComplete="off" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} /></Field>}
            {(form.provider === "ollama" || form.provider === "openai_compatible" || form.provider === "openai" || form.provider === "anthropic") && (
              <Field label={`Base URL${["openai", "anthropic"].includes(form.provider) ? " (optional)" : ""}`}><Input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder={prov?.default_base_url || "https://…/v1"} /></Field>)}
          </div>
        </Dialog>
      )}
    </div>
  );
}

function Pricing({ admin }: { admin: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["pricing"], queryFn: () => api<any[]>("/pricing") });
  const [edits, setEdits] = useState<Record<string, any>>({});
  const [adding, setAdding] = useState({ provider: "", model: "", input_per_mtok: "", output_per_mtok: "", context_window: "" });
  async function save(rows: any[]) {
    try { await api("/pricing", { method: "PUT", body: rows }); setEdits({}); qc.invalidateQueries({ queryKey: ["pricing"] }); qc.invalidateQueries({ queryKey: ["models"] }); toast("Pricing updated"); }
    catch (e) { toast(errorMessage(e), "error"); }
  }
  if (q.isLoading) return <Spinner />;
  const num = (v: any) => (v === "" || v === null || v === undefined ? null : Number(v));
  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-600">Cost estimates use these prices (USD per million tokens). They are seeded at install time and may be out of date — check your provider&apos;s pricing page. {admin ? "Changes apply to new estimates immediately." : "Only installation administrators can edit them."}</p>
      <div className="overflow-x-auto rounded-lg border border-line bg-paper">
        <table className="w-full text-sm">
          <thead className="border-b border-line text-left text-xs text-ink-400"><tr><th className="px-3 py-2 font-medium">Provider</th><th className="px-3 py-2 font-medium">Model</th><th className="px-3 py-2 font-medium">Context</th><th className="px-3 py-2 font-medium">Input $/1M</th><th className="px-3 py-2 font-medium">Output $/1M</th><th className="px-3 py-2 font-medium">Cached $/1M</th><th className="px-3 py-2 font-medium">Updated</th></tr></thead>
          <tbody>{q.data?.map((r) => {
            const e = edits[r.id] || {};
            const cell = (k: string) => admin ? <input aria-label={k} className="h-7 w-24 rounded border border-line px-1.5 text-right tabular-nums" value={e[k] ?? r[k] ?? ""} onChange={(ev) => setEdits({ ...edits, [r.id]: { ...e, [k]: ev.target.value } })} /> : <span className="tabular-nums">{r[k] ?? "—"}</span>;
            return (
              <tr key={r.id} className="border-b border-line last:border-0">
                <td className="px-3 py-1.5 text-ink-600">{r.provider}</td><td className="px-3 py-1.5">{r.display_name || r.model} <code className="font-mono text-2xs text-ink-400">{r.model}</code></td>
                <td className="px-3 py-1.5">{cell("context_window")}</td><td className="px-3 py-1.5">{cell("input_per_mtok")}</td><td className="px-3 py-1.5">{cell("output_per_mtok")}</td><td className="px-3 py-1.5">{cell("cached_input_per_mtok")}</td>
                <td className="px-3 py-1.5 text-xs text-ink-400">{ago(r.updated_at)}</td>
              </tr>);
          })}</tbody>
        </table>
      </div>
      {admin && Object.keys(edits).length > 0 && <Button variant="primary" onClick={() => save(Object.entries(edits).map(([id, e]) => {
        const r = q.data!.find((x) => x.id === id)!;
        return { provider: r.provider, model: r.model, display_name: r.display_name, capabilities: r.capabilities, active: r.active,
          context_window: num(e.context_window ?? r.context_window), input_per_mtok: num(e.input_per_mtok ?? r.input_per_mtok), output_per_mtok: num(e.output_per_mtok ?? r.output_per_mtok), cached_input_per_mtok: num(e.cached_input_per_mtok ?? r.cached_input_per_mtok) };
      }))}>Save {Object.keys(edits).length} change(s)</Button>}
      {admin && (
        <div className="flex flex-wrap items-end gap-2 rounded-lg border border-line bg-paper p-3">
          {(["provider", "model", "context_window", "input_per_mtok", "output_per_mtok"] as const).map((k) => <Field key={k} label={k.replace(/_/g, " ")}><Input className="w-36" value={adding[k]} onChange={(e) => setAdding({ ...adding, [k]: e.target.value })} /></Field>)}
          <Button disabled={!adding.provider || !adding.model} onClick={() => save([{ provider: adding.provider, model: adding.model, context_window: num(adding.context_window), input_per_mtok: num(adding.input_per_mtok), output_per_mtok: num(adding.output_per_mtok) }])}>Add model</Button>
        </div>
      )}
    </div>
  );
}

