"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, ErrorBox, Field, Input } from "@/components/ui";

function LoginForm() {
  const router = useRouter();
  const next = useSearchParams().get("next") || "/dashboard";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<{ message: string } | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }) });
    setBusy(false);
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      setError({ message: d.detail ?? "Sign-in failed" });
      return;
    }
    router.push(next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard");
  }
  return (
    <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-line bg-surface p-6">
      <div>
        <h1 className="text-lg font-semibold">Sign in</h1>
        <p className="text-sm text-ink-2">AI Recruiter — recruitment operations</p>
      </div>
      <ErrorBox error={error} />
      <Field label="Work e-mail"><Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
      <Field label="Password"><Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
      <Button type="submit" loading={busy} className="w-full justify-center">Sign in</Button>
      <Button type="button" variant="ghost" className="w-full justify-center"
        onClick={() => window.location.assign(new URL("/api/backend/auth/oidc/login", window.location.origin))}>
        Sign in with SSO
      </Button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Suspense><LoginForm /></Suspense>
    </main>
  );
}
