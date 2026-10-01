"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Badge, Button, Code, Dialog, Empty, ErrorBox, Field, Icon, Input, Select, Spinner, Textarea, Toggle, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { ago } from "@/lib/format";
import { useWorkspace } from "@/lib/session";
import type { Workflow } from "@/lib/types";

const KINDS = [["webhook", "Webhook", "Webhook", "A signed HTTP request starts the workflow"], ["schedule", "Schedule", "CalendarClock", "Runs on a cron schedule"],
  ["event", "Event", "Radio", "Runs when an event is published"], ["file", "File upload", "FileInput", "Runs when a file is uploaded to this project"]] as const;

export function Triggers({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const { workspace } = useWorkspace();
  const list = useQuery({ queryKey: ["triggers", projectId], queryFn: () => api<any[]>(`/projects/${projectId}/triggers`) });
  const wfs = useQuery({ queryKey: ["workflows", projectId, false], queryFn: () => api<Workflow[]>(`/projects/${projectId}/workflows`) });
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState<any | null>(null);
  const [form, setForm] = useState<any>({ kind: "webhook", name: "", workflow_id: "", config: { cron: "daily", timezone: "UTC", auth: "hmac" } });
  const [err, setErr] = useState<unknown>(null);
  const [preview, setPreview] = useState<string[]>([]);
  const [event, setEvent] = useState({ name: "", correlation_key: "", payload: "{}" });
  useEffect(() => {
    if (form.kind !== "schedule" || !form.config.cron) return;
    const t = setTimeout(() => api<{ next: string[] }>(`/schedules/preview?cron=${encodeURIComponent(form.config.cron)}&timezone=${encodeURIComponent(form.config.timezone || "UTC")}`)
      .then((r) => setPreview(r.next), () => setPreview([])), 300);
    return () => clearTimeout(t);
  }, [form.kind, form.config.cron, form.config.timezone]);
  async function create() {
    setErr(null);
    try {
      const cfg = { ...form.config };
      if (form.kind === "file" && typeof cfg.extensions === "string") cfg.extensions = cfg.extensions.split(",").map((x: string) => x.trim()).filter(Boolean);
      const t = await api<any>(`/projects/${projectId}/triggers`, { body: { ...form, config: cfg } });
      setOpen(false); setCreated(t); qc.invalidateQueries({ queryKey: ["triggers", projectId] });
    } catch (e) { setErr(e); }
  }
  async function toggle(t: any) {
    await api(`/triggers/${t.id}`, { method: "PUT", body: { ...t, enabled: !t.enabled } }).catch((e) => toast(errorMessage(e), "error"));
    qc.invalidateQueries({ queryKey: ["triggers", projectId] });
  }
  async function publishEvent() {
    try {
      const r = await api<any>(`/workspaces/${workspace!.id}/events`, { body: { name: event.name, correlation_key: event.correlation_key || null, payload: JSON.parse(event.payload || "{}") } });
      toast(`Resumed ${r.runs_resumed} waiting run(s), started ${r.runs_started.length}`);
    } catch (e) { toast(errorMessage(e), "error"); }
  }
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const wfName = (id: string) => wfs.data?.find((w) => w.id === id)?.name || "workflow";
  return (
    <div className="space-y-6">
      <div className="flex justify-end"><Button variant="primary" icon="Plus" onClick={() => setOpen(true)}>New trigger</Button></div>
      {list.isLoading ? <Spinner /> : !list.data?.length ? (
        <Empty icon="Zap" title="No triggers" body="Start published workflows from webhooks, schedules, events or file uploads — no one has to press Run." />
      ) : (
        <div className="divide-y divide-line rounded-lg border border-line bg-paper shadow-card">
          {list.data.map((t) => {
            const k = KINDS.find((x) => x[0] === t.kind)!;
            return (
              <div key={t.id} className="flex items-center gap-4 px-4 py-3">
                <span className="rounded-md bg-canvas p-2 text-ink-600"><Icon name={k[2]} /></span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 font-medium">{t.name}<Badge>{k[1]}</Badge>{!t.enabled && <Badge tone="warn">disabled</Badge>}</div>
                  <div className="truncate text-xs text-ink-500">→ {wfName(t.workflow_id)}
                    {t.kind === "schedule" && ` · ${t.config.cron} ${t.config.timezone} · next ${t.next_run_at ? new Date(t.next_run_at).toLocaleString() : "—"}`}
                    {t.kind === "event" && ` · on ${t.config.event_name}`}
                    {t.kind === "webhook" && <> · <code className="font-mono">{origin}{t.path}</code></>}
                    {t.last_run_at && ` · last ${ago(t.last_run_at)}`}</div>
                  {t.config.last_error && <div className="text-xs text-state-failed">Last attempt failed: {t.config.last_error}</div>}
                </div>
                <Toggle checked={t.enabled} onChange={() => toggle(t)} label="" />
                <button aria-label="Delete trigger" className="text-ink-400 hover:text-state-failed" onClick={async () => { if (confirm(`Delete ${t.name}?`)) { await api(`/triggers/${t.id}`, { method: "DELETE" }); qc.invalidateQueries({ queryKey: ["triggers", projectId] }); } }}><Icon name="Trash2" /></button>
              </div>
            );
          })}
        </div>
      )}
      <section className="rounded-lg border border-line bg-paper p-4 shadow-card">
        <h3 className="text-sm font-semibold">Publish a test event</h3>
        <p className="mt-0.5 text-xs text-ink-500">Resumes runs waiting for this event (matching correlation key) and starts event-triggered workflows. From code: <code className="font-mono">POST /api/v1/workspaces/{"{id}"}/events</code> with an access token.</p>
        <div className="mt-3 grid grid-cols-[1fr_1fr_2fr_auto] items-end gap-2">
          <Field label="Event name"><Input value={event.name} onChange={(e) => setEvent({ ...event, name: e.target.value })} placeholder="order.paid" /></Field>
          <Field label="Correlation key"><Input value={event.correlation_key} onChange={(e) => setEvent({ ...event, correlation_key: e.target.value })} /></Field>
          <Field label="Payload"><Input className="font-mono text-xs" value={event.payload} onChange={(e) => setEvent({ ...event, payload: e.target.value })} /></Field>
          <Button disabled={!event.name} onClick={publishEvent}>Publish</Button>
        </div>
      </section>
      <Dialog open={open} onClose={() => setOpen(false)} title="New trigger" wide
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" onClick={create} disabled={!form.name || !form.workflow_id}>Create trigger</Button></>}>
        <div className="space-y-4">
          <ErrorBox error={err} />
          <div className="grid grid-cols-4 gap-2">
            {KINDS.map(([k, l, icon, d]) => (
              <button key={k} onClick={() => setForm({ ...form, kind: k })} className={`rounded-md border p-2.5 text-left text-xs ${form.kind === k ? "border-accent-500 bg-accent-50" : "border-line"}`}>
                <Icon name={icon} className="text-accent-500" /><div className="mt-1 font-medium">{l}</div><div className="text-ink-500">{d}</div></button>))}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Workflow"><Select value={form.workflow_id} onChange={(e) => setForm({ ...form, workflow_id: e.target.value })}>
              <option value="">Choose…</option>{wfs.data?.map((w) => <option key={w.id} value={w.id} disabled={!w.latest_version}>{w.name}{!w.latest_version ? " (not published)" : ""}</option>)}</Select></Field>
          </div>
          <p className="text-xs text-ink-500">Triggers run the latest published version of the workflow.</p>
          {form.kind === "schedule" && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Schedule" hint="hourly, daily, weekly, monthly, or cron (min hour day month weekday)"><Input className="font-mono" value={form.config.cron} onChange={(e) => setForm({ ...form, config: { ...form.config, cron: e.target.value } })} /></Field>
              <Field label="Time zone"><Input value={form.config.timezone} onChange={(e) => setForm({ ...form, config: { ...form.config, timezone: e.target.value } })} placeholder="Asia/Kolkata" /></Field>
              <div className="col-span-2 text-xs text-ink-500">{preview.length ? <>Next runs: {preview.slice(0, 3).map((p) => new Date(p).toLocaleString()).join(" · ")}</> : "Enter a valid schedule to preview."}</div>
            </div>
          )}
          {form.kind === "event" && <Field label="Event name"><Input value={form.config.event_name || ""} onChange={(e) => setForm({ ...form, config: { ...form.config, event_name: e.target.value } })} placeholder="lead.created" /></Field>}
          {form.kind === "file" && <Field label="Only these extensions (optional)"><Input value={form.config.extensions || ""} onChange={(e) => setForm({ ...form, config: { ...form.config, extensions: e.target.value } })} placeholder=".csv, .pdf" /></Field>}
          {form.kind === "webhook" && (
            <Field label="Authentication"><Select value={form.config.auth} onChange={(e) => setForm({ ...form, config: { ...form.config, auth: e.target.value } })}>
              <option value="hmac">HMAC signature + timestamp (recommended; replay-protected)</option><option value="token">Shared secret header</option></Select></Field>
          )}
          {form.kind !== "schedule" && <Field label="Payload schema (optional JSON)"><Textarea mono rows={2} placeholder='{"email": "string"}' onBlur={(e) => { try { setForm({ ...form, config: { ...form.config, payload_schema: e.target.value ? JSON.parse(e.target.value) : undefined } }); } catch { toast("Schema must be JSON", "error"); } }} /></Field>}
        </div>
      </Dialog>
      {created?.secret && (
        <Dialog open onClose={() => setCreated(null)} title="Webhook created" wide footer={<Button onClick={() => setCreated(null)}>I&apos;ve stored the secret</Button>}>
          <div className="space-y-3 text-sm">
            <p className="font-medium text-warn">Copy the signing secret now. It won&apos;t be shown again.</p>
            <Code value={created.secret} maxH="max-h-20" />
            <p>POST to <code className="font-mono text-xs">{origin}{created.path}</code>{created.config.auth === "hmac" ? " with headers:" : " with header X-Isocline-Token: <secret>"}</p>
            {created.config.auth === "hmac" && <Code value={`ts=$(date +%s)
body='{"company":"Acme"}'
sig="sha256=$(printf '%s.%s' "$ts" "$body" | openssl dgst -sha256 -hmac "$SECRET" -hex | sed 's/^.* //')"
curl -X POST ${origin}${created.path} \\
  -H "X-Isocline-Timestamp: $ts" -H "X-Isocline-Signature: $sig" \\
  -H "Content-Type: application/json" -d "$body"`} />}
            <p className="text-xs text-ink-500">Signatures older than 5 minutes are rejected and each signature works once. Send an Idempotency-Key header to make retries safe.</p>
          </div>
        </Dialog>
      )}
    </div>
  );
}
