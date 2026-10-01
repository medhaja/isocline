"use client";
import clsx from "clsx";
import { Icon } from "@/components/ui";
import { fmtCost } from "@/lib/format";
import type { ExecutionPlan } from "@/lib/types";

const range = (r: [number, number] | undefined, f: (n: number) => string = (n) => n.toLocaleString()) =>
  !r ? "—" : r[0] === r[1] ? f(r[0]) : `${f(r[0])}–${f(r[1])}`;
const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}K` : String(n));

export default function PlanView({ plan, compact }: { plan: ExecutionPlan; compact?: boolean }) {
  const t = plan.totals;
  const fails = plan.checks.filter((c) => c.status === "fail");
  const warns = plan.checks.filter((c) => c.status === "warn");
  const cats = Array.from(new Set(plan.checks.map((c) => c.category)));
  return (
    <div className="space-y-3">
      <div className={clsx("flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium",
        plan.status === "READY" ? "bg-state-completed/10 text-state-completed" : "bg-state-failed/10 text-state-failed")}>
        <Icon name={plan.status === "READY" ? "CircleCheck" : "OctagonX"} />
        {plan.status === "READY" ? "Ready to run" : `Blocked — ${fails.length} check${fails.length === 1 ? "" : "s"} failed`}
        {warns.length > 0 && <span className="ml-auto text-xs font-normal text-warn">{warns.length} warning{warns.length === 1 ? "" : "s"}</span>}
      </div>
      {t && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-md border border-line p-3 text-xs sm:grid-cols-4">
          <div><dt className="text-ink-400">Model calls</dt><dd className="font-medium tabular-nums">{range(t.llm_calls)}</dd></div>
          <div><dt className="text-ink-400">Tokens</dt><dd className="font-medium tabular-nums">{range(t.tokens, k)}</dd></div>
          <div><dt className="text-ink-400">Cost (est.)</dt><dd className="font-medium tabular-nums">{range(t.cost_usd, (n) => fmtCost(n, false))}</dd></div>
          <div><dt className="text-ink-400">Active time</dt><dd className="font-medium tabular-nums">{range(t.active_seconds, (n) => `${n}s`)}</dd></div>
          <div><dt className="text-ink-400">Agents</dt><dd className="tabular-nums">{plan.counts.agents}</dd></div>
          <div><dt className="text-ink-400">Parallel branches</dt><dd className="tabular-nums">{plan.counts.parallel_branches}</dd></div>
          <div><dt className="text-ink-400">Approvals possible</dt><dd className="tabular-nums">{plan.counts.human_approvals}</dd></div>
          <div><dt className="text-ink-400">Durable waits</dt><dd className="tabular-nums">{plan.counts.durable_waits}</dd></div>
        </dl>
      )}
      {!compact && (
        <ul className="space-y-1 text-xs">
          {cats.map((cat) => {
            const cs = plan.checks.filter((c) => c.category === cat);
            const worst = cs.some((c) => c.status === "fail") ? "fail" : cs.some((c) => c.status === "warn") ? "warn" : "pass";
            const shown = cs.filter((c) => c.status !== "pass" || cs.length === 1);
            return (
              <li key={cat}>
                <div className="flex items-center gap-1.5 font-medium">
                  <Icon name={worst === "fail" ? "CircleX" : worst === "warn" ? "TriangleAlert" : "CircleCheck"} size={13}
                    className={worst === "fail" ? "text-state-failed" : worst === "warn" ? "text-warn" : "text-state-completed"} />{cat}
                </div>
                {shown.filter((c) => c.status !== "pass" || c.message !== "No issues").map((c, i) => <p key={i} className="ml-5 text-ink-500">{c.message}</p>)}
              </li>
            );
          })}
        </ul>
      )}
      {plan.note && <p className="text-2xs text-ink-400">{plan.note}</p>}
    </div>
  );
}
