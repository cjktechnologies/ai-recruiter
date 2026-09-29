"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useCan, useMe } from "@/components/shell";
import { A, AIBadge, Badge, Button, Card, ErrorBox, Input, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { api, ApiError, newIdempotencyKey, useApi } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtMoney, titleCase } from "@/lib/format";
import type { Job, Requisition } from "@/lib/types";

export default function RequisitionDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const can = useCan();
  const me = useMe();
  const { data: r, reload } = useApi<Requisition>(`/requisitions/${id}`);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  if (!r) return <Loading />;

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try { await fn(); await reload(); } catch (e) { setError(e as ApiError); await reload(); } finally { setBusy(false); }
  }
  const step = r.approval?.steps.find((s) => s.step_order === r.approval?.current_step);
  const canDecide = r.status === "pending_approval" && can("requisitions:approve") && step &&
    (me?.roles.includes(step.approver_role) || me?.roles.includes("org_admin"));

  return (
    <>
      <PageHeader title={`${r.reference} · ${r.title}`} subtitle={<StatusBadge status={r.status} />} actions={<>
        {["draft", "rejected", "on_hold"].includes(r.status) && can("requisitions:submit") &&
          <Button loading={busy} onClick={() => act(() => api(`/requisitions/${id}/submit`, { method: "POST" }))}>Validate & submit</Button>}
        {r.status === "approved" && can("jobs:create") && (r.job_ids?.length ?? 0) === 0 &&
          <Button loading={busy} onClick={() => act(async () => {
            const job = await api<Job>(`/requisitions/${id}/jobs`, { method: "POST" });
            router.push(`/jobs/${job.id}`);
          })}>Create job (AI-drafted JD)</Button>}
        {r.job_ids?.map((j) => <A key={j} href={`/jobs/${j}`}>Open job →</A>)}
      </>} />
      <ErrorBox error={error} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Details" className="lg:col-span-2">
          <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-3">
            {[["Headcount", r.headcount], ["Type", titleCase(r.employment_type)], ["Work model", titleCase(r.remote_policy)],
              ["Location", r.location ?? "—"], ["Level", r.job_level ?? "—"], ["Target start", fmtDate(r.target_start_date)],
              ["Budget", `${fmtMoney(r.budget_min, r.currency)} – ${fmtMoney(r.budget_max, r.currency)}`],
              ["Min. experience", r.min_years_experience ? `${r.min_years_experience} yrs` : "—"]].map(([k, v]) => (
              <div key={String(k)}><dt className="text-ink-3">{k}</dt><dd>{v}</dd></div>))}
          </dl>
          <h3 className="mt-4 text-sm font-semibold">Justification</h3>
          <p className="text-sm text-ink-2">{r.justification}</p>
          <h3 className="mt-4 text-sm font-semibold">Skills</h3>
          <div className="mt-1 flex flex-wrap gap-1">
            {r.required_skills.map((s) => <Badge key={s} tone="info">{s}</Badge>)}
            {r.preferred_skills.map((s) => <Badge key={s}>{s} (preferred)</Badge>)}
          </div>
        </Card>
        <div className="space-y-4">
          <Card title="Approval workflow">
            {!r.approval ? <p className="text-sm text-ink-3">Not submitted yet.</p> : (
              <ol className="space-y-2 text-sm">
                {r.approval.steps.map((s) => (
                  <li key={s.id} className="flex items-start justify-between gap-2">
                    <span>{s.step_order}. {titleCase(s.approver_role)}{s.comment && <span className="block text-xs text-ink-3">“{s.comment}”</span>}</span>
                    <span className="text-right"><StatusBadge status={s.status} /><span className="block text-xs text-ink-3">{s.decided_at ? fmtDateTime(s.decided_at) : ""}</span></span>
                  </li>
                ))}
              </ol>
            )}
            {canDecide && (
              <div className="mt-3 space-y-2 border-t border-line pt-3">
                <Input placeholder="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
                <div className="flex gap-2">
                  <Button loading={busy} onClick={() => act(() => api(`/requisitions/${id}/decision`, { method: "POST", body: { decision: "approve", comment }, idempotencyKey: newIdempotencyKey("req") }))}>Approve</Button>
                  <Button variant="danger" disabled={busy} onClick={() => act(() => api(`/requisitions/${id}/decision`, { method: "POST", body: { decision: "reject", comment }, idempotencyKey: newIdempotencyKey("req") }))}>Reject</Button>
                </div>
              </div>
            )}
          </Card>
          <Card title="Requisition Agent review" actions={<AIBadge label="AI check" />}>
            {!r.ai_validation ? <p className="text-sm text-ink-3">Runs on submit.</p> : (
              <div className="space-y-2 text-sm">
                <div>Completeness: <b>{Math.round(r.ai_validation.completeness * 100)}%</b> · {r.ai_validation.valid ? <Badge tone="good">Valid</Badge> : <Badge tone="critical">Needs changes</Badge>}</div>
                <ul className="space-y-1">
                  {r.ai_validation.issues.map((i, k) => (
                    <li key={k}><Badge tone={i.severity === "error" ? "critical" : i.severity === "warning" ? "warn" : "info"}>{i.severity}</Badge> {i.message}</li>))}
                </ul>
                <div className="text-xs text-ink-3">Proposed route: {r.ai_validation.approval_route.map(titleCase).join(" → ")}</div>
              </div>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
