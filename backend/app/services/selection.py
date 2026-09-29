"""Evaluation, comparison, selection approval and verification (references / background checks)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents import EvaluationAgent
from app.ai.agents.base import AgentContext
from app.ai.agents.evaluation import AssessmentIn as EvalAssessment
from app.ai.agents.evaluation import EvaluationInput, ScorecardIn as EvalScorecard
from app.core.config import get_settings
from app.core.errors import ConflictError, InvalidTransition, NotFoundError, ValidationFailed
from app.core.principal import Principal
from app.core.security import new_opaque_token, token_digest
from app.db.base import utcnow
from app.domain.enums import (
    ActorType, AgentName, ApplicationStage, AssessmentResultStatus, EvaluationDecision, InterviewStatus,
    VerificationStatus,
)
from app.models.assessments import Assessment, AssessmentResult
from app.models.governance import AIRecommendation
from app.models.interviews import Interview, InterviewScorecard
from app.models.org import Organization, User
from app.models.pipeline import Application
from app.models.selection import BackgroundCheck, CandidateEvaluation, CandidateReference
from app.schemas.pipeline import BackgroundCheckIn, BackgroundCheckUpdate, ReferenceIn
from app.services import applications as app_service
from app.services import screening as screening_service
from app.services.audit import audit
from app.services.notify import notify_role, notify_users

DEFAULT_REFERENCE_QUESTIONS = [
    {"id": "relationship", "question": "How do you know the candidate and for how long?"},
    {"id": "strengths", "question": "What are the candidate's main professional strengths?"},
    {"id": "development", "question": "In which areas could the candidate develop further?"},
    {"id": "rehire", "question": "Would you work with the candidate again? (yes/no)"},
]


def gather_evidence(db: Session, app: Application) -> EvaluationInput:
    scr = screening_service.latest(db, app)
    results = list(db.scalars(select(AssessmentResult).where(
        AssessmentResult.application_id == app.id,
        AssessmentResult.status.in_([AssessmentResultStatus.SCORED, AssessmentResultStatus.SUBMITTED]))))
    interviews = [i for i in db.scalars(select(Interview).where(Interview.application_id == app.id))
                  if i.status != InterviewStatus.CANCELLED]
    cards = list(db.scalars(select(InterviewScorecard).where(
        InterviewScorecard.interview_id.in_([i.id for i in interviews]),
        InterviewScorecard.submitted_at.is_not(None)))) if interviews else []
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_([c.interviewer_id for c in cards])))}
    return EvaluationInput(
        job_title=app.job.title,
        screening_score=scr.score if scr else None,
        screening_recommendation=scr.recommendation if scr else None,
        screening_reviewer_decision=scr.reviewer_decision if scr else None,
        assessments=[EvalAssessment(title=(db.get(Assessment, r.assessment_id).title  # type: ignore[union-attr]
                                           if db.get(Assessment, r.assessment_id) else "Assessment"),
                                    percentage=r.percentage, passed=r.passed, competency_scores=r.competency_scores)
                     for r in results],
        scorecards=[EvalScorecard(interviewer=names.get(c.interviewer_id, "interviewer"),
                                  overall_rating=c.overall_rating, recommendation=c.recommendation,
                                  ratings=c.ratings) for c in cards],
        expected_interviewers=sum(len(i.interviewers) for i in interviews if i.status != InterviewStatus.NO_SHOW),
    )


def run_evaluation(db: Session, app: Application, p: Principal | None, workflow_run_id=None) -> CandidateEvaluation:  # type: ignore[no-untyped-def]
    if app.stage not in (ApplicationStage.INTERVIEW, ApplicationStage.EVALUATION):
        raise InvalidTransition("Evaluation requires the interview or evaluation stage")
    evidence = gather_evidence(db, app)
    outcome = EvaluationAgent().run(AgentContext(db, app.organization_id, p.user_id if p else None, workflow_run_id),
                                    evidence, entity_type="application", entity_id=app.id)
    o = outcome.output
    ev = CandidateEvaluation(
        organization_id=app.organization_id, application_id=app.id, evidence=evidence.model_dump(mode="json"),
        competency_matrix=o.competency_matrix, overall_score=o.overall_score, ai_recommendation=o.recommendation,
        ai_rationale=o.rationale, risks=o.risks, agent_execution_id=outcome.execution.id,
    )
    db.add(ev)
    db.add(AIRecommendation(
        organization_id=app.organization_id, execution_id=outcome.execution.id, agent=AgentName.EVALUATION,
        entity_type="application", entity_id=app.id, kind="selection_recommendation",
        recommendation=o.recommendation, confidence=round(o.overall_score / 100, 2),
        facts=[{"statement": f"{c}: mean {v['mean']} over {v['n']} rating(s)", "evidence": None, "source": "scorecards"}
               for c, v in o.competency_matrix.items()],
        interpretations=[{"kind": "rationale", "text": o.rationale, "ai_generated": o.ai_generated}]
        + [{"kind": "risk", "text": r, "ai_generated": False} for r in o.risks],
        explanation=o.rationale,
    ))
    if app.stage == ApplicationStage.INTERVIEW:
        app_service.move_stage(db, app, ApplicationStage.EVALUATION, principal=p, actor=ActorType.AGENT,
                               reason="All interview feedback received; evaluation compiled")
    notify_users(db, app.organization_id, [app.job.hiring_manager_id, app.recruiter_id], kind="evaluation_ready",
                 title=f"Evaluation ready: {app.candidate.full_name}", link=f"/applications/{app.id}")
    db.flush()
    return ev


def decide_evaluation(db: Session, ev: CandidateEvaluation, app: Application, p: Principal,
                      decision: EvaluationDecision, rationale: str) -> CandidateEvaluation:
    from app.ai.orchestrator import Orchestrator

    if ev.decision:
        raise ConflictError("Evaluation already decided")
    if app.stage != ApplicationStage.EVALUATION:
        raise InvalidTransition("Application is not in evaluation")
    ev.decision, ev.decided_by_id, ev.decided_at, ev.decision_rationale = decision, p.user_id, utcnow(), rationale
    for rec in db.scalars(select(AIRecommendation).where(AIRecommendation.execution_id == ev.agent_execution_id)):
        agrees = (decision == EvaluationDecision.ADVANCE_TO_SELECTION) == (rec.recommendation in ("yes", "strong_yes"))
        rec.review_status = "accepted" if agrees else "overridden"
        rec.reviewed_by_id, rec.reviewed_at, rec.review_comment = p.user_id, utcnow(), rationale
    audit(db, action="evaluation.decided", entity_type="application", entity_id=app.id, principal=p,
          changes={"decision": decision, "ai_recommendation": ev.ai_recommendation, "rationale": rationale})
    if decision == EvaluationDecision.ADVANCE_TO_SELECTION:
        app_service.move_stage(db, app, ApplicationStage.SELECTION, principal=p, reason=rationale)
        Orchestrator(db).handle(app, "evaluation.advanced", principal=p)
        notify_role(db, app.organization_id, "hr_manager", kind="selection_approval",
                    title=f"Approve selection: {app.candidate.full_name}", link=f"/applications/{app.id}")
    elif decision == EvaluationDecision.REJECT:
        app_service.reject(db, app, p, rationale[:300], notify_candidate=True)
    else:
        app_service.move_stage(db, app, ApplicationStage.INTERVIEW, principal=p, reason="More interviews requested")
        Orchestrator(db).handle(app, "evaluation.more_interviews", principal=p)
    return ev


def approve_selection(db: Session, app: Application, p: Principal, approve: bool, comment: str | None,
                      skip_verification: bool) -> Application:
    from app.ai.orchestrator import Orchestrator

    if app.stage != ApplicationStage.SELECTION:
        raise InvalidTransition("Application is not awaiting selection approval")
    ev = db.scalar(select(CandidateEvaluation).where(CandidateEvaluation.application_id == app.id)
                   .order_by(CandidateEvaluation.created_at.desc()).limit(1))
    if ev and ev.decided_by_id == p.user_id and "org_admin" not in p.roles:
        raise ValidationFailed("Segregation of duties: selection must be approved by someone other than the decider")
    audit(db, action="selection.decision", entity_type="application", entity_id=app.id, principal=p,
          changes={"approve": approve, "comment": comment, "skip_verification": skip_verification})
    if not approve:
        return app_service.reject(db, app, p, comment or "Selection not approved", notify_candidate=True)
    target = ApplicationStage.OFFER if skip_verification else ApplicationStage.VERIFICATION
    app_service.move_stage(db, app, target, principal=p, reason=comment or "Selection approved")
    Orchestrator(db).handle(app, "selection.approved_offer" if skip_verification else "selection.approved_verify",
                            principal=p)
    return app


def comparison(db: Session, app_ids: list[uuid.UUID], p: Principal) -> list[dict]:
    out = []
    for aid in app_ids[:10]:
        app = db.get(Application, aid)
        if not app or app.organization_id != p.organization_id:
            raise NotFoundError("Application not found")
        ev = db.scalar(select(CandidateEvaluation).where(CandidateEvaluation.application_id == aid)
                       .order_by(CandidateEvaluation.created_at.desc()).limit(1))
        scr = screening_service.latest(db, app)
        evidence = gather_evidence(db, app)
        out.append({
            "application_id": str(aid), "candidate": app.candidate.full_name, "stage": app.stage,
            "match_score": app.match_score, "screening_recommendation": scr.recommendation if scr else None,
            "assessment_pct": [a.percentage for a in evidence.assessments],
            "interview_overall": [s.overall_rating for s in evidence.scorecards],
            "evaluation_score": ev.overall_score if ev else None,
            "ai_recommendation": ev.ai_recommendation if ev else None,
            "competencies": ev.competency_matrix if ev else {}, "risks": ev.risks if ev else [],
            "decision": ev.decision if ev else None,
        })
    return out


def _require_verification(app: Application) -> None:
    if app.stage not in (ApplicationStage.VERIFICATION, ApplicationStage.SELECTION, ApplicationStage.OFFER):
        raise InvalidTransition("Verification is only available after selection")


def add_reference(db: Session, app: Application, data: ReferenceIn, p: Principal) -> tuple[CandidateReference, str | None]:
    _require_verification(app)
    token = new_opaque_token() if data.send_request else None
    ref = CandidateReference(
        organization_id=p.organization_id, application_id=app.id, referee_name=data.referee_name,
        referee_email=data.referee_email.lower(), referee_phone=data.referee_phone,
        relationship_to_candidate=data.relationship_to_candidate, company=data.company,
        questionnaire=DEFAULT_REFERENCE_QUESTIONS, requested_at=utcnow(),
        access_token_hash=token_digest(token) if token else None,
    )
    db.add(ref)
    db.flush()
    link = None
    if token:
        from app.integrations.messaging import get_email_sender
        from app.services.notify import render_template

        org = db.get(Organization, p.organization_id)
        link = f"{get_settings().public_base_url}/reference/{token}"
        subject, body = render_template("reference_request", {
            "referee_name": data.referee_name, "candidate_name": app.candidate.full_name,
            "job_title": app.job.title, "company": org.name if org else "", "link": link})
        get_email_sender().send(to=ref.referee_email, subject=subject, body=body)
    audit(db, action="reference.requested", entity_type="application", entity_id=app.id, principal=p,
          changes={"referee": data.referee_name})
    return ref, link


def reference_by_token(db: Session, token: str) -> CandidateReference:
    ref = db.scalar(select(CandidateReference).where(CandidateReference.access_token_hash == token_digest(token)))
    if not ref or ref.requested_at < utcnow() - timedelta(days=30):
        raise NotFoundError("Reference link not found or expired")
    return ref


def submit_reference(db: Session, ref: CandidateReference, responses: dict, decline: bool) -> CandidateReference:
    if ref.status in (VerificationStatus.COMPLETED, VerificationStatus.DECLINED):
        raise ConflictError("Reference already submitted")
    allowed = {q["id"] for q in ref.questionnaire}
    ref.responses = {k: str(v)[:4000] for k, v in responses.items() if k in allowed}
    ref.status = VerificationStatus.DECLINED if decline else VerificationStatus.COMPLETED
    ref.completed_at = utcnow()
    ref.access_token_hash = None  # single use
    app = db.get(Application, ref.application_id)
    assert app
    notify_users(db, ref.organization_id, [app.recruiter_id], kind="reference_received",
                 title=f"Reference received for {app.candidate.full_name}", link=f"/applications/{app.id}")
    audit(db, action="reference.completed", entity_type="application", entity_id=app.id,
          organization_id=ref.organization_id, actor_type=ActorType.SYSTEM, changes={"declined": decline})
    _check_verification_complete(db, app)
    return ref


def request_background_check(db: Session, app: Application, data: BackgroundCheckIn, p: Principal) -> BackgroundCheck:
    _require_verification(app)
    if not data.consent_confirmed:
        raise ValidationFailed("Candidate consent for background checks is required")
    bc = BackgroundCheck(organization_id=p.organization_id, application_id=app.id, provider=data.provider,
                         check_types=data.check_types, consent_obtained_at=utcnow(), requested_by_id=p.user_id,
                         requested_at=utcnow())
    db.add(bc)
    db.flush()
    audit(db, action="background_check.requested", entity_type="application", entity_id=app.id, principal=p,
          changes={"provider": data.provider, "types": data.check_types})
    return bc


def update_background_check(db: Session, bc: BackgroundCheck, data: BackgroundCheckUpdate, p: Principal | None
                            ) -> BackgroundCheck:
    bc.status, bc.result, bc.result_detail = data.status, data.result, data.result_detail
    if data.status in (VerificationStatus.COMPLETED, VerificationStatus.FAILED):
        bc.completed_at = utcnow()
    app = db.get(Application, bc.application_id)
    assert app
    audit(db, action="background_check.updated", entity_type="application", entity_id=app.id, principal=p,
          organization_id=bc.organization_id, changes={"status": data.status, "result": data.result})
    if data.result == "adverse":
        # Adverse results always go to a human (e.g. pre-adverse action process); never auto-reject.
        notify_role(db, bc.organization_id, "hr_manager", kind="background_check_adverse",
                    title=f"Adverse background check: {app.candidate.full_name}", link=f"/applications/{app.id}")
    _check_verification_complete(db, app)
    return bc


def _check_verification_complete(db: Session, app: Application) -> None:
    from app.ai.orchestrator import Orchestrator

    refs = list(db.scalars(select(CandidateReference).where(CandidateReference.application_id == app.id)))
    checks = list(db.scalars(select(BackgroundCheck).where(BackgroundCheck.application_id == app.id)))
    open_items = [r for r in refs if r.status in (VerificationStatus.REQUESTED, VerificationStatus.IN_PROGRESS)] + \
        [c for c in checks if c.status in (VerificationStatus.REQUESTED, VerificationStatus.IN_PROGRESS)]
    adverse = any(c.result == "adverse" for c in checks)
    if (refs or checks) and not open_items and not adverse and app.stage == ApplicationStage.VERIFICATION:
        app_service.move_stage(db, app, ApplicationStage.OFFER, principal=None, actor=ActorType.SYSTEM,
                               reason="Verification complete")
        Orchestrator(db).handle(app, "verification.completed")
        notify_users(db, app.organization_id, [app.recruiter_id], kind="verification_complete",
                     title=f"Verification complete: {app.candidate.full_name} — ready for offer",
                     link=f"/applications/{app.id}")

