"use client";
import clsx from "clsx";
import * as Icons from "lucide-react";
import { createContext, forwardRef, useContext, useEffect, useId, useMemo, useRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { create } from "zustand";

export function Icon({ name, className, size = 16 }: { name: string; className?: string; size?: number }) {
  const C = (Icons as any)[name] || Icons.Circle;
  return <C className={className} size={size} strokeWidth={1.75} aria-hidden />;
}

type Variant = "primary" | "secondary" | "ghost" | "danger" | "dark";
export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; loading?: boolean; icon?: string }>(
  function Button({ variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest }, ref) {
    return (
      <button ref={ref} disabled={disabled || loading}
        className={clsx("inline-flex items-center justify-center gap-1.5 rounded-md font-medium shadow-card transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 disabled:cursor-not-allowed disabled:opacity-50",
          size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
          variant === "primary" && "bg-accent-500 text-paper hover:bg-accent-600",
          variant === "secondary" && "border border-line bg-paper text-ink-900 hover:bg-canvas",
          variant === "ghost" && "text-ink-700 shadow-none hover:bg-ink-900/5",
          variant === "danger" && "bg-state-failed text-paper hover:brightness-95",
          variant === "dark" && "border border-line bg-paper text-ink-700 hover:bg-canvas",
          className)} {...rest}>
        {loading ? <Spinner /> : icon ? <Icon name={icon} size={size === "sm" ? 14 : 16} /> : null}
        {children}
      </button>
    );
  });

export function Spinner({ className }: { className?: string }) {
  return <span className={clsx("inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent", className)} role="status" aria-label="Loading" />;
}

const field = "w-full rounded-md border border-line bg-paper px-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-100 disabled:bg-canvas";

/* Accessible labelling: a Field links its <label> to the first form control inside it (by id), so every
   labelled input is announced with its name by screen readers. */
// Label ↔ control linking. Each Field owns a persistent slot; the first control rendered inside it claims the slot
// with its own stable id and keeps it for its lifetime (released on unmount). Deterministic under concurrent or
// interrupted renders — no per-render mutable flags — so a label can never point at another field's control.
const FieldCtx = createContext<{ id: string; owner: { current: string | null } } | null>(null);

export function useFieldId(explicit?: string): string | undefined {
  const ctx = useContext(FieldCtx);
  const me = useId();
  useEffect(() => () => { if (ctx && ctx.owner.current === me) ctx.owner.current = null; }, [ctx, me]);
  if (explicit) return explicit;
  if (!ctx) return undefined;
  if (ctx.owner.current === null) ctx.owner.current = me;
  return ctx.owner.current === me ? ctx.id : undefined;
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, id, ...p }, ref) {
  const fid = useFieldId(id);
  return <input ref={ref} id={fid} className={clsx(field, "h-9", className)} {...p} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { mono?: boolean }>(function Textarea({ className, mono, id, ...p }, ref) {
  const fid = useFieldId(id);
  return <textarea ref={ref} id={fid} className={clsx(field, "min-h-[72px] py-2 leading-relaxed", mono && "font-mono text-xs", className)} {...p} />;
});

export function Select({ className, children, id, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  const fid = useFieldId(id);
  return <select id={fid} className={clsx(field, "h-9 pr-7", className)} {...p}>{children}</select>;
}

export function Field({ label, hint, error, children, htmlFor }: { label: string; hint?: ReactNode; error?: string | null; children: ReactNode; htmlFor?: string }) {
  const auto = useId();
  const id = htmlFor || auto;
  const owner = useRef<string | null>(null);
  const ctx = useMemo(() => (htmlFor ? null : { id, owner }), [htmlFor, id]);
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs font-medium text-ink-700">{label}</label>
      <FieldCtx.Provider value={ctx}>{children}</FieldCtx.Provider>
      {error ? <p className="text-xs text-state-failed">{error}</p> : hint ? <p className="text-xs text-ink-400">{hint}</p> : null}
    </div>
  );
}

export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 text-sm">
      <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={clsx("mt-0.5 h-4 w-7 shrink-0 rounded-full p-0.5 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-500", checked ? "bg-accent-500" : "bg-ink-200")}>
        <span className={clsx("block h-3 w-3 rounded-full bg-white transition-transform", checked && "translate-x-3")} />
      </button>
      <span><span className="text-ink-900">{label}</span>{hint && <span className="block text-xs text-ink-400">{hint}</span>}</span>
    </label>
  );
}

const STATUS_STYLE: Record<string, string> = {
  running: "bg-state-running/15 text-warn", queued: "bg-ink-200/60 text-ink-700", resuming: "bg-state-running/15 text-warn",
  completed: "bg-state-completed/12 text-state-completed", passed: "bg-state-completed/12 text-state-completed",
  failed: "bg-state-failed/12 text-state-failed", error: "bg-state-failed/12 text-state-failed",
  waiting: "bg-state-waiting/12 text-state-waiting", pending: "bg-state-waiting/12 text-state-waiting",
  skipped: "bg-ink-200/50 text-ink-600", cancelled: "bg-ink-200/50 text-ink-600",
  draft: "bg-ink-200/60 text-ink-700", published: "bg-accent-50 text-accent-700", archived: "bg-ink-200/40 text-ink-400",
  active: "bg-state-completed/12 text-state-completed", paused: "bg-ink-200/60 text-ink-700",
  approved: "bg-state-completed/12 text-state-completed", rejected: "bg-state-failed/12 text-state-failed",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium", STATUS_STYLE[status] || "bg-ink-200/60 text-ink-700", className)}>
      {(status === "running" || status === "resuming") && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-state-running" />}
      {status}
    </span>
  );
}

