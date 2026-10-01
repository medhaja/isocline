"use client";
import clsx from "clsx";
import { useState } from "react";
import { Badge, Button, Code, Icon, StatusBadge, Tabs } from "@/components/ui";
import { fmtCost, fmtMs, fmtTokens, toText } from "@/lib/format";
import type { NodeRun, Run, RunEvent, WFNode } from "@/lib/types";

/* Minimal, safe markdown rendering (headings, lists, bold, code, links) — no HTML injection. */
export function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: React.ReactNode[] = [];
  let list: string[] = [];
  let ordered = false;
  const inline = (s: string, k: number) => {
    const parts = s.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g);
    return <span key={k}>{parts.map((p, i) => {
      if (/^\*\*[^*]+\*\*$/.test(p)) return <strong key={i}>{p.slice(2, -2)}</strong>;
      if (/^`[^`]+`$/.test(p)) return <code key={i}>{p.slice(1, -1)}</code>;
      const m = p.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
      if (m) return <a key={i} href={m[2]} target="_blank" rel="noopener noreferrer nofollow">{m[1]}</a>;
      return p;
    })}</span>;
  };
  const flush = () => {
    if (!list.length) return;
    const items = list.map((l, i) => <li key={i}>{inline(l, i)}</li>);
    out.push(ordered ? <ol key={out.length}>{items}</ol> : <ul key={out.length}>{items}</ul>);
    list = [];
  };
  lines.forEach((l, i) => {
    const h = l.match(/^(#{1,3})\s+(.*)/);
    const ul = l.match(/^\s*[-*]\s+(.*)/);
    const ol = l.match(/^\s*\d+[.)]\s+(.*)/);
    if (ul || ol) { if (list.length && ordered !== !!ol) flush(); ordered = !!ol; list.push((ul || ol)![1]); return; }
    flush();
    if (h) { const T = (`h${h[1].length}`) as "h1" | "h2" | "h3"; out.push(<T key={i}>{inline(h[2], i)}</T>); }
    else if (l.trim()) out.push(<p key={i}>{inline(l, i)}</p>);
  });
  flush();
  return <div className="prose-report text-sm text-ink-900">{out}</div>;
}

export function OutputView({ value }: { value: any }) {
  const [raw, setRaw] = useState(false);
  if (value === null || value === undefined) return <p className="text-sm text-ink-400">No output.</p>;
  const isText = typeof value === "string";
  const isFile = value && typeof value === "object" && "filename" in value && "content" in value;
  return (
    <div className="space-y-2">
      <div className="flex justify-end gap-2">
        {isFile && <Button size="sm" icon="Download" onClick={() => download(value.filename, value.content)}>Download {value.filename}</Button>}
        <Button size="sm" variant="ghost" icon="Copy" onClick={() => navigator.clipboard.writeText(toText(value))}>Copy</Button>
        {isText && <Button size="sm" variant="ghost" onClick={() => setRaw(!raw)}>{raw ? "Formatted" : "Raw"}</Button>}
      </div>
      {isText && !raw ? <div className="rounded-md border border-line bg-paper p-4"><Markdown text={value} /></div> : <Code value={isFile ? value.content : value} maxH="max-h-[60vh]" />}
    </div>
  );
}

function download(name: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/plain" }));
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  URL.revokeObjectURL(url);
}

export function RunSummary({ run }: { run: Run }) {
  const items = [
    ["Status", <StatusBadge key="s" status={run.status} />],
    ["Duration", fmtMs(run.duration_ms ?? (run.started_at ? Date.now() - new Date(run.started_at).getTime() : null))],
    ["Model calls", `${run.llm_calls} / ${run.limits?.max_llm_calls ?? "—"}`],
    ["Tool calls", run.tool_calls],
    ["Tokens", `${fmtTokens(run.input_tokens)} in · ${fmtTokens(run.output_tokens)} out`],
    ["Cost", <span key="c" title="Estimated from the server pricing table">{fmtCost(run.cost_usd)}{run.limits?.max_cost ? <span className="text-ink-400"> of ${run.limits.max_cost}</span> : null}</span>],
  ];
  return (
    <dl className="grid grid-cols-3 gap-x-6 gap-y-2 text-sm lg:grid-cols-6">
      {items.map(([k, v]) => <div key={k as string}><dt className="text-xs text-ink-400">{k}</dt><dd className="tabular-nums text-ink-900">{v}</dd></div>)}
    </dl>
  );
}

export function RunError({ run, nodes }: { run: Run; nodes: WFNode[] }) {
  if (!run.error) return null;
  const e = run.error;
  const node = nodes.find((n) => n.id === e.node_id);
  return (
    <div className="rounded-md border border-state-failed/30 bg-state-failed/5 p-3 text-sm">
      <div className="flex items-center gap-2 font-medium text-state-failed"><Icon name="CircleX" />{e.code === "budget_exceeded" ? "Budget limit reached" : e.code === "cancelled" ? "Cancelled" : node ? `${node.name} failed` : "Run failed"}</div>
      <p className="mt-1 text-ink-700">{e.message}</p>
      {e.code === "budget_exceeded" && e.details && (
        <dl className="mt-2 grid grid-cols-2 gap-1 text-xs text-ink-600">
          {Object.entries(e.details).map(([k, v]) => <div key={k}><dt className="inline text-ink-400">{k.replace(/_/g, " ")}: </dt><dd className="inline">{String(v)}</dd></div>)}
        </dl>
      )}
      {e.details?.kind && <p className="mt-1 text-xs text-ink-400">Error type: {e.details.kind}</p>}
    </div>
  );
}

export function Timeline({ nodeRuns, graph, onSelect, selected }: { nodeRuns: NodeRun[]; graph: WFNode[]; onSelect: (id: string) => void; selected?: string | null }) {
  const rows = nodeRuns.filter((n) => n.started_at && n.status !== "skipped");
  if (!rows.length) return <p className="text-sm text-ink-400">Nothing has started yet.</p>;
  const t0 = Math.min(...rows.map((r) => new Date(r.started_at!).getTime()));
  const t1 = Math.max(...rows.map((r) => (r.finished_at ? new Date(r.finished_at).getTime() : Date.now())));
  const span = Math.max(1, t1 - t0);
  const color: Record<string, string> = { completed: "bg-state-completed", failed: "bg-state-failed", running: "bg-state-running", waiting: "bg-state-waiting", cancelled: "bg-ink-300" };
  return (
    <div className="space-y-1">
      {rows.map((r) => {
        const s = new Date(r.started_at!).getTime() - t0;
        const e = (r.finished_at ? new Date(r.finished_at).getTime() : Date.now()) - t0;
        const name = graph.find((n) => n.id === r.node_id)?.name || r.node_key;
        return (
          <button key={r.id} onClick={() => onSelect(r.node_id)} className={clsx("grid w-full grid-cols-[160px_1fr_70px] items-center gap-3 rounded px-1 py-0.5 text-left text-xs hover:bg-canvas", selected === r.node_id && "bg-accent-50")}>
            <span className="truncate text-ink-700">{name}{r.scope && <span className="text-ink-400"> · {r.scope.split("/").pop()}</span>}</span>
            <span className="relative h-3 rounded-sm bg-canvas">
              <span className={clsx("absolute inset-y-0 rounded-sm", color[r.status] || "bg-ink-300")} style={{ left: `${(s / span) * 100}%`, width: `${Math.max(0.6, ((e - s) / span) * 100)}%` }} />
            </span>
            <span className="text-right tabular-nums text-ink-400">{fmtMs(r.latency_ms)}</span>
          </button>
        );
      })}
    </div>
  );
}

export function UsageTable({ nodeRuns, graph, mode }: { nodeRuns: NodeRun[]; graph: WFNode[]; mode: "tokens" | "cost" }) {
  const rows = nodeRuns.filter((n) => n.llm_calls > 0).sort((a, b) => (mode === "cost" ? b.cost_usd - a.cost_usd : b.input_tokens + b.output_tokens - (a.input_tokens + a.output_tokens)));
  if (!rows.length) return <p className="text-sm text-ink-400">No model calls in this run.</p>;
  const total = rows.reduce((s, r) => s + (mode === "cost" ? r.cost_usd : r.input_tokens + r.output_tokens), 0) || 1;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs text-ink-400"><tr><th className="py-1 font-medium">Node</th><th className="py-1 font-medium">Model</th>
        <th className="py-1 text-right font-medium">Input</th><th className="py-1 text-right font-medium">Output</th><th className="py-1 text-right font-medium">Cached</th><th className="py-1 text-right font-medium">Cost (est.)</th><th className="w-32" /></tr></thead>
      <tbody>{rows.map((r) => {
        const v = mode === "cost" ? r.cost_usd : r.input_tokens + r.output_tokens;
        return (
          <tr key={r.id} className="border-t border-line">
            <td className="py-1.5">{graph.find((n) => n.id === r.node_id)?.name || r.node_key}{r.scope && <span className="text-xs text-ink-400"> {r.scope}</span>}</td>
            <td className="py-1.5 text-ink-600">{r.model}{r.fallback_used && <Badge tone="warn" className="ml-1">fallback</Badge>}</td>
            <td className="py-1.5 text-right tabular-nums">{fmtTokens(r.input_tokens)}</td><td className="py-1.5 text-right tabular-nums">{fmtTokens(r.output_tokens)}</td>
            <td className="py-1.5 text-right tabular-nums text-ink-400">{fmtTokens(r.cached_tokens)}</td><td className="py-1.5 text-right tabular-nums">{fmtCost(r.cost_usd)}</td>
            <td className="pl-3"><div className="h-1.5 rounded bg-canvas"><div className="h-1.5 rounded bg-accent-500" style={{ width: `${(v / total) * 100}%` }} /></div></td>
          </tr>);
      })}</tbody>
    </table>
  );
}

export function EventLog({ events }: { events: RunEvent[] }) {
  if (!events.length) return <p className="text-sm text-ink-400">No events yet.</p>;
  return (
    <ol className="space-y-0.5 font-mono text-2xs">
      {events.map((e) => (
        <li key={e.seq} className="grid grid-cols-[70px_150px_1fr] gap-2">
          <span className="text-ink-400">{e.ts ? new Date(e.ts).toLocaleTimeString() : ""}</span>
          <span className={clsx(e.type.includes("FAIL") ? "text-state-failed" : e.type.includes("COMPLETED") ? "text-state-completed" : e.type.includes("WAIT") ? "text-state-waiting" : e.type.includes("RETRY") || e.type.includes("FALLBACK") || e.type.includes("BUDGET") ? "text-warn" : "text-ink-700")}>{e.type}</span>
          <span className="truncate text-ink-600" title={JSON.stringify(e.data)}>{summarize(e)}</span>
        </li>
      ))}
    </ol>
  );
}

function summarize(e: RunEvent) {
  const d = e.data || {};
  const parts = [d.node_id && `node=${d.node_id}`, d.scope && `scope=${d.scope}`, d.tool && `tool=${d.tool}`, d.handle && `→ ${d.handle}`,
    d.attempt && `attempt ${d.attempt}`, d.from && `${d.from} → ${d.to}`, d.error?.message || (typeof d.error === "string" ? d.error : null), d.reason, d.status && !d.node_id ? d.status : null];
  return parts.filter(Boolean).join("  ");
}

type InspectTab = "overview" | "input" | "output" | "tools" | "attempts";
export function NodeInspector({ nr, node, onReplay, onClose }: { nr: NodeRun | undefined; node: WFNode | undefined; onReplay?: (nodeId: string) => void; onClose?: () => void }) {
  const [tab, setTab] = useState<InspectTab>("overview");
  if (!node) return null;
  if (!nr) return (
    <div className="p-4 text-sm"><div className="flex items-center justify-between"><h3 className="font-semibold">{node.name}</h3>{onClose && <button onClick={onClose} aria-label="Close"><Icon name="X" /></button>}</div>
      <p className="mt-2 text-ink-400">This node hasn&apos;t run in this execution.</p></div>
  );
  const input = nr.input || {};
  return (
    <div className="flex h-full flex-col text-sm">
      <div className="flex items-center gap-2 px-4 pt-3">
        <h3 className="flex-1 truncate font-semibold">{node.name}</h3><StatusBadge status={nr.status} />
        {onReplay && ["completed", "failed", "skipped", "cancelled"].includes(nr.status) && <Button size="sm" icon="RotateCcw" onClick={() => onReplay(nr.node_id)}>Re-run from here</Button>}
        {onClose && <button onClick={onClose} aria-label="Close inspector" className="text-ink-400 hover:text-ink-900"><Icon name="X" /></button>}
      </div>
      <div className="px-4"><Tabs<InspectTab> value={tab} onChange={setTab} tabs={[{ id: "overview", label: "Overview" }, { id: "input", label: "Input" }, { id: "output", label: "Output" },
        { id: "tools", label: "Tool calls", count: nr.tool_runs.length }, { id: "attempts", label: "Attempts", count: (nr.attempts || []).length }]} /></div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {tab === "overview" && (
          <>
            {nr.error && <div className="rounded-md bg-state-failed/5 p-2.5 text-state-failed"><div className="font-medium">{nr.error.kind || nr.error.type || "Error"}</div><div className="text-xs">{nr.error.message}</div></div>}
            <dl className="grid grid-cols-2 gap-2 text-xs">
              {nr.model && <Row k="Model" v={<>{nr.provider}/{nr.model}{nr.fallback_used && <Badge tone="warn" className="ml-1">fallback used</Badge>}</>} />}
              <Row k="Latency" v={fmtMs(nr.latency_ms)} />
              {nr.llm_calls > 0 && <><Row k="Model calls" v={nr.llm_calls} /><Row k="Tokens" v={`${fmtTokens(nr.input_tokens)} in / ${fmtTokens(nr.output_tokens)} out${nr.cached_tokens ? ` / ${fmtTokens(nr.cached_tokens)} cached` : ""}`} /><Row k="Cost (est.)" v={fmtCost(nr.cost_usd)} /></>}
              {nr.handle && <Row k="Branch taken" v={nr.handle} />}
              {nr.scope && <Row k="Iteration" v={nr.scope} />}
              {input.ignored_params && <Row k="Ignored parameters" v={input.ignored_params.join(", ")} />}
              {input.context_warning && <Row k="Context" v={input.context_warning} />}
              {input.context_truncated && <Row k="Context" v="Truncated to fit the model" />}
              {input.evaluated && <Row k="Rule" v={`${JSON.stringify(input.evaluated.left)} ${input.evaluated.operator} ${JSON.stringify(input.evaluated.right)} → ${input.evaluated.result}`} />}
            </dl>
            {nr.reasoning_summary && <div><div className="mb-1 text-xs font-medium text-ink-700">Reasoning summary</div><p className="rounded-md bg-canvas p-2.5 text-xs">{nr.reasoning_summary}</p></div>}
            <div><div className="mb-1 text-xs font-medium text-ink-700">Output</div><OutputView value={nr.output} /></div>
          </>
        )}
        {tab === "input" && (
          <>
            {input.system_prompt && <Block title="System prompt" value={input.system_prompt} />}
            {input.user_message && <Block title="Message sent (after variable resolution)" value={input.user_message} />}
            {input.retrieved_knowledge && <Block title="Retrieved knowledge" value={input.retrieved_knowledge} />}
            {input.upstream && !input.user_message && <Block title="Upstream outputs" value={input.upstream} />}
            <Block title="Configuration used" value={nr.config} />
          </>
        )}
        {tab === "output" && <OutputView value={nr.output} />}
        {tab === "tools" && (nr.tool_runs.length ? nr.tool_runs.map((t) => (
          <div key={t.id} className="rounded-md border border-line p-2.5">
            <div className="flex items-center justify-between text-xs"><span className="font-medium">{t.tool}</span><span className={t.success ? "text-state-completed" : "text-state-failed"}>{t.success ? "ok" : "failed"} · {fmtMs(t.duration_ms)}</span></div>
            <Block title="Input" value={t.input} /><Block title={t.success ? "Result" : "Error"} value={t.success ? t.output : t.error} />
          </div>)) : <p className="text-ink-400">No tool calls.</p>)}
        {tab === "attempts" && ((nr.attempts || []).length ? (
          <ol className="space-y-1.5 text-xs">{nr.attempts.map((a: any, i: number) => (
            <li key={i} className="rounded-md bg-canvas p-2"><span className="font-medium">{a.model ? `${a.provider}/${a.model}` : `Attempt ${a.attempt ?? i + 1}`}</span> — {a.status}
              {a.error && <span className="text-state-failed"> · {typeof a.error === "string" ? a.error : a.error.message}</span>}
              {a.from_run_id && <span className="text-ink-400"> · reused from run {a.from_run_id.slice(0, 8)}</span>}</li>))}</ol>
        ) : <p className="text-ink-400">Single attempt.</p>)}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="col-span-2 grid grid-cols-[110px_1fr] gap-2"><dt className="text-ink-400">{k}</dt><dd className="text-ink-900">{v}</dd></div>;
}
function Block({ title, value }: { title: string; value: any }) {
  return <div><div className="mb-1 mt-2 text-xs font-medium text-ink-700">{title}</div><Code value={value} maxH="max-h-64" /></div>;
}
