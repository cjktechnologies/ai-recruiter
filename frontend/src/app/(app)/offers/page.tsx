"use client";

import { useState } from "react";
import { A, Card, Loading, PageHeader, Select, StatusBadge, Table } from "@/components/ui";
import { useApi, type Page } from "@/lib/api";
import { fmtDate, fmtMoney, titleCase } from "@/lib/format";
import type { Offer } from "@/lib/types";

export default function Offers() {
  const [status, setStatus] = useState("");
  const { data } = useApi<Page<Offer>>("/offers", { status, page_size: 100 });
  return (
    <>
      <PageHeader title="Offer management" subtitle="Drafts, approvals, sent offers and responses." />
      <Card>
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="mb-3 max-w-[14rem]">
          {["", "draft", "pending_approval", "approved", "sent", "accepted", "declined", "expired", "withdrawn"].map((s) => <option key={s} value={s}>{s ? titleCase(s) : "All statuses"}</option>)}
        </Select>
        {!data ? <Loading /> : <Table head={["Role", "Salary", "Band", "Start", "Status", ""]} rows={data.items.map((o) => [o.job_title,
          fmtMoney(o.base_salary, o.currency), o.within_band === false ? "Outside" : "Within", fmtDate(o.start_date), <StatusBadge key="s" status={o.status} />,
          <A key="o" href={`/offers/${o.id}`}>Open</A>])} />}
      </Card>
    </>
  );
}
