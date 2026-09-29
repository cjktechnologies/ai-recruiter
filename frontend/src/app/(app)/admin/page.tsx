"use client";

import { useState } from "react";
import { useCan } from "@/components/shell";
import { Badge, Button, Card, ErrorBox, Field, Input, Loading, PageHeader, Select, StatusBadge, Table, Tabs } from "@/components/ui";
import { api, ApiError, useApi, type Page } from "@/lib/api";
import { fmtDateTime, fmtMoney, titleCase } from "@/lib/format";
import type { User } from "@/lib/types";

interface Role { id: string; key: string; name: string; permissions: string[]; is_system: boolean }
interface Band { id: string; name: string; job_level: string; currency: string; min_salary: string; max_salary: string; max_bonus_pct: number }
interface Integration { id: string; kind: string; name: string; is_enabled: boolean; has_secret: boolean; last_sync_at: string | null; last_error: string | null }
interface Policy { ai_screening_enabled: boolean; ai_interview_summaries_enabled: boolean; auto_screen_on_apply: boolean; bias_monitoring_enabled: boolean; adverse_impact_threshold: number; data_retention_days: number; require_consent_for_ai: boolean; faq: { q: string; a: string }[] }

export default function Admin() {
  const can = useCan();
  const [tab, setTab] = useState("Users");
  const [error, setError] = useState<ApiError | null>(null);
  const { data: users, reload: rUsers } = useApi<Page<User>>("/users", { page_size: 200 });
  const { data: roles } = useApi<Role[]>("/roles");
  const { data: departments, reload: rDeps } = useApi<{ id: string; name: string; code: string | null }[]>("/departments");
  const { data: bands, reload: rBands } = useApi<Band[]>("/compensation-bands");
  const { data: integrations, reload: rInt } = useApi<Integration[]>(can("integrations:read") ? "/integrations" : null);
  const { data: policy, setData: setPolicy } = useApi<Policy>(can("governance:read") ? "/governance/policy" : null);
  const [nu, setNu] = useState({ email: "", full_name: "", role: "recruiter", password: "" });
  const [nd, setNd] = useState("");
  const [nb, setNb] = useState({ name: "", job_level: "", currency: "USD", min_salary: "", max_salary: "", max_bonus_pct: "0" });
  const [ni, setNi] = useState({ kind: "hris_webhook", name: "", config: "{}", secret: "{}" });
  async function act(fn: () => Promise<unknown>, after?: () => void) { setError(null); try { await fn(); after?.(); } catch (e) { setError(e as ApiError); } }

  return (
    <>
      <PageHeader title="Administration" />
      <ErrorBox error={error} />
      <Tabs tabs={["Users", "Roles", "Departments", "Compensation", "Integrations", "AI governance"]} active={tab} onChange={setTab} />
      {tab === "Users" && (
        <Card title="Users">
          {!users ? <Loading /> : <Table head={["Name", "E-mail", "Roles", "Last login", "Status", ""]} rows={users.items.map((u) => [u.full_name, u.email,
            u.role_keys.map((r) => <Badge key={r}>{titleCase(r)}</Badge>), fmtDateTime(u.last_login_at), u.is_active ? <Badge key="s" tone="good">Active</Badge> : <Badge key="s">Inactive</Badge>,
            can("users:update") && <Button key="t" variant="ghost" onClick={() => act(() => api(`/users/${u.id}`, { method: "PATCH", body: { is_active: !u.is_active } }), rUsers)}>{u.is_active ? "Deactivate" : "Activate"}</Button>])} />}
          {can("users:create") && (
            <div className="mt-4 grid gap-2 border-t border-line pt-3 md:grid-cols-5">
              <Input placeholder="Full name" value={nu.full_name} onChange={(e) => setNu({ ...nu, full_name: e.target.value })} />
              <Input placeholder="E-mail" value={nu.email} onChange={(e) => setNu({ ...nu, email: e.target.value })} />
              <Select value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}>{roles?.map((r) => <option key={r.key} value={r.key}>{r.name}</option>)}</Select>
              <Input type="password" placeholder="Initial password (or SSO)" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} />
              <Button onClick={() => act(() => api("/users", { method: "POST", body: { email: nu.email, full_name: nu.full_name, roles: [nu.role], password: nu.password || null } }), rUsers)}>Invite user</Button>
            </div>)}
        </Card>
      )}
      {tab === "Roles" && (
        <Card title="Roles & permissions">
          <Table head={["Role", "Type", "Permissions"]} rows={(roles ?? []).map((r) => [r.name, r.is_system ? "System" : "Custom",
            <span key="p" className="text-xs text-ink-2">{r.permissions.length} permissions: {r.permissions.slice(0, 12).join(", ")}{r.permissions.length > 12 ? "…" : ""}</span>])} />
        </Card>
      )}
      {tab === "Departments" && (
        <Card title="Departments">
          <Table head={["Name", "Code"]} rows={(departments ?? []).map((d) => [d.name, d.code ?? "—"])} />
          {can("departments:manage") && <div className="mt-3 flex gap-2"><Input placeholder="Department name" value={nd} onChange={(e) => setNd(e.target.value)} className="max-w-xs" />
            <Button disabled={!nd} onClick={() => act(() => api("/departments", { method: "POST", body: { name: nd } }), () => { setNd(""); rDeps(); })}>Add</Button></div>}
        </Card>
      )}
      {tab === "Compensation" && (
        <Card title="Approved compensation bands (used by the Offer agent)">
          <Table head={["Name", "Level", "Range", "Max bonus"]} rows={(bands ?? []).map((b) => [b.name, b.job_level, `${fmtMoney(b.min_salary, b.currency)} – ${fmtMoney(b.max_salary, b.currency)}`, `${b.max_bonus_pct}%`])} />
          {can("compensation:manage") && (
            <div className="mt-3 grid gap-2 md:grid-cols-7">
              {(["name", "job_level", "currency", "min_salary", "max_salary", "max_bonus_pct"] as const).map((k) => <Input key={k} placeholder={titleCase(k)} value={nb[k]} onChange={(e) => setNb({ ...nb, [k]: e.target.value })} />)}
              <Button onClick={() => act(() => api("/compensation-bands", { method: "POST", body: { ...nb, max_bonus_pct: Number(nb.max_bonus_pct) } }), rBands)}>Add band</Button>
            </div>)}
        </Card>
      )}
      {tab === "Integrations" && (
        <Card title="Integrations" actions={<Badge>Secrets are encrypted and never displayed</Badge>}>
          <Table head={["Name", "Kind", "Enabled", "Credentials", "Last sync", "Last error"]} rows={(integrations ?? []).map((i) => [i.name, titleCase(i.kind),
            <StatusBadge key="e" status={i.is_enabled ? "approved" : "cancelled"} />, i.has_secret ? "Stored" : "—", fmtDateTime(i.last_sync_at), i.last_error ?? "—"])} />
          {can("integrations:manage") && (
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              <Select value={ni.kind} onChange={(e) => setNi({ ...ni, kind: e.target.value })}>
                {["google_calendar", "microsoft_graph", "smtp", "twilio", "hris_webhook", "job_board", "background_check"].map((k) => <option key={k} value={k}>{titleCase(k)}</option>)}</Select>
              <Input placeholder="Name" value={ni.name} onChange={(e) => setNi({ ...ni, name: e.target.value })} />
              <Field label="Config (JSON)" hint='e.g. {"url": "https://hris.example.com/hooks"} or {"organizer_email": "..."}'><Input value={ni.config} onChange={(e) => setNi({ ...ni, config: e.target.value })} /></Field>
              <Field label="Secret (JSON)" hint='e.g. {"signing_secret": "..."} or {"access_token": "..."}'><Input type="password" value={ni.secret} onChange={(e) => setNi({ ...ni, secret: e.target.value })} /></Field>
              <Button onClick={() => act(() => api("/integrations", { method: "POST", body: { kind: ni.kind, name: ni.name, config: JSON.parse(ni.config || "{}"), secret: JSON.parse(ni.secret || "{}") } }), rInt)}>Add integration</Button>
            </div>)}
        </Card>
      )}
      {tab === "AI governance" && policy && (
        <Card title="AI governance & privacy policy">
          <div className="space-y-2 text-sm">
            {(["ai_screening_enabled", "auto_screen_on_apply", "ai_interview_summaries_enabled", "bias_monitoring_enabled", "require_consent_for_ai"] as const).map((k) => (
              <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={policy[k]} disabled={!can("governance:manage")} onChange={(e) => setPolicy({ ...policy, [k]: e.target.checked })} />{titleCase(k)}</label>))}
            <div className="grid max-w-md grid-cols-2 gap-2">
              <Field label="Adverse-impact threshold"><Input type="number" step="0.05" value={policy.adverse_impact_threshold} onChange={(e) => setPolicy({ ...policy, adverse_impact_threshold: Number(e.target.value) })} /></Field>
              <Field label="Data retention (days)"><Input type="number" value={policy.data_retention_days} onChange={(e) => setPolicy({ ...policy, data_retention_days: Number(e.target.value) })} /></Field>
            </div>
            {can("governance:manage") && <div className="flex gap-2">
              <Button onClick={() => act(async () => setPolicy(await api<Policy>("/governance/policy", { method: "PUT", body: policy as never })))}>Save policy</Button>
              <Button variant="secondary" onClick={() => act(async () => { const r = await api<{ anonymized: number }>("/governance/retention/run", { method: "POST" }); alert(`${r.anonymized} expired candidate records anonymized`); })}>Apply retention now</Button>
            </div>}
          </div>
        </Card>
      )}
    </>
  );
}
