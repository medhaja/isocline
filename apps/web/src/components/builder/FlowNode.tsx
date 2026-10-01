"use client";
import clsx from "clsx";
import { Handle, NodeResizer, Position, type NodeProps } from "@xyflow/react";
import { memo } from "react";
import { Icon } from "@/components/ui";
import { fmtCost, fmtTokens } from "@/lib/format";
import { CATEGORY_TINT, SPEC, hasTarget, sourceHandles } from "@/lib/nodes";
import type { WFNode } from "@/lib/types";
import type { LiveNode } from "@/lib/useRunStream";
import { useBuilder } from "@/store/builder";

export interface FlowData extends Record<string, unknown> { node: WFNode; live?: LiveNode; issues?: number; readOnly?: boolean;
  heat?: { value: number; label: string; level: number } }
const HEAT = ["rgb(var(--paper))", "rgb(var(--state-failed) / .10)", "rgb(var(--state-failed) / .20)", "rgb(var(--state-failed) / .32)", "rgb(var(--state-failed) / .46)", "rgb(var(--state-failed) / .62)"];

const STATE_BORDER: Record<string, string> = {
  running: "border-state-running animate-pulseRing", completed: "border-state-completed", failed: "border-state-failed",
  waiting: "border-state-waiting", skipped: "border-dashed border-ink-300 opacity-60", cancelled: "border-ink-300 opacity-60", queued: "border-ink-300",
};
const STATE_LABEL: Record<string, string> = { running: "Running", completed: "Done", failed: "Failed", waiting: "Waiting for approval", skipped: "Skipped", cancelled: "Cancelled", queued: "Queued" };
const STATE_STRIP: Record<string, string> = {
  running: "bg-state-running/10 text-state-running", completed: "bg-state-completed/10 text-state-completed", failed: "bg-state-failed/10 text-state-failed",
  waiting: "bg-state-waiting/15 text-warn", skipped: "bg-ink-200/50 text-ink-500", cancelled: "bg-ink-200/50 text-ink-500",
};
const HANDLE_TONE: Record<string, string> = { ok: "!bg-state-completed", bad: "!bg-state-failed", neutral: "!bg-state-waiting" };

