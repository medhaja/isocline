"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Badge, Button, Dialog, ErrorBox, Field, Input, Select, Spinner, Textarea, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { ago } from "@/lib/format";
import type { ExecutionPlan, WFNode } from "@/lib/types";
import { useBuilder } from "@/store/builder";
import PlanView from "./PlanView";

const memKey = (id: string) => `isc_run_input:${id}`;

export function RunDialog({ open, onClose, workflowId, projectId, inputs, onStart, error, goalMode }: {
  open: boolean; onClose: () => void; workflowId: string; projectId: string; inputs: WFNode[];
  onStart: (input: Record<string, any>) => Promise<void>; error: unknown; goalMode?: boolean;
}) {
  const plan = useQuery({ queryKey: ["plan", workflowId, open], enabled: open, retry: false,
    queryFn: () => api<ExecutionPlan>(`/workflows/${workflowId}/plan`, { body: { graph: useBuilder.getState().graph() } }) });
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [localErr, setLocalErr] = useState<string | null>(null);
  const files = useQuery({ queryKey: ["files", projectId], enabled: open && inputs.some((n) => n.type === "input_file"), queryFn: () => api<any[]>(`/projects/${projectId}/documents`) });
  useEffect(() => {
    if (!open) return;
    try { setValues(JSON.parse(localStorage.getItem(memKey(workflowId)) || "{}")); } catch { setValues({}); }
    setLocalErr(null);
  }, [open, workflowId]);

  async function start() {
    const input: Record<string, any> = {};
    for (const n of inputs) {
      if (n.type.startsWith("trigger_")) {
        const raw = values["__payload"] ?? "";
        if (raw) { try { Object.assign(input, JSON.parse(raw)); } catch { return setLocalErr("The trigger payload must be valid JSON"); } }
        continue;
      }
      const f = n.config.field || n.key;
      const raw = values[f] ?? "";
      if (!raw && n.config.required !== false && (n.config.default === null || n.config.default === undefined || n.config.default === "")) return setLocalErr(`“${n.config.label || n.name}” is required`);
      if (n.type === "input_json" && raw) { try { input[f] = JSON.parse(raw); } catch { return setLocalErr(`“${n.name}” must be valid JSON`); } }
      else if (n.type === "input_chat" && raw) input[f] = raw;
      else if (raw) input[f] = raw;
    }
    setLocalErr(null);
    try { localStorage.setItem(memKey(workflowId), JSON.stringify(values)); } catch { /* ignore */ }
    setBusy(true);
    try { await onStart(input); } finally { setBusy(false); }
  }

  return (
    <Dialog open={open} onClose={onClose} title="Run workflow"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" icon="Play" loading={busy} onClick={start} data-autofocus
        disabled={plan.data?.status === "BLOCKED"} title={plan.data?.status === "BLOCKED" ? "Preflight blocked this run" : undefined}>Start run</Button></>} wide>
      <div className="grid gap-5 md:grid-cols-[1fr_1fr]">
      <div className="space-y-4">
        <ErrorBox error={localErr || error} title={error ? "The workflow can't run yet" : undefined} />
        {inputs.length === 0 && <p className="text-sm text-ink-600">This workflow has no input nodes, so it runs without input.</p>}
        {goalMode && <p className="rounded-md bg-accent-50 p-2.5 text-xs text-ink-700">Goal Mode: the harness planner composes the steps inside the limits in workflow settings. The plan is shown on the run page.</p>}
        {inputs.some((n) => n.type.startsWith("trigger_")) && (
          <Field label="Test trigger payload (JSON)" hint="Triggered runs normally start from the Triggers tab or an external system."><Textarea mono rows={4} value={values["__payload"] ?? ""} onChange={(e) => setValues({ ...values, __payload: e.target.value })} placeholder='{"email": "a@b.com"}' /></Field>
        )}
        {inputs.filter((n) => !n.type.startsWith("trigger_")).map((n) => {
          const f = n.config.field || n.key;
          const label = n.config.label || n.name;
          const set = (v: string) => setValues({ ...values, [f]: v });
          return (
            <Field key={n.id} label={`${label}${n.config.required === false ? " (optional)" : ""}`} hint={<code className="font-mono">{`{{input.${f}}}`}</code>}>
              {n.type === "input_json" ? <Textarea mono rows={5} value={values[f] ?? ""} onChange={(e) => set(e.target.value)} placeholder='{"key": "value"}' />
                : n.type === "input_file" ? <Select value={values[f] ?? ""} onChange={(e) => set(e.target.value)}><option value="">Choose a project file…</option>{files.data?.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}</Select>
                : n.type === "input_url" ? <Input type="url" value={values[f] ?? ""} onChange={(e) => set(e.target.value)} placeholder="https://" />
                : <Textarea rows={n.type === "input_chat" ? 4 : 2} value={values[f] ?? ""} onChange={(e) => set(e.target.value)} placeholder={n.config.default ? `Default: ${n.config.default}` : undefined} />}
            </Field>
          );
        })}
        <p className="text-xs text-ink-400">Runs keep going on the server if you close this page. Limits from workflow settings apply.</p>
      </div>
      <div>
        <div className="mb-2 text-xs font-semibold text-ink-700">Execution plan & preflight</div>
        {plan.isLoading ? <Spinner /> : plan.error ? <ErrorBox error={plan.error} /> : plan.data && <PlanView plan={plan.data} />}
      </div>
      </div>
    </Dialog>
  );
}

