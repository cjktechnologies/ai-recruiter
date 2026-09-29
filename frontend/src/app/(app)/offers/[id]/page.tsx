"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { useCan, useMe } from "@/components/shell";
import { A, AIBadge, Badge, Button, Card, ErrorBox, Field, Input, Loading, PageHeader, StatusBadge, Textarea } from "@/components/ui";
import { api, ApiError, newIdempotencyKey, useApi } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtMoney, titleCase } from "@/lib/format";
import type { Offer } from "@/lib/types";

export default function OfferDetail() {
  const { id } = useParams<{ id: string }>();
  const can = useCan();
  const me = useMe();
  const { data: o, reload, setData } = useApi<Offer>(`/offers/${id}`);
  const [edit, setEdit] = useState<{ base_salary: string; start_date: string; letter_body: string } | null>(null);
  const [comment, setComment] = useState("");
  const [link, setLink] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  if (!o) return <Loading />;
  async function act(fn: () => Promise<unknown>) { setBusy(true); setError(null); try { await fn(); await reload(); } catch (e) { setError(e as ApiError); } finally { setBusy(false); } }
  const pending = o.approvals.find((a) => a.status === "pending");
  const canApprove = o.status === "pending_approval" && can("offers:approve") && pending && (me?.roles.includes(pending.approver_role) || me?.roles.includes("org_admin"));
  return (
    <>
      <PageHeader title={`Offer v${o.version} · ${o.job_title}`} subtitle={<><StatusBadge status={o.status} /> <A href={`/applications/${o.application_id}`}>application</A></>} actions={<>
        {o.status === "draft" && can("offers:update") && <Button loading={busy} onClick={() => act(() => api(`/offers/${id}/submit`, { method: "POST" }))}>Submit for approval</Button>}
        {o.status === "approved" && can("offers:send") && <Button loading={busy} onClick={() => act(async () => { const r = await api<{ candidate_link: string }>(`/offers/${id}/send`, { method: "POST", idempotencyKey: `send-${id}` }); setLink(r.candidate_link); })}>Send to candidate</Button>}
        {!["accepted", "declined", "withdrawn"].includes(o.status) && can("offers:update") && <Button variant="danger" onClick={() => { const r = prompt("Reason for withdrawal"); if (r) act(() => api(`/offers/${id}/withdraw`, { method: "POST", body: { reason: r } })); }}>Withdraw</Button>}
      </>} />
      <ErrorBox error={error} />
      {link && <p className="mb-3 text-sm text-ink-2">Sent. Candidate link: {link}</p>}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Terms" actions={o.status === "draft" && can("offers:update") && !edit && <Button variant="secondary" onClick={() => setEdit({ base_salary: o.base_salary, start_date: o.start_date ?? "", letter_body: o.letter_body ?? "" })}>Edit</Button>}>
          {edit ? (
            <div className="space-y-2">
              <Field label="Base salary"><Input type="number" value={edit.base_salary} onChange={(e) => setEdit({ ...edit, base_salary: e.target.value })} /></Field>
              <Field label="Start date"><Input type="date" value={edit.start_date} onChange={(e) => setEdit({ ...edit, start_date: e.target.value })} /></Field>
              <Button loading={busy} onClick={() => act(async () => { setData(await api<Offer>(`/offers/${id}`, { method: "PATCH", body: { base_salary: edit.base_salary, start_date: edit.start_date || null, letter_body: edit.letter_body } })); setEdit(null); })}>Save</Button>
            </div>
          ) : (
            <dl className="space-y-1 text-sm">
              <div>Base salary: <b>{fmtMoney(o.base_salary, o.currency)}</b> {o.within_band === false ? <Badge tone="warn">Outside band — finance approval</Badge> : <Badge tone="good">Within band</Badge>}</div>
              <div>Bonus target: {o.bonus_pct ?? 0}%</div>
              <div>Benefits: {o.benefits.join(", ") || "—"}</div>
              <div>Start: {fmtDate(o.start_date)}</div>
              <div>Expires: {fmtDateTime(o.expires_at)}</div>
            </dl>
          )}
        </Card>
        <Card title="Approval chain">
          <ol className="space-y-2 text-sm">{o.approvals.map((a) => <li key={a.id} className="flex justify-between">{a.step_order}. {titleCase(a.approver_role)} <StatusBadge status={a.status} /></li>)}</ol>
          {canApprove && (
            <div className="mt-3 space-y-2 border-t border-line pt-3">
              <Input placeholder="Comment" value={comment} onChange={(e) => setComment(e.target.value)} />
              <div className="flex gap-2">
                <Button loading={busy} onClick={() => act(() => api(`/offers/${id}/decision`, { method: "POST", body: { decision: "approve", comment }, idempotencyKey: newIdempotencyKey("offer") }))}>Approve</Button>
                <Button variant="danger" disabled={busy} onClick={() => act(() => api(`/offers/${id}/decision`, { method: "POST", body: { decision: "reject", comment }, idempotencyKey: newIdempotencyKey("offer") }))}>Request changes</Button>
              </div>
            </div>)}
        </Card>
        <Card title="Offer letter" actions={<AIBadge label="Drafted by Offer agent" />}>
          {edit ? <Textarea rows={16} value={edit.letter_body} onChange={(e) => setEdit({ ...edit, letter_body: e.target.value })} /> : <pre className="whitespace-pre-wrap font-sans text-sm">{o.letter_body}</pre>}
        </Card>
      </div>
    </>
  );
}
