"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Badge, Button, Card, Field, Input } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { fmtDate } from "@/lib/format";

function Portal() {
  const org = useSearchParams().get("org") ?? "";
  const { data: apps, error, reload } = useApi<{ id: string; job_title: string; status: string; applied_at: string }[]>("/portal/applications");
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  if (error || !apps) {
    return (
      <Card title="Candidate portal sign-in">
        {sent ? <p className="text-sm">If we have your application on file, we&apos;ve e-mailed you a sign-in link.</p> : (
          <form className="space-y-3" onSubmit={async (e) => { e.preventDefault(); const fd = new FormData(); fd.append("email", email);
            await api(`/public/${org}/portal/link`, { method: "POST", body: fd }); setSent(true); }}>
            <Field label="E-mail used to apply"><Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
            <Button type="submit" disabled={!org}>E-mail me a sign-in link</Button>
          </form>)}
      </Card>
    );
  }
  return (
    <div className="space-y-4">
      <Card title="Your applications">
        <ul className="divide-y divide-line text-sm">
          {apps.map((a) => (
            <li key={a.id} className="flex items-center justify-between py-2">
              <span>{a.job_title} <span className="text-ink-3">· applied {fmtDate(a.applied_at)}</span></span>
              <span className="flex items-center gap-2"><Badge tone="info">{a.status}</Badge>
                {!["Withdrawn", "Closed", "Hired"].includes(a.status) && <Button variant="ghost" onClick={async () => { if (confirm("Withdraw this application?")) { await api(`/portal/applications/${a.id}/withdraw`, { method: "POST" }); reload(); } }}>Withdraw</Button>}</span>
            </li>))}
        </ul>
      </Card>
      <Card title="Ask a question">
        <div className="flex gap-2"><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. What happens next?" />
          <Button disabled={!q} onClick={async () => setAnswer((await api<{ answer: string }>("/portal/chat", { method: "POST", body: { message: q } })).answer)}>Ask</Button></div>
        {answer && <p className="mt-2 text-sm">{answer}</p>}
      </Card>
      <Card title="Your data">
        <div className="flex gap-2">
          <Button variant="secondary" onClick={async () => { const d = await api("/portal/me/export"); const a = document.createElement("a");
            a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: "application/json" })); a.download = "my-data.json"; a.click(); }}>Download my data</Button>
          <Button variant="danger" onClick={async () => { if (confirm("Request deletion of all your data?")) { await api("/portal/me/erasure-request", { method: "POST" }); alert("Request received."); } }}>Request deletion</Button>
        </div>
      </Card>
    </div>
  );
}

export default function PortalPage() {
  return <main className="mx-auto max-w-2xl px-4 py-10"><h1 className="mb-4 text-xl font-semibold">Candidate portal</h1><Suspense><Portal /></Suspense></main>;
}
