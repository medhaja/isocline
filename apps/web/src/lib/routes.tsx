"use client";
/**
 * Links to pages that show one record. They use a query parameter (`/runs/view?id=…`) instead of a path segment
 * (`/runs/…`) so the UI can be exported as static files (output: "export") and served by the desktop app without a
 * Node.js server. Always build these URLs with `routes`, never by hand.
 */
import { useSearchParams } from "next/navigation";
import { Fragment, Suspense, type ReactNode } from "react";

const q = (id: string) => encodeURIComponent(id);

export const routes = {
  run: (id: string) => `/runs/view?id=${q(id)}`,
  workflow: (id: string) => `/workflows/view?id=${q(id)}`,
  evaluation: (id: string) => `/evaluations/view?id=${q(id)}`,
  project: (id: string, tab?: string) => `/projects/view?id=${q(id)}${tab ? `&tab=${encodeURIComponent(tab)}` : ""}`,
};

function Gate({ render }: { render: (id: string) => ReactNode }) {
  const id = useSearchParams().get("id");
  if (!id) return <div className="p-8 text-sm text-ink-400">Nothing selected.</div>;
  // Keyed by id: opening another record remounts the page, as a separate route would.
  return <Fragment key={id}>{render(id)}</Fragment>;
}

/** Page wrapper that reads `?id=` (inside the Suspense boundary that useSearchParams requires for static export). */
export function IdPage({ render }: { render: (id: string) => ReactNode }) {
  return <Suspense fallback={null}><Gate render={render} /></Suspense>;
}
