"use client";
import { useEffect, useRef, useState } from "react";
import type { NodeStatus, RunEvent, RunStatus } from "./types";

export interface LiveNode { status: NodeStatus; tokens?: number; cost?: number | null; model?: string; provider?: string; attempt?: number; fallback?: boolean; iterations?: number; handle?: string | null; error?: string }

const TERMINAL: RunStatus[] = ["completed", "failed", "cancelled"];

/** Applies one event to the per-node live state. Top-level scope drives node colours; loop iterations show a count. */
export function reduceEvent(state: Record<string, LiveNode>, ev: RunEvent): Record<string, LiveNode> {
  const d = ev.data || {};
  const id = d.node_id as string | undefined;
  if (!id) return state;
  const inLoop = !!d.scope;
  const cur = state[id] || { status: "queued" as NodeStatus };
  const put = (patch: Partial<LiveNode>) => ({ ...state, [id]: { ...cur, ...patch } });
  switch (ev.type) {
    case "NODE_QUEUED": return inLoop ? state : put({ status: cur.status === "completed" ? cur.status : "queued" });
    case "NODE_STARTED": return put({ status: "running" });
    case "NODE_RETRY": return put({ status: "running", attempt: d.attempt, error: d.error });
    case "NODE_FALLBACK": return put({ fallback: true, model: d.to || cur.model });
    case "NODE_COMPLETED":
      if (inLoop) return put({ status: cur.status === "failed" ? "failed" : "running", tokens: (cur.tokens || 0) + (d.input_tokens || 0) + (d.output_tokens || 0) });
      return put({ status: "completed", handle: d.handle, tokens: (cur.tokens || 0) + (d.input_tokens || 0) + (d.output_tokens || 0), cost: d.cost_usd ?? cur.cost, model: d.model || cur.model, provider: d.provider, fallback: d.fallback_used ?? cur.fallback, iterations: d.iterations ?? cur.iterations });
    case "NODE_FAILED": return put({ status: d.status === "cancelled" ? "cancelled" : "failed", error: d.error?.message });
    case "NODE_SKIPPED": return inLoop ? state : put({ status: d.status === "cancelled" ? "cancelled" : d.reused ? cur.status : "skipped" });
    case "NODE_WAITING": return put({ status: "waiting" });
    case "LOOP_ITERATION": return put({ status: "running", iterations: (d.index ?? 0) + 1 });
    default: return state;
  }
}

export function useRunStream(runId: string | null | undefined, onEvent?: (ev: RunEvent) => void) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [nodes, setNodes] = useState<Record<string, LiveNode>>({});
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [connected, setConnected] = useState(false);
  const cb = useRef(onEvent);
  cb.current = onEvent;

  useEffect(() => {
    setEvents([]); setNodes({}); setStatus(null);
    if (!runId) return;
    let closed = false;
    let lastSeq = 0;
    const es = new EventSource(`/api/v1/runs/${runId}/events`, { withCredentials: true });
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false); // EventSource reconnects with Last-Event-ID automatically
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data) as RunEvent;
      if (ev.seq <= lastSeq) return; // de-dup across reconnects
      lastSeq = ev.seq;
      setEvents((xs) => [...xs, ev]);
      setNodes((s) => reduceEvent(s, ev));
      if (ev.type === "RUN_STARTED" || ev.type === "RUN_RESUMED") setStatus("running");
      if (ev.type === "RUN_WAITING") setStatus("waiting");
      if (ev.type === "RUN_COMPLETED") setStatus("completed");
      if (ev.type === "RUN_FAILED") setStatus("failed");
      if (ev.type === "RUN_CANCELLED") setStatus("cancelled");
      cb.current?.(ev);
    };
    es.addEventListener("end", (m: MessageEvent) => {
      const s = JSON.parse(m.data).status as RunStatus;
      if (TERMINAL.includes(s)) { setStatus(s); closed = true; es.close(); setConnected(false); }
    });
    return () => { if (!closed) es.close(); };
  }, [runId]);

  return { events, nodes, status, connected };
}
