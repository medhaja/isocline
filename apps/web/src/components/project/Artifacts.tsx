"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Code, Empty, Icon, Input, Select, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";

const KIND_ICON: Record<string, string> = { csv: "Sheet", json: "Braces", pdf: "FileText", image: "Image", text: "FileText", report: "ScrollText", code: "FileCode", zip: "FileArchive", table: "Table" };

export function Artifacts({ projectId }: { projectId: string }) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const list = useQuery({ queryKey: ["artifacts", projectId, q, kind], queryFn: () => api<any[]>(`/projects/${projectId}/artifacts?${new URLSearchParams({ ...(q ? { q } : {}), ...(kind ? { kind } : {}) })}`) });
  const detail = useQuery({ queryKey: ["artifact", sel], enabled: !!sel, queryFn: () => api<any>(`/artifacts/${sel}`) });
  const preview = useQuery({ queryKey: ["artifact-preview", sel], enabled: !!sel, queryFn: () => api<any>(`/artifacts/${sel}/preview`) });
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_420px]">
      <div className="space-y-3">
        <div className="flex gap-2">
          <Input placeholder="Search by name or producing node" value={q} onChange={(e) => setQ(e.target.value)} />
          <Select className="w-40" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Type">
            <option value="">All types</option>{["csv", "json", "pdf", "image", "text", "report", "code", "zip"].map((k) => <option key={k}>{k}</option>)}</Select>
        </div>
        {list.isLoading ? <Spinner /> : !list.data?.length ? <Empty icon="FileBox" title="No artifacts" body="Files produced by runs (sandbox outputs, file outputs, file inputs passed as artifacts) appear here with their lineage." /> : (
          <div className="divide-y divide-line rounded-lg border border-line bg-paper shadow-card">
            {list.data.map((a) => (
              <button key={a.id} onClick={() => setSel(a.id)} className={`flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-canvas/60 ${sel === a.id ? "bg-accent-50/50" : ""}`}>
                <Icon name={KIND_ICON[a.kind] || "File"} className="text-ink-400" />
                <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{a.name}</span>
                  <span className="text-xs text-ink-500">{a.node_key ? `by ${a.node_key}` : "uploaded"} · {(a.size_bytes / 1024).toFixed(1)} KB · {ago(a.created_at)}</span></span>
                <Badge>{a.kind}</Badge>
              </button>
            ))}
          </div>
        )}
      </div>
      <aside className="space-y-4">
        {!sel ? <p className="text-sm text-ink-400">Select an artifact to preview it and inspect its lineage.</p> : !detail.data ? <Spinner /> : (
          <div className="space-y-4 rounded-lg border border-line bg-paper p-4 shadow-card">
            <div><div className="font-semibold">{detail.data.name}</div>
              <div className="text-xs text-ink-500">{detail.data.mime} · sha256 {detail.data.checksum.slice(0, 12)}…</div></div>
            <div className="flex gap-2">
              <a href={`/api/v1/artifacts/${sel}/download`}><Button size="sm" icon="Download">Download</Button></a>
              {detail.data.run_id && <Link href={`/runs/${detail.data.run_id}`}><Button size="sm" variant="ghost">Open producing run</Button></Link>}
            </div>
            {preview.data?.type === "image" && <img src={preview.data.data_url} alt={detail.data.name} className="max-h-64 rounded-md border border-line" />}
            {preview.data?.type === "text" && <Code value={preview.data.text} maxH="max-h-64" />}
            {preview.data?.type === "table" && (
              <div className="max-h-64 overflow-auto rounded-md border border-line"><table className="w-full text-xs">
                <thead className="bg-canvas"><tr>{Object.keys(preview.data.rows[0] || {}).map((k) => <th key={k} className="px-2 py-1 text-left font-medium">{k}</th>)}</tr></thead>
                <tbody>{preview.data.rows.map((r: any, i: number) => <tr key={i} className="border-t border-line">{Object.values(r).map((v: any, j) => <td key={j} className="px-2 py-1">{String(v)}</td>)}</tr>)}</tbody>
              </table></div>)}
            {preview.data?.type === "binary" && <p className="text-xs text-ink-400">{preview.data.note}</p>}
            <div>
              <div className="mb-1 text-xs font-semibold">Lineage</div>
              {detail.data.lineage.edges.length === 0 ? <p className="text-xs text-ink-400">No parent or derived artifacts.</p> : (
                <ul className="space-y-0.5 text-xs">{detail.data.lineage.edges.map((e: any, i: number) => {
                  const f = detail.data.lineage.nodes.find((n: any) => n.id === e.from), t = detail.data.lineage.nodes.find((n: any) => n.id === e.to);
                  return <li key={i}><button className="text-accent-600" onClick={() => setSel(e.from)}>{f?.name}</button> → <button className="text-accent-600" onClick={() => setSel(e.to)}>{t?.name}</button>{e.transformation && <span className="text-ink-400"> ({e.transformation})</span>}</li>;
                })}</ul>)}
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold">Produced by / consumed by</div>
              <p className="text-xs text-ink-600">{detail.data.node_key ? `Node ${detail.data.node_key}` : "Upload"}{detail.data.transformation ? ` via ${detail.data.transformation}` : ""}</p>
              {detail.data.consumers.map((c: any, i: number) => <p key={i} className="text-xs text-ink-600">→ {c.node_key} in <Link className="text-accent-600" href={`/runs/${c.run_id}`}>run {c.run_id.slice(0, 8)}</Link></p>)}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
