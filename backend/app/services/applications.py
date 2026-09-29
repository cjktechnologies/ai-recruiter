"""Applications and pipeline stage transitions (with human-in-the-loop gate enforcement)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApprovalRequired, ConflictError, InvalidTransition, PermissionDenied
from app.core.principal import Principal
from app.db.base import utcnow
from app.domain.enums import ActorType, ApplicationStage, ApplicationStatus, JobStatus
from app.domain.pipeline import can_transition, gate_for
from app.models.candidates import Candidate
from app.models.pipeline import Application, ApplicationStageHistory
from app.models.recruitment import Job
from app.services.audit import audit
from app.services.notify import notify_users, queue_candidate_message

STAGE_LABEL = {
    ApplicationStage.SCREENING: "screening",
    ApplicationStage.SCREENED: "review",
    ApplicationStage.ASSESSMENT: "assessment",
    ApplicationStage.INTERVIEW: "interview",
    ApplicationStage.EVALUATION: "evaluation",
    ApplicationStage.SELECTION: "final review",
    ApplicationStage.VERIFICATION: "reference and background check",
    ApplicationStage.OFFER: "offer",
}
CANDIDATE_VISIBLE = {ApplicationStage.ASSESSMENT, ApplicationStage.INTERVIEW, ApplicationStage.OFFER}


def create(
    db: Session,
    *,
    job: Job,
    candidate: Candidate,
    source: str,
    p: Principal | None,
    cover_letter: str | None = None,
    answers: dict | None = None,
) -> Application:
    if job.status != JobStatus.PUBLISHED and p is None:
        raise InvalidTransition("This job is not accepting applications")
    if job.status == JobStatus.CLOSED:
        raise InvalidTransition("This job is closed")
    if candidate.anonymized_at:
        raise ConflictError("Candidate data has been erased")
    if db.scalar(select(Application).where(Application.job_id == job.id, Application.candidate_id == candidate.id)):
        raise ConflictError("Candidate has already applied to this job")
    app = Application(
        organization_id=job.organization_id,
        job_id=job.id,
        candidate_id=candidate.id,
        source=source,
        cover_letter=cover_letter,
        screening_answers=answers or {},
        recruiter_id=job.recruiter_id,
        job=job,
        candidate=candidate,
    )
    db.add(app)
    db.flush()
    db.add(
        ApplicationStageHistory(
            application_id=app.id,
            from_stage=None,
            to_stage=ApplicationStage.APPLIED,
            changed_by_id=p.user_id if p else None,
            actor_type=ActorType.USER if p else ActorType.CANDIDATE,
            reason=f"source={source}",
        )
    )
    queue_candidate_message(
        db,
        candidate=candidate,
        template_key="application_received",
        variables={"job_title": job.title},
        application_id=app.id,
    )
    notify_users(
        db,
        job.organization_id,
        [job.recruiter_id],
        kind="new_application",
        title=f"New application: {candidate.full_name} → {job.title}",
        link=f"/applications/{app.id}",
    )
    audit(
        db,
        action="application.created",
        entity_type="application",
        entity_id=app.id,
        principal=p,
        organization_id=job.organization_id,
        changes={"job_id": str(job.id), "source": source},
    )
    return app


def move_stage(
    db: Session,
    app: Application,
    to_stage: ApplicationStage,
    *,
    principal: Principal | None,
    actor: ActorType = ActorType.USER,
    reason: str | None = None,
    notify: bool = True,
) -> Application:
    """Single choke point for every stage change. Agents cannot pass human gates."""
    current = ApplicationStage(app.stage)
    if current == to_stage and to_stage != ApplicationStage.INTERVIEW:
        return app
    if not can_transition(current, to_stage):
        raise InvalidTransition(f"Cannot move application from {current} to {to_stage}")
    gate = gate_for(current, to_stage)
    if gate:
        if actor != ActorType.USER or principal is None:
            raise ApprovalRequired(f"{gate.reason} (requires '{gate.permission}')")
        if not principal.has(gate.permission):
            raise PermissionDenied(f"{gate.reason}; you lack '{gate.permission}'")
    app.stage = to_stage
    app.stage_changed_at = utcnow()
    if to_stage == ApplicationStage.REJECTED:
        app.status = ApplicationStatus.REJECTED
    elif to_stage == ApplicationStage.WITHDRAWN:
        app.status = ApplicationStatus.WITHDRAWN
    elif to_stage == ApplicationStage.HIRED:
        app.status, app.hired_at = ApplicationStatus.HIRED, utcnow()
    db.add(
        ApplicationStageHistory(
            application_id=app.id,
            from_stage=current,
            to_stage=to_stage,
            changed_by_id=principal.user_id if principal and actor == ActorType.USER else None,
            actor_type=actor,
            reason=reason,
        )
    )
    if notify and to_stage in CANDIDATE_VISIBLE:
        queue_candidate_message(
            db,
            candidate=app.candidate,
            template_key="status_update",
            application_id=app.id,
            variables={
                "job_title": app.job.title,
                "stage": STAGE_LABEL.get(to_stage, to_stage),
                "extra": "We'll be in touch with details shortly.",
            },
        )
    audit(
        db,
        action="application.stage_changed",
        entity_type="application",
        entity_id=app.id,
        principal=principal,
        organization_id=app.organization_id,
        actor_type=actor,
        actor_id=None if actor == ActorType.USER else actor.value,
        changes={"from": current, "to": to_stage, "reason": reason},
    )
    return app


def record_hire(db: Session, app: Application, *, actor: ActorType, principal: Principal | None, reason: str) -> None:
    """OFFER → HIRED is gated on an explicit acceptance: either the candidate's own signed response via the
    offer link, or a human recording it. Agents can never call this."""
    if actor == ActorType.AGENT:
        raise ApprovalRequired("Only the candidate or an authorised human can record an acceptance")
    if app.stage != ApplicationStage.OFFER:
        raise InvalidTransition("Application is not at the offer stage")
    app.stage, app.status = ApplicationStage.HIRED, ApplicationStatus.HIRED
    app.stage_changed_at = app.hired_at = utcnow()
    db.add(
        ApplicationStageHistory(
            application_id=app.id,
            from_stage=ApplicationStage.OFFER,
            to_stage=ApplicationStage.HIRED,
            actor_type=actor,
            changed_by_id=principal.user_id if principal else None,
            reason=reason,
        )
    )
    audit(
        db,
        action="application.hired",
        entity_type="application",
        entity_id=app.id,
        principal=principal,
        organization_id=app.organization_id,
        actor_type=actor,
        changes={"reason": reason},
    )


def reject(db: Session, app: Application, p: Principal, reason: str, notify_candidate: bool) -> Application:
    move_stage(db, app, ApplicationStage.REJECTED, principal=p, reason=reason, notify=False)
    app.rejection_reason = reason
    if notify_candidate:
        queue_candidate_message(
            db,
            candidate=app.candidate,
            template_key="rejection",
            application_id=app.id,
            variables={"job_title": app.job.title},
            sent_by_id=p.user_id,
        )
    from app.ai.orchestrator import Orchestrator

    Orchestrator(db).handle(app, "application.closed", principal=p)
    return app


def withdraw(db: Session, app: Application, p: Principal | None, reason: str | None = None) -> Application:
    move_stage(
        db,
        app,
        ApplicationStage.WITHDRAWN,
        principal=p,
        actor=ActorType.CANDIDATE if p is None or p.is_candidate else ActorType.USER,
        reason=reason or "withdrawn",
        notify=False,
    )
    from app.ai.orchestrator import Orchestrator

    Orchestrator(db).handle(app, "application.closed", principal=p)
    return app


def pipeline_counts(db: Session, org_id: uuid.UUID, job_id: uuid.UUID | None = None) -> dict[str, int]:
    stmt = select(Application.stage, func.count()).where(Application.organization_id == org_id)
    if job_id:
        stmt = stmt.where(Application.job_id == job_id)
    return {str(stage): int(n) for stage, n in db.execute(stmt.group_by(Application.stage))}
