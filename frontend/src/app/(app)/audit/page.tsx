"use client";

import { useState } from "react";
import { Badge, Button, Card, Input, Loading, PageHeader, Table } from "@/components/ui";
import { useApi, type Page } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

interface Log { id: string; actor_type: string; actor_id: string | null; action: string; entity_type: string; entity_id: string | null; changes: Record<string, unknown>; ip_address: string | null; request_id: string | null; created_at: string }

export default function Audit() {
  const [action, setAction] = useState("");
  const [entity, setEntity] = useState("");
  const [page, setPage] = useState(1);
  const { data } = useApi<Page<Log>>("/audit-logs", { action, entity_id: entity, page, page_size: 50 });
  return (
    <>
      <PageHeader title="Audit log" subtitle="Append-only record of every change, decision and AI action (tamper-protected at the database level)." />
      <Card>
        <div className="mb-3 flex gap-2">
          <Input placeholder="Action prefix (e.g. offer.)" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} className="max-w-xs" />
          <Input placeholder="Entity id" value={entity} onChange={(e) => { setEntity(e.target.value); setPage(1); }} className="max-w-xs" />
        </div>
        {!data ? <Loading /> : <>
          <Table head={["When", "Actor", "Action", "Entity", "Changes"]} rows={data.items.map((l) => [fmtDateTime(l.created_at),
            <Badge key="a" tone={l.actor_type === "agent" ? "ai" : "neutral"}>{l.actor_type}</Badge>, <code key="c" className="text-xs">{l.action}</code>,
            <span key="e" className="text-xs">{l.entity_type} {l.entity_id?.slice(0, 8)}</span>,
            <pre key="p" className="max-w-md overflow-x-auto whitespace-pre-wrap text-xs text-ink-2">{JSON.stringify(l.changes)}</pre>])} />
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <Button variant="secondary" disabled={page * 50 >= data.total} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        </>}
      </Card>
    </>
  );
}