export function Badge({ children, tone = "neutral", className }: { children: ReactNode; tone?: "neutral" | "blue" | "warn"; className?: string }) {
  return <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-medium",
    tone === "neutral" && "bg-ink-200/60 text-ink-700", tone === "blue" && "bg-accent-50 text-accent-700", tone === "warn" && "bg-state-running/15 text-warn", className)}>{children}</span>;
}

export function Dialog({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    setTimeout(() => ref.current?.querySelector<HTMLElement>("input,textarea,select,button[data-autofocus]")?.focus(), 0);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/45 p-4 pt-[8vh] backdrop-blur-[1px]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal aria-label={title} className={clsx("w-full rounded-lg bg-paper shadow-pop", wide ? "max-w-3xl" : "max-w-lg")}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 className="text-[15px] font-semibold text-ink-900">{title}</h2>
          <button onClick={onClose} className="rounded p-1 text-ink-400 hover:bg-canvas hover:text-ink-900" aria-label="Close"><Icon name="X" /></button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, dark }: { tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (t: T) => void; dark?: boolean }) {
  return (
    <div role="tablist" className={clsx("flex gap-1 border-b", dark ? "border-ink-700" : "border-line")}>
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={clsx("-mb-px border-b-2 px-3 py-2 text-[13px] font-medium transition-colors",
            value === t.id ? (dark ? "border-accent-500 text-paper" : "border-accent-500 text-ink-900") : (dark ? "border-transparent text-ink-400 hover:text-ink-200" : "border-transparent text-ink-400 hover:text-ink-700"))}>
          {t.label}{t.count !== undefined && <span className="ml-1.5 text-ink-400">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Empty({ icon, title, body, action }: { icon: string; title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-paper px-6 py-14 text-center">
      <div className="mb-3 rounded-md bg-canvas p-2.5 text-ink-600"><Icon name={icon} size={20} /></div>
      <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
      {body && <p className="mt-1 max-w-sm text-sm text-ink-400">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorBox({ error, title }: { error: unknown; title?: string }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  const details = (error as any)?.details;
  return (
    <div className="rounded-md border border-state-failed/30 bg-state-failed/5 px-3 py-2 text-sm text-state-failed" role="alert">
      {title && <div className="font-medium">{title}</div>}
      <div>{msg}</div>
      {Array.isArray(details) && details.length > 0 && (
        <ul className="mt-1 list-disc pl-4 text-xs">{details.slice(0, 8).map((d: any, i: number) => <li key={i}>{typeof d === "string" ? d : d.message || JSON.stringify(d)}</li>)}</ul>
      )}
    </div>
  );
}

export function Code({ value, className, maxH = "max-h-80" }: { value: any; className?: string; maxH?: string }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return <pre className={clsx("overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-canvas p-3 font-mono text-xs leading-relaxed text-ink-800", maxH, className)}>{text ?? "—"}</pre>;
}

// ------------------------------------------------------------------ toasts
interface Toast { id: number; text: string; tone: "ok" | "error" | "info" }
export const useToasts = create<{ items: Toast[]; push: (text: string, tone?: Toast["tone"]) => void; remove: (id: number) => void }>((set) => ({
  items: [],
  push: (text, tone = "ok") => {
    const id = Date.now() + Math.random();
    set((s) => ({ items: [...s.items, { id, text, tone }] }));
    setTimeout(() => set((s) => ({ items: s.items.filter((t) => t.id !== id) })), tone === "error" ? 7000 : 3500);
  },
  remove: (id) => set((s) => ({ items: s.items.filter((t) => t.id !== id) })),
}));
export const toast = (t: string, tone?: Toast["tone"]) => useToasts.getState().push(t, tone);

export function Toaster() {
  const { items, remove } = useToasts();
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col gap-2" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={clsx("pointer-events-auto flex max-w-sm items-start gap-2 rounded-md px-3.5 py-2.5 text-sm text-paper shadow-pop",
          t.tone === "error" ? "bg-state-failed" : t.tone === "info" ? "bg-ink-800" : "bg-ink-900")}>
          <Icon name={t.tone === "error" ? "AlertCircle" : t.tone === "info" ? "Info" : "Check"} className="mt-0.5 shrink-0" />
          <span className="flex-1">{t.text}</span>
          <button onClick={() => remove(t.id)} aria-label="Dismiss" className="opacity-70 hover:opacity-100"><Icon name="X" size={14} /></button>
        </div>
      ))}
    </div>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-paper px-4 py-3.5 shadow-card">
      <div className="text-xs text-ink-500">{label}</div>
      <div className="mt-1 text-[22px] font-semibold tabular-nums tracking-tight text-ink-900">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-400">{sub}</div>}
    </div>
  );
}
