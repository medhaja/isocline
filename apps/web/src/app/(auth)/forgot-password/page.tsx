"use client";
import Link from "next/link";
import { useState } from "react";
import AuthShell from "@/components/shell/AuthShell";
import { Button, ErrorBox, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";

export default function Forgot() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { await api("/auth/forgot-password", { body: { email } }); setSent(true); } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <AuthShell title="Reset your password" footer={<Link className="font-medium text-accent-600 hover:underline" href="/login">Back to sign in</Link>}>
      {sent ? (
        <p className="text-sm text-ink-700">If an account exists for <strong>{email}</strong>, we sent a link to reset the password. It expires in one hour.</p>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <ErrorBox error={error} />
          <Field label="Email" htmlFor="email"><Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Button type="submit" variant="primary" loading={busy} className="w-full">Send reset link</Button>
        </form>
      )}
    </AuthShell>
  );
}
