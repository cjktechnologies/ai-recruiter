"""Assessments: authoring, question bank, generation, candidate invitations, scoring."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents import AssessmentBuilderAgent, AssessmentScoringAgent
from app.ai.agents.assessment import BankQuestion, BuildInput, QuestionForScoring, ScoreInput
from app.ai.agents.base import AgentContext
from app.core.config import get_settings
from app.core.errors import ConflictError, InvalidTransition, NotFoundError, ValidationFailed
from app.core.principal import Principal
from app.core.security import new_opaque_token, token_digest
from app.db.base import utcnow
from app.domain.enums import ActorType, ApplicationStage, AssessmentResultStatus, QuestionKind
from app.models.assessments import Assessment, AssessmentQuestion, AssessmentResult
from app.models.pipeline import Application
from app.models.recruitment import Job
from app.schemas.pipeline import AssessmentIn, GenerateAssessmentIn, QuestionIn
from app.services import applications as app_service
from app.services.audit import audit
from app.services.common import get_scoped
from app.services.notify import notify_users, queue_candidate_message

OBJECTIVE = {QuestionKind.SINGLE_CHOICE, QuestionKind.MULTI_CHOICE, QuestionKind.RATING}


def _validate_question(q: QuestionIn) -> None:
    if q.kind in (QuestionKind.SINGLE_CHOICE, QuestionKind.MULTI_CHOICE):
        if len(q.options) < 2:
            raise ValidationFailed("Choice questions need at least two options")
        key = q.correct_answer or {}
        vals = [key.get("value")] if q.kind == QuestionKind.SINGLE_CHOICE else key.get("values", [])
        if not vals or any(v not in q.options for v in vals):
            raise ValidationFailed("correct_answer must reference the provided options")


def add_bank_question(db: Session, data: QuestionIn, p: Principal) -> AssessmentQuestion:
    _validate_question(data)
    q = AssessmentQuestion(organization_id=p.organization_id, assessment_id=None, **data.model_dump())
    db.add(q)
    db.flush()
    return q


def create(db: Session, data: AssessmentIn, p: Principal) -> Assessment:
    if data.job_id:
        get_scoped(db, Job, data.job_id, p)
    a = Assessment(
        organization_id=p.organization_id,
        created_by_id=p.user_id,
        **data.model_dump(exclude={"questions", "bank_question_ids"}),
    )
    db.add(a)
    db.flush()
    pos = 0
    for qd in data.questions:
        _validate_question(qd)
        a.questions.append(AssessmentQuestion(organization_id=p.organization_id, position=pos, **qd.model_dump()))
        pos += 1
    for bid in data.bank_question_ids:
        src = get_scoped(db, AssessmentQuestion, bid, p, label="Question")
        a.questions.append(_copy_question(src, p.organization_id, pos))
        pos += 1
    db.flush()
    audit(
        db,
        action="assessment.created",
        entity_type="assessment",
        entity_id=a.id,
        principal=p,
        changes={"title": a.title, "questions": pos},
    )
    return a


def _copy_question(src: AssessmentQuestion, org_id: uuid.UUID, pos: int) -> AssessmentQuestion:
    return AssessmentQuestion(
        organization_id=org_id,
        kind=src.kind,
        prompt=src.prompt,
        options=list(src.options),
        correct_answer=src.correct_answer,
        rubric=src.rubric,
        competency=src.competency,
        difficulty=src.difficulty,
        points=src.points,
        position=pos,
        tags=list(src.tags),
    )


def generate(db: Session, data: GenerateAssessmentIn, p: Principal) -> Assessment:
    job = get_scoped(db, Job, data.job_id, p)
    skills = [r.name for r in job.requirements if r.kind == "skill"]
    if not skills:
        raise ValidationFailed("Job has no skill requirements to assess")
    bank = list(
        db.scalars(
            select(AssessmentQuestion).where(
                AssessmentQuestion.organization_id == p.organization_id, AssessmentQuestion.assessment_id.is_(None)
            )
        )
    )
    out = (
        AssessmentBuilderAgent()
        .run(
            AgentContext(db, p.organization_id, p.user_id),
            BuildInput(
                skills=skills,
                max_questions=data.max_questions,
                bank=[
                    BankQuestion(
                        id=q.id,
                        kind=q.kind,
                        competency=q.competency,
                        tags=q.tags,
                        difficulty=q.difficulty,
                        points=q.points,
                    )
                    for q in bank
                ],
            ),
            entity_type="job",
            entity_id=job.id,
        )
        .output
    )
    if not out.question_ids:
        raise ValidationFailed("No matching questions in the question bank; add questions tagged with job skills")
    return create(
        db,
        AssessmentIn(
            title=data.title or f"{job.title} assessment",
            kind=data.kind,
            job_id=job.id,
            bank_question_ids=out.question_ids,
            instructions=f"Covers: {', '.join(out.coverage)}",
        ),
        p,
    )


def invite(
    db: Session, app: Application, assessment: Assessment, p: Principal, expires_in_days: int
) -> tuple[AssessmentResult, str]:
    if app.stage != ApplicationStage.ASSESSMENT:
        raise InvalidTransition("Application must be in the assessment stage")
    if not assessment.is_active or not assessment.questions:
        raise ValidationFailed("Assessment is inactive or has no questions")
    if db.scalar(
        select(AssessmentResult).where(
            AssessmentResult.assessment_id == assessment.id, AssessmentResult.application_id == app.id
        )
    ):
        raise ConflictError("Candidate already invited to this assessment")
    token = new_opaque_token()
    now = utcnow()
    res = AssessmentResult(
        organization_id=p.organization_id,
        assessment_id=assessment.id,
        application_id=app.id,
        access_token_hash=token_digest(token),
        invited_at=now,
        expires_at=now + timedelta(days=expires_in_days),
    )
    db.add(res)
    db.flush()
    link = f"{get_settings().public_base_url}/assessment/{token}"
    queue_candidate_message(
        db,
        candidate=app.candidate,
        template_key="assessment_invitation",
        application_id=app.id,
        sent_by_id=p.user_id,
        variables={
            "job_title": app.job.title,
            "assessment_title": assessment.title,
            "duration": assessment.duration_minutes,
            "deadline": res.expires_at.date(),
            "link": link,
        },
    )
    audit(
        db,
        action="assessment.invited",
        entity_type="application",
        entity_id=app.id,
        principal=p,
        changes={"assessment_id": str(assessment.id)},
    )
    return res, link


def by_token(db: Session, token: str) -> AssessmentResult:
    res = db.scalar(select(AssessmentResult).where(AssessmentResult.access_token_hash == token_digest(token)))
    if not res:
        raise NotFoundError("Assessment link not found")
    if res.expires_at < utcnow() and res.status in (AssessmentResultStatus.INVITED, AssessmentResultStatus.IN_PROGRESS):
        res.status = AssessmentResultStatus.EXPIRED
    return res


def start(db: Session, res: AssessmentResult) -> None:
    if res.status == AssessmentResultStatus.INVITED:
        res.status, res.started_at = AssessmentResultStatus.IN_PROGRESS, utcnow()


def _score(db: Session, res: AssessmentResult, answers: dict, overrides: dict[str, float] | None) -> None:
    a = db.get(Assessment, res.assessment_id)
    assert a
    out = (
        AssessmentScoringAgent()
        .run(
            AgentContext(db, res.organization_id),
            ScoreInput(
                questions=[
                    QuestionForScoring(
                        id=str(q.id),
                        kind=q.kind,
                        points=q.points,
                        competency=q.competency,
                        correct_answer=q.correct_answer,
                        rubric=q.rubric,
                    )
                    for q in a.questions
                ],
                answers=answers,
                passing_pct=a.passing_score,
            ),
            entity_type="assessment_result",
            entity_id=res.id,
        )
        .output
    )
    per = {k: v.model_dump() for k, v in out.per_question.items()}
    if overrides:
        for qid, score in overrides.items():
            if qid not in per:
                raise ValidationFailed(f"Unknown question {qid}")
            if not 0 <= score <= per[qid]["max"]:
                raise ValidationFailed(f"Score for {qid} must be between 0 and {per[qid]['max']}")
            per[qid].update(score=score, needs_review=False, auto=False, note="Scored by reviewer")
    total = sum(v["score"] for v in per.values())
    max_total = sum(v["max"] for v in per.values()) or 1
    pct = round(100 * total / max_total, 1)
    needs_review = any(v["needs_review"] for v in per.values())
    res.answers, res.question_scores = answers, per
    res.score, res.max_score, res.percentage = round(total, 2), round(max_total, 2), pct
    res.competency_scores = out.competency_scores
    res.passed = None if needs_review else pct >= a.passing_score
    res.status = AssessmentResultStatus.SUBMITTED if needs_review else AssessmentResultStatus.SCORED


def submit(db: Session, res: AssessmentResult, answers: dict) -> AssessmentResult:
    if res.status not in (AssessmentResultStatus.INVITED, AssessmentResultStatus.IN_PROGRESS):
        raise InvalidTransition(f"Assessment cannot be submitted (status {res.status})")
    a = db.get(Assessment, res.assessment_id)
    assert a
    valid_ids = {str(q.id) for q in a.questions}
    clean = {k: v for k, v in answers.items() if k in valid_ids}
    for v in clean.values():
        if isinstance(v, str) and len(v) > 20000:
            raise ValidationFailed("Answer too long")
    res.submitted_at = utcnow()
    _score(db, res, clean, None)
    app = db.get(Application, res.application_id)
    assert app
    notify_users(
        db,
        res.organization_id,
        [app.recruiter_id],
        kind="assessment_submitted",
        title=f"Assessment submitted: {app.candidate.full_name}",
        link=f"/applications/{app.id}",
    )
    audit(
        db,
        action="assessment.submitted",
        entity_type="application",
        entity_id=app.id,
        organization_id=res.organization_id,
        actor_type=ActorType.CANDIDATE,
        actor_id=str(app.candidate_id),
        changes={"percentage": res.percentage, "status": res.status},
    )
    _advance_workflow(db, app, res)
    return res


def manual_score(
    db: Session, res: AssessmentResult, overrides: dict[str, float], feedback: str | None, p: Principal
) -> AssessmentResult:
    if res.status not in (AssessmentResultStatus.SUBMITTED, AssessmentResultStatus.SCORED):
        raise InvalidTransition("Only submitted assessments can be scored")
    _score(
        db,
        res,
        res.answers,
        {**{k: v["score"] for k, v in res.question_scores.items() if not v.get("needs_review")}, **overrides},
    )
    res.scored_by_id, res.candidate_feedback = p.user_id, feedback
    audit(
        db,
        action="assessment.scored",
        entity_type="assessment_result",
        entity_id=res.id,
        principal=p,
        changes={"overrides": overrides, "percentage": res.percentage},
    )
    app = db.get(Application, res.application_id)
    assert app
    _advance_workflow(db, app, res, principal=p)
    return res


def _advance_workflow(db: Session, app: Application, res: AssessmentResult, principal: Principal | None = None) -> None:
    from app.ai.orchestrator import Orchestrator

    event = "assessment.scored" if res.status == AssessmentResultStatus.SCORED else "assessment.needs_review"
    Orchestrator(db).handle(app, event, principal=principal)
    if (
        res.status == AssessmentResultStatus.SCORED
        and res.passed
        and principal is not None
        and app.stage == ApplicationStage.ASSESSMENT
    ):
        app_service.move_stage(
            db, app, ApplicationStage.INTERVIEW, principal=principal, reason=f"Assessment passed ({res.percentage}%)"
        )
