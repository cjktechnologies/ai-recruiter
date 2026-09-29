"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useCan } from "@/components/shell";
import { AIBadge, Badge, Button, Card, ErrorBox, Input, Loading, PageHeader, Select, StatusBadge, Table, Tabs, Textarea } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { fmtMoney, titleCase } from "@/lib/format";
import { STAGES, type Job, type Requirement, type Stage } from "@/lib/types";

interface Card_ { id: string; candidate_name: string; stage: Stage; match_score: number | null; source: string; status: string }
interface Pipeline { counts: Record<string, number>; applications: Card_[] }
interface Sourced { candidate_id: string; full_name: string; headline: string | null; score: number; matched: string[]; missing: string[] }

export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const can = useCan();
  const { data: job, setData } = useApi<Job>(`/jobs/${id}`);
  const { data: pipe } = useApi<Pipeline>(`/jobs/${id}/pipeline`);
  const [tab, setTab] = useState("Pipeline");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<{ description: string; advertisement: string; inclusive_language_issues: string[] } | null>(null);
  const [reqs, setReqs] = useState<Requirement[] | null>(null);
  const [sourced, setSourced] = useState<{ candidates: Sourced[]; recommended_channels: string[] } | null>(null);
  if (!job) return <Loading />;

  async function act<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    try { return await fn(); } catch (e) { setError(e as ApiError); } finally { setBusy(false); }
  }
  const editableReqs = reqs ?? job.requirements;

  return (
    <>
      <PageHeader title={job.title} subtitle={<span className="flex items-center gap-2"><StatusBadge status={job.status} />
        {job.location} · {titleCase(job.remote_policy)} · {fmtMoney(job.salary_min, job.currency)}–{fmtMoney(job.salary_max, job.currency)}</span>}
        actions={<>
          {["draft", "paused"].includes(job.status) && can("jobs:publish") &&
            <Button loading={busy} onClick={() => act(async () => setData(await api<Job>(`/jobs/${id}/publish`, { method: "POST" })))}>Publish</Button>}
          {job.status === "published" && can("jobs:publish") && <>
            <Button variant="secondary" onClick={() => act(async () => setData(await api<Job>(`/jobs/${id}/close`, { method: "POST", query: { pause: true } })))}>Pause</Button>
            <Button variant="secondary" onClick={() => act(async () => setData(await api<Job>(`/jobs/${id}/close`, { method: "POST" })))}>Close</Button>
          </>}
        </>} />
      <ErrorBox error={error} />
      <Tabs tabs={["Pipeline", "Description", "Requirements & screening", "Sourcing"]} active={tab} onChange={setTab} />

      {tab === "Pipeline" && (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {STAGES.concat(["rejected"] as Stage[]).map((stage) => {
            const cards = pipe?.applications.filter((a) => a.stage === stage) ?? [];
            return (
              <div key={stage} className="w-56 shrink-0 rounded-lg border border-line bg-surface-2/50">
                <div className="flex justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wide text-ink-2">
                  <span>{titleCase(stage)}</span><span>{cards.length}</span>
                </div>
                <ul className="space-y-2 px-2 pb-2">
                  {cards.map((c) => (
                    <li key={c.id}>
                      <Link href={`/applications/${c.id}`} className="block rounded-md border border-line bg-surface p-2 text-sm hover:border-accent">
                        <div className="font-medium">{c.candidate_name}</div>
                        <div className="mt-1 flex items-center justify-between text-xs text-ink-3">
                          <span>{c.source}</span>
                          {c.match_score !== null && <span title="Explainable match score">Match {Math.round(c.match_score)}</span>}
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}

      {tab === "Description" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Current description">
            <pre className="whitespace-pre-wrap font-sans text-sm">{job.description}</pre>
          </Card>
          <Card title="Job Description Agent" actions={<>
            <AIBadge label="AI draft" />
            {can("jobs:update") && <Button variant="secondary" loading={busy} onClick={() => act(async () => setDraft(await api(`/jobs/${id}/generate-description`, { method: "POST" })))}>Generate</Button>}
          </>}>
            {!draft ? <p className="text-sm text-ink-3">Generate an inclusive JD and advert from the requirements. Nothing is saved until you accept it.</p> : (
              <div className="space-y-3">
                {draft.inclusive_language_issues.length > 0 && <div className="text-sm text-warn">{draft.inclusive_language_issues.join("; ")}</div>}
                <Textarea rows={14} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
                <Textarea rows={3} value={draft.advertisement} onChange={(e) => setDraft({ ...draft, advertisement: e.target.value })} />
                <Button loading={busy} onClick={() => act(async () => { setData(await api<Job>(`/jobs/${id}`, { method: "PATCH", body: { description: draft.description, advertisement: draft.advertisement } })); setDraft(null); })}>Accept & save</Button>
              </div>
            )}
          </Card>
        </div>
      )}

      {tab === "Requirements & screening" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Requirements (drive screening & matching)" actions={can("jobs:update") && reqs &&
            <Button loading={busy} onClick={() => act(async () => { setData(await api<Job>(`/jobs/${id}/requirements`, { method: "PUT", body: reqs.map((r) => ({ kind: r.kind, name: r.name, min_years: r.min_years, is_mandatory: r.is_mandatory, weight: r.weight })) })); setReqs(null); })}>Save</Button>}>
            <Table head={["Kind", "Name", "Min yrs", "Weight", "Mandatory", ""]} rows={editableReqs.map((r, i) => {
              const upd = (patch: Partial<Requirement>) => setReqs(editableReqs.map((x, j) => (j === i ? { ...x, ...patch } : x)));
              return [
                <Select key="k" value={r.kind} onChange={(e) => upd({ kind: e.target.value })}>
                  {["skill", "experience", "education", "certification", "language", "location", "work_authorization"].map((k) => <option key={k}>{k}</option>)}
                </Select>,
                <Input key="n" value={r.name} onChange={(e) => upd({ name: e.target.value })} />,
                <Input key="y" type="number" className="w-16" value={r.min_years ?? ""} onChange={(e) => upd({ min_years: e.target.value ? Number(e.target.value) : null })} />,
                <Input key="w" type="number" step="0.5" className="w-16" value={r.weight} onChange={(e) => upd({ weight: Number(e.target.value) })} />,
                <input key="m" type="checkbox" checked={r.is_mandatory} onChange={(e) => upd({ is_mandatory: e.target.checked })} aria-label="Mandatory" />,
                <Button key="d" variant="ghost" onClick={() => setReqs(editableReqs.filter((_, j) => j !== i))}>✕</Button>,
              ];
            })} />
            <Button variant="secondary" className="mt-2" onClick={() => setReqs([...editableReqs, { kind: "skill", name: "", min_years: null, is_mandatory: false, weight: 1 }])}>Add requirement</Button>
          </Card>
          <Card title="Knock-out questions">
            <ul className="space-y-1 text-sm">
              {(job.screening_config.knockout_questions ?? []).map((q) => <li key={q.id}>{q.question} <Badge>expects {String(q.expected)}</Badge></li>)}
              {!job.screening_config.knockout_questions?.length && <li className="text-ink-3">None configured.</li>}
            </ul>
            <p className="mt-3 text-xs text-ink-3">Screening outcomes are advisory. A recruiter reviews every result, and overriding the AI requires a documented reason.</p>
          </Card>
        </div>
      )}

      {tab === "Sourcing" && (
        <Card title="Talent Sourcing Agent" actions={<Button loading={busy} onClick={() => act(async () => setSourced(await api(`/jobs/${id}/sourcing`, { method: "POST" })))}>Find matches in talent pool</Button>}>
          <p className="mb-3 text-sm text-ink-3">Searches only candidates who consented to talent-pool processing and are not marked do-not-contact.</p>
          {sourced && <>
            <div className="mb-2 text-sm">Approved channels: {sourced.recommended_channels.map((c) => <Badge key={c}>{c}</Badge>)}</div>
            <Table head={["Candidate", "Score", "Matched", "Missing"]} rows={sourced.candidates.map((c) => [
              <Link key="n" className="text-accent hover:underline" href={`/candidates/${c.candidate_id}`}>{c.full_name}</Link>,
              Math.round(c.score), c.matched.join(", ") || "—", c.missing.join(", ") || "—"])} empty="No consented matches found." />
          </>}
        </Card>
      )}
    </>
  );
}
