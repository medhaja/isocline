"use client";
import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Icon, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useMe, useWorkspace } from "@/lib/session";
import { useTheme, type ThemePref } from "@/lib/theme";
import type { Approval, Project } from "@/lib/types";
import { Logo } from "./AuthShell";

const NAV: { group: string; items: { href: string; label: string; icon: string; badge?: "approvals" | "alerts"}[] }[] = [
  { group: "Build", items: [
    { href: "/dashboard", label: "Dashboard", icon: "LayoutGrid" },
    { href: "/projects", label: "Projects", icon: "FolderKanban" },
    { href: "/templates", label: "Templates", icon: "Blocks" },
    { href: "/agents", label: "Agents", icon: "Bot" },
  ] },
  { group: "Operate", items: [
    { href: "/approvals", label: "Approvals", icon: "UserCheck", badge: "approvals" },
    { href: "/monitoring", label: "Monitoring", icon: "Activity", badge: "alerts" },
    { href: "/usage", label: "Usage", icon: "ChartColumn" },
  ] },
  { group: "Govern", items: [
    { href: "/models", label: "Models", icon: "Cpu" },
    { href: "/providers", label: "Keys & secrets", icon: "KeyRound" },
    { href: "/policies", label: "Policies", icon: "ShieldCheck" },
    { href: "/integrations", label: "Integrations", icon: "Plug" },
    { href: "/settings", label: "Settings", icon: "Settings" },
  ] },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const me = useMe();
  const nav = NAV;
  const { workspace, workspaces, setWorkspace } = useWorkspace();
  const path = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const [palette, setPalette] = useState(false);
  const [theme, setTheme] = useTheme();
  // Collapsible rail: remembered per browser; collapsed by default on narrow screens.
  const [collapsed, setCollapsedState] = useState(false);
  useEffect(() => {
    const saved = localStorage.getItem("isc_rail");
    setCollapsedState(saved ? saved === "1" : window.innerWidth < 1100);
  }, []);
  const setCollapsed = (c: boolean) => { localStorage.setItem("isc_rail", c ? "1" : "0"); setCollapsedState(c); };
  const approvals = useQuery({ queryKey: ["approvals", workspace?.id], enabled: !!workspace,
    queryFn: () => api<Approval[]>(`/workspaces/${workspace!.id}/approvals`), refetchInterval: 20_000 });
  const alerts = useQuery({ queryKey: ["alerts", workspace?.id], enabled: !!workspace,
    queryFn: () => api<any[]>(`/workspaces/${workspace!.id}/alerts`), refetchInterval: 60_000 });

  useEffect(() => {
    if (me.isError) router.replace(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
  }, [me.isError, router]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function signOut() {
    await api("/auth/logout", { method: "POST" }).catch(() => {});
    qc.clear();
    router.push("/login");
  }

  if (me.isError) return <div className="flex h-screen items-center justify-center text-ink-400"><Spinner /></div>;
  if (me.isLoading || !workspace) {
    if (me.data && me.data.workspaces.length === 0) {
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-2 text-center">
          <p className="text-sm text-ink-700">Your account isn&apos;t a member of any workspace.</p>
          <button className="text-sm text-accent-600 hover:underline" onClick={signOut}>Sign out</button>
        </div>
      );
    }
    return <div className="flex h-screen items-center justify-center text-ink-400"><Spinner /></div>;
  }
  const counts = { approvals: approvals.data?.length || 0, alerts: alerts.data?.length || 0 };

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className={clsx("flex shrink-0 flex-col border-r border-line bg-paper transition-[width] duration-200", collapsed ? "w-[60px]" : "w-[232px]")}>
        <div className={clsx("flex items-center pb-3 pt-4", collapsed ? "justify-center px-2" : "gap-2 px-4")}>
          <Logo />{!collapsed && <span className="text-[15px] font-semibold tracking-[-0.02em]">Isocline</span>}
        </div>
        {!collapsed && (
          <div className="px-3">
            <label className="sr-only" htmlFor="ws">Workspace</label>
            <select id="ws" value={workspace.id} onChange={(e) => { setWorkspace(e.target.value); qc.invalidateQueries(); router.push("/dashboard"); }}
              className="h-8 w-full rounded-md border border-line bg-canvas px-2 text-xs font-medium text-ink-700 focus:border-accent-500 focus:outline-none">
              {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </div>
        )}
        <div className={clsx(collapsed ? "px-2" : "px-3")}>
          <button onClick={() => setPalette(true)} title="Jump to (Ctrl/⌘ K)" aria-label="Jump to"
            className={clsx("mt-2 flex h-8 w-full items-center rounded-md border border-line text-xs text-ink-400 hover:border-ink-300 hover:text-ink-600", collapsed ? "justify-center" : "gap-2 px-2")}>
            <Icon name="Search" size={14} />{!collapsed && <><span className="flex-1 text-left">Jump to</span><kbd className="rounded bg-canvas px-1 font-mono text-2xs">⌘K</kbd></>}
          </button>
        </div>
        <nav className={clsx("mt-4 flex-1 space-y-4 overflow-y-auto", collapsed ? "px-2" : "px-2.5")} aria-label="Main">
          {nav.map((g) => (
            <div key={g.group}>
              {collapsed ? <div className="mx-auto mb-1.5 h-px w-6 bg-line" aria-hidden /> : <div className="px-2.5 pb-1 text-2xs font-medium text-ink-400">{g.group}</div>}
              {g.items.map((n) => {
                const active = path === n.href || path.startsWith(n.href + "/");
                const count = n.badge ? counts[n.badge] : 0;
                return (
                  <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined} title={collapsed ? n.label : undefined}
                    className={clsx("relative flex items-center rounded-md py-1.5 text-[13px] transition-colors",
                      collapsed ? "justify-center px-0" : "gap-2.5 px-2.5",
                      active ? "bg-accent-50 font-medium text-ink-900" : "text-ink-600 hover:bg-canvas hover:text-ink-900")}>
                    {active && <span className="absolute -left-2.5 top-1.5 h-[calc(100%-12px)] w-[3px] rounded-r bg-accent-500" aria-hidden />}
                    <Icon name={n.icon} className={active ? "text-accent-600" : "text-ink-400"} />
                    {!collapsed && <span className="flex-1">{n.label}</span>}
                    {!!count && <span className={clsx("rounded-full text-2xs font-semibold text-paper", collapsed ? "absolute -right-0.5 -top-0.5 min-w-[16px] px-1 text-center" : "px-1.5",
                      n.badge === "alerts" ? "bg-state-failed" : "bg-state-waiting")}>{count}</span>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className={clsx("border-t border-line", collapsed ? "space-y-1 p-2" : "space-y-2 p-3")}>
          {!collapsed && <ThemeSwitch value={theme} onChange={setTheme} />}
          <div className={clsx("flex items-center", collapsed ? "flex-col gap-1" : "gap-2")}>
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-50 text-xs font-semibold text-accent-700" title={me.data?.user.email}>
              {(me.data?.user.name || "?").slice(0, 1).toUpperCase()}
            </div>
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-medium text-ink-800">{me.data?.user.name}</div>
                <div className="truncate text-2xs text-ink-400">{me.data?.user.email}</div>
              </div>
            )}
            {collapsed && <button onClick={() => setTheme(theme === "dark" ? "light" : "dark")} title="Toggle dark mode" aria-label="Toggle dark mode"
              className="rounded p-1 text-ink-400 hover:bg-canvas hover:text-ink-800"><Icon name={theme === "dark" ? "Sun" : "Moon"} size={14} /></button>}
            <button onClick={signOut} title="Sign out" aria-label="Sign out" className="rounded p-1 text-ink-400 hover:bg-canvas hover:text-ink-800"><Icon name="LogOut" size={14} /></button>
          </div>
          <button onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={clsx("flex h-7 items-center rounded-md text-2xs text-ink-400 hover:bg-canvas hover:text-ink-700", collapsed ? "w-full justify-center" : "w-full gap-2 px-1.5")}>
            <Icon name={collapsed ? "PanelLeftOpen" : "PanelLeftClose"} size={14} />{!collapsed && "Collapse"}
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">{children}</main>
      {palette && <CommandPalette onClose={() => setPalette(false)} workspaceId={workspace.id} nav={nav} />}
    </div>
  );
}

function CommandPalette({ onClose, workspaceId, nav }: { onClose: () => void; workspaceId: string; nav: typeof NAV }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const projects = useQuery({ queryKey: ["projects", workspaceId], queryFn: () => api<Project[]>(`/workspaces/${workspaceId}/projects`) });
  const dash = useQuery({ queryKey: ["dashboard", workspaceId], queryFn: () => api<any>(`/workspaces/${workspaceId}/dashboard`) });
  useEffect(() => { input.current?.focus(); }, []);
  const items = useMemo(() => {
    const all = [
      ...nav.flatMap((g) => g.items.map((n) => ({ label: n.label, hint: g.group, href: n.href, icon: n.icon }))),
      ...(projects.data || []).map((p) => ({ label: p.name, hint: "Project", href: `/projects/${p.id}`, icon: "FolderKanban" })),
      ...((dash.data?.recent_workflows || []) as any[]).map((w) => ({ label: w.name, hint: `Workflow · ${w.project_name}`, href: `/workflows/${w.id}`, icon: "Workflow" })),
    ];
    const s = q.toLowerCase();
    return all.filter((x) => !s || x.label.toLowerCase().includes(s) || x.hint.toLowerCase().includes(s)).slice(0, 12);
  }, [q, projects.data, dash.data, nav]);
  const go = (href: string) => { onClose(); router.push(href); };
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 pt-[14vh] backdrop-blur-[1px]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-label="Command palette" className="w-full max-w-lg animate-fadeIn overflow-hidden rounded-xl border border-line bg-paper shadow-pop">
        <div className="flex items-center gap-2 border-b border-line px-4">
          <Icon name="Search" className="text-ink-400" />
          <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setI(0); }} placeholder="Search pages, projects and workflows"
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-ink-400"
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(x + 1, items.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(x - 1, 0)); }
              if (e.key === "Enter" && items[i]) go(items[i].href);
            }} />
        </div>
        <ul className="max-h-80 overflow-y-auto p-1.5" role="listbox">
          {items.map((it, k) => (
            <li key={it.href + k} role="option" aria-selected={k === i}>
              <button onMouseEnter={() => setI(k)} onClick={() => go(it.href)}
                className={clsx("flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm", k === i ? "bg-canvas" : "")}>
                <Icon name={it.icon} className="text-ink-400" /><span className="flex-1 truncate">{it.label}</span><span className="text-2xs text-ink-400">{it.hint}</span>
              </button>
            </li>
          ))}
          {!items.length && <li className="px-3 py-6 text-center text-sm text-ink-400">No matches</li>}
        </ul>
      </div>
    </div>
  );
}

