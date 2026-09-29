"use client";

import { useState } from "react";
import { A, Card, Input, Loading, PageHeader, Select, StatusBadge, Table } from "@/components/ui";
import { useApi, type Page } from "@/lib/api";
import { fmtDate, titleCase } from "@/lib/format";
import type { Job } from "@/lib/types";

export default function Jobs() {
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const { data } = useApi<Page<Job>>("/jobs", { status, q, page_size: 50 });
  return (
    <>
      <PageHeader title="Jobs" subtitle="Draft, publish and manage vacancies; open a job to see its pipeline." />
      <Card>
        <div className="mb-3 flex gap-2">
          <Input placeholder="Search jobs" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs" />
          <Select value={status} onChange={(e) => setStatus(e.target.value)} className="max-w-[10rem]">
            {["", "draft", "published", "paused", "closed"].map((s) => <option key={s} value={s}>{s ? titleCase(s) : "All"}</option>)}
          </Select>
        </div>
        {!data ? <Loading /> : <Table head={["Title", "Location", "Type", "Published", "Status"]} rows={data.items.map((j) => [
          <A key="t" href={`/jobs/${j.id}`}>{j.title}</A>, j.location ?? "—", titleCase(j.employment_type),
          fmtDate(j.published_at), <StatusBadge key="s" status={j.status} />])} />}
      </Card>
    </>
  );
}
