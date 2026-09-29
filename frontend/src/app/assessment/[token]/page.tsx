"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { Button, Card, ErrorBox, Loading, Textarea } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";

interface Q { id: string; kind: string; prompt: string; options: string[]; points: number }
interface A { title: string; instructions: string | null; duration_minutes: number; status: string; questions: Q[] }

export default function TakeAssessment() {
  const { token } = useParams<{ token: string }>();
  const { data, error: loadErr } = useApi<A>(`/public/assessments/${token}`);
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState(false);
  if (loadErr) return <main className="p-10 text-center">{loadErr.message}</main>;
  if (!data) return <Loading />;
  if (done || !["invited", "in_progress"].includes(data.status)) return <main className="p-10 text-center">Thank you — this assessment is complete.</main>;
  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <h1 className="text-xl font-semibold">{data.title}</h1>
      <p className="mb-4 text-sm text-ink-2">{data.instructions} · {data.duration_minutes} minutes. Need an accommodation? Reply to your invitation e-mail.</p>
      <ErrorBox error={error} />
      <div className="space-y-3">
        {data.questions.map((q, i) => (
          <Card key={q.id} title={`${i + 1}. ${q.prompt}`}>
            {q.kind === "single_choice" && q.options.map((o) => <label key={o} className="flex gap-2 text-sm"><input type="radio" name={q.id} onChange={() => setAnswers({ ...answers, [q.id]: o })} />{o}</label>)}
            {q.kind === "multi_choice" && q.options.map((o) => <label key={o} className="flex gap-2 text-sm"><input type="checkbox" onChange={(e) => {
              const cur = (answers[q.id] as string[]) ?? [];
              setAnswers({ ...answers, [q.id]: e.target.checked ? [...cur, o] : cur.filter((x) => x !== o) });
            }} />{o}</label>)}
            {!q.kind.endsWith("choice") && <Textarea rows={q.kind === "short_text" ? 2 : 6} className={q.kind === "code" ? "font-mono" : ""} onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })} />}
          </Card>))}
      </div>
      <Button className="mt-4" onClick={async () => { try { await api(`/public/assessments/${token}/submit`, { method: "POST", body: { answers } }); setDone(true); } catch (e) { setError(e as ApiError); } }}>Submit answers</Button>
    </main>
  );
}
