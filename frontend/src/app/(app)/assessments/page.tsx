"use client";

import { useState } from "react";
import { useCan } from "@/components/shell";
import { Badge, Button, Card, ErrorBox, Field, Input, Loading, PageHeader, Select, Table, Textarea } from "@/components/ui";
import { api, ApiError, useApi, type Page } from "@/lib/api";
import { titleCase } from "@/lib/format";
import type { Job } from "@/lib/types";

interface Q { id: string; kind: string; prompt: string; competency: string | null; difficulty: string; points: number; tags: string[] }
interface A_ { id: string; title: string; kind: string; duration_minutes: number; passing_score: number; questions: Q[]; job_id: string | null }

export default function Assessments() {
  const can = useCan();
  const { data: list, reload } = useApi<Page<A_>>("/assessments", { page_size: 100 });
  const { data: bank, reload: reloadBank } = useApi<Q[]>("/question-bank");
  const { data: jobs } = useApi<Page<Job>>("/jobs", { page_size: 100 });
  const [jobId, setJobId] = useState("");
  const [q, setQ] = useState({ kind: "single_choice", prompt: "", options: "", answer: "", competency: "", points: "1", tags: "" });
  const [error, setError] = useState<ApiError | null>(null);
  async function act(fn: () => Promise<unknown>) { setError(null); try { await fn(); reload(); reloadBank(); } catch (e) { setError(e as ApiError); } }
  function addQuestion() {
    const options = q.options.split("\n").map((s) => s.trim()).filter(Boolean);
    const correct = q.kind === "single_choice" ? { value: q.answer } : q.kind === "multi_choice" ? { values: q.answer.split(",").map((s) => s.trim()) }
      : { keywords: q.answer.split(",").map((s) => s.trim()).filter(Boolean) };
    return act(() => api("/question-bank", { method: "POST", body: { kind: q.kind, prompt: q.prompt, options, correct_answer: correct,
      competency: q.competency || null, points: Number(q.points), tags: q.tags.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean) } }));
  }
  if (!list) return <Loading />;
  return (
    <>
      <PageHeader title="Assessments" subtitle="Structured technical & competency assessments with auto-scoring and human review of free text."
        actions={can("assessments:manage") && <>
          <Select value={jobId} onChange={(e) => setJobId(e.target.value)}><option value="">Generate for job…</option>{jobs?.items.map((j) => <option key={j.id} value={j.id}>{j.title}</option>)}</Select>
          <Button disabled={!jobId} onClick={() => act(() => api("/assessments/generate", { method: "POST", body: { job_id: jobId } }))}>Generate (Assessment agent)</Button></>} />
      <ErrorBox error={error} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Assessments">
          <Table head={["Title", "Type", "Questions", "Duration", "Pass mark"]} rows={list.items.map((a) => [a.title, titleCase(a.kind), a.questions.length, `${a.duration_minutes} min`, `${a.passing_score}%`])} />
        </Card>
        <Card title="Question bank">
          <Table head={["Question", "Competency", "Type", "Pts"]} rows={(bank ?? []).map((x) => [<span key="p" className="line-clamp-2">{x.prompt}</span>,
            x.competency ?? "—", <Badge key="k">{titleCase(x.kind)}</Badge>, x.points])} />
          {can("assessments:manage") && (
            <div className="mt-4 space-y-2 border-t border-line pt-3">
              <div className="grid gap-2 md:grid-cols-3">
                <Select value={q.kind} onChange={(e) => setQ({ ...q, kind: e.target.value })}>{["single_choice", "multi_choice", "short_text", "long_text", "code"].map((k) => <option key={k} value={k}>{titleCase(k)}</option>)}</Select>
                <Input placeholder="Competency / skill" value={q.competency} onChange={(e) => setQ({ ...q, competency: e.target.value })} />
                <Input type="number" placeholder="Points" value={q.points} onChange={(e) => setQ({ ...q, points: e.target.value })} />
              </div>
              <Textarea rows={2} placeholder="Question prompt" value={q.prompt} onChange={(e) => setQ({ ...q, prompt: e.target.value })} />
              {q.kind.endsWith("choice") && <Textarea rows={3} placeholder="Options (one per line)" value={q.options} onChange={(e) => setQ({ ...q, options: e.target.value })} />}
              <Field label={q.kind.endsWith("choice") ? "Correct option(s) (comma separated)" : "Rubric keywords (comma separated)"}>
                <Input value={q.answer} onChange={(e) => setQ({ ...q, answer: e.target.value })} /></Field>
              <Input placeholder="Tags (comma separated, e.g. python)" value={q.tags} onChange={(e) => setQ({ ...q, tags: e.target.value })} />
              <Button onClick={addQuestion} disabled={!q.prompt}>Add to bank</Button>
            </div>)}
        </Card>
      </div>
    </>
  );
}
