"""Assessment Agent: builds structured assessments from the question bank and scores responses.

Objective questions are auto-scored. Free-text / code answers receive a *suggested* rubric score
(keyword coverage) that is flagged for human confirmation — it is never final on its own.
"""

from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, Field

from app.ai.agents.base import AgentContext, BaseAgent, RunState
from app.domain.enums import AgentName


class BankQuestion(BaseModel):
    id: uuid.UUID
    kind: str
    competency: str | None = None
    tags: list[str] = Field(default_factory=list)
    difficulty: str = "medium"
    points: float = 1


class BuildInput(BaseModel):
    skills: list[str]
    bank: list[BankQuestion]
    max_questions: int = 10


class BuildOutput(BaseModel):
    question_ids: list[uuid.UUID]
    coverage: dict[str, int]
    uncovered_skills: list[str]


class QuestionForScoring(BaseModel):
    id: str
    kind: str
    points: float
    competency: str | None = None
    correct_answer: dict | None = None  # {"value": ...} | {"values": [...]} | {"keywords": [...]}
    rubric: str | None = None


class ScoreInput(BaseModel):
    questions: list[QuestionForScoring]
    answers: dict[str, object]
    passing_pct: float = 60


class QuestionScore(BaseModel):
    score: float
    max: float
    auto: bool
    needs_review: bool
    note: str


class ScoreOutput(BaseModel):
    score: float
    max_score: float
    percentage: float
    passed: bool | None
    needs_human_review: bool
    per_question: dict[str, QuestionScore]
    competency_scores: dict[str, float]


class AssessmentBuilderAgent(BaseAgent[BuildInput, BuildOutput]):
    name = AgentName.ASSESSMENT

    def execute(self, ctx: AgentContext, p: BuildInput, state: RunState) -> BuildOutput:
        wanted = [s.lower() for s in p.skills]
        chosen: list[uuid.UUID] = []
        coverage: dict[str, int] = {}
        per_skill = max(1, p.max_questions // max(1, len(wanted)))
        for skill in wanted:
            pool = [q for q in p.bank if q.id not in chosen and (
                (q.competency or "").lower() == skill or skill in [t.lower() for t in q.tags])]
            pool.sort(key=lambda q: {"easy": 0, "medium": 1, "hard": 2}.get(q.difficulty, 1))
            for q in pool[:per_skill]:
                if len(chosen) < p.max_questions:
                    chosen.append(q.id)
                    coverage[skill] = coverage.get(skill, 0) + 1
        return BuildOutput(question_ids=chosen, coverage=coverage,
                           uncovered_skills=[s for s in wanted if s not in coverage])


def _norm(v: object) -> str:
    return re.sub(r"\s+", " ", str(v).strip().lower())


def score_answers(p: ScoreInput) -> ScoreOutput:
    per: dict[str, QuestionScore] = {}
    comp_tot: dict[str, list[float]] = {}
    for q in p.questions:
        ans = p.answers.get(q.id)
        key = q.correct_answer or {}
        if ans is None or ans == "" or ans == []:
            qs = QuestionScore(score=0, max=q.points, auto=True, needs_review=False, note="No answer")
        elif q.kind == "single_choice" and "value" in key:
            ok = _norm(ans) == _norm(key["value"])
            qs = QuestionScore(score=q.points if ok else 0, max=q.points, auto=True, needs_review=False,
                               note="Correct" if ok else "Incorrect")
        elif q.kind == "multi_choice" and "values" in key:
            given = {_norm(a) for a in (ans if isinstance(ans, list) else [ans])}
            correct = {_norm(a) for a in key["values"]}
            tp = len(given & correct)
            fp = len(given - correct)
            frac = max(0.0, (tp - fp) / len(correct)) if correct else 0.0
            qs = QuestionScore(score=round(q.points * frac, 2), max=q.points, auto=True, needs_review=False,
                               note=f"{tp}/{len(correct)} correct, {fp} incorrect")
        elif q.kind == "rating":
            try:
                val = float(ans)  # type: ignore[arg-type]
                qs = QuestionScore(score=round(q.points * max(0, min(val, 5)) / 5, 2), max=q.points, auto=True,
                                   needs_review=False, note="Self-rating")
            except (TypeError, ValueError):
                qs = QuestionScore(score=0, max=q.points, auto=True, needs_review=False, note="Invalid rating")
        else:
            keywords = [k.lower() for k in key.get("keywords", [])]
            text = _norm(ans)
            if keywords:
                hit = sum(1 for k in keywords if k in text)
                frac = hit / len(keywords)
                note = f"Suggested: {hit}/{len(keywords)} rubric keywords present"
            else:
                frac, note = 0.0, "No rubric keywords; score manually"
            qs = QuestionScore(score=round(q.points * frac, 2), max=q.points, auto=False, needs_review=True, note=note)
        per[q.id] = qs
        if q.competency:
            comp_tot.setdefault(q.competency, [0.0, 0.0])
            comp_tot[q.competency][0] += qs.score
            comp_tot[q.competency][1] += qs.max
    total = sum(v.score for v in per.values())
    max_total = sum(v.max for v in per.values()) or 1.0
    pct = round(100 * total / max_total, 1)
    needs_review = any(v.needs_review for v in per.values())
    return ScoreOutput(
        score=round(total, 2), max_score=round(max_total, 2), percentage=pct,
        passed=None if needs_review else pct >= p.passing_pct, needs_human_review=needs_review,
        per_question=per,
        competency_scores={c: round(100 * s / m, 1) if m else 0 for c, (s, m) in comp_tot.items()},
    )


class AssessmentScoringAgent(BaseAgent[ScoreInput, ScoreOutput]):
    name = AgentName.ASSESSMENT

    def summarize_input(self, payload: ScoreInput) -> dict:
        return {"questions": len(payload.questions), "answered": len(payload.answers)}

    def execute(self, ctx: AgentContext, p: ScoreInput, state: RunState) -> ScoreOutput:
        return score_answers(p)
