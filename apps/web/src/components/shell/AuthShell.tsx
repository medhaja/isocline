import Link from "next/link";
import type { ReactNode } from "react";

/* Left panel shows the product's characteristic object: a small multi-agent graph mid-run. */
function MiniGraph() {
  const n = (x: number, y: number, label: string, color: string, w = 104) => (
    <g transform={`translate(${x},${y})`}>
      <rect width={w} height="34" rx="6" fill="rgb(var(--paper))" stroke="rgb(var(--line))" />
      <rect width="3" height="34" rx="1.5" fill={color} />
      <text x="12" y="21" fill="rgb(var(--ink-800))" fontSize="11" fontFamily="Instrument Sans Variable, sans-serif">{label}</text>
    </g>
  );
  const e = (d: string, c = "rgb(var(--ink-300))", dash = false) => <path d={d} fill="none" stroke={c} strokeWidth="1.5" strokeDasharray={dash ? "5 4" : undefined} />;
  return (
    <svg viewBox="0 0 520 240" className="w-full max-w-md" role="img" aria-label="Example workflow: research feeding financial and risk analysts, merged into a manager report">
      {e("M112 120 H150", "rgb(var(--state-completed))")}
      {e("M254 120 C 275 120, 275 60, 296 60", "rgb(var(--state-completed))")}
      {e("M254 120 C 275 120, 275 180, 296 180", "rgb(var(--state-running))", true)}
      {e("M400 60 C 420 60, 420 120, 408 120")}
      {e("M400 180 C 420 180, 420 120, 408 120")}
      {n(8, 103, "Company", "rgb(var(--accent-500))")}
      {n(150, 103, "Research", "rgb(var(--state-completed))")}
      {n(296, 43, "Financial analyst", "rgb(var(--state-completed))", 104)}
      {n(296, 163, "Risk analyst", "rgb(var(--state-running))")}
      <g transform="translate(410,103)"><rect width="100" height="34" rx="6" fill="none" stroke="rgb(var(--ink-300))" strokeDasharray="4 3" /><text x="12" y="21" fill="rgb(var(--ink-400))" fontSize="11" fontFamily="Instrument Sans Variable, sans-serif">Manager</text></g>
    </svg>
  );
}

export default function AuthShell({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <main className="grid min-h-screen bg-paper lg:grid-cols-[1.1fr_1fr]">
      <section className="contour-backdrop relative hidden flex-col justify-between border-r border-line bg-canvas p-10 lg:flex">
        <Link href="/" className="flex items-center gap-2 text-ink-900"><Logo /><span className="text-[15px] font-semibold tracking-[-0.02em]">Isocline</span></Link>
        <div className="space-y-7">
          <MiniGraph />
          <div className="max-w-md space-y-3">
            <p className="text-[28px] font-semibold leading-[1.15] tracking-[-0.025em] text-ink-900">Agent workflows that finish what they start.</p>
            <p className="text-[15px] leading-relaxed text-ink-600">
              Draw the workflow, give each agent its own model and tools, and run it. Approvals can wait for days, and a crashed
              worker picks up where it stopped.
            </p>
          </div>
        </div>
        <p className="text-xs text-ink-500">Open source and self-hosted. Your keys, your models.</p>
      </section>
      <section className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <div className="mb-6 lg:hidden"><Logo /></div>
          <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-ink-900">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-ink-400">{subtitle}</p>}
          <div className="mt-6">{children}</div>
          {footer && <div className="mt-6 text-sm text-ink-400">{footer}</div>}
        </div>
      </section>
    </main>
  );
}

export function Logo({ className }: { className?: string }) {
  /* Isoclines: nested contour lines of equal slope. */
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" className={className} aria-hidden fill="none" strokeLinecap="round">
      <path d="M3 17.5c3.2-4.6 6.6-6.2 10.2-4.8 2.7 1.1 5 .6 7.8-1.7" stroke="rgb(var(--accent-500))" strokeWidth="1.9" />
      <path d="M3 12.5c3-4.2 6.2-5.6 9.6-4.3 2.6 1 4.9.5 8.4-2.2" stroke="rgb(var(--accent-500))" strokeOpacity=".62" strokeWidth="1.7" />
      <path d="M3 7.6c2.7-3.6 5.6-4.7 8.6-3.6 2.4.9 4.6.4 7.8-1.7" stroke="rgb(var(--accent-500))" strokeOpacity=".32" strokeWidth="1.5" />
    </svg>
  );
}
