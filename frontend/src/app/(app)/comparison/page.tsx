"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { A, AIBadge, Badge, Card, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/api";
import { titleCase } from "@/lib/format";

interface Row { application_id: string; candidate: string; stage: string; match_score: number | null; screening_recommendation: string | null;
  assessment_pct: (number | null)[]; interview_overall: (number | null)[]; evaluation_score: number | null; ai_recommendation: string | null;
  competencies: Record<string, { mean: number }>; risks: string[]; decision: string | null }

function Compare() {
  const ids = (useSearchParams().get("ids") ?? "").split(",").filter(Boolean);
  const { data, error } = useApi<Row[]>(ids.length >= 2 ? "/comparison" : null, { application_ids: ids });
  if (ids.length < 2) return <p className="text-sm text-ink-3">Select at least two applications to compare (from the screening workspace).</p>;
  if (error) return <p className="text-critical">{error.message}</p>;
  if (!data) return <Loading />;
  const comps = Array.from(new Set(data.flatMap((r) => Object.keys(r.competencies))));
  const rows: [string, (r: Row) => React.ReactNode][] = [
    ["Stage", (r) => titleCase(r.stage)],
    ["Match score", (r) => r.match_score?.toFixed(0) ?? "—"],
    ["Screening (AI)", (r) => <StatusBadge status={r.screening_recommendation} />],
    ["Assessments", (r) => r.assessment_pct.map((p) => `${p}%`).join(", ") || "—"],
    ["Interview ratings", (r) => r.interview_overall.join(", ") || "—"],
    ["Evidence score", (r) => r.evaluation_score ?? "—"],
    ["Evaluation (AI)", (r) => <StatusBadge status={r.ai_recommendation} />],
    ...comps.map((c) => [c, (r: Row) => r.competencies[c]?.mean ?? "—"] as [string, (r: Row) => React.ReactNode]),
    ["Risks", (r) => r.risks.map((k) => <div key={k} className="text-xs text-serious">{k}</div>)],
    ["Decision", (r) => r.decision ? titleCase(r.decision) : <Badge>Pending</Badge>],
  ];
  return (
    <Card actions={<AIBadge label="AI summaries are advisory" />} title="Side-by-side evidence">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr><th />{data.map((r) => <th key={r.application_id} className="px-3 py-2 text-left"><A href={`/applications/${r.application_id}`}>{r.candidate}</A></th>)}</tr></thead>
          <tbody>{rows.map(([label, fn]) => (
            <tr key={label} className="border-t border-line"><th className="px-3 py-2 text-left font-medium text-ink-2">{label}</th>
              {data.map((r) => <td key={r.application_id} className="px-3 py-2">{fn(r)}</td>)}</tr>))}</tbody>
        </table>
      </div>
    </Card>
  );
}

export default function ComparisonPage() {
  return (<><PageHeader title="Candidate comparison" /><Suspense><Compare /></Suspense></>);
}
