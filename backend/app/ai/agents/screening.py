"""Candidate Screening Agent: rule-based eligibility + evidence-based summary + advisory recommendation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.ai.agents.base import AgentContext, BaseAgent, RunState
from app.ai.agents.matching import MatchInput, MatchOutput, compute_match
from app.ai.guardrails import scrub_protected, validate_ai_rationale, wrap_untrusted
from app.domain.enums import AgentName, Recommendation

REC_ORDER = [Recommendation.STRONG_NO, Recommendation.NO, Recommendation.MAYBE, Recommendation.YES,
             Recommendation.STRONG_YES]


class KnockoutQuestion(BaseModel):
    id: str
    question: str
    expected: bool | str


class ScreeningInput(BaseModel):
    job_title: str
    match_input: MatchInput
    knockout_questions: list[KnockoutQuestion] = Field(default_factory=list)
    answers: dict[str, bool | str] = Field(default_factory=dict)
    candidate_text: str = ""  # sanitized CV / cover letter text (untrusted)
    security_flags: list[str] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=lambda: {"strong_yes": 80, "yes": 65, "maybe": 45})


class RuleResult(BaseModel):
    rule: str
    passed: bool
    mandatory: bool
    detail: str
    evidence: str | None = None


class Fact(BaseModel):
    statement: str
    evidence: str | None
    source: str


class Interpretation(BaseModel):
    kind: str  # strength|gap|probe|summary
    text: str
    ai_generated: bool = True


class ScreeningOutput(BaseModel):
    eligible: bool
    score: float
    recommendation: Recommendation
    rule_results: list[RuleResult]
    facts: list[Fact]
    interpretations: list[Interpretation]
    summary: str
    match: MatchOutput
    requires_human_review: bool = True


class LLMScreening(BaseModel):
    summary: str
    strengths: list[str]
    gaps: list[str]
    probe_questions: list[str]
    recommendation: Recommendation
    confidence: float = Field(ge=0, le=1)
    security_notes: list[str]


def deterministic_recommendation(eligible: bool, score: float, thresholds: dict[str, float]) -> Recommendation:
    if not eligible:
        return Recommendation.NO
    if score >= thresholds.get("strong_yes", 80):
        return Recommendation.STRONG_YES
    if score >= thresholds.get("yes", 65):
        return Recommendation.YES
    if score >= thresholds.get("maybe", 45):
        return Recommendation.MAYBE
    return Recommendation.NO


class ScreeningAgent(BaseAgent[ScreeningInput, ScreeningOutput]):
    name = AgentName.SCREENING
    prompt_key = "screening"

    def summarize_input(self, payload: ScreeningInput) -> dict:
        return {
            "job_title": payload.job_title,
            "requirements": len(payload.match_input.requirements),
            "knockouts": len(payload.knockout_questions),
            "text_chars": len(payload.candidate_text),
            "security_flags": payload.security_flags,
        }

    def execute(self, ctx: AgentContext, payload: ScreeningInput, state: RunState) -> ScreeningOutput:
        match = compute_match(payload.match_input)
        rules: list[RuleResult] = [
            RuleResult(
                rule=f"{m.kind}: {m.requirement}", passed=m.matched, mandatory=m.mandatory, detail=m.detail,
                evidence=m.evidence,
            )
            for m in match.matches
        ]
        for q in payload.knockout_questions:
            ans = payload.answers.get(q.id)
            passed = ans is not None and str(ans).strip().lower() == str(q.expected).strip().lower()
            rules.append(
                RuleResult(
                    rule=f"knockout: {q.question}", passed=passed, mandatory=True,
                    detail="Answer matches requirement" if passed else f"Answer '{ans}' does not meet requirement",
                    evidence=None if ans is None else str(ans),
                )
            )
        # Work authorization etc. are "needs verification", not failures.
        eligible = all(r.passed for r in rules if r.mandatory and not r.rule.startswith("work_authorization"))
        facts = [
            Fact(statement=m.detail, evidence=m.evidence, source="candidate_material")
            for m in match.matches if m.evidence
        ]
        for q in payload.knockout_questions:
            if q.id in payload.answers:
                facts.append(Fact(statement=f"Answered '{q.question}'", evidence=str(payload.answers[q.id]),
                                  source="application_form"))
        det_rec = deterministic_recommendation(eligible, match.score, payload.thresholds)
        strengths = [m.requirement for m in match.matches if m.matched and m.weight >= 1]
        gaps = [m.detail for m in match.matches if not m.matched]
        interpretations = [
            Interpretation(kind="strength", text=f"Meets requirement: {s}", ai_generated=False) for s in strengths[:8]
        ] + [Interpretation(kind="gap", text=g, ai_generated=False) for g in gaps[:8]]
        interpretations += [
            Interpretation(kind="probe", text=f"Probe depth of experience with {m.requirement}", ai_generated=False)
            for m in match.matches if 0 < m.partial < 1
        ][:5]
        summary = (
            f"{'Meets' if eligible else 'Does not meet'} mandatory criteria for {payload.job_title}. "
            f"Match score {match.score}/100 ({len(strengths)} requirements evidenced, {len(gaps)} gaps). "
            "Deterministic rule-based assessment; recruiter review required."
        )
        recommendation = det_rec

        suspicious = any(f.startswith("injection:") for f in payload.security_flags)
        if suspicious:
            state.flags.append("llm_skipped:suspected_prompt_injection")
            interpretations.append(Interpretation(
                kind="security", ai_generated=False,
                text="Candidate document contains instruction-like content; AI interpretation withheld. "
                     "Review the original document manually.",
            ))
        else:
            llm = self.ask_llm(state, schema=LLMScreening, user=self._build_prompt(payload, rules, match))
            if llm is not None:
                text_blob = " ".join([llm.summary, *llm.strengths, *llm.gaps, *llm.probe_questions])
                violations = validate_ai_rationale(text_blob)
                if violations:
                    state.flags.extend(violations)
                    llm.summary = scrub_protected(llm.summary)
                    llm.strengths = [scrub_protected(s) for s in llm.strengths]
                    llm.gaps = [scrub_protected(s) for s in llm.gaps]
                    llm.probe_questions = [scrub_protected(s) for s in llm.probe_questions]
                if llm.security_notes:
                    state.flags.append("llm_reported_security_notes")
                summary = llm.summary
                interpretations = (
                    [Interpretation(kind="strength", text=s) for s in llm.strengths]
                    + [Interpretation(kind="gap", text=g) for g in llm.gaps]
                    + [Interpretation(kind="probe", text=p) for p in llm.probe_questions]
                )
                recommendation = llm.recommendation
                # AI may never recommend advancing a candidate who fails mandatory rules.
                if not eligible and REC_ORDER.index(recommendation) > REC_ORDER.index(Recommendation.MAYBE):
                    recommendation = Recommendation.MAYBE
                    state.flags.append("recommendation_capped:ineligible")
                if abs(REC_ORDER.index(recommendation) - REC_ORDER.index(det_rec)) >= 2:
                    state.flags.append("ai_rules_disagreement")
        return ScreeningOutput(
            eligible=eligible, score=match.score, recommendation=recommendation, rule_results=rules,
            facts=facts, interpretations=interpretations, summary=summary, match=match,
        )

    @staticmethod
    def _build_prompt(payload: ScreeningInput, rules: list[RuleResult], match: MatchOutput) -> str:
        rule_lines = "\n".join(f"- [{'PASS' if r.passed else 'FAIL'}{' (mandatory)' if r.mandatory else ''}] "
                               f"{r.rule}: {r.detail}" for r in rules)
        return (
            f"Job title: {payload.job_title}\n"
            f"Deterministic match score: {match.score}/100 (coverage {match.coverage_score})\n"
            f"Rule checks:\n{rule_lines}\n\n"
            f"{wrap_untrusted('candidate_cv', payload.candidate_text[:30000])}\n\n"
            "Produce the screening interpretation JSON."
        )
