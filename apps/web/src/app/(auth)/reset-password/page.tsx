"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import AuthShell from "@/components/shell/AuthShell";
import { Button, ErrorBox, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";

function ResetForm() {
  const token = useSearchParams().get("token") || "";
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { await api("/auth/reset-password", { body: { token, password } }); router.push("/dashboard"); } catch (err) { setError(err); setBusy(false); }
  }
  if (!token) return <ErrorBox error="This reset link is incomplete. Request a new one." />;
  return (
    <form onSubmit={submit} className="space-y-4">
      <ErrorBox error={error} />
      <Field label="New password" htmlFor="pw" hint="At least 10 characters"><Input id="pw" type="password" minLength={10} required autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
      <Button type="submit" variant="primary" loading={busy} className="w-full">Set new password</Button>
    </form>
  );
}

export default function Reset() {
  return <AuthShell title="Choose a new password"><Suspense><ResetForm /></Suspense></AuthShell>;
}
