"""Recruitment Analytics Agent: turns computed metrics into actionable insights."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.ai.agents.base import AgentContext, BaseAgent, RunState
from app.domain.enums import AgentName


class AnalyticsInput(BaseModel):
    metrics: dict
    sla_days: dict[str, int] = Field(default_factory=lambda: {"screening": 3, "interview": 10, "offer": 5})


class Insight(BaseModel):
    severity: str  # info|warning|critical
    title: str
    detail: str
    metric: str


class AnalyticsOutput(BaseModel):
    insights: list[Insight]
    ai_generated: bool


class LLMInsights(BaseModel):
    insights: list[Insight]


class AnalyticsAgent(BaseAgent[AnalyticsInput, AnalyticsOutput]):
    name = AgentName.ANALYTICS
    prompt_key = "analytics"

    def summarize_input(self, payload: AnalyticsInput) -> dict:
        return {"metric_keys": sorted(payload.metrics.keys())}

    def execute(self, ctx: AgentContext, p: AnalyticsInput, state: RunState) -> AnalyticsOutput:
        m = p.metrics
        out: list[Insight] = []
        for stage, days in (m.get("avg_days_in_stage") or {}).items():
            limit = p.sla_days.get(stage)
            if limit and days and days > limit:
                out.append(Insight(severity="warning", metric=f"avg_days_in_stage.{stage}",
                                   title=f"{stage.title()} is a bottleneck",
                                   detail=f"Candidates spend {days:.1f} days on average vs SLA {limit} days."))
        oar = m.get("offer_acceptance_rate")
        if oar is not None and oar < 70 and (m.get("offers_sent") or 0) >= 3:
            out.append(Insight(severity="warning", metric="offer_acceptance_rate", title="Low offer acceptance",
                               detail=f"Only {oar:.0f}% of offers accepted; review compensation competitiveness."))
        sources = m.get("source_effectiveness") or []
        if sources:
            best = max(sources, key=lambda s: s.get("hire_rate", 0))
            if best.get("hires", 0):
                out.append(Insight(severity="info", metric="source_effectiveness", title="Most effective source",
                                   detail=f"'{best['source']}' converts {best['hire_rate']:.1f}% of applicants to hires."))
        for f in m.get("fairness_alerts") or []:
            out.append(Insight(severity="critical", metric="fairness", title="Adverse impact alert",
                               detail=f"{f['stage']}: selection-rate ratio {f['impact_ratio']:.2f} for {f['group']} "
                                      "is below the four-fifths threshold. Review screening criteria."))
        conv = m.get("screening_conversion")
        if conv is not None and conv < 10 and (m.get("applications") or 0) > 20:
            out.append(Insight(severity="info", metric="screening_conversion", title="Low screening pass-through",
                               detail=f"{conv:.1f}% of applicants pass screening; consider refining the advert."))
        llm = self.ask_llm(state, schema=LLMInsights, user=f"Metrics JSON: {m}")
        if llm:
            return AnalyticsOutput(insights=out + llm.insights, ai_generated=True)
        return AnalyticsOutput(insights=out, ai_generated=False)
