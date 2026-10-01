"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import AuthShell from "@/components/shell/AuthShell";
import { ErrorBox, Spinner } from "@/components/ui";
import { api } from "@/lib/api";

function Verify() {
  const token = useSearchParams().get("token") || "";
  const [state, setState] = useState<"working" | "done" | unknown>("working");
  useEffect(() => { api("/auth/verify-email", { body: { token } }).then(() => setState("done"), (e) => setState(e)); }, [token]);
  if (state === "working") return <p className="flex items-center gap-2 text-sm text-ink-700"><Spinner /> Verifying…</p>;
  if (state === "done") return <p className="text-sm text-ink-700">Your email is verified. <Link className="font-medium text-accent-600 hover:underline" href="/dashboard">Continue</Link></p>;
  return <ErrorBox error={state} />;
}

export default function VerifyEmail() {
  return <AuthShell title="Verify email"><Suspense><Verify /></Suspense></AuthShell>;
}
