"use client";

import Link from "next/link";
import { markAllRead } from "@/components/shell";
import { Button, Card, Loading, PageHeader } from "@/components/ui";
import { api, useApi, type Page } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

interface Notification { id: string; title: string; body: string | null; link: string | null; read_at: string | null; created_at: string }

export default function Notifications() {
  const { data, reload } = useApi<Page<Notification>>("/notifications", { page_size: 50 });
  if (!data) return <Loading />;
  return (
    <>
      <PageHeader title="Notifications" actions={<Button variant="secondary" onClick={async () => { await markAllRead(); reload(); }}>Mark all read</Button>} />
      <Card>
        <ul className="divide-y divide-line">
          {data.items.map((n) => (
            <li key={n.id} className="flex items-start justify-between gap-3 py-2 text-sm">
              <div>
                <div className={n.read_at ? "text-ink-2" : "font-medium"}>
                  {n.link ? <Link href={n.link} onClick={() => api(`/notifications/${n.id}/read`, { method: "POST" })} className="hover:underline">{n.title}</Link> : n.title}
                </div>
                {n.body && <div className="text-ink-3">{n.body}</div>}
              </div>
              <span className="shrink-0 text-xs text-ink-3">{fmtDateTime(n.created_at)}</span>
            </li>
          ))}
          {data.items.length === 0 && <li className="py-6 text-center text-ink-3">You&apos;re all caught up.</li>}
        </ul>
      </Card>
    </>
  );
}