export function VersionsDialog({ open, onClose, workflowId, onRestored, latest }: { open: boolean; onClose: () => void; workflowId: string; onRestored: (g: any, rev: number) => void; latest: number }) {
  const qc = useQueryClient();
  const versions = useQuery({ queryKey: ["versions", workflowId], enabled: open, queryFn: () => api<any[]>(`/workflows/${workflowId}/versions`) });
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function publish() {
    setBusy(true); setErr(null);
    try {
      const v = await api<any>(`/workflows/${workflowId}/publish`, { body: { notes } });
      toast(`Published version ${v.version}`); setNotes("");
      qc.invalidateQueries({ queryKey: ["versions", workflowId] }); qc.invalidateQueries({ queryKey: ["workflow", workflowId] });
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  async function restore(v: number) {
    if (!confirm(`Replace the current draft with version ${v}? The draft's current state can be undone with ⌘Z until you leave the page.`)) return;
    try { const wf = await api<any>(`/workflows/${workflowId}/versions/${v}/restore`, { method: "POST" }); onRestored(wf.graph, wf.revision); toast(`Draft restored from v${v}`); onClose(); }
    catch (e) { toast(errorMessage(e), "error"); }
  }
  return (
    <Dialog open={open} onClose={onClose} title="Versions" wide>
      <div className="space-y-5">
        <div className="rounded-md border border-line p-3">
          <h3 className="text-sm font-semibold">Publish the current draft</h3>
          <p className="mt-0.5 text-xs text-ink-400">Creates version {latest + 1}, an immutable snapshot that triggers, sub-workflows and evaluations can target. Your draft stays editable.</p>
          <ErrorBox error={err} />
          <div className="mt-2 flex gap-2"><Input placeholder="What changed? (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} /><Button variant="primary" loading={busy} onClick={publish}>Publish</Button></div>
        </div>
        {versions.isLoading ? <Spinner /> : !versions.data?.length ? <p className="text-sm text-ink-400">No published versions yet.</p> : (
          <ul className="divide-y divide-line rounded-md border border-line">
            {versions.data.map((v) => (
              <li key={v.id} className="flex items-center justify-between px-3 py-2.5 text-sm">
                <span><span className="font-medium">v{v.version}</span>{v.version === latest && <Badge tone="blue" className="ml-2">latest</Badge>}
                  <span className="ml-2 text-ink-400">{ago(v.created_at)} · {v.node_count} nodes</span>{v.notes && <span className="block text-xs text-ink-600">{v.notes}</span>}</span>
                <span className="flex gap-3 text-xs">
                  <a className="text-accent-600 hover:underline" href={`/api/v1/workflows/${workflowId}/export?version=${v.version}`}>Export</a>
                  <button className="text-accent-600 hover:underline" onClick={() => restore(v.version)}>Restore to draft</button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Dialog>
  );
}
