"use client";

import Link from "next/link";
import { useState } from "react";
import { useCan } from "@/components/shell";
import { A, Button, Card, Input, Loading, PageHeader, Select, StatusBadge, Table } from "@/components/ui";
import { useApi, type Page } from "@/lib/api";
import { fmtDate, fmtMoney, titleCase } from "@/lib/format";
import type { Requisition } from "@/lib/types";

const STATUSES = ["", "draft", "pending_approval", "approved", "rejected", "on_hold", "filled", "cancelled"];

export default function Requisitions() {
  const can = useCan();
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const { data } = useApi<Page<Requisition>>("/requisitions", { status, q, page, page_size: 20 });
  return (
    <>
      <PageHeader title="Hiring requisitions" subtitle="Approved requisitions become jobs"
        actions={can("requisitions:create") && <Link href="/requisitions/new"><Button>New requisition</Button></Link>} />
      <Card>
        <div className="mb-3 flex flex-wrap gap-2">
          <Input placeholder="Search title or reference" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="max-w-xs" />
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="max-w-[12rem]">
            {STATUSES.map((s) => <option key={s} value={s}>{s ? titleCase(s) : "All statuses"}</option>)}
          </Select>
        </div>
        {!data ? <Loading /> : (
          <>
            <Table head={["Reference", "Title", "Headcount", "Budget", "Target start", "Status"]} rows={data.items.map((r) => [
              <A key="r" href={`/requisitions/${r.id}`}>{r.reference}</A>, r.title, r.headcount,
              `${fmtMoney(r.budget_min, r.currency)} – ${fmtMoney(r.budget_max, r.currency)}`, fmtDate(r.target_start_date),
              <StatusBadge key="s" status={r.status} />])} />
            <div className="mt-3 flex items-center justify-between text-sm text-ink-3">
              <span>{data.total} total</span>
              <div className="flex gap-2">
                <Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
                <Button variant="secondary" disabled={page * data.page_size >= data.total} onClick={() => setPage(page + 1)}>Next</Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
