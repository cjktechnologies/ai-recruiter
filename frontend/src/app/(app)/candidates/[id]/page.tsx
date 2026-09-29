"use client";

import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { useCan } from "@/components/shell";
import { A, Badge, Button, Card, ErrorBox, Loading, PageHeader, Select, StatusBadge, Table, Tabs, Textarea } from "@/components/ui";
import { api, ApiError, useApi, type Page } from "@/lib/api";
import { fmtDate, fmtDateTime, titleCase } from "@/lib/format";
import type { Application, Candidate, Job } from "@/lib/types";

interface Doc { id: string; filename: string; kind: string; scan_status: string; parse_status: string; security_flags: string[]; created_at: string; size_bytes: number }
interface Note { id: string; body: string; visibility: string; created_at: string }
interface Comm { id: string; channel: string; subject: string | null; status: string; created_at: string; ai_generated: boolean }
interface Consent { id: string; purpose: string; granted: boolean; recorded_at: string; expires_at: string | null }
interface Dup { candidate_id: string; full_name: string; email: string; reasons: string[]; score: number }

export default function CandidateDetail() {
  const { id } = useParams<{ id: string }>();
  const can = useCan();
  const { data: c, reload } = useApi<Candidate>(`/candidates/${id}`);
  const { data: apps, reload: reloadApps } = useApi<Page<Application>>("/applications", { candidate_id: id });
  const { data: docs, reload: reloadDocs } = useApi<Doc[]>(`/candidates/${id}/documents`);
  const { data: notes, reload: reloadNotes } = useApi<Note[]>(`/candidates/${id}/notes`);
  const { data: comms } = useApi<Comm[]>(can("communications:read") ? `/candidates/${id}/communications` : null);
  const { data: consents } = useApi<Consent[]>(`/candidates/${id}/consents`);
  const { data: dups } = useApi<Dup[]>(`/candidates/${id}/duplicates`);
  const { data: jobs } = useApi<Page<Job>>("/jobs", { status: "published", page_size: 100 });
  const [tab, setTab] = useState("Profile");
  const [note, setNote] = useState("");
  const [jobId, setJobId] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const file = useRef<HTMLInputElement>(null);
  if (!c) return <Loading />;

  async function act(fn: () => Promise<unknown>, after?: () => void) {
    setError(null);
    try { await fn(); after?.(); } catch (e) { setError(e as ApiError); }
  }
  async function upload() {
    const f = file.current?.files?.[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    fd.append("kind", "cv");
    await act(() => api(`/candidates/${id}/documents`, { method: "POST", body: fd }), () => { reloadDocs(); reload(); });
  }

  return (
    <>
      <PageHeader title={c.full_name} subtitle={<>{c.headline ?? c.current_title} {c.anonymized_at && <Badge tone="critical">Personal data erased</Badge>}</>}
        actions={<>
          {can("candidates:export") && <Button variant="secondary" onClick={() => act(async () => {
            const data = await api(`/candidates/${id}/export`);
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
            const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `candidate-${id}.json`; a.click();
          })}>Export (DSAR)</Button>}
          {can("candidates:delete") && !c.anonymized_at && <Button variant="danger" onClick={() => confirm("Erase all personal data? This cannot be undone.") && act(() => api(`/candidates/${id}`, { method: "DELETE" }), reload)}>Erase data</Button>}
        </>} />
      <ErrorBox error={error} />
      {dups && dups.length > 0 && (
        <div className="mb-4 rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm">
          Possible duplicate: {dups.map((d) => <span key={d.candidate_id}><A href={`/candidates/${d.candidate_id}`}>{d.full_name}</A> ({d.reasons.join(", ")}) </span>)}
          {can("candidates:delete") && <Button variant="secondary" className="ml-2" onClick={() => act(() => api(`/candidates/${id}/merge`, { method: "POST", body: { duplicate_id: dups[0].candidate_id } }), reload)}>Merge into this profile</Button>}
        </div>
      )}
      <Tabs tabs={["Profile", "Applications", "Documents", "Notes", "Communications", "Consent"]} active={tab} onChange={setTab} />

      {tab === "Profile" && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="Contact & summary">
            <dl className="space-y-1 text-sm">
              <div><dt className="inline text-ink-3">E-mail: </dt><dd className="inline">{c.email}</dd></div>
              <div><dt className="inline text-ink-3">Phone: </dt><dd className="inline">{c.phone ?? <span className="text-ink-3">hidden</span>}</dd></div>
              <div><dt className="inline text-ink-3">Location: </dt><dd className="inline">{c.location ?? "—"}</dd></div>
              <div><dt className="inline text-ink-3">Experience: </dt><dd className="inline">{c.years_experience ?? "—"} yrs</dd></div>
              <div><dt className="inline text-ink-3">Languages: </dt><dd className="inline">{c.languages?.join(", ") || "—"}</dd></div>
              <div><dt className="inline text-ink-3">Retention until: </dt><dd className="inline">{fmtDate(c.retention_until)}</dd></div>
            </dl>
            {c.summary && <p className="mt-3 text-sm text-ink-2">{c.summary}</p>}
          </Card>
          <Card title="Skills (with source evidence)" className="lg:col-span-2">
            <ul className="space-y-1.5 text-sm">
              {c.skills?.map((s) => (
                <li key={s.name}><Badge tone={s.source === "extracted" ? "info" : "neutral"}>{s.name}</Badge>
                  {s.evidence && <span className="ml-2 text-xs text-ink-3">“{s.evidence}”</span>}</li>))}
            </ul>
          </Card>
          <Card title="Experience" className="lg:col-span-2">
            <Table head={["Title", "Company", "From", "To", "Months"]} rows={(c.experience ?? []).map((e) => [e.title ?? "—", e.company ?? "—", e.start ?? "", e.end ?? "", e.months])} />
          </Card>
          <Card title="Education">
            <ul className="text-sm">{c.education?.map((e, i) => <li key={i}>{e.degree} {e.field} — {e.institution}</li>)}</ul>
          </Card>
        </div>
      )}

      {tab === "Applications" && (
        <Card title="Applications" actions={can("applications:create") && <>
          <Select value={jobId} onChange={(e) => setJobId(e.target.value)}><option value="">Add to job…</option>
            {jobs?.items.map((j) => <option key={j.id} value={j.id}>{j.title}</option>)}</Select>
          <Button disabled={!jobId} onClick={() => act(() => api("/applications", { method: "POST", body: { job_id: jobId, candidate_id: id, source: "sourced" }, idempotencyKey: `add-${id}-${jobId}` }), reloadApps)}>Add</Button>
        </>}>
          <Table head={["Job", "Stage", "Match", "Applied"]} rows={(apps?.items ?? []).map((a) => [
            <A key="j" href={`/applications/${a.id}`}>{a.job_title}</A>, <StatusBadge key="s" status={a.stage} />,
            a.match_score !== null ? Math.round(a.match_score) : "—", fmtDate(a.applied_at)])} />
        </Card>
      )}

      {tab === "Documents" && (
        <Card title="Documents" actions={can("documents:upload") && <>
          <input ref={file} type="file" accept=".pdf,.docx,.txt,.md" className="text-sm" aria-label="Choose file" />
          <Button onClick={upload}>Upload & parse</Button></>}>
          <p className="mb-2 text-xs text-ink-3">Uploads are type-checked, malware-scanned and screened for hidden instructions before any AI processing.</p>
          <Table head={["File", "Uploaded", "Scan", "Parse", "Security flags", ""]} rows={(docs ?? []).map((d) => [
            d.filename, fmtDateTime(d.created_at), <StatusBadge key="s" status={d.scan_status} />, <StatusBadge key="p" status={d.parse_status} />,
            d.security_flags.length ? <span key="f" className="text-xs text-serious">{d.security_flags.join(", ")}</span> : "—",
            d.scan_status === "clean" ? <a key="d" className="text-accent hover:underline" href={`/api/backend/candidates/${id}/documents/${d.id}/download`}>Download</a> : "",
          ])} />
        </Card>
      )}

      {tab === "Notes" && (
        <Card title="Notes">
          <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a note (visible to the hiring team)" />
          <Button className="mt-2" disabled={!note} onClick={() => act(() => api(`/candidates/${id}/notes`, { method: "POST", body: { body: note } }), () => { setNote(""); reloadNotes(); })}>Add note</Button>
          <ul className="mt-4 divide-y divide-line text-sm">{notes?.map((n) => <li key={n.id} className="py-2">{n.body}<div className="text-xs text-ink-3">{fmtDateTime(n.created_at)} · {n.visibility}</div></li>)}</ul>
        </Card>
      )}

      {tab === "Communications" && (
        <Card title="Communication history">
          <Table head={["When", "Channel", "Subject", "Status"]} rows={(comms ?? []).map((m) => [fmtDateTime(m.created_at), titleCase(m.channel),
            <span key="s">{m.subject}{m.ai_generated && <Badge tone="ai">AI</Badge>}</span>, <StatusBadge key="st" status={m.status} />])} />
        </Card>
      )}

      {tab === "Consent" && (
        <Card title="Consent records">
          <Table head={["Purpose", "Granted", "Recorded", "Expires"]} rows={(consents ?? []).map((k) => [titleCase(k.purpose),
            k.granted ? <Badge key="g" tone="good">Granted</Badge> : <Badge key="g" tone="critical">Withheld</Badge>, fmtDateTime(k.recorded_at), fmtDate(k.expires_at)])} />
        </Card>
      )}
    </>
  );
}
