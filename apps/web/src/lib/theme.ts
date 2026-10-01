"use client";
import { useEffect, useState } from "react";

export type ThemePref = "system" | "light" | "dark";
const KEY = "isc_theme";

function apply(pref: ThemePref) {
  const dark = pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

/** Light / dark / follow the system. Stored per browser; the layout applies it before first paint. */
export function useTheme(): [ThemePref, (p: ThemePref) => void] {
  const [pref, setPref] = useState<ThemePref>("system");
  useEffect(() => {
    const saved = (localStorage.getItem(KEY) as ThemePref | null) || "system";
    setPref(saved);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => { if ((localStorage.getItem(KEY) || "system") === "system") apply("system"); };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  const set = (p: ThemePref) => { localStorage.setItem(KEY, p); setPref(p); apply(p); };
  return [pref, set];
}
