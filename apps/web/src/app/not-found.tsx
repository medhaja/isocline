import Link from "next/link";
export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-2 text-center">
      <h1 className="text-lg font-semibold">This page doesn&apos;t exist</h1>
      <p className="text-sm text-ink-400">The link may be broken, or the item was deleted.</p>
      <Link href="/dashboard" className="mt-2 text-sm font-medium text-accent-600 hover:underline">Go to dashboard</Link>
    </main>
  );
}
