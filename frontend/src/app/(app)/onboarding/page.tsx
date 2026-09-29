"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { useCan } from "@/components/shell";
import { A, Card, Loading, PageHeader, Select, StatusBadge, Table } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { fmtDate, titleCase } from "@/lib/format";

interface Task { id: string; application_id: string; title: string; category: string; status: string; due_date: string | null }

function Tasks() {
  const app = useSearchParams().get("application");
  const can = useCan();
  const { data, reload } = useApi<Task[]>("/onboarding/tasks");
  if (!data) return <Loading />;
  const rows = data.filter((t) => !app || t.application_id === app);
  return (
    <Card title="Preboarding & onboarding checklist">
      <Table head={["Task", "Category", "Due", "Status", "Hire"]} rows={rows.map((t) => [t.title, titleCase(t.category), fmtDate(t.due_date),
        can("onboarding:manage") ? <Select key="s" value={t.status} className="w-36" onChange={async (e) => { await api(`/onboarding/tasks/${t.id}`, { method: "PATCH", body: { status: e.target.value } }); reload(); }}>
          {["pending", "in_progress", "done", "blocked"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}</Select> : <StatusBadge key="s" status={t.status} />,
        <A key="a" href={`/applications/${t.application_id}`}>View</A>])} empty="No onboarding tasks yet." />
    </Card>
  );
}

export default function Onboarding() {
  return (<><PageHeader title="Onboarding" subtitle="HRIS handoff, IT provisioning and preboarding tasks for new hires." /><Suspense><Tasks /></Suspense></>);
}
