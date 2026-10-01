"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Button, Dialog, Empty, ErrorBox, Field, Input, Spinner, StatusBadge, toast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { ago } from "@/lib/format";

interface KB { id: string; name: string; description: string; chunk_size: number; chunk_overlap: number; document_count: number }
interface Doc { id: string; filename: string; size_bytes: number; status: string; error: string | null; chunk_count: number; created_at: string }

export function Knowledge({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const kbs = useQuery({ queryKey: ["kbs", projectId], queryFn: () => api<KB[]>(`/projects/${projectId}/knowledge-bases`) });
  const files = useQuery({ queryKey: ["files", projectId], queryFn: () => api<(Doc & { knowledge_base_id: string | null })[]>(`/projects/${projectId}/documents`) });
  const [sel, setSel] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", chunk_size: 1000, chunk_overlap: 150 });
  const [err, setErr] = useState<unknown>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const current = kbs.data?.find((k) => k.id === sel) || kbs.data?.[0];
  const docs = useQuery({
    queryKey: ["docs", current?.id], enabled: !!current, queryFn: () => api<Doc[]>(`/knowledge-bases/${current!.id}/documents`),
    refetchInterval: (q) => (q.state.data?.some((d) => d.status === "pending" || d.status === "processing") ? 2000 : false),
  });
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<any[] | null>(null);

  async function create() {
    setErr(null);
    try { const k = await api<KB>(`/projects/${projectId}/knowledge-bases`, { body: form }); setCreating(false); setSel(k.id); qc.invalidateQueries({ queryKey: ["kbs", projectId] }); }
    catch (e) { setErr(e); }
  }
  async function upload(list: FileList, target: "kb" | "project") {
    for (const f of Array.from(list)) {
      const form = new FormData();
      form.append("file", f);
      try {
        await api(target === "kb" ? `/knowledge-bases/${current!.id}/documents` : `/projects/${projectId}/documents`, { form });
        toast(`Uploaded ${f.name}`);
      } catch (e) { toast(`${f.name}: ${errorMessage(e)}`, "error"); }
    }
    qc.invalidateQueries({ queryKey: ["docs"] }); qc.invalidateQueries({ queryKey: ["kbs", projectId] }); qc.invalidateQueries({ queryKey: ["files", projectId] });
  }
  async function del(d: Doc) {
    if (!confirm(`Delete ${d.filename}?`)) return;
    await api(`/documents/${d.id}`, { method: "DELETE" }).catch((e) => toast(errorMessage(e), "error"));
    qc.invalidateQueries({ queryKey: ["docs"] }); qc.invalidateQueries({ queryKey: ["files", projectId] });
  }
  async function search() {
    try { setResults((await api<{ results: any[] }>(`/knowledge-bases/${current!.id}/search`, { body: { query } })).results); }
    catch (e) { toast(errorMessage(e), "error"); }
  }

  if (kbs.isLoading) return <Spinner />;
  const loose = (files.data || []).filter((f) => !f.knowledge_base_id);
  return (
    <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
      <aside className="space-y-2">
        <div className="flex items-center justify-between"><h2 className="text-sm font-semibold">Knowledge bases</h2>
          <Button size="sm" icon="Plus" onClick={() => setCreating(true)}>New</Button></div>
        {kbs.data?.map((k) => (
          <button key={k.id} onClick={() => { setSel(k.id); setResults(null); }}
            className={`block w-full rounded-md border px-3 py-2 text-left text-sm ${current?.id === k.id ? "border-accent-500 bg-accent-50" : "border-line bg-paper hover:border-ink-300"}`}>
            <div className="font-medium">{k.name}</div><div className="text-xs text-ink-400">{k.document_count} documents</div>
          </button>
        ))}
        <div className="pt-4">
          <h2 className="text-sm font-semibold">Project files</h2>
          <p className="mb-2 text-xs text-ink-400">For File input nodes and the File reader tool. Not embedded.</p>
          <Button size="sm" icon="Upload" onClick={() => { const i = document.createElement("input"); i.type = "file"; i.multiple = true; i.accept = ".pdf,.docx,.txt,.md,.csv,.json"; i.onchange = () => i.files && upload(i.files, "project"); i.click(); }}>Upload file</Button>
          <ul className="mt-2 space-y-1 text-xs">
            {loose.map((f) => <li key={f.id} className="flex justify-between gap-2"><span className="truncate" title={f.id}>{f.filename}</span>
              <button className="shrink-0 text-accent-600" onClick={() => { navigator.clipboard.writeText(f.id); toast("Document id copied"); }}>copy id</button></li>)}
          </ul>
        </div>
      </aside>
      <section>
        {!current ? (
          <Empty icon="Library" title="No knowledge bases" body="Upload documents so agents can retrieve relevant passages (RAG). Attach a knowledge base to an agent in its settings."
            action={<Button variant="primary" icon="Plus" onClick={() => setCreating(true)}>New knowledge base</Button>} />
        ) : (
          <div className="space-y-5">
            <div className="flex items-start justify-between">
              <div><h2 className="font-semibold">{current.name}</h2><p className="text-xs text-ink-400">Chunks of {current.chunk_size} characters with {current.chunk_overlap} overlap</p></div>
              <div className="flex gap-2">
                <input ref={fileInput} type="file" multiple accept=".pdf,.docx,.txt,.md,.csv,.json" className="hidden" onChange={(e) => e.target.files && upload(e.target.files, "kb")} />
                <Button icon="Upload" variant="primary" onClick={() => fileInput.current?.click()}>Upload documents</Button>
                <Button variant="ghost" icon="Trash2" onClick={async () => { if (confirm(`Delete ${current.name} and its documents?`)) { await api(`/knowledge-bases/${current.id}`, { method: "DELETE" }); setSel(null); qc.invalidateQueries({ queryKey: ["kbs", projectId] }); } }} />
              </div>
            </div>
            <div className="overflow-hidden rounded-lg border border-line bg-paper">
              <table className="w-full text-sm">
                <thead className="border-b border-line text-left text-xs text-ink-400"><tr><th className="px-4 py-2 font-medium">File</th><th className="px-4 py-2 font-medium">Status</th><th className="px-4 py-2 font-medium">Chunks</th><th className="px-4 py-2 font-medium">Size</th><th className="px-4 py-2 font-medium">Added</th><th /></tr></thead>
                <tbody>
                  {docs.data?.length === 0 && <tr><td colSpan={6} className="px-4 py-6 text-center text-ink-400">PDF, DOCX, TXT, Markdown, CSV and JSON up to the upload limit.</td></tr>}
                  {docs.data?.map((d) => (
                    <tr key={d.id} className="border-b border-line last:border-0">
                      <td className="px-4 py-2">{d.filename}{d.error && <div className="text-xs text-state-failed">{d.error}</div>}</td>
                      <td className="px-4 py-2"><StatusBadge status={d.status === "ready" ? "completed" : d.status === "processing" ? "running" : d.status} /></td>
                      <td className="px-4 py-2 tabular-nums">{d.chunk_count}</td>
                      <td className="px-4 py-2 tabular-nums text-ink-600">{(d.size_bytes / 1024).toFixed(0)} KB</td>
                      <td className="px-4 py-2 text-ink-600">{ago(d.created_at)}</td>
                      <td className="px-4 py-2 text-right">
                        {d.status === "failed" && <button className="mr-3 text-xs text-accent-600" onClick={() => api(`/documents/${d.id}/reprocess`, { method: "POST" }).then(() => qc.invalidateQueries({ queryKey: ["docs"] }))}>Retry</button>}
                        <button className="text-xs text-state-failed" onClick={() => del(d)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="rounded-lg border border-line bg-paper p-4">
              <h3 className="text-sm font-semibold">Test retrieval</h3>
              <div className="mt-2 flex gap-2"><Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Ask something the documents should answer" onKeyDown={(e) => e.key === "Enter" && query && search()} />
                <Button onClick={search} disabled={!query}>Search</Button></div>
              {results && (results.length === 0 ? <p className="mt-3 text-sm text-ink-400">No passages found.</p> : (
                <ol className="mt-3 space-y-2">
                  {results.map((r, i) => <li key={i} className="rounded-md bg-canvas p-2.5 text-sm"><div className="mb-1 text-xs text-ink-400">{r.source} · chunk {r.chunk} · score {r.score}</div>{r.content.slice(0, 500)}</li>)}
                </ol>
              ))}
            </div>
          </div>
        )}
      </section>
      <Dialog open={creating} onClose={() => setCreating(false)} title="New knowledge base"
        footer={<><Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button><Button variant="primary" disabled={!form.name} onClick={create}>Create</Button></>}>
        <div className="space-y-4">
          <ErrorBox error={err} />
          <Field label="Name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Chunk size (characters)"><Input type="number" value={form.chunk_size} onChange={(e) => setForm({ ...form, chunk_size: +e.target.value })} /></Field>
            <Field label="Overlap"><Input type="number" value={form.chunk_overlap} onChange={(e) => setForm({ ...form, chunk_overlap: +e.target.value })} /></Field>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
