"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import AuthShell from "@/components/shell/AuthShell";
import { Button, ErrorBox, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";
import { useMeta } from "@/lib/session";

export default function Register() {
  const router = useRouter();
  const qc = useQueryClient();
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState<unknown>(null);
  const meta = useMeta();
  const [busy, setBusy] = useState(false);
  const short = form.password.length > 0 && form.password.length < 10;
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (short) return;
    setBusy(true); setError(null);
    try {
      await api("/auth/register", { body: form });
      await qc.invalidateQueries({ queryKey: ["me"] });
      router.push("/dashboard?welcome=1");
    } catch (err) { setError(err); setBusy(false); }
  }
  return (
    <AuthShell title="Create your account" subtitle="You'll get a personal workspace to start building."
      footer={<>Already have an account? <Link className="font-medium text-accent-600 hover:underline" href="/login">Sign in</Link></>}>
      <form onSubmit={submit} className="space-y-4">
        {meta.data?.signup === "first_account_only" && <p className="rounded-md bg-canvas p-2 text-xs text-ink-600">On this installation only the first account can register; it becomes the administrator. Later sign-ups need ISOCLINE_ALLOW_SIGNUP=true.</p>}
        <ErrorBox error={error} />
        <Field label="Name" htmlFor="name"><Input id="name" autoComplete="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Email" htmlFor="email"><Input id="email" type="email" autoComplete="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
        <Field label="Password" htmlFor="pw" hint="At least 10 characters" error={short ? "Use at least 10 characters" : null}>
          <Input id="pw" type="password" autoComplete="new-password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </Field>
        <Button type="submit" variant="primary" loading={busy} className="w-full">Create account</Button>
      </form>
    </AuthShell>
  );
}
