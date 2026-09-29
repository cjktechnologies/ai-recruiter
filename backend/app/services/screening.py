"""Screening: runs the Screening Agent and records the recruiter's review/override."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents import ScreeningAgent
from app.ai.agents.base import AgentContext
from app.ai.agents.matching import CandidateSkillIn, MatchInput, RequirementIn
from app.ai.agents.screening import KnockoutQuestion, ScreeningInput
from app.core.errors import ConflictError, ValidationFailed
from app.core.principal import Principal
from app.db.base import utcnow
from app.domain.enums import (
    ActorType,
    AgentName,
    ApplicationStage,
    ConsentPurpose,
    DocumentKind,
    ParseStatus,
    Recommendation,
    ReviewStatus,
)
from app.models.candidates import CandidateDocument
from app.models.governance import AIRecommendation
from app.models.org import Organization
from app.models.pipeline import Application, ScreeningResult
from app.services import applications as app_service
from app.services.audit import audit
from app.services.candidates import has_consent
from app.services.notify import notify_users

POSITIVE = {Recommendation.YES, Recommendation.STRONG_YES}
NEGATIVE = {Recommendation.NO, Recommendation.STRONG_NO}


def build_input(db: Session, app: Application) -> ScreeningInput:
    job, cand = app.job, app.candidate
    doc = db.scalar(
        select(CandidateDocument)
        .where(
            CandidateDocument.candidate_id == cand.id,
            CandidateDocument.kind == DocumentKind.CV,
            CandidateDocument.parse_status == ParseStatus.PARSED,
        )
        .order_by(CandidateDocument.created_at.desc())
        .limit(1)
    )
    parsed = (doc.parsed_data or {}) if doc else {}
    cfg = job.screening_config or {}
    education = [f"{e.get('degree')} {e.get('field') or ''}".strip() for e in (cand.education or [])]
    return ScreeningInput(
        job_title=job.title,
        match_input=MatchInput(
            requirements=[
                RequirementIn(
                    kind=r.kind, name=r.name, min_years=r.min_years, is_mandatory=r.is_mandatory, weight=r.weight
                )
                for r in job.requirements
            ],
            job_embedding=job.embedding,
            candidate_skills=[
                CandidateSkillIn(name=cs.skill.name, years=cs.years, evidence=cs.evidence) for cs in cand.skills
            ],
            candidate_years=cand.years_experience,
            candidate_embedding=cand.embedding,
            candidate_location=cand.location,
            candidate_languages=cand.languages or [],
            candidate_education=education,
            candidate_certifications=parsed.get("certifications", []),
        ),
        knockout_questions=[KnockoutQuestion(**q) for q in cfg.get("knockout_questions", [])],
        answers=app.screening_answers or {},
        candidate_text=(doc.parsed_text or "") if doc else (app.cover_letter or ""),
        security_flags=(doc.security_flags if doc else []),
        thresholds=cfg.get("thresholds") or {"strong_yes": 80, "yes": 65, "maybe": 45},
    )


def run(db: Session, app: Application, *, triggered_by: Principal | None, workflow_run_id=None) -> ScreeningResult:
    org = db.get(Organization, app.organization_id)
    policy = (org.settings if org else {}) or {}
    if not policy.get("ai_screening_enabled", True):
        raise ValidationFailed("AI screening is disabled for this organization")
    if policy.get("require_consent_for_ai", True) and not has_consent(
        db, app.candidate, ConsentPurpose.AI_ASSISTED_SCREENING
    ):
        raise ValidationFailed("Candidate has not consented to AI-assisted screening; screen manually")
    if app.stage == ApplicationStage.APPLIED:
        app_service.move_stage(
            db,
            app,
            ApplicationStage.SCREENING,
            principal=triggered_by,
            actor=ActorType.AGENT,
            reason="AI screening started",
        )
    outcome = ScreeningAgent().run(
        AgentContext(db, app.organization_id, triggered_by.user_id if triggered_by else None, workflow_run_id),
        build_input(db, app),
        entity_type="application",
        entity_id=app.id,
    )
    o = outcome.output
    result = ScreeningResult(
        organization_id=app.organization_id,
        application_id=app.id,
        rule_results=[r.model_dump() for r in o.rule_results],
        eligible=o.eligible,
        score=o.score,
        facts=[f.model_dump() for f in o.facts],
        interpretations=[i.model_dump() for i in o.interpretations],
        summary=o.summary,
        recommendation=o.recommendation,
        agent_execution_id=outcome.execution.id,
    )
    db.add(result)
    app.match_score = o.score
    db.add(
        AIRecommendation(
            organization_id=app.organization_id,
            execution_id=outcome.execution.id,
            agent=AgentName.SCREENING,
            entity_type="application",
            entity_id=app.id,
            kind="screening_outcome",
            recommendation=o.recommendation,
            confidence=round(o.score / 100, 2),
            facts=result.facts,
            interpretations=result.interpretations,
            explanation=o.summary,
        )
    )
    if app.stage == ApplicationStage.SCREENING:
        app_service.move_stage(
            db,
            app,
            ApplicationStage.SCREENED,
            principal=triggered_by,
            actor=ActorType.AGENT,
            reason="AI screening complete; awaiting recruiter review",
        )
    notify_users(
        db,
        app.organization_id,
        [app.recruiter_id],
        kind="screening_ready",
        title=f"Screening ready for review: {app.candidate.full_name}",
        link=f"/applications/{app.id}",
    )
    db.flush()
    return result


def latest(db: Session, app: Application) -> ScreeningResult | None:
    return db.scalar(
        select(ScreeningResult)
        .where(ScreeningResult.application_id == app.id)
        .order_by(ScreeningResult.created_at.desc())
        .limit(1)
    )


def review(
    db: Session,
    result: ScreeningResult,
    app: Application,
    p: Principal,
    *,
    decision: str,
    next_stage: ApplicationStage | None,
    override_reason: str | None,
    rejection_reason: str | None,
) -> ScreeningResult:
    if result.review_status != ReviewStatus.PENDING_REVIEW:
        raise ConflictError("Screening result already reviewed")
    rec = Recommendation(result.recommendation)
    overriding = (
        (decision == "advance" and rec in NEGATIVE)
        or (decision == "reject" and rec in POSITIVE)
        or (decision == "advance" and not result.eligible)
    )
    if overriding and not (override_reason and len(override_reason.strip()) >= 10):
        raise ValidationFailed("Overriding the AI recommendation requires a documented reason (min 10 chars)")
    result.review_status = ReviewStatus.OVERRIDDEN if overriding else ReviewStatus.ACCEPTED
    result.reviewed_by_id, result.reviewed_at = p.user_id, utcnow()
    result.reviewer_decision, result.override_reason = decision, override_reason
    for ai_rec in db.scalars(
        select(AIRecommendation).where(AIRecommendation.execution_id == result.agent_execution_id)
    ):
        ai_rec.review_status, ai_rec.reviewed_by_id, ai_rec.reviewed_at = result.review_status, p.user_id, utcnow()
        ai_rec.review_comment = override_reason
    audit(
        db,
        action="screening.reviewed",
        entity_type="application",
        entity_id=app.id,
        principal=p,
        changes={
            "decision": decision,
            "ai_recommendation": rec,
            "overridden": overriding,
            "override_reason": override_reason,
        },
    )
    from app.ai.orchestrator import Orchestrator

    if decision == "advance":
        target = next_stage or ApplicationStage.INTERVIEW
        if target not in (ApplicationStage.ASSESSMENT, ApplicationStage.INTERVIEW):
            raise ValidationFailed("next_stage must be assessment or interview")
        app_service.move_stage(db, app, target, principal=p, reason="Recruiter advanced after screening review")
        Orchestrator(db).handle(app, "screening.reviewed", principal=p, payload={"next": target})
    elif decision == "reject":
        app_service.reject(db, app, p, rejection_reason or "Not progressing after screening", notify_candidate=True)
    return result
