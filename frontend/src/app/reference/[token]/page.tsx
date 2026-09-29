"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { Button, ErrorBox, Field, Loading, Textarea } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";

export default function ReferenceForm() {
  const { token } = useParams<{ token: string }>();
  const { data, error: loadErr } = useApi<{ referee_name: string; questions: { id: string; question: string }[] }>(`/public/references/${token}`);
  const [r, setR] = useState<Record<string, string>>({});
  const [done, setDone] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  if (loadErr) return <main className="p-10 text-center">{loadErr.message}</main>;
  if (!data) return <Loading />;
  if (done) return <main className="p-10 text-center">Thank you for your reference.</main>;
  const send = async (decline: boolean) => { try { await api(`/public/references/${token}`, { method: "POST", body: { responses: r, decline } }); setDone(true); } catch (e) { setError(e as ApiError); } };
  return (
    <main className="mx-auto max-w-xl space-y-3 px-4 py-10">
      <h1 className="text-xl font-semibold">Reference request</h1>
      <p className="text-sm text-ink-2">Hello {data.referee_name}, thank you for helping. Please answer factually about job-related conduct and performance.</p>
      <ErrorBox error={error} />
      {data.questions.map((q) => <Field key={q.id} label={q.question}><Textarea rows={3} onChange={(e) => setR({ ...r, [q.id]: e.target.value })} /></Field>)}
      <div className="flex gap-2"><Button onClick={() => send(false)}>Submit</Button><Button variant="secondary" onClick={() => send(true)}>Decline to provide</Button></div>
    </main>
  );
}
