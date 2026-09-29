"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Badge, Button, Card, Input, Loading } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { titleCase } from "@/lib/format";

interface PublicJob { title: string; slug: string; location: string | null; remote_policy: string; employment_type: string }

export default function Careers() {
  const { org } = useParams<{ org: string }>();
  const { data, error } = useApi<PublicJob[]>(`/public/${org}/jobs`);
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="text-2xl font-semibold">Open positions</h1>
      <p className="mb-6 text-sm text-ink-2">We review every application. AI helps us organise applications; people make every decision.</p>
      {error && <p className="text-critical">{error.message}</p>}
      {!data ? <Loading /> : (
        <ul className="space-y-2">
          {data.map((j) => (
            <li key={j.slug}><Link href={`/careers/${org}/${j.slug}`} className="block rounded-lg border border-line bg-surface p-4 hover:border-accent">
              <div className="font-medium">{j.title}</div>
              <div className="mt-1 flex gap-2 text-sm text-ink-2">{j.location} <Badge>{titleCase(j.remote_policy)}</Badge> <Badge>{titleCase(j.employment_type)}</Badge></div>
            </Link></li>))}
          {data.length === 0 && <li className="text-ink-3">No open positions right now.</li>}
        </ul>
      )}
      <Card title="Questions? Ask our recruiting assistant" className="mt-8">
        <div className="flex gap-2">
          <Input placeholder="e.g. How long does the process take?" value={q} onChange={(e) => setQ(e.target.value)} />
          <Button disabled={!q} onClick={async () => setAnswer((await api<{ answer: string }>(`/public/${org}/chat`, { method: "POST", body: { message: q } })).answer)}>Ask</Button>
        </div>
        {answer && <p className="mt-3 text-sm">{answer}</p>}
      </Card>
      <p className="mt-6 text-center text-sm"><Link href={`/portal?org=${org}`} className="text-accent hover:underline">Already applied? Track your application</Link></p>
    </main>
  );
}
