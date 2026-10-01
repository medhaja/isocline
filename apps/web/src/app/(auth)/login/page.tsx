"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import AuthShell from "@/components/shell/AuthShell";
import { Button, ErrorBox, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api("/auth/login", { body: { email, password } });
      await qc.invalidateQueries({ queryKey: ["me"] });
      const next = params.get("next");
      router.push(next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard");
    } catch (err) { setError(err); setBusy(false); }
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <ErrorBox error={error} />
      <Field label="Email" htmlFor="email"><Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
      <Field label="Password" htmlFor="pw"><Input id="pw" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
      <div className="flex items-center justify-between">
        <Link href="/forgot-password" className="text-sm text-accent-600 hover:underline">Forgot password?</Link>
        <Button type="submit" variant="primary" loading={busy}>Sign in</Button>
      </div>
    </form>
  );
}

export default function Login() {
  return (
    <AuthShell title="Sign in" footer={<>New to Isocline? <Link className="font-medium text-accent-600 hover:underline" href="/register">Create an account</Link></>}>
      <Suspense><LoginForm /></Suspense>
    </AuthShell>
  );
}
