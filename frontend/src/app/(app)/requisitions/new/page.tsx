"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Card, ErrorBox, Field, Input, PageHeader, Select, Textarea } from "@/components/ui";
import { api, ApiError, useApi, type Page } from "@/lib/api";
import type { Requisition, User } from "@/lib/types";

const list = (s: string) => s.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);

export default function NewRequisition() {
  const router = useRouter();
  const { data: departments } = useApi<{ id: string; name: string }[]>("/departments");
  const { data: managers } = useApi<Page<User>>("/users", { role: "hiring_manager", page_size: 100 });
  const [f, setF] = useState({
    title: "", department_id: "", headcount: "1", employment_type: "full_time", location: "", remote_policy: "hybrid",
    job_level: "", justification: "", responsibilities: "", required_skills: "", preferred_skills: "",
    min_years_experience: "", budget_min: "", budget_max: "", currency: "USD", target_start_date: "", hiring_manager_id: "",
  });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.value });

  async function save(submit: boolean) {
    setBusy(true);
    setError(null);
    try {
      const req = await api<Requisition>("/requisitions", { method: "POST", body: {
        title: f.title, department_id: f.department_id || null, headcount: Number(f.headcount),
        employment_type: f.employment_type, location: f.location || null, remote_policy: f.remote_policy,
        job_level: f.job_level || null, justification: f.justification, responsibilities: list(f.responsibilities),
        required_skills: list(f.required_skills), preferred_skills: list(f.preferred_skills),
        min_years_experience: f.min_years_experience ? Number(f.min_years_experience) : null,
        budget_min: f.budget_min || null, budget_max: f.budget_max || null, currency: f.currency,
        target_start_date: f.target_start_date || null, hiring_manager_id: f.hiring_manager_id || null,
      } });
      if (submit) {
        try { await api(`/requisitions/${req.id}/submit`, { method: "POST" }); } catch { /* validation issues shown on detail page */ }
      }
      router.push(`/requisitions/${req.id}`);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="New hiring requisition" subtitle="The Requisition Agent validates completeness, budget and inclusive language on submit." />
      <ErrorBox error={error} />
      <Card>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Job title"><Input value={f.title} onChange={set("title")} required /></Field>
          <Field label="Department">
            <Select value={f.department_id} onChange={set("department_id")}>
              <option value="">—</option>
              {departments?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          </Field>
          <Field label="Hiring manager">
            <Select value={f.hiring_manager_id} onChange={set("hiring_manager_id")}>
              <option value="">—</option>
              {managers?.items.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
            </Select>
          </Field>
          <Field label="Headcount"><Input type="number" min={1} value={f.headcount} onChange={set("headcount")} /></Field>
          <Field label="Employment type">
            <Select value={f.employment_type} onChange={set("employment_type")}>
              {["full_time", "part_time", "contract", "temporary", "internship"].map((v) => <option key={v} value={v}>{v.replace("_", " ")}</option>)}
            </Select>
          </Field>
          <Field label="Work model">
            <Select value={f.remote_policy} onChange={set("remote_policy")}>
              {["onsite", "hybrid", "remote"].map((v) => <option key={v}>{v}</option>)}
            </Select>
          </Field>
          <Field label="Location"><Input value={f.location} onChange={set("location")} /></Field>
          <Field label="Job level" hint="Matches compensation bands (e.g. L4)"><Input value={f.job_level} onChange={set("job_level")} /></Field>
          <Field label="Budget min"><Input type="number" value={f.budget_min} onChange={set("budget_min")} /></Field>
          <Field label="Budget max"><Input type="number" value={f.budget_max} onChange={set("budget_max")} /></Field>
          <Field label="Currency"><Input maxLength={3} value={f.currency} onChange={set("currency")} /></Field>
          <Field label="Target start date"><Input type="date" value={f.target_start_date} onChange={set("target_start_date")} /></Field>
          <Field label="Minimum years of experience"><Input type="number" value={f.min_years_experience} onChange={set("min_years_experience")} /></Field>
          <div className="md:col-span-2"><Field label="Business justification"><Textarea value={f.justification} onChange={set("justification")} /></Field></div>
          <Field label="Responsibilities" hint="One per line"><Textarea value={f.responsibilities} onChange={set("responsibilities")} /></Field>
          <div className="space-y-4">
            <Field label="Required skills" hint="Comma separated"><Input value={f.required_skills} onChange={set("required_skills")} /></Field>
            <Field label="Preferred skills" hint="Comma separated"><Input value={f.preferred_skills} onChange={set("preferred_skills")} /></Field>
          </div>
        </div>
        <div className="mt-5 flex gap-2">
          <Button onClick={() => save(true)} loading={busy}>Save & submit for approval</Button>
          <Button variant="secondary" onClick={() => save(false)} disabled={busy}>Save draft</Button>
        </div>
      </Card>
    </>
  );
}
