"use client";

import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Button, Card, ErrorBox, Field, Input, Loading, Select, Textarea } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { fmtMoney } from "@/lib/format";

interface PublicJob { title: string; description: string; location: string | null; salary_min: string | null; salary_max: string | null; currency: string; knockout_questions: { id: string; question: string }[] }

export default function Apply() {
  const { org, slug } = useParams<{ org: string; slug: string }>();
  const { data: job } = useApi<PublicJob>(`/public/${org}/jobs/${slug}`);
  const key = useMemo(() => `apply-${crypto.randomUUID()}`, []);
  const [f, setF] = useState({ first_name: "", last_name: "", email: "", phone: "", location: "", linkedin_url: "", cover_letter: "" });
  const [answers, setAnswers] = useState<Record<string, boolean>>({});
  const [consent, setConsent] = useState({ recruitment: false, ai: true, pool: false });
  const [eeo, setEeo] = useState({ gender: "", ethnicity: "", age_band: "", disability: "" });
  const [cv, setCv] = useState<File | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!job) return <Loading />;
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!cv) return;
    setBusy(true); setError(null);
    const fd = new FormData();
    Object.entries(f).forEach(([k, v]) => v && fd.append(k, v));
    fd.append("consent_recruitment", String(consent.recruitment));
    fd.append("consent_ai_screening", String(consent.ai));
    fd.append("consent_talent_pool", String(consent.pool));
    fd.append("answers", JSON.stringify(answers));
    const eeoFilled = Object.fromEntries(Object.entries(eeo).filter(([, v]) => v));
    if (Object.keys(eeoFilled).length) fd.append("eeo", JSON.stringify(eeoFilled));
    fd.append("cv", cv);
    try { await api(`/public/${org}/jobs/${slug}/apply`, { method: "POST", body: fd, idempotencyKey: key }); setDone(true); }
    catch (err) { setError(err as ApiError); } finally { setBusy(false); }
  }
  if (done) return <main className="mx-auto max-w-xl px-4 py-16 text-center"><h1 className="text-xl font-semibold">Application received — thank you!</h1><p className="mt-2 text-ink-2">We&apos;ve e-mailed a confirmation. You can track progress in the candidate portal.</p></main>;
  return (
    <main className="mx-auto grid max-w-5xl gap-6 px-4 py-10 lg:grid-cols-2">
      <article>
        <h1 className="text-2xl font-semibold">{job.title}</h1>
        <p className="text-sm text-ink-2">{job.location} {job.salary_min && `· ${fmtMoney(job.salary_min, job.currency)} – ${fmtMoney(job.salary_max, job.currency)}`}</p>
        <pre className="mt-4 whitespace-pre-wrap font-sans text-sm">{job.description}</pre>
      </article>
      <Card title="Apply">
        <form onSubmit={submit} className="space-y-3">
          <ErrorBox error={error} />
          <div className="grid grid-cols-2 gap-2">
            <Field label="First name"><Input required value={f.first_name} onChange={(e) => setF({ ...f, first_name: e.target.value })} /></Field>
            <Field label="Last name"><Input required value={f.last_name} onChange={(e) => setF({ ...f, last_name: e.target.value })} /></Field>
          </div>
          <Field label="E-mail"><Input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Phone (optional)"><Input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></Field>
            <Field label="Location (optional)"><Input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
          </div>
          <Field label="CV (PDF, DOCX or TXT, max 10 MB)"><input type="file" required accept=".pdf,.docx,.txt" onChange={(e) => setCv(e.target.files?.[0] ?? null)} className="text-sm" /></Field>
          {job.knockout_questions.map((q) => (
            <Field key={q.id} label={q.question}><Select required value={answers[q.id] === undefined ? "" : String(answers[q.id])} onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value === "true" })}>
              <option value="">Select…</option><option value="true">Yes</option><option value="false">No</option></Select></Field>))}
          <Field label="Cover letter (optional)"><Textarea rows={3} value={f.cover_letter} onChange={(e) => setF({ ...f, cover_letter: e.target.value })} /></Field>
          <fieldset className="space-y-1 rounded border border-line p-3 text-sm">
            <legend className="px-1 font-medium">Privacy & consent</legend>
            <label className="flex gap-2"><input type="checkbox" required checked={consent.recruitment} onChange={(e) => setConsent({ ...consent, recruitment: e.target.checked })} />I consent to my data being processed for this application (required).</label>
            <label className="flex gap-2"><input type="checkbox" checked={consent.ai} onChange={(e) => setConsent({ ...consent, ai: e.target.checked })} />Allow AI-assisted screening (a person always makes the decision; untick for fully manual review).</label>
            <label className="flex gap-2"><input type="checkbox" checked={consent.pool} onChange={(e) => setConsent({ ...consent, pool: e.target.checked })} />Keep my profile for future opportunities.</label>
          </fieldset>
          <details className="rounded border border-line p-3 text-sm">
            <summary className="cursor-pointer font-medium">Voluntary equal-opportunity survey (optional)</summary>
            <p className="my-2 text-xs text-ink-3">Used only in aggregate to monitor fairness. Never visible to reviewers or AI screening.</p>
            <div className="grid grid-cols-2 gap-2">
              {(["gender", "ethnicity", "age_band", "disability"] as const).map((k) => <Input key={k} placeholder={k.replace("_", " ")} value={eeo[k]} onChange={(e) => setEeo({ ...eeo, [k]: e.target.value })} />)}
            </div>
          </details>
          <Button type="submit" loading={busy} disabled={!cv || !consent.recruitment}>Submit application</Button>
        </form>
      </Card>
    </main>
  );
}
