"use client";

import Link from "next/link";
import { useState } from "react";
import { AIBadge, Badge, Button, Card, Loading, PageHeader, StatusBadge, Table } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { Application, Screening } from "@/lib/types";

export default function ScreeningWorkspace() {
  const { data } = useApi<{ screening: Screening; application: Application }[]>("/screening/queue", { limit: 200 });
  const [selected, setSelected] = useState<string[]>([]);
  if (!data) return <Loading />;
  return (
    <>
      <PageHeader title="AI screening workspace" subtitle="Evidence-based summaries awaiting a recruiter decision, ranked by match score."
        actions={selected.length >= 2 && <Link href={`/comparison?ids=${selected.join(",")}`}><Button variant="secondary">Compare {selected.length}</Button></Link>} />
      <Card actions={<AIBadge label="Advisory only" />} title={`${data.length} awaiting review`}>
        <Table head={["", "Candidate", "Job", "Match", "Mandatory", "AI recommendation", "Summary"]} rows={data.map(({ screening: s, application: a }) => [
          <input key="c" type="checkbox" aria-label="Select for comparison" checked={selected.includes(a.id)}
            onChange={(e) => setSelected(e.target.checked ? [...selected, a.id] : selected.filter((x) => x !== a.id))} />,
          <Link key="n" className="text-accent hover:underline" href={`/applications/${a.id}`}>{a.candidate_name}</Link>, a.job_title,
          <b key="m">{Math.round(s.score)}</b>, s.eligible ? <Badge key="e" tone="good">Met</Badge> : <Badge key="e" tone="critical">Not met</Badge>,
          <StatusBadge key="r" status={s.recommendation} />, <span key="s" className="line-clamp-2 text-ink-2">{s.summary}</span>])}
          empty="Nothing to review — great job!" />
      </Card>
    </>
  );
}
