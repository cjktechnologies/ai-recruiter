"use client";

import { useState } from "react";
import { BarList, ColumnChart } from "@/components/charts";
import { useCan } from "@/components/shell";
import { Badge, Card, Input, Loading, PageHeader, Select, Stat, Table } from "@/components/ui";
import { useApi, type Page } from "@/lib/api";
import { fmtMoney, pct, titleCase } from "@/lib/format";
import { STAGES, type Job } from "@/lib/types";

interface M {
  applications: number; hires: number; funnel: Record<string, number>; screening_conversion: number | null; interview_conversion: number | null;
  offer_acceptance_rate: number | null; time_to_hire_days: number | null; time_to_fill_days: number | null; cost_per_hire: number | null;
  avg_days_in_stage: Record<string, number>; sla_breaches: Record<string, number>;
  source_effectiveness: { source: string; applications: number; interviews: number; hires: number; hire_rate: number }[];
  recruiter_workload: Record<string, number>; hiring_manager_workload: Record<string, number>; interviewer_workload: Record<string, number>;
  assessment_performance: { completed: number; avg_percentage: number | null; pass_rate: number | null };
  quality_of_hire: { avg_interview_rating_of_hires: number | null; avg_match_score_of_hires: number | null };
  applications_by_week: { week: string; applications: number }[];
  fairness_alerts: { dimension: string; group: string; stage: string; selection_rate: number; impact_ratio: number; sample: number }[];
}
const entries = (o: Record<string, number>) => Object.entries(o).map(([label, value]) => ({ label: titleCase(label), value }));

export default function Analytics() {
  const can = useCan();
  const [f, setF] = useState({ department_id: "", job_id: "", source: "", location: "", date_from: "", date_to: "" });
  const { data: departments } = useApi<{ id: string; name: string }[]>("/departments");
  const { data: jobs } = useApi<Page<Job>>("/jobs", { page_size: 100 });
  const { data: m } = useApi<M>("/analytics/overview", {
    ...f, date_from: f.date_from ? new Date(f.date_from).toISOString() : "", date_to: f.date_to ? new Date(f.date_to).toISOString() : "" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <>
      <PageHeader title="Recruitment analytics" />
      <div className="mb-4 flex flex-wrap gap-2">
        <Select value={f.department_id} onChange={set("department_id")} className="w-44"><option value="">All departments</option>{departments?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select>
        <Select value={f.job_id} onChange={set("job_id")} className="w-52"><option value="">All positions</option>{jobs?.items.map((j) => <option key={j.id} value={j.id}>{j.title}</option>)}</Select>
        <Input placeholder="Source" value={f.source} onChange={set("source")} className="w-32" />
        <Input placeholder="Location" value={f.location} onChange={set("location")} className="w-32" />
        <Input type="date" value={f.date_from} onChange={set("date_from")} className="w-40" aria-label="From" />
        <Input type="date" value={f.date_to} onChange={set("date_to")} className="w-40" aria-label="To" />
      </div>
      {!m ? <Loading /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
            <Stat label="Applications" value={m.applications} />
            <Stat label="Hires" value={m.hires} />
            <Stat label="Time to fill" value={m.time_to_fill_days ? `${m.time_to_fill_days}d` : "—"} />
            <Stat label="Time to hire" value={m.time_to_hire_days ? `${m.time_to_hire_days}d` : "—"} />
            <Stat label="Cost per hire" value={fmtMoney(m.cost_per_hire)} />
            <Stat label="Screening conv." value={pct(m.screening_conversion)} />
            <Stat label="Interview conv." value={pct(m.interview_conversion)} />
            <Stat label="Offer acceptance" value={pct(m.offer_acceptance_rate)} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Candidate pipeline (reached stage)"><BarList title="Funnel" data={STAGES.map((s) => ({ label: titleCase(s), value: m.funnel[s] ?? 0 }))} /></Card>
            <Card title="Application volume by week"><ColumnChart title="Applications per week" data={m.applications_by_week.map((w) => ({ label: w.week, value: w.applications }))} /></Card>
            <Card title="Average days in stage (SLA)"><BarList title="Days in stage" unit="d" data={Object.entries(m.avg_days_in_stage).map(([k, v]) => ({ label: titleCase(k), value: v, hint: `${m.sla_breaches[k] ?? 0} SLA breaches` }))} /></Card>
            <Card title="Source of hire & effectiveness">
              <Table head={["Source", "Applied", "Interviewed", "Hired", "Hire rate"]} rows={m.source_effectiveness.map((s) => [s.source, s.applications, s.interviews, s.hires, `${s.hire_rate}%`])} />
            </Card>
            <Card title="Recruiter workload (active)"><BarList title="Recruiter workload" data={entries(m.recruiter_workload)} /></Card>
            <Card title="Hiring-manager workload (awaiting action)"><BarList title="Hiring manager workload" data={entries(m.hiring_manager_workload)} /></Card>
            <Card title="Assessment performance">
              <div className="grid grid-cols-3 gap-3"><Stat label="Completed" value={m.assessment_performance.completed} />
                <Stat label="Average" value={pct(m.assessment_performance.avg_percentage)} /><Stat label="Pass rate" value={pct(m.assessment_performance.pass_rate)} /></div>
            </Card>
            <Card title="Quality-of-hire indicators">
              <div className="grid grid-cols-2 gap-3"><Stat label="Avg interview rating (hires)" value={m.quality_of_hire.avg_interview_rating_of_hires ?? "—"} />
                <Stat label="Avg match score (hires)" value={m.quality_of_hire.avg_match_score_of_hires ?? "—"} /></div>
            </Card>
          </div>
          {can("governance:read") && (
            <Card title="Fairness monitoring (four-fifths rule)" actions={<Badge tone="info">Voluntary self-ID · groups &lt; 5 suppressed</Badge>}>
              <Table head={["Dimension", "Group", "Stage", "Selection rate", "Impact ratio", "Sample"]} rows={m.fairness_alerts.map((a) => [titleCase(a.dimension), a.group, titleCase(a.stage),
                `${a.selection_rate}%`, <Badge key="r" tone="critical">{a.impact_ratio}</Badge>, a.sample])} empty="No adverse impact detected." />
            </Card>
          )}
        </div>
      )}
    </>
  );
}
