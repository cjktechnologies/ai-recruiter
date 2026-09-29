"use client";

import { BarList, ColumnChart } from "@/components/charts";
import { useCan } from "@/components/shell";
import { A, Badge, Card, Loading, PageHeader, Stat, StatusBadge, Table } from "@/components/ui";
import { useApi, type Page } from "@/lib/api";
import { fmtDateTime, pct, titleCase } from "@/lib/format";
import { STAGES, type Interview, type Requisition } from "@/lib/types";

interface Overview {
  applications: number; active_applications: number; hires: number; funnel: Record<string, number>;
  time_to_hire_days: number | null; offer_acceptance_rate: number | null; screening_conversion: number | null;
  applications_by_week: { week: string; applications: number }[];
}

export default function Dashboard() {
  const can = useCan();
  const { data: m } = useApi<Overview>("/analytics/overview");
  const { data: reqs } = useApi<Page<Requisition>>("/requisitions", { status: "pending_approval", page_size: 5 });
  const { data: queue } = useApi<unknown[]>(can("screening:review") ? "/screening/queue" : null, { limit: 50 });
  const { data: ivs } = useApi<Interview[]>("/interviews", { mine: true, start: new Date().toISOString() });
  const { data: insights } = useApi<{ insights: { severity: string; title: string; detail: string }[] }>("/analytics/insights");
  if (!m) return <Loading />;
  return (
    <>
      <PageHeader title="Recruitment dashboard" subtitle="Live pipeline, approvals and AI insights" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Active applications" value={m.active_applications} />
        <Stat label="Awaiting screening review" value={queue?.length ?? "—"} />
        <Stat label="Hires" value={m.hires} />
        <Stat label="Time to hire" value={m.time_to_hire_days ? `${m.time_to_hire_days}d` : "—"} />
        <Stat label="Offer acceptance" value={pct(m.offer_acceptance_rate)} />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title="Pipeline funnel" className="lg:col-span-2">
          <BarList title="Candidates reaching each stage" data={STAGES.map((s) => ({ label: titleCase(s), value: m.funnel[s] ?? 0 }))} />
        </Card>
        <Card title="AI insights" actions={<Badge tone="ai">✦ Analytics agent</Badge>}>
          <ul className="space-y-2 text-sm">
            {(insights?.insights ?? []).map((i, k) => (
              <li key={k}>
                <Badge tone={i.severity === "critical" ? "critical" : i.severity === "warning" ? "warn" : "info"}>{titleCase(i.severity)}</Badge>{" "}
                <span className="font-medium">{i.title}</span>
                <div className="text-ink-2">{i.detail}</div>
              </li>
            ))}
            {insights && insights.insights.length === 0 && <li className="text-ink-3">No issues detected.</li>}
          </ul>
        </Card>
        <Card title="Applications per week" className="lg:col-span-2">
          <ColumnChart title="Applications per week" data={m.applications_by_week.map((w) => ({ label: w.week, value: w.applications }))} />
        </Card>
        <Card title="Pending requisition approvals">
          <Table head={["Requisition", "Status"]} rows={(reqs?.items ?? []).map((r) => [
            <A key="a" href={`/requisitions/${r.id}`}>{r.reference} · {r.title}</A>, <StatusBadge key="s" status={r.status} />])} />
        </Card>
        <Card title="My upcoming interviews" className="lg:col-span-3">
          <Table head={["When", "Candidate", "Role", "Type"]} rows={(ivs ?? []).slice(0, 8).map((i) => [
            fmtDateTime(i.scheduled_start), <A key="c" href={`/interviews/${i.id}`}>{i.candidate_name}</A>, i.job_title,
            titleCase(i.kind)])} empty="No upcoming interviews." />
        </Card>
      </div>
    </>
  );
}
