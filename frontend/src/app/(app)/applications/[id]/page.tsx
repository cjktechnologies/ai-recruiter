"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useCan } from "@/components/shell";
import { A, AIBadge, Badge, Button, Card, cx, ErrorBox, Input, Loading, PageHeader, Select, StatusBadge, Table, Textarea } from "@/components/ui";
import { api, ApiError, newIdempotencyKey, useApi, type Page } from "@/lib/api";
import { fmtDateTime, fmtMoney, titleCase } from "@/lib/format";
import { STAGES, type Application, type Evaluation, type Interview, type Offer, type Screening, type User } from "@/lib/types";

interface AResult { id: string; assessment_id: string; status: string; percentage: number | null; passed: boolean | null; question_scores: Record<string, { score: number; max: number; needs_review: boolean; note: string }> }
interface Assessment { id: string; title: string }
interface Ref { id: string; referee_name: string; status: string; responses: Record<string, string> }
interface BG { id: string; provider: string; status: string; result: string | null }
interface Slot { start: string; end: string; score: number }

function Stepper({ stage }: { stage: string }) {
  const idx = STAGES.indexOf(stage as never);
  return (
    <ol className="mb-5 flex flex-wrap gap-1 text-xs">
      {STAGES.map((s, i) => (
        <li key={s} className={cx("rounded px-2 py-1", i < idx ? "bg-good/15 text-good" : i === idx ? "bg-accent text-white" : "bg-surface-2 text-ink-3")}>{titleCase(s)}</li>
      ))}
      {["rejected", "withdrawn"].includes(stage) && <li className="rounded bg-critical/15 px-2 py-1 text-critical">{titleCase(stage)}</li>}
    </ol>
  );
}

