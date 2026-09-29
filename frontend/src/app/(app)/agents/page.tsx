"use client";

import { useState } from "react";
import { Badge, Card, Loading, PageHeader, Select, Stat, StatusBadge, Table } from "@/components/ui";
import { useApi, type Page } from "@/lib/api";
import { fmtDateTime, titleCase } from "@/lib/format";

interface Agent { key: string; name: string; description: string; provider: string; stats_7d: { runs: number; failed: number; blocked: number; avg_latency_ms: number; tokens: number } }
interface Exec { id: string; agent: string; status: string; provider: string; model: string; prompt_version: string; latency_ms: number; tokens_in: number; tokens_out: number; guardrail_flags: string[]; started_at: string; entity_type: string | null; error: string | null }
interface WF { id: string; application_id: string; current_node: string; waiting_on: string | null; status: string; updated_at: string }

export default function Agents() {
  const [agent, setAgent] = useState("");
  const [flagged, setFlagged] = useState(false);
  const { data: agents } = useApi<Agent[]>("/agents");
  const { data: execs } = useApi<Page<Exec>>("/agents/executions", { agent, flagged, page_size: 50 });
  const { data: evalm } = useApi<Record<string, Record<string, number | null>>>("/ai/evaluation");
  const { data: wfs } = useApi<WF[]>("/workflows", { limit: 100 });
  if (!agents) return <Loading />;
  const totals = agents.reduce((a, x) => ({ runs: a.runs + x.stats_7d.runs, failed: a.failed + x.stats_7d.failed }), { runs: 0, failed: 0 });
  const waiting = (wfs ?? []).filter((w) => w.status === "waiting_human");
  const byGate = waiting.reduce<Record<string, number>>((acc, w) => ({ ...acc, [w.waiting_on ?? "?"]: (acc[w.waiting_on ?? "?"] ?? 0) + 1 }), {});
  return (
    <>
      <PageHeader title="AI agent monitoring" subtitle={`Provider: ${agents[0]?.provider}. Every execution is logged with prompt version, tokens, latency and guardrail flags.`} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Runs (7 days)" value={totals.runs} />
        <Stat label="Failures (7 days)" value={totals.failed} />
        <Stat label="Workflows awaiting humans" value={waiting.length} />
        <Stat label="Screening human agreement" value={evalm?.screening?.agreement_rate != null ? `${evalm.screening.agreement_rate}%` : "—"} hint="Share of AI recommendations accepted" />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Agents" className="lg:col-span-2">
          <Table head={["Agent", "Runs", "Failed", "Blocked", "Avg latency", "Tokens"]} rows={agents.map((a) => [
            <span key="n"><b>{a.name}</b><div className="text-xs text-ink-3">{a.description}</div></span>, a.stats_7d.runs,
            a.stats_7d.failed ? <Badge key="f" tone="critical">{a.stats_7d.failed}</Badge> : 0, a.stats_7d.blocked, `${a.stats_7d.avg_latency_ms} ms`, a.stats_7d.tokens])} />
        </Card>
        <Card title="Human-in-the-loop gates">
          <Table head={["Waiting on", "Workflows"]} rows={Object.entries(byGate).map(([k, v]) => [<code key="k" className="text-xs">{k}</code>, v])} empty="No workflows waiting." />
          <h3 className="mb-1 mt-4 text-sm font-semibold">Human–AI agreement</h3>
          <Table head={["Agent", "Accepted", "Overridden", "Agreement"]} rows={Object.entries(evalm ?? {}).map(([k, v]) => [titleCase(k), v.accepted ?? 0, v.overridden ?? 0, v.agreement_rate != null ? `${v.agreement_rate}%` : "—"])} />
        </Card>
      </div>
      <Card title="Recent executions" className="mt-4" actions={<>
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={flagged} onChange={(e) => setFlagged(e.target.checked)} />Guardrail flags only</label>
        <Select value={agent} onChange={(e) => setAgent(e.target.value)} className="w-48"><option value="">All agents</option>{agents.map((a) => <option key={a.key} value={a.key}>{a.name}</option>)}</Select></>}>
        {!execs ? <Loading /> : <Table head={["When", "Agent", "Status", "Model / prompt", "Latency", "Tokens", "Flags"]} rows={execs.items.map((e) => [
          fmtDateTime(e.started_at), titleCase(e.agent), <StatusBadge key="s" status={e.status} />, <span key="m" className="text-xs">{e.provider}/{e.model}<br />{e.prompt_version}</span>,
          `${e.latency_ms} ms`, e.tokens_in + e.tokens_out, <span key="f" className="text-xs text-serious">{e.guardrail_flags.join(", ")}{e.error}</span>])} />}
      </Card>
    </>
  );
}
