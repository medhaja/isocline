"use client";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api";
import type { User, Workspace } from "./types";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api<{ user: User; workspaces: Workspace[] }>("/auth/me"), staleTime: 60_000, retry: false });
}

const KEY = "isc_workspace";

/** Current workspace: remembered per browser, defaults to the first one the user belongs to. */
export function useWorkspace(): { workspace: Workspace | null; setWorkspace: (id: string) => void; workspaces: Workspace[] } {
  const me = useMe();
  const [id, setId] = useState<string | null>(null);
  useEffect(() => { try { setId(localStorage.getItem(KEY)); } catch { /* storage unavailable */ } }, []);
  const list = me.data?.workspaces || [];
  const ws = list.find((w) => w.id === id) || list[0] || null;
  return {
    workspace: ws, workspaces: list,
    setWorkspace: (v) => { try { localStorage.setItem(KEY, v); } catch { /* ignore */ } setId(v); },
  };
}

export type Meta = {
  name: string; version: string; edition: string; test_provider: boolean; signup: "open" | "first_account_only";
};

/** Installation facts from GET /api/v1/meta (public). */
export function useMeta() {
  return useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta"), staleTime: 5 * 60_000, retry: 1 });
}