export default function ApplicationWorkspace() {
  const { id } = useParams<{ id: string }>();
  const can = useCan();
  const { data: app, reload } = useApi<Application>(`/applications/${id}`);
  const { data: screenings, reload: rScr } = useApi<Screening[]>(can("screening:read") ? `/applications/${id}/screening` : null);
  const { data: results, reload: rRes } = useApi<AResult[]>(`/applications/${id}/assessment-results`);
  const { data: assessments } = useApi<Page<Assessment>>(can("assessments:invite") ? "/assessments" : null, { page_size: 100 });
  const { data: interviews, reload: rIv } = useApi<Interview[]>("/interviews", { application_id: id });
  const { data: evals, reload: rEv } = useApi<Evaluation[]>(can("evaluations:read") ? `/applications/${id}/evaluations` : null);
  const { data: refs, reload: rRefs } = useApi<Ref[]>(can("verification:read") ? `/applications/${id}/references` : null);
  const { data: checks, reload: rBg } = useApi<BG[]>(can("verification:read") ? `/applications/${id}/background-checks` : null);
  const { data: offers, reload: rOff } = useApi<Page<Offer>>(can("offers:read") ? "/offers" : null, { application_id: id });
  const { data: interviewers } = useApi<Page<User>>(can("interviews:schedule") ? "/users" : null, { page_size: 200, active: true });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});
  const [panel, setPanel] = useState<string[]>([]);
  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [links, setLinks] = useState<Record<string, string>>({});
  if (!app) return <Loading />;
  const fv = (k: string) => form[k] ?? "";
  const setFv = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value });
  const reloadAll = () => { reload(); rScr(); rRes(); rIv(); rEv(); rRefs(); rBg(); rOff(); };
  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await fn(); reloadAll(); } catch (e) { setError(e as ApiError); } finally { setBusy(false); }
  }
  const scr = screenings?.[0];
  const ev = evals?.[0];
  const offer = offers?.items[0];
  const terminal = ["hired", "rejected", "withdrawn"].includes(app.stage);

  return (
    <>
      <PageHeader title={app.candidate_name ?? "Application"}
        subtitle={<>for <A href={`/jobs/${app.job_id}`}>{app.job_title}</A> · <A href={`/candidates/${app.candidate_id}`}>profile</A> · source {app.source}</>}
        actions={!terminal && can("applications:reject") && <>
          <Input placeholder="Rejection reason" value={fv("reject")} onChange={setFv("reject")} className="w-56" />
          <Button variant="danger" disabled={fv("reject").length < 2} loading={busy}
            onClick={() => act(() => api(`/applications/${id}/reject`, { method: "POST", body: { reason: fv("reject"), notify_candidate: true } }))}>Reject</Button>
        </>} />
      <Stepper stage={app.stage} />
      {app.workflow && (
        <div className="mb-4 rounded-md border border-line bg-surface px-3 py-2 text-sm">
          Orchestrator: <b>{titleCase(app.workflow.current_node)}</b> · <StatusBadge status={app.workflow.status} />
          {app.workflow.waiting_on && <span className="ml-2 text-ink-2">waiting on <code className="text-xs">{app.workflow.waiting_on}</code></span>}
        </div>
      )}
      <ErrorBox error={error} />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {/* --- Screening --- */}
          <Card title="Screening" actions={<>{scr && <AIBadge label="Screening agent" />}
            {can("screening:run") && !terminal && <Button variant="secondary" loading={busy} onClick={() => act(() => api(`/applications/${id}/screening`, { method: "POST" }))}>{scr ? "Re-run" : "Run AI screening"}</Button>}</>}>
            {!scr ? <p className="text-sm text-ink-3">No screening yet.</p> : (
              <div className="space-y-4 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  {scr.eligible ? <Badge tone="good">Meets mandatory criteria</Badge> : <Badge tone="critical">Mandatory criteria not met</Badge>}
                  <span>Match <b>{Math.round(scr.score)}</b>/100</span>
                  <span>AI recommendation: <StatusBadge status={scr.recommendation} /></span>
                  <span>Review: <StatusBadge status={scr.review_status} /></span>
                </div>
                <div>
                  <h3 className="mb-1 font-semibold">Facts from candidate material</h3>
                  <ul className="space-y-1">
                    {scr.facts.map((f, i) => <li key={i}>{f.statement}{f.evidence && <span className="ml-1 text-xs text-ink-3">— “{f.evidence}”</span>}</li>)}
                  </ul>
                </div>
                <div>
                  <h3 className="mb-1 font-semibold">Rule checks</h3>
                  <Table head={["Rule", "Result", "Detail"]} rows={scr.rule_results.map((r) => [
                    <span key="r">{r.rule}{r.mandatory && <Badge>mandatory</Badge>}</span>,
                    r.passed ? <Badge key="p" tone="good">Pass</Badge> : <Badge key="p" tone="critical">Fail</Badge>, r.detail])} />
                </div>
                <div className="rounded-md border border-ai/30 bg-ai/5 p-3">
                  <h3 className="mb-1 flex items-center gap-2 font-semibold">Interpretation <AIBadge label={scr.interpretations.some((i) => i.ai_generated) ? "AI-generated" : "Rule-based"} /></h3>
                  <p>{scr.summary}</p>
                  <ul className="mt-2 space-y-0.5">{scr.interpretations.map((i, k) => <li key={k}><Badge>{i.kind}</Badge> {i.text}</li>)}</ul>
                </div>
                {scr.review_status === "pending_review" && app.stage === "screened" && can("screening:review") && (
                  <div className="space-y-2 border-t border-line pt-3">
                    <h3 className="font-semibold">Your decision</h3>
                    <div className="grid gap-2 md:grid-cols-3">
                      <Select value={fv("next") || "interview"} onChange={setFv("next")}><option value="interview">Advance to interview</option><option value="assessment">Advance to assessment</option></Select>
                      <Input placeholder="Override reason (required if disagreeing with AI)" value={fv("override")} onChange={setFv("override")} className="md:col-span-2" />
                    </div>
                    <div className="flex gap-2">
                      <Button loading={busy} onClick={() => act(() => api(`/screening/${scr.id}/review`, { method: "POST", body: { decision: "advance", next_stage: fv("next") || "interview", override_reason: fv("override") || null } }))}>Advance</Button>
                      <Button variant="danger" disabled={busy} onClick={() => act(() => api(`/screening/${scr.id}/review`, { method: "POST", body: { decision: "reject", override_reason: fv("override") || null, rejection_reason: "Not progressing after screening" } }))}>Reject</Button>
                      <Button variant="secondary" disabled={busy} onClick={() => act(() => api(`/screening/${scr.id}/review`, { method: "POST", body: { decision: "hold" } }))}>Hold</Button>
                    </div>
                  </div>
                )}
                {scr.override_reason && <p className="text-xs text-ink-3">Recruiter override: {scr.override_reason}</p>}
              </div>
            )}
          </Card>

          {/* --- Assessments --- */}
          {(app.stage === "assessment" || (results?.length ?? 0) > 0) && (
            <Card title="Assessments" actions={app.stage === "assessment" && can("assessments:invite") && <>
              <Select value={fv("assessment")} onChange={setFv("assessment")}><option value="">Choose assessment…</option>
                {assessments?.items.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}</Select>
              <Button disabled={!fv("assessment")} loading={busy} onClick={() => act(async () => {
                const r = await api<{ candidate_link: string }>(`/applications/${id}/assessments`, { method: "POST", body: { assessment_id: fv("assessment") } });
                setLinks({ ...links, assessment: r.candidate_link });
              })}>Invite</Button></>}>
              {links.assessment && <p className="mb-2 text-xs text-ink-3">Candidate link (also e-mailed): {links.assessment}</p>}
              <Table head={["Status", "Score", "Result", "Review"]} rows={(results ?? []).map((r) => [
                <StatusBadge key="s" status={r.status} />, r.percentage !== null ? `${r.percentage}%` : "—",
                r.passed === null ? "—" : r.passed ? <Badge key="p" tone="good">Passed</Badge> : <Badge key="p" tone="critical">Below threshold</Badge>,
                r.status === "submitted" && can("assessments:score") ? (
                  <div key="rv" className="space-y-1">
                    {Object.entries(r.question_scores).filter(([, q]) => q.needs_review).map(([qid, q]) => (
                      <div key={qid} className="flex items-center gap-1 text-xs">
                        <span className="text-ink-3">{q.note}</span>
                        <Input type="number" min={0} max={q.max} className="w-16" placeholder={String(q.score)} value={fv(`q-${qid}`)} onChange={setFv(`q-${qid}`)} />/{q.max}
                      </div>))}
                    <Button variant="secondary" onClick={() => act(() => api(`/assessment-results/${r.id}/score`, { method: "POST", body: { question_scores: Object.fromEntries(
                      Object.entries(r.question_scores).filter(([, q]) => q.needs_review).map(([qid, q]) => [qid, Number(fv(`q-${qid}`) || q.score)])) } }))}>Confirm scores</Button>
                  </div>) : "—"])} />
            </Card>
          )}

          {/* --- Interviews --- */}
          {(["interview", "evaluation"].includes(app.stage) || (interviews?.length ?? 0) > 0) && (
            <Card title="Interviews">
              <Table head={["When", "Type", "Status", ""]} rows={(interviews ?? []).map((i) => [fmtDateTime(i.scheduled_start), titleCase(i.kind),
                <StatusBadge key="s" status={i.status} />, <A key="o" href={`/interviews/${i.id}`}>Open</A>])} empty="No interviews scheduled." />
              {app.stage === "interview" && can("interviews:schedule") && (
                <div className="mt-4 space-y-3 border-t border-line pt-3 text-sm">
                  <h3 className="font-semibold">Schedule an interview</h3>
                  <div className="flex flex-wrap gap-2">
                    {interviewers?.items.filter((u) => u.role_keys.some((r) => ["interviewer", "hiring_manager", "recruiter", "hr_manager"].includes(r))).map((u) => (
                      <label key={u.id} className="flex items-center gap-1 rounded border border-line px-2 py-1">
                        <input type="checkbox" checked={panel.includes(u.id)} onChange={(e) => setPanel(e.target.checked ? [...panel, u.id] : panel.filter((x) => x !== u.id))} />{u.full_name}
                      </label>))}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="secondary" disabled={!panel.length} loading={busy} onClick={() => act(async () => setSlots(await api<Slot[]>(`/applications/${id}/interview-slots`, { method: "POST", body: { interviewer_ids: panel } })))}>
                      Suggest slots (Scheduling agent)</Button>
                    <Select value={fv("kind") || "video"} onChange={setFv("kind")} className="w-40">
                      {["phone_screen", "video", "technical", "panel", "onsite", "final"].map((k) => <option key={k} value={k}>{titleCase(k)}</option>)}</Select>
                  </div>
                  {slots && (
                    <div className="flex flex-wrap gap-2">
                      {slots.map((s) => (
                        <Button key={s.start} variant="secondary" loading={busy} onClick={() => act(() => api(`/applications/${id}/interviews`, { method: "POST", body: {
                          kind: fv("kind") || "video", scheduled_start: s.start, scheduled_end: s.end, interviewer_ids: panel, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone } }).then(() => setSlots(null)))}>
                          {fmtDateTime(s.start)}</Button>))}
                      {slots.length === 0 && <span className="text-ink-3">No common availability in the next 10 days.</span>}
                    </div>
                  )}
                </div>
              )}
            </Card>
          )}

          {/* --- Evaluation --- */}
          {(ev || ["evaluation", "interview"].includes(app.stage)) && can("evaluations:read") && (
            <Card title="Evaluation" actions={<>{ev && <AIBadge label="Evaluation agent" />}
              {can("evaluations:run") && ["interview", "evaluation"].includes(app.stage) && <Button variant="secondary" loading={busy} onClick={() => act(() => api(`/applications/${id}/evaluations`, { method: "POST" }))}>Compile evaluation</Button>}</>}>
              {!ev ? <p className="text-sm text-ink-3">Compiled automatically once all interview feedback is in.</p> : (
                <div className="space-y-3 text-sm">
                  <div className="flex gap-3">Evidence score <b>{ev.overall_score}</b> · AI recommendation <StatusBadge status={ev.ai_recommendation} /></div>
                  <Table head={["Competency", "Mean (1-5)", "Ratings", "Spread"]} rows={Object.entries(ev.competency_matrix).map(([k, v]) => [k, v.mean, v.n,
                    v.spread >= 2 ? <Badge key="s" tone="warn">{v.spread}</Badge> : v.spread])} />
                  {ev.risks.length > 0 && <ul className="text-serious">{ev.risks.map((r) => <li key={r}>⚠ {r}</li>)}</ul>}
                  <p className="rounded-md border border-ai/30 bg-ai/5 p-2">{ev.ai_rationale}</p>
                  {!ev.decision && app.stage === "evaluation" && can("evaluations:decide") && (
                    <div className="space-y-2 border-t border-line pt-3">
                      <Textarea rows={2} placeholder="Decision rationale (required)" value={fv("rationale")} onChange={setFv("rationale")} />
                      <div className="flex gap-2">
                        {[["advance_to_selection", "Advance to selection"], ["hold", "More interviews"], ["reject", "Reject"]].map(([d, l]) => (
                          <Button key={d} variant={d === "reject" ? "danger" : d === "hold" ? "secondary" : "primary"} disabled={fv("rationale").length < 5} loading={busy}
                            onClick={() => act(() => api(`/evaluations/${ev.id}/decision`, { method: "POST", body: { decision: d, rationale: fv("rationale") } }))}>{l}</Button>))}
                      </div>
                    </div>
                  )}
                  {ev.decision && <p>Decision: <b>{titleCase(ev.decision)}</b> — {ev.decision_rationale}</p>}
                </div>
              )}
            </Card>
          )}

          {/* --- Selection approval --- */}
          {app.stage === "selection" && can("selection:approve") && (
            <Card title="Selection approval">
              <p className="mb-2 text-sm text-ink-2">Approver must differ from the person who made the evaluation decision.</p>
              <Input placeholder="Comment" value={fv("sel")} onChange={setFv("sel")} />
              <label className="mt-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={fv("skip") === "1"} onChange={(e) => setForm({ ...form, skip: e.target.checked ? "1" : "" })} /> Skip reference/background checks</label>
              <div className="mt-2 flex gap-2">
                <Button loading={busy} onClick={() => act(() => api(`/applications/${id}/selection`, { method: "POST", body: { decision: "approve", comment: fv("sel") || null, skip_verification: fv("skip") === "1" }, idempotencyKey: newIdempotencyKey("sel") }))}>Approve selection</Button>
                <Button variant="danger" disabled={busy} onClick={() => act(() => api(`/applications/${id}/selection`, { method: "POST", body: { decision: "reject", comment: fv("sel") || null }, idempotencyKey: newIdempotencyKey("sel") }))}>Decline</Button>
              </div>
            </Card>
          )}

          {/* --- Verification --- */}
          {(app.stage === "verification" || (refs?.length ?? 0) > 0 || (checks?.length ?? 0) > 0) && can("verification:read") && (
            <Card title="Verification">
              <div className="grid gap-4 md:grid-cols-2 text-sm">
                <div>
                  <h3 className="mb-1 font-semibold">References</h3>
                  <ul className="space-y-1">{refs?.map((r) => <li key={r.id}>{r.referee_name} <StatusBadge status={r.status} />
                    {Object.entries(r.responses).map(([k, v]) => <div key={k} className="text-xs text-ink-3">{k}: {v}</div>)}</li>)}</ul>
                  {app.stage === "verification" && can("verification:manage") && (
                    <div className="mt-2 space-y-1">
                      <Input placeholder="Referee name" value={fv("rn")} onChange={setFv("rn")} />
                      <Input placeholder="Referee e-mail" value={fv("re")} onChange={setFv("re")} />
                      <Input placeholder="Relationship" value={fv("rr")} onChange={setFv("rr")} />
                      <Button variant="secondary" onClick={() => act(() => api(`/applications/${id}/references`, { method: "POST", body: { referee_name: fv("rn"), referee_email: fv("re"), relationship_to_candidate: fv("rr") || "Manager" } }))}>Request reference</Button>
                    </div>)}
                </div>
                <div>
                  <h3 className="mb-1 font-semibold">Background checks</h3>
                  <ul className="space-y-1">{checks?.map((b) => <li key={b.id} className="flex items-center gap-2">{b.provider} <StatusBadge status={b.status} /> <StatusBadge status={b.result} />
                    {b.status === "requested" && can("verification:manage") && <Select className="w-32" defaultValue="" onChange={(e) => e.target.value && act(() => api(`/background-checks/${b.id}`, { method: "PATCH", body: { status: "completed", result: e.target.value } }))}>
                      <option value="">Record result…</option><option value="clear">Clear</option><option value="consider">Consider</option><option value="adverse">Adverse</option></Select>}</li>)}</ul>
                  {app.stage === "verification" && can("verification:manage") && (
                    <Button variant="secondary" className="mt-2" onClick={() => confirm("Confirm the candidate consented to a background check.") && act(() => api(`/applications/${id}/background-checks`, { method: "POST", body: { consent_confirmed: true } }))}>Request check</Button>)}
                </div>
              </div>
            </Card>
          )}

          {/* --- Offer --- */}
          {(app.stage === "offer" || offer) && can("offers:read") && (
            <Card title="Offer" actions={app.stage === "offer" && !offer && can("offers:create") && <Button loading={busy} onClick={() => act(() => api(`/applications/${id}/offers`, { method: "POST", body: {} }))}>Draft offer (Offer agent)</Button>}>
              {offer ? <div className="text-sm">v{offer.version} · {fmtMoney(offer.base_salary, offer.currency)} · <StatusBadge status={offer.status} />
                {offer.within_band === false && <Badge tone="warn">Outside band</Badge>} · <A href={`/offers/${offer.id}`}>Manage offer →</A></div>
                : <p className="text-sm text-ink-3">The Offer agent proposes pay within the approved compensation band.</p>}
            </Card>
          )}

          {app.stage === "hired" && can("onboarding:read") && (
            <Card title="Onboarding" actions={can("onboarding:handoff") && <Button loading={busy} onClick={() => act(() => api(`/applications/${id}/onboarding`, { method: "POST", idempotencyKey: `handoff-${id}` }))}>Hand off to HRIS / onboarding</Button>}>
              <Link href={`/onboarding?application=${id}`} className="text-sm text-accent hover:underline">View onboarding checklist →</Link>
            </Card>
          )}
        </div>

        <Card title="Timeline">
          <ol className="space-y-2 text-sm">
            {app.history?.map((h) => (
              <li key={h.id} className="border-l-2 border-line pl-3">
                <div><b>{titleCase(h.to_stage)}</b> <Badge tone={h.actor_type === "agent" ? "ai" : "neutral"}>{h.actor_type}</Badge></div>
                <div className="text-xs text-ink-3">{fmtDateTime(h.changed_at)}{h.reason ? ` · ${h.reason}` : ""}</div>
              </li>))}
          </ol>
        </Card>
      </div>
    </>
  );
}