function WorkflowNode({ data, selected }: NodeProps) {
  const { node, live, issues, readOnly, heat } = data as FlowData;
  const spec = SPEC[node.type];
  const tint = CATEGORY_TINT[spec.category];
  const handles = sourceHandles(node);

  if (node.type === "note") return <NoteNode node={node} selected={!!selected} readOnly={readOnly} />;
  if (node.type === "group") {
    return (
      <div className={clsx("h-full w-full rounded-lg border-2 border-dashed bg-ink-900/[0.03]", selected ? "border-accent-500" : "border-ink-300")}>
        {!readOnly && <NodeResizer isVisible={selected} minWidth={200} minHeight={120} lineClassName="!border-accent-500" handleClassName="!bg-accent-500"
          onResizeEnd={(_, p) => useBuilder.getState().updateConfig(node.id, { width: Math.round(p.width), height: Math.round(p.height) })} />}
        <div className="px-3 py-1.5 text-xs font-medium text-ink-600">{node.name}</div>
      </div>
    );
  }

  const model = node.config?.model;
  const status = live?.status;
  return (
    <div className={clsx("group relative w-[240px] rounded-[11px] border-2 bg-paper shadow-node transition-[border-color,box-shadow] duration-150",
      status && !heat ? STATE_BORDER[status] : selected ? "border-accent-500" : "border-transparent hover:border-ink-200")}
      style={heat ? { background: HEAT[heat.level], borderColor: heat.level >= 4 ? "rgb(var(--state-failed))" : undefined } : undefined}
      aria-label={`${node.name}${status ? `, ${STATE_LABEL[status]}` : ""}`}>
      <div className="absolute inset-y-0 left-0 w-1 rounded-l-md" style={{ background: tint }} />
      {hasTarget(node) && <Handle type="target" position={Position.Left} className="!-left-[6px]" />}
      <div className="py-2.5 pl-4 pr-3">
        <div className="flex items-center gap-2">
          <span style={{ color: tint }}><Icon name={spec.icon} size={15} /></span>
          <span className="flex-1 truncate text-[13px] font-medium text-ink-900">{node.name}</span>
          {!!issues && <span title={`${issues} issue(s)`} className="h-2 w-2 rounded-full bg-state-failed" />}
          {status && <StatusDot status={status} />}
        </div>
        <div className="mt-0.5 flex items-center gap-1 truncate font-mono text-2xs text-ink-400">
          <span className="truncate">{node.key}</span>
          {node.contract && <span title={`Contract: out ${node.contract.output?.type}`} className="rounded bg-accent-50 px-1 text-accent-700">{node.contract.output?.type !== "Any" ? node.contract.output?.type : "contract"}</span>}
          {node.harness?.cache?.mode && node.harness.cache.mode !== "disabled" && <span title={`${node.harness.cache.mode} cache`}><Icon name="DatabaseZap" size={11} /></span>}
          {node.harness?.checkpoint && <span title="Checkpoint"><Icon name="Flag" size={11} /></span>}
          {!!node.harness?.recovery?.length && <span title="Recovery rules"><Icon name="LifeBuoy" size={11} /></span>}
          {node.harness?.compensation && <span title="Compensation"><Icon name="Undo2" size={11} /></span>}
        </div>
        {heat && <div className="mt-1.5 rounded bg-paper/70 px-1.5 py-0.5 text-2xs font-medium tabular-nums text-ink-800">{heat.label}</div>}
        {node.type === "agent" && (
          <div className="mt-2 space-y-1">
            <div className={clsx("truncate text-xs", model?.model ? "text-ink-600" : "text-state-failed")}>
              {model?.provider === "auto" ? <span className="rounded bg-accent-50 px-1 font-medium text-accent-700">AUTO · {model.model !== "auto" ? model.model : (node.config.routing?.objective || "balanced")}{live?.model ? ` → ${live.model}` : ""}</span>
                : model?.model ? `${live?.fallback && live.model ? live.model : model.model}` : "No model selected"}
              {live?.fallback && <span className="ml-1 text-state-running">(fallback)</span>}
            </div>
            {(node.config.tools?.length > 0 || node.config.knowledge_base_ids?.length > 0) && (
              <div className="flex flex-wrap gap-1">
                {node.config.tools.map((t: string) => <span key={t} className="rounded bg-canvas px-1 text-2xs text-ink-600">{t.replace("_", " ")}</span>)}
                {node.config.knowledge_base_ids?.length > 0 && <span className="rounded bg-canvas px-1 text-2xs text-ink-600">knowledge</span>}
              </div>
            )}
          </div>
        )}
        {node.type === "condition" && node.config.rule?.left && (
          <div className="mt-1.5 truncate font-mono text-2xs text-ink-600">{node.config.rule.left} {node.config.rule.operator} {String(node.config.rule.right ?? "")}</div>
        )}
        {(node.type === "loop" || node.type === "retry") && <div className="mt-1.5 text-2xs text-ink-600">max {node.config.max_iterations} iterations{live?.iterations ? ` · ran ${live.iterations}` : ""}</div>}
        {node.type === "wait_timer" && <div className="mt-1.5 text-2xs text-ink-600">{node.config.until ? `until ${node.config.until}` : `${Math.round((node.config.duration_seconds || 0) / 60)} min`}</div>}
        {node.type === "wait_event" && <div className="mt-1.5 truncate font-mono text-2xs text-ink-600">{node.config.event_name || "event?"}</div>}
        {node.type === "subworkflow" && <div className="mt-1.5 text-2xs text-ink-600">{node.config.workflow_id ? (node.config.version ? `pinned v${node.config.version}` : "latest version") : "choose a workflow"}</div>}
        {status && status !== "queued" && !heat && (
          <div className={clsx("mt-2 flex items-center gap-1.5 rounded px-1.5 py-0.5 text-2xs font-medium", STATE_STRIP[status])} role="status">
            <span className={clsx("h-1.5 w-1.5 rounded-full bg-current", status === "running" && "animate-pulse")} aria-hidden />{STATE_LABEL[status]}
          </div>
        )}
        {live && (live.tokens || live.cost || live.attempt) ? (
          <div className="mt-2 flex gap-3 border-t border-line pt-1.5 text-2xs tabular-nums text-ink-400">
            {!!live.tokens && <span>{fmtTokens(live.tokens)} tok</span>}
            {live.cost !== undefined && live.cost !== null && <span>{fmtCost(live.cost)}</span>}
            {!!live.attempt && live.attempt > 1 && <span className="text-state-running">attempt {live.attempt}</span>}
          </div>
        ) : null}
      </div>
      {handles.length === 1 && handles[0].id === null ? (
        <Handle type="source" position={Position.Right} className="!-right-[6px]" />
      ) : handles.map((h, i) => (
        <div key={h.id ?? "out"} className="absolute -right-[6px] flex items-center" style={{ top: `${((i + 1) / (handles.length + 1)) * 100}%` }}>
          <span className="pointer-events-none absolute right-3 -translate-y-1/2 whitespace-nowrap rounded bg-paper/90 px-1 text-2xs text-ink-400">{h.label}</span>
          <Handle id={h.id ?? undefined} type="source" position={Position.Right} className={clsx("!relative !right-0 !top-0 !translate-y-[-50%]", h.tone && HANDLE_TONE[h.tone])} />
        </div>
      ))}
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const icon = { completed: "CircleCheck", failed: "CircleX", waiting: "CirclePause", skipped: "CircleMinus", cancelled: "CircleSlash", queued: "CircleDashed", running: "LoaderCircle" }[status] || "Circle";
  const color = { completed: "text-state-completed", failed: "text-state-failed", waiting: "text-state-waiting", running: "text-state-running animate-spin", skipped: "text-ink-400", cancelled: "text-ink-400", queued: "text-ink-400" }[status];
  return <span className={color} title={STATE_LABEL[status]}><Icon name={icon} size={15} /></span>;
}

function NoteNode({ node, selected, readOnly }: { node: WFNode; selected: boolean; readOnly?: boolean }) {
  return (
    <div className={clsx("w-[220px] rounded-md border bg-state-waiting/10 p-2.5 shadow-node", selected ? "border-accent-500" : "border-state-waiting/30")}>
      {readOnly ? <p className="whitespace-pre-wrap text-xs text-ink-700">{node.config.text}</p> : (
        <textarea aria-label="Note" className="nodrag min-h-[60px] w-full resize-y bg-transparent text-xs text-ink-700 focus:outline-none" placeholder="Write a note…"
          value={node.config.text || ""} onChange={(e) => useBuilder.getState().updateConfig(node.id, { text: e.target.value }, `note:${node.id}`)} />
      )}
    </div>
  );
}

export default memo(WorkflowNode);
