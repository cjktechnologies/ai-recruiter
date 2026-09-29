"""Candidate Evaluation Agent: consolidates screening, assessment and interview evidence."""

from __future__ import annotations

import statistics

from pydantic import BaseModel, Field

from app.ai.agents.base import AgentContext, BaseAgent, RunState
from app.ai.guardrails import scrub_protected, validate_ai_rationale
from app.domain.enums import AgentName, Recommendation

REC_SCORE = {"strong_no": 1, "no": 2, "maybe": 3, "yes": 4, "strong_yes": 5}


class ScorecardIn(BaseModel):
    interviewer: str
    overall_rating: float | None
    recommendation: str | None
    ratings: list[dict] = Field(default_factory=list)  # [{"competency":..,"rating":..,"evidence":..}]


class AssessmentIn(BaseModel):
    title: str
    percentage: float | None
    passed: bool | None
    competency_scores: dict[str, float] = Field(default_factory=dict)


class EvaluationInput(BaseModel):
    job_title: str
    screening_score: float | None = None
    screening_recommendation: str | None = None
    screening_reviewer_decision: str | None = None
    assessments: list[AssessmentIn] = Field(default_factory=list)
    scorecards: list[ScorecardIn] = Field(default_factory=list)
    expected_interviewers: int = 0


class EvaluationOutput(BaseModel):
    overall_score: float
    recommendation: Recommendation
    competency_matrix: dict[str, dict[str, float | int]]
    strengths: list[str]
    concerns: list[str]
    risks: list[str]
    rationale: str
    ai_generated: bool


class LLMEvaluation(BaseModel):
    rationale: str
    strengths: list[str]
    concerns: list[str]


class EvaluationAgent(BaseAgent[EvaluationInput, EvaluationOutput]):
    name = AgentName.EVALUATION
    prompt_key = "evaluation"

    def execute(self, ctx: AgentContext, p: EvaluationInput, state: RunState) -> EvaluationOutput:
        matrix: dict[str, list[float]] = {}
        for sc in p.scorecards:
            for r in sc.ratings:
                if r.get("rating") is not None:
                    matrix.setdefault(r["competency"], []).append(float(r["rating"]))
        for a in p.assessments:
            for comp, pct in a.competency_scores.items():
                matrix.setdefault(comp, []).append(1 + 4 * pct / 100)  # map % onto 1-5 scale
        comp_summary = {
            c: {"mean": round(statistics.mean(v), 2), "n": len(v),
                "spread": round(max(v) - min(v), 2) if len(v) > 1 else 0.0}
            for c, v in matrix.items()
        }
        components: list[tuple[float, float]] = []  # (score 0-100, weight)
        if p.screening_score is not None:
            components.append((p.screening_score, 0.2))
        pcts = [a.percentage for a in p.assessments if a.percentage is not None]
        if pcts:
            components.append((statistics.mean(pcts), 0.3))
        overall_ratings = [s.overall_rating for s in p.scorecards if s.overall_rating is not None]
        if overall_ratings:
            components.append(((statistics.mean(overall_ratings) - 1) / 4 * 100, 0.5))
        total_w = sum(w for _, w in components) or 1
        overall = round(sum(s * w for s, w in components) / total_w, 1) if components else 0.0

        risks: list[str] = []
        if p.expected_interviewers and len(p.scorecards) < p.expected_interviewers:
            risks.append(f"Missing scorecards: {len(p.scorecards)}/{p.expected_interviewers} submitted")
        recs = [REC_SCORE[s.recommendation] for s in p.scorecards if s.recommendation in REC_SCORE]
        if len(recs) > 1 and max(recs) - min(recs) >= 3:
            risks.append("Strong interviewer disagreement — calibrate before deciding")
        for c, v in comp_summary.items():
            if v["spread"] >= 2.5:
                risks.append(f"Inconsistent ratings for {c} (spread {v['spread']})")
        if not p.scorecards:
            risks.append("No interview evidence")
        if any(a.passed is False for a in p.assessments):
            risks.append("One or more assessments below passing threshold")

        strengths = [c for c, v in comp_summary.items() if v["mean"] >= 4]
        concerns = [c for c, v in comp_summary.items() if v["mean"] < 3]
        if overall >= 80 and not concerns:
            rec = Recommendation.STRONG_YES
        elif overall >= 65:
            rec = Recommendation.YES
        elif overall >= 50:
            rec = Recommendation.MAYBE
        else:
            rec = Recommendation.NO
        if "No interview evidence" in risks and rec in (Recommendation.STRONG_YES, Recommendation.YES):
            rec = Recommendation.MAYBE
        rationale = (
            f"Weighted evidence score {overall}/100 from {len(components)} source(s). "
            f"Strong competencies: {', '.join(strengths) or 'none identified'}. "
            f"Concerns: {', '.join(concerns) or 'none identified'}. Advisory only — hiring manager decides."
        )
        ai_generated = False
        llm = self.ask_llm(state, schema=LLMEvaluation, user=p.model_dump_json() + f"\nComputed: {comp_summary}")
        if llm:
            if flags := validate_ai_rationale(llm.rationale):
                state.flags.extend(flags)
                llm.rationale = scrub_protected(llm.rationale)
            rationale, ai_generated = llm.rationale, True
            strengths = strengths + [s for s in llm.strengths if s not in strengths]
            concerns = concerns + [c for c in llm.concerns if c not in concerns]
        return EvaluationOutput(
            overall_score=overall, recommendation=rec, competency_matrix=comp_summary, strengths=strengths,
            concerns=concerns, risks=risks, rationale=rationale, ai_generated=ai_generated,
        )
