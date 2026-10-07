"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Badge, Icon, Select, Spinner, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, fmtCost, fmtMs, fmtTokens } from "@/lib/format";
import { useWorkspace } from "@/lib/session";
import type { Credential, ModelInfo, ModelRef, ProviderInfo, Run } from "@/lib/types";
import { routes } from "@/lib/routes";

export function RunsTable({ runs, showWorkflow = true, compareFrom }: { runs: Run[]; showWorkflow?: boolean; compareFrom?: (id: string) => void }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-paper">
      <table className="w-full text-sm">
        <thead className="border-b border-line text-left text-xs text-ink-400">
          <tr>
            <th className="px-4 py-2 font-medium">Status</th>
            {showWorkflow && <th className="px-4 py-2 font-medium">Workflow</th>}
            <th className="px-4 py-2 font-medium">Started</th>
            <th className="px-4 py-2 font-medium">Duration</th>
            <th className="px-4 py-2 text-right font-medium">Tokens</th>
            <th className="px-4 py-2 text-right font-medium">Cost (est.)</th>
            <th className="px-4 py-2 font-medium">Trigger</th>
            {compareFrom && <th />}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className="border-b border-line last:border-0 hover:bg-canvas/60">
              <td className="px-4 py-2"><Link href={routes.run(r.id)} className="inline-flex items-center gap-2"><StatusBadge status={r.status} /></Link></td>
              {showWorkflow && <td className="px-4 py-2"><Link href={routes.run(r.id)} className="font-medium text-ink-900 hover:text-accent-600">{r.workflow_name}</Link></td>}
              <td className="px-4 py-2 text-ink-600"><Link href={routes.run(r.id)}>{ago(r.created_at)}</Link></td>
              <td className="px-4 py-2 tabular-nums text-ink-600">{fmtMs(r.duration_ms)}</td>
              <td className="px-4 py-2 text-right tabular-nums text-ink-600">{fmtTokens(r.input_tokens + r.output_tokens)}</td>
              <td className="px-4 py-2 text-right tabular-nums text-ink-600">{fmtCost(r.cost_usd)}</td>
              <td className="px-4 py-2 text-ink-400">{r.parent_run_id ? "replay" : r.trigger}</td>
              {compareFrom && <td className="px-2"><button className="text-xs text-accent-600 hover:underline" onClick={() => compareFrom(r.id)}>Compare</button></td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function useProviders() {
  const { workspace } = useWorkspace();
  return useQuery({ queryKey: ["providers", workspace?.id], enabled: !!workspace, queryFn: () => api<ProviderInfo[]>(`/providers?workspace_id=${workspace!.id}`) });
}

export function useCredentials() {
  const { workspace } = useWorkspace();
  return useQuery({ queryKey: ["credentials", workspace?.id], enabled: !!workspace, queryFn: () => api<Credential[]>(`/workspaces/${workspace!.id}/credentials`) });
}

export function useModels(provider: string | undefined, credentialId?: string | null) {
  const { workspace } = useWorkspace();
  return useQuery({
    queryKey: ["models", workspace?.id, provider, credentialId || ""], enabled: !!workspace && !!provider, staleTime: 5 * 60_000,
    queryFn: () => api<{ models: ModelInfo[]; warning: string | null; source: string }>(
      `/providers/${provider}/models?workspace_id=${workspace!.id}${credentialId ? `&credential_id=${credentialId}` : ""}`),
  });
}

function fmtPrice(n: number) {
  return n === 0 ? "0" : n < 1 ? n.toFixed(n < 0.1 ? 3 : 2).replace(/0+$/, "") : String(+n.toFixed(2));
}

/** " · $2 in / $12 out per 1M tokens", " · free" for local models, "" when the price is unknown. */
function priceLabel(p: ModelInfo["pricing"]) {
  if (!p) return "";
  if (p.input_per_mtok === 0 && p.output_per_mtok === 0) return " · free";
  return ` · $${fmtPrice(p.input_per_mtok)} in / $${fmtPrice(p.output_per_mtok)} out per 1M tokens`;
}

/** Provider → credential → model. Only lists providers that exist on this server; flags unconfigured ones. */
export function ModelPicker({ value, onChange, compact, allowAuto }: { value: ModelRef; onChange: (v: ModelRef) => void; compact?: boolean; allowAuto?: boolean }) {
  const providers = useProviders();
  const creds = useCredentials();
  const models = useModels(value.provider && value.provider !== "auto" ? value.provider : undefined, value.credential_id);
  const provCreds = (creds.data || []).filter((c) => c.provider === value.provider);
  const current = providers.data?.find((p) => p.id === value.provider);
  const known = models.data?.models.some((m) => m.id === value.model);
  // Free-text model ids only where the server cannot know the list: local Ollama and custom OpenAI-compatible endpoints.
  const customIds = value.provider === "ollama" || value.provider === "openai_compatible";
  return (
    <div className={compact ? "grid grid-cols-2 gap-2" : "space-y-2"}>
      <Select aria-label="Provider" value={value.provider} onChange={(e) => onChange(e.target.value === "auto" ? { provider: "auto", model: "auto" } : { provider: e.target.value, model: "", credential_id: null })}>
        <option value="">Choose provider…</option>
        {allowAuto && <option value="auto">AUTO — let the harness choose</option>}
        {providers.data?.map((p) => (
          <option key={p.id} value={p.id}>{p.name}{!p.configured ? " (no key yet)" : ""}</option>
        ))}
      </Select>
      {value.provider && value.provider !== "auto" && (
        <div className="space-y-1">
          {models.isLoading ? <div className="flex h-9 items-center gap-2 text-xs text-ink-400"><Spinner /> Loading models…</div> : (
            <>
              <Select aria-label="Model" value={known || !value.model || !customIds ? value.model : "__custom"} onChange={(e) => onChange({ ...value, model: e.target.value === "__custom" ? value.model || "" : e.target.value })}>
                <option value="">Choose model…</option>
                {models.data?.models.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}{priceLabel(m.pricing)}</option>
                ))}
                {!known && value.model && !customIds && <option value={value.model}>{value.model} (not available with this key)</option>}
                {customIds && <option value="__custom">Other model id…</option>}
              </Select>
              {customIds && ((!known && value.model !== "") || (models.data && models.data.models.length === 0)) ? (
                <input aria-label="Model id" className="h-8 w-full rounded-md border border-line px-2 font-mono text-xs" placeholder="model id, e.g. llama3.1:8b"
                  value={value.model} onChange={(e) => onChange({ ...value, model: e.target.value.trim() })} />
              ) : null}
              {!known && value.model && !customIds && models.data && models.data.models.length > 0 && (
                <p className="flex items-center gap-1 text-xs text-warn"><Icon name="TriangleAlert" size={12} />
                  {value.model} is not offered for this key or has no known price. Choose a listed model.</p>
              )}
            </>
          )}
          {!compact && provCreds.length > 1 && (
            <Select aria-label="Credential" value={value.credential_id || ""} onChange={(e) => onChange({ ...value, credential_id: e.target.value || null })}>
              <option value="">Default key ({provCreds[0].name})</option>
              {provCreds.map((c) => <option key={c.id} value={c.id}>{c.name} ····{c.hint}</option>)}
            </Select>
          )}
          {current && !current.configured && (
            <p className="flex items-center gap-1 text-xs text-warn"><Icon name="TriangleAlert" size={12} />
              No {current.name} key in this workspace. <Link href="/providers" className="underline">Add one</Link></p>
          )}
          {current?.is_test && <Badge tone="warn">Test provider — deterministic, not an AI model</Badge>}
          {models.data?.warning && (current?.configured || models.data.models.length === 0) && <p className="text-xs text-ink-400">{models.data.warning}</p>}
        </div>
      )}
    </div>
  );
}