export function PageHeader({ title, description, actions, back, tabs }: { title: ReactNode; description?: ReactNode; actions?: ReactNode;
  back?: { href: string; label: string }; tabs?: ReactNode }) {
  return (
    <header className="border-b border-line bg-paper px-8 pt-5">
      {back && <Link href={back.href} className="mb-1.5 inline-flex items-center gap-1 text-xs text-ink-400 hover:text-ink-700"><Icon name="ChevronLeft" size={14} />{back.label}</Link>}
      <div className={clsx("flex items-start justify-between gap-4", tabs ? "pb-3" : "pb-5")}>
        <div className="min-w-0">
          <h1 className="truncate text-[22px] font-semibold text-ink-900">{title}</h1>
          {description && <p className="mt-1 max-w-2xl text-[13px] text-ink-500">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {tabs}
    </header>
  );
}


function ThemeSwitch({ value, onChange }: { value: ThemePref; onChange: (p: ThemePref) => void }) {
  const opts: { v: ThemePref; icon: string; label: string }[] = [{ v: "light", icon: "Sun", label: "Light" }, { v: "dark", icon: "Moon", label: "Dark" }, { v: "system", icon: "Monitor", label: "System" }];
  return (
    <div role="radiogroup" aria-label="Theme" className="grid grid-cols-3 rounded-md border border-line bg-canvas p-0.5">
      {opts.map((o) => (
        <button key={o.v} role="radio" aria-checked={value === o.v} onClick={() => onChange(o.v)} title={o.label}
          className={clsx("flex h-6 items-center justify-center gap-1 rounded text-2xs", value === o.v ? "bg-paper font-medium text-ink-900 shadow-card" : "text-ink-500 hover:text-ink-800")}>
          <Icon name={o.icon} size={12} />{o.label}
        </button>
      ))}
    </div>
  );
}
