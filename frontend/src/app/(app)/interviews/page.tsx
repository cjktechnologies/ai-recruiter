"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Button, Card, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/api";
import { titleCase } from "@/lib/format";
import type { Interview } from "@/lib/types";

function startOfWeek(d: Date) { const x = new Date(d); x.setHours(0, 0, 0, 0); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x; }

export default function InterviewCalendar() {
  const [week, setWeek] = useState(() => startOfWeek(new Date()));
  const end = useMemo(() => new Date(week.getTime() + 7 * 86400000), [week]);
  const { data } = useApi<Interview[]>("/interviews", { start: week.toISOString(), end: end.toISOString() });
  const days = Array.from({ length: 7 }, (_, i) => new Date(week.getTime() + i * 86400000));
  return (
    <>
      <PageHeader title="Interview calendar" subtitle={`Week of ${week.toLocaleDateString()}`} actions={<>
        <Button variant="secondary" onClick={() => setWeek(new Date(week.getTime() - 7 * 86400000))}>← Prev</Button>
        <Button variant="secondary" onClick={() => setWeek(startOfWeek(new Date()))}>Today</Button>
        <Button variant="secondary" onClick={() => setWeek(new Date(week.getTime() + 7 * 86400000))}>Next →</Button></>} />
      {!data ? <Loading /> : (
        <div className="grid gap-2 md:grid-cols-7">
          {days.map((d) => {
            const items = data.filter((i) => new Date(i.scheduled_start).toDateString() === d.toDateString());
            return (
              <Card key={d.toISOString()} title={d.toLocaleDateString(undefined, { weekday: "short", day: "numeric" })}>
                <ul className="space-y-2">
                  {items.map((i) => (
                    <li key={i.id}><Link href={`/interviews/${i.id}`} className="block rounded border border-line p-2 text-xs hover:border-accent">
                      <div className="font-medium">{new Date(i.scheduled_start).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · {i.candidate_name}</div>
                      <div className="text-ink-3">{titleCase(i.kind)} · {i.job_title}</div>
                      <StatusBadge status={i.status} />
                    </Link></li>))}
                  {items.length === 0 && <li className="text-xs text-ink-3">—</li>}
                </ul>
              </Card>);
          })}
        </div>
      )}
    </>
  );
}
