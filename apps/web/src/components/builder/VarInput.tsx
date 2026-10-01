"use client";
import { useFieldId } from "@/components/ui";
import clsx from "clsx";
import { useMemo, useRef, useState } from "react";
import type { VarSuggestion } from "@/lib/graph";

/** Textarea/input with {{variable}} autocomplete. Typing "{{" opens suggestions limited to upstream nodes. */
export default function VarInput({ value, onChange, suggestions, multiline = true, rows = 4, placeholder, mono, ariaLabel }: {
  value: string; onChange: (v: string) => void; suggestions: VarSuggestion[]; multiline?: boolean; rows?: number; placeholder?: string; mono?: boolean; ariaLabel?: string;
}) {
  const ref = useRef<HTMLTextAreaElement & HTMLInputElement>(null);
  const [query, setQuery] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const filtered = useMemo(() => (query === null ? [] : suggestions.filter((s) => s.label.toLowerCase().includes(query.toLowerCase())).slice(0, 8)), [query, suggestions]);

  function detect(v: string, caret: number) {
    const before = v.slice(0, caret);
    const m = before.match(/\{\{\s*([\w.]*)$/);
    setQuery(m ? m[1] : null);
    setActive(0);
  }
  function insert(s: VarSuggestion) {
    const el = ref.current!;
    const caret = el.selectionStart ?? value.length;
    const before = value.slice(0, caret).replace(/\{\{\s*[\w.]*$/, "");
    const after = value.slice(caret).replace(/^[\w.]*\s*\}\}/, "");
    const next = before + s.expr + after;
    onChange(next);
    setQuery(null);
    requestAnimationFrame(() => { el.focus(); const p = (before + s.expr).length; el.setSelectionRange(p, p); });
  }
  const fid = useFieldId();
  const common = {
    ref, value, placeholder, "aria-label": ariaLabel, id: fid,
    className: clsx("w-full rounded-md border border-line bg-paper px-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-100",
      multiline ? "py-2 leading-relaxed" : "h-9", mono && "font-mono text-xs"),
    onChange: (e: any) => { onChange(e.target.value); detect(e.target.value, e.target.selectionStart); },
    onKeyDown: (e: React.KeyboardEvent) => {
      if (!filtered.length) return;
      if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => (a + 1) % filtered.length); }
      if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => (a - 1 + filtered.length) % filtered.length); }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); insert(filtered[active]); }
      if (e.key === "Escape") { e.stopPropagation(); setQuery(null); }
    },
    onBlur: () => setTimeout(() => setQuery(null), 150),
  };
  return (
    <div className="relative">
      {multiline ? <textarea {...common} rows={rows} /> : <input {...common} />}
      {filtered.length > 0 && (
        <ul role="listbox" className="absolute left-0 right-0 z-30 mt-1 max-h-56 overflow-y-auto rounded-md border border-line bg-paper py-1 shadow-pop">
          {filtered.map((s, i) => (
            <li key={s.expr} role="option" aria-selected={i === active} onMouseDown={(e) => { e.preventDefault(); insert(s); }}
              className={clsx("cursor-pointer px-2.5 py-1", i === active ? "bg-accent-50" : "hover:bg-canvas")}>
              <div className="font-mono text-xs text-ink-900">{s.label}</div><div className="text-2xs text-ink-400">{s.detail}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function VarChips({ suggestions, onPick }: { suggestions: VarSuggestion[]; onPick: (s: VarSuggestion) => void }) {
  if (!suggestions.length) return <p className="text-2xs text-ink-400">Connect upstream nodes to reference their output.</p>;
  return (
    <div className="flex flex-wrap gap-1">
      {suggestions.slice(0, 10).map((s) => (
        <button key={s.expr} type="button" title={s.detail} onClick={() => onPick(s)} className="rounded bg-canvas px-1.5 py-0.5 font-mono text-2xs text-ink-600 hover:bg-accent-50 hover:text-accent-700">{s.label}</button>
      ))}
    </div>
  );
}
