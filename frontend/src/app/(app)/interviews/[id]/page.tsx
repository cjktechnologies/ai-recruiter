"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { useCan, useMe } from "@/components/shell";
import { A, AIBadge, Badge, Button, Card, ErrorBox, Field, Input, Loading, PageHeader, Select, StatusBadge, Textarea } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { fmtDateTime, titleCase } from "@/lib/format";
import type { Interview } from "@/lib/types";

interface Template { id: string; competencies: { name: string; description?: string }[]; questions: { question: string; competency?: string }[] }
interface Card_ { id: string; interviewer_id: string; overall_rating: number | null; recommendation: string | null; ratings: { competency: string; rating: number; evidence: string | null }[]; submitted_at: string | null; strengths: string | null; concerns: string | null }

export default function InterviewDetail() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const can = useCan();
  const { data: iv, reload } = useApi<Interview>(`/interviews/${id}`);
  const { data: templates } = useApi<Template[]>("/interview-templates");
  const { data: cards, reload: rCards } = useApi<Card_[]>(`/interviews/${id}/scorecards`);
  const [ratings, setRatings] = useState<Record<string, { rating: string; evidence: string }>>({});
  const [overall, setOverall] = useState("3");
  const [rec, setRec] = useState("yes");
  const [notes, setNotes] = useState({ strengths: "", concerns: "" });
  const [transcript, setTranscript] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  if (!iv) return <Loading />;
  const template = templates?.find((t) => t.id === iv.template_id);
  const comps = template?.competencies.map((c) => c.name) ?? ["Technical depth", "Problem solving", "Collaboration", "Communication"];
  const mine = cards?.find((c) => c.interviewer_id === me?.id);
  const onPanel = iv.interviewers.some((i) => i.user_id === me?.id);
  async function act(fn: () => Promise<unknown>) { setBusy(true); setError(null); try { await fn(); reload(); rCards(); } catch (e) { setError(e as ApiError); } finally { setBusy(false); } }

  return (
    <>
      <PageHeader title={`${titleCase(iv.kind)} interview · ${iv.candidate_name}`} subtitle={<>{fmtDateTime(iv.scheduled_start)} ({iv.timezone}) · <StatusBadge status={iv.status} /> · <A href={`/applications/${iv.application_id}`}>application</A></>}
        actions={<>{iv.meeting_url && <a href={iv.meeting_url} target="_blank" rel="noreferrer"><Button variant="secondary">Join meeting</Button></a>}
          {iv.status === "scheduled" && can("interviews:schedule") && <Button variant="danger" onClick={() => { const r = prompt("Cancellation reason"); if (r) act(() => api(`/interviews/${id}/cancel`, { method: "POST", body: { reason: r } })); }}>Cancel</Button>}
          {iv.status === "scheduled" && onPanel && <Button variant="secondary" onClick={() => act(() => api(`/interviews/${id}/complete`, { method: "POST" }))}>Mark completed</Button>}</>} />
      <ErrorBox error={error} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Structured guide">
          <ul className="list-disc space-y-1 pl-5 text-sm">{(template?.questions ?? []).map((q, i) => <li key={i}>{q.question} {q.competency && <Badge>{q.competency}</Badge>}</li>)}
            {!template?.questions.length && <li className="text-ink-3">Probe each competency with behavioural questions (“Tell me about a time…”).</li>}</ul>
        </Card>
        <Card title="Interview assistant" actions={<AIBadge />}>
          {iv.ai_summary ? (
            <div className="space-y-2 text-sm">
              <p>{iv.ai_summary.summary}</p>
              {iv.ai_summary.competency_evidence.map((e) => (
                <div key={e.competency}><b>{e.competency}</b> <Badge tone={e.evidence_strength === "none" ? "critical" : e.evidence_strength === "strong" ? "good" : "warn"}>{e.evidence_strength}</Badge>
                  <ul className="ml-4 list-disc text-xs text-ink-2">{e.quotes.map((q, i) => <li key={i}>“{q}”</li>)}</ul></div>))}
              {iv.ai_summary.follow_up_questions.length > 0 && <div className="text-xs text-ink-3">Follow-ups: {iv.ai_summary.follow_up_questions.join(" · ")}</div>}
            </div>
          ) : onPanel || can("interviews:manage") ? (
            <div className="space-y-2">
              <Textarea rows={6} placeholder="Paste the transcript (Interviewer:/Candidate: lines)…" value={transcript} onChange={(e) => setTranscript(e.target.value)} />
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />Candidate consented to recording/transcription</label>
              <Button disabled={!consent || transcript.length < 20} loading={busy} onClick={() => act(() => api(`/interviews/${id}/transcript`, { method: "POST", body: { transcript, consent_confirmed: consent } }))}>Summarize & map competencies</Button>
            </div>
          ) : <p className="text-sm text-ink-3">No transcript yet.</p>}
        </Card>
        {onPanel && !mine?.submitted_at && (
          <Card title="Your scorecard" className="lg:col-span-2">
            <p className="mb-3 text-xs text-ink-3">Submit independently — you won’t see other panelists’ scores first. Rate job-related evidence only.</p>
            <div className="grid gap-3 md:grid-cols-2">
              {comps.map((c) => (
                <div key={c} className="rounded border border-line p-2">
                  <div className="mb-1 text-sm font-medium">{c}</div>
                  <div className="flex gap-2">
                    <Select className="w-24" value={ratings[c]?.rating ?? ""} onChange={(e) => setRatings({ ...ratings, [c]: { evidence: ratings[c]?.evidence ?? "", rating: e.target.value } })}>
                      <option value="">—</option>{[1, 2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}</Select>
                    <Input placeholder="Evidence" value={ratings[c]?.evidence ?? ""} onChange={(e) => setRatings({ ...ratings, [c]: { rating: ratings[c]?.rating ?? "", evidence: e.target.value } })} />
                  </div>
                </div>))}
              <Field label="Overall (1-5)"><Select value={overall} onChange={(e) => setOverall(e.target.value)}>{[1, 2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}</Select></Field>
              <Field label="Recommendation"><Select value={rec} onChange={(e) => setRec(e.target.value)}>{["strong_yes", "yes", "maybe", "no", "strong_no"].map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}</Select></Field>
              <Field label="Strengths"><Textarea rows={2} value={notes.strengths} onChange={(e) => setNotes({ ...notes, strengths: e.target.value })} /></Field>
              <Field label="Concerns"><Textarea rows={2} value={notes.concerns} onChange={(e) => setNotes({ ...notes, concerns: e.target.value })} /></Field>
            </div>
            <Button className="mt-3" loading={busy} onClick={() => act(() => api(`/interviews/${id}/scorecards`, { method: "POST", body: {
              overall_rating: Number(overall), recommendation: rec, strengths: notes.strengths || null, concerns: notes.concerns || null,
              ratings: Object.entries(ratings).filter(([, v]) => v.rating).map(([k, v]) => ({ competency: k, rating: Number(v.rating), evidence: v.evidence || null })) } }))}>Submit scorecard</Button>
          </Card>
        )}
        <Card title="Scorecards" className="lg:col-span-2">
          <ul className="space-y-2 text-sm">{cards?.map((c) => (
            <li key={c.id} className="rounded border border-line p-2">Overall <b>{c.overall_rating}</b> · <StatusBadge status={c.recommendation} />
              <div className="mt-1 flex flex-wrap gap-1">{c.ratings.map((r) => <Badge key={r.competency}>{r.competency}: {r.rating}</Badge>)}</div>
              {c.strengths && <div className="text-xs text-ink-2">+ {c.strengths}</div>}{c.concerns && <div className="text-xs text-ink-2">− {c.concerns}</div>}</li>))}
            {cards?.length === 0 && <li className="text-ink-3">No scorecards submitted yet.</li>}</ul>
        </Card>
      </div>
    </>
  );
}
