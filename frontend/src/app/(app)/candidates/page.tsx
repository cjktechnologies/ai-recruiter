"use client";

import { useState } from "react";
import { useCan } from "@/components/shell";
import { A, Badge, Button, Card, ErrorBox, Field, Input, Loading, PageHeader, Table } from "@/components/ui";
import { api, ApiError, useApi, type Page } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Candidate } from "@/lib/types";

export default function Candidates() {
  const can = useCan();
  const [q, setQ] = useState("");
  const [skill, setSkill] = useState("");
  const [page, setPage] = useState(1);
  const { data, reload } = useApi<Page<Candidate>>("/candidates", { q, skills: skill ? [skill] : undefined, page, page_size: 25 });
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ first_name: "", last_name: "", email: "", phone: "", source: "sourced", skills: "" });
  const [error, setError] = useState<ApiError | null>(null);
  async function add() {
    setError(null);
    try {
      await api("/candidates", { method: "POST", body: { ...f, phone: f.phone || null,
        skills: f.skills.split(",").map((s) => s.trim()).filter(Boolean) } });
      setAdding(false);
      reload();
    } catch (e) { setError(e as ApiError); }
  }
  return (
    <>
      <PageHeader title="Candidates" subtitle="Search the CRM by name, e-mail, title or skill."
        actions={can("candidates:create") && <Button onClick={() => setAdding(!adding)}>Add candidate</Button>} />
      {adding && (
        <Card title="New candidate" className="mb-4">
          <ErrorBox error={error} />
          <div className="grid gap-3 md:grid-cols-3">
            {(["first_name", "last_name", "email", "phone", "source", "skills"] as const).map((k) => (
              <Field key={k} label={k.replace("_", " ")}><Input value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></Field>
            ))}
          </div>
          <Button className="mt-3" onClick={add}>Create</Button>
        </Card>
      )}
      <Card>
        <div className="mb-3 flex flex-wrap gap-2">
          <Input placeholder="Search" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="max-w-xs" />
          <Input placeholder="Skill (e.g. Python)" value={skill} onChange={(e) => { setSkill(e.target.value); setPage(1); }} className="max-w-[12rem]" />
        </div>
        {!data ? <Loading /> : <>
          <Table head={["Name", "Headline", "Experience", "Source", "Tags", "Added"]} rows={data.items.map((c) => [
            <A key="n" href={`/candidates/${c.id}`}>{c.full_name}</A>, c.headline ?? c.current_title ?? "—",
            c.years_experience ? `${c.years_experience} yrs` : "—", c.source,
            <span key="t" className="flex flex-wrap gap-1">{c.tags.map((t) => <Badge key={t}>{t}</Badge>)}</span>, fmtDate(c.created_at)])} />
          <div className="mt-3 flex justify-between text-sm text-ink-3"><span>{data.total} candidates</span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
              <Button variant="secondary" disabled={page * 25 >= data.total} onClick={() => setPage(page + 1)}>Next</Button>
            </div>
          </div>
        </>}
      </Card>
    </>
  );
}
