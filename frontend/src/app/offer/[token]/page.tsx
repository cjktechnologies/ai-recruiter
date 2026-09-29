"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { Button, Card, ErrorBox, Loading, Textarea } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { fmtDate, fmtMoney } from "@/lib/format";

interface O { company: string; job_title: string; base_salary: string; currency: string; bonus_pct: number | null; benefits: string[]; start_date: string | null; expires_at: string | null; letter_body: string | null; status: string }

export default function OfferResponse() {
  const { token } = useParams<{ token: string }>();
  const { data, reload, error: loadErr } = useApi<O>(`/public/offers/${token}`);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  if (loadErr) return <main className="p-10 text-center">{loadErr.message}</main>;
  if (!data) return <Loading />;
  async function respond(accept: boolean) {
    try { await api(`/public/offers/${token}/respond`, { method: "POST", body: { accept, reason: reason || null } }); reload(); } catch (e) { setError(e as ApiError); }
  }
  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <h1 className="text-xl font-semibold">{data.company}: offer for {data.job_title}</h1>
      <ErrorBox error={error} />
      <Card className="my-4" title="Summary">
        <ul className="text-sm"><li>Base salary: <b>{fmtMoney(data.base_salary, data.currency)}</b> per year</li>
          {data.bonus_pct ? <li>Bonus target: {data.bonus_pct}%</li> : null}<li>Benefits: {data.benefits.join(", ")}</li>
          <li>Start date: {fmtDate(data.start_date)}</li><li>Respond by: {fmtDate(data.expires_at)}</li></ul>
      </Card>
      <Card title="Offer letter"><pre className="whitespace-pre-wrap font-sans text-sm">{data.letter_body}</pre></Card>
      {data.status === "sent" ? (
        <div className="mt-4 space-y-2">
          <Textarea rows={2} placeholder="Optional message (e.g. reason if declining)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="flex gap-2"><Button onClick={() => respond(true)}>Accept offer</Button><Button variant="secondary" onClick={() => respond(false)}>Decline</Button></div>
        </div>
      ) : <p className="mt-4 text-sm">Status: <b>{data.status}</b></p>}
    </main>
  );
}
