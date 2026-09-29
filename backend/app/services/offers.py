"""Offers: AI drafting within compensation bands, approval chain, sending, candidate response."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.agents import OfferAgent
from app.ai.agents.base import AgentContext
from app.ai.agents.offer import Band, OfferInput
from app.core.config import get_settings
from app.core.errors import ConflictError, InvalidTransition, NotFoundError, PermissionDenied, ValidationFailed
from app.core.principal import Principal
from app.core.security import new_opaque_token, token_digest
from app.db.base import utcnow
from app.domain.enums import ActorType, ApplicationStage, ApprovalStatus, OfferStatus, RequisitionStatus
from app.models.org import Organization
from app.models.pipeline import Application
from app.models.recruitment import CompensationBand, HiringRequisition
from app.models.selection import CandidateEvaluation, Offer, OfferApproval
from app.schemas.pipeline import OfferDraftIn, OfferUpdate
from app.services import applications as app_service
from app.services.approvals import can_act_on_step
from app.services.audit import audit, diff
from app.services.notify import notify_role, notify_users, queue_candidate_message


def _band(db: Session, app: Application) -> CompensationBand | None:
    job = app.job
    if not job.job_level:
        return None
    bands = list(db.scalars(select(CompensationBand).where(CompensationBand.organization_id == app.organization_id,
                                                           CompensationBand.job_level == job.job_level)))
    for b in bands:
        if b.department_id == job.department_id and (not b.location or b.location == job.location):
            return b
    return bands[0] if bands else None


def draft(db: Session, app: Application, data: OfferDraftIn, p: Principal) -> Offer:
    if app.stage != ApplicationStage.OFFER:
        raise InvalidTransition("Application must be in the offer stage")
    active = db.scalar(select(Offer).where(Offer.application_id == app.id, Offer.status.in_([
        OfferStatus.DRAFT, OfferStatus.PENDING_APPROVAL, OfferStatus.APPROVED, OfferStatus.SENT])))
    if active:
        raise ConflictError("An active offer already exists; withdraw it to create a new version")
    band = _band(db, app)
    req = db.get(HiringRequisition, app.job.requisition_id) if app.job.requisition_id else None
    ev = db.scalar(select(CandidateEvaluation).where(CandidateEvaluation.application_id == app.id)
                   .order_by(CandidateEvaluation.created_at.desc()).limit(1))
    org = db.get(Organization, p.organization_id)
    start = data.start_date or (utcnow() + timedelta(days=30)).date()
    expires = utcnow() + timedelta(days=data.expires_in_days)
    out = OfferAgent().run(
        AgentContext(db, p.organization_id, p.user_id),
        OfferInput(company=org.name if org else "", candidate_first_name=app.candidate.first_name,
                   job_title=app.job.title,
                   band=Band(id=str(band.id), min_salary=band.min_salary, max_salary=band.max_salary,
                             currency=band.currency, max_bonus_pct=band.max_bonus_pct, benefits=band.benefits)
                   if band else None,
                   requisition_budget_max=req.budget_max if req else app.job.salary_max,
                   evaluation_score=ev.overall_score if ev else None, requested_salary=data.base_salary,
                   start_date=start, expires_on=expires.date()),
        entity_type="application", entity_id=app.id,
    ).output
    version = (db.scalar(select(func.max(Offer.version)).where(Offer.application_id == app.id)) or 0) + 1
    offer = Offer(
        organization_id=p.organization_id, application_id=app.id, version=version, job_title=app.job.title,
        base_salary=out.base_salary, currency=out.currency if band else (app.job.currency or out.currency),
        bonus_pct=out.bonus_pct, equity=data.equity, benefits=out.benefits, start_date=start, expires_at=expires,
        compensation_band_id=band.id if band else None, within_band=out.within_band, letter_body=out.letter_body,
        created_by_id=p.user_id,
        approvals=[OfferApproval(step_order=i, approver_role=r) for i, r in enumerate(out.approval_chain, start=1)],
    )
    db.add(offer)
    db.flush()
    audit(db, action="offer.drafted", entity_type="offer", entity_id=offer.id, principal=p,
          changes={"salary": out.base_salary, "within_band": out.within_band, "chain": out.approval_chain,
                   "rationale": out.rationale})
    return offer


def update(db: Session, offer: Offer, data: OfferUpdate, p: Principal) -> Offer:
    if offer.status != OfferStatus.DRAFT:
        raise InvalidTransition("Only draft offers can be edited")
    changes = diff(offer, data.model_dump(exclude_unset=True))
    if "base_salary" in changes and offer.compensation_band_id:
        band = db.get(CompensationBand, offer.compensation_band_id)
        assert band
        offer.within_band = band.min_salary <= offer.base_salary <= band.max_salary
        roles = [a.approver_role for a in offer.approvals]
        if not offer.within_band and "finance_approver" not in roles:
            offer.approvals.append(OfferApproval(step_order=len(roles) + 1, approver_role="finance_approver"))
    audit(db, action="offer.updated", entity_type="offer", entity_id=offer.id, principal=p, changes=changes)
    return offer


def submit(db: Session, offer: Offer, p: Principal) -> Offer:
    from app.ai.orchestrator import Orchestrator

    if offer.status != OfferStatus.DRAFT:
        raise InvalidTransition("Only draft offers can be submitted")
    offer.status = OfferStatus.PENDING_APPROVAL
    first = offer.approvals[0]
    notify_role(db, offer.organization_id, first.approver_role, kind="offer_approval",
                title=f"Approve offer: {offer.job_title}", link=f"/offers/{offer.id}")
    app = db.get(Application, offer.application_id)
    assert app
    Orchestrator(db).handle(app, "offer.submitted", principal=p)
    audit(db, action="offer.submitted", entity_type="offer", entity_id=offer.id, principal=p)
    return offer


def decide(db: Session, offer: Offer, p: Principal, approve: bool, comment: str | None) -> Offer:
    from app.ai.orchestrator import Orchestrator

    if offer.status != OfferStatus.PENDING_APPROVAL:
        raise InvalidTransition("Offer is not pending approval")
    step = next((a for a in offer.approvals if a.status == ApprovalStatus.PENDING), None)
    if step is None:
        raise ConflictError("No pending approval step")
    if not can_act_on_step(step, p):  # type: ignore[arg-type]
        raise PermissionDenied(f"This step requires the '{step.approver_role}' role")
    if offer.created_by_id == p.user_id and "org_admin" not in p.roles:
        raise PermissionDenied("Segregation of duties: the offer author cannot approve it")
    step.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    step.decided_by_id, step.decided_at, step.comment = p.user_id, utcnow(), comment
    app = db.get(Application, offer.application_id)
    assert app
    if not approve:
        # Changes requested: back to draft; the whole chain restarts after edits.
        offer.status = OfferStatus.DRAFT
        for a in offer.approvals:
            a.status = ApprovalStatus.PENDING
        notify_users(db, offer.organization_id, [offer.created_by_id], kind="offer_rejected",
                     title=f"Offer changes requested: {offer.job_title}", body=comment, link=f"/offers/{offer.id}")
        Orchestrator(db).handle(app, "offer.rejected", principal=p)
    elif all(a.status == ApprovalStatus.APPROVED for a in offer.approvals):
        offer.status = OfferStatus.APPROVED
        notify_users(db, offer.organization_id, [offer.created_by_id, app.recruiter_id], kind="offer_approved",
                     title=f"Offer approved: {offer.job_title}", link=f"/offers/{offer.id}")
        Orchestrator(db).handle(app, "offer.approved", principal=p)
    else:
        nxt = next(a for a in offer.approvals if a.status == ApprovalStatus.PENDING)
        notify_role(db, offer.organization_id, nxt.approver_role, kind="offer_approval",
                    title=f"Approve offer: {offer.job_title}", link=f"/offers/{offer.id}")
    audit(db, action="offer.approval_decision", entity_type="offer", entity_id=offer.id, principal=p,
          changes={"approve": approve, "step": step.approver_role, "comment": comment})
    return offer


def send(db: Session, offer: Offer, p: Principal) -> tuple[Offer, str]:
    from app.ai.orchestrator import Orchestrator

    if offer.status != OfferStatus.APPROVED:
        raise InvalidTransition("Only fully approved offers can be sent")
    if offer.expires_at and offer.expires_at < utcnow():
        raise ValidationFailed("Offer expiry date has passed; update it first")
    token = new_opaque_token()
    offer.response_token_hash = token_digest(token)
    offer.status, offer.sent_at = OfferStatus.SENT, utcnow()
    app = db.get(Application, offer.application_id)
    assert app
    link = f"{get_settings().public_base_url}/offer/{token}"
    queue_candidate_message(db, candidate=app.candidate, template_key="offer_sent", application_id=app.id,
                            sent_by_id=p.user_id, force=True, variables={
                                "job_title": offer.job_title, "link": link,
                                "deadline": offer.expires_at.date() if offer.expires_at else "the stated date"})
    Orchestrator(db).handle(app, "offer.sent", principal=p)
    audit(db, action="offer.sent", entity_type="offer", entity_id=offer.id, principal=p)
    return offer, link


def by_token(db: Session, token: str) -> Offer:
    offer = db.scalar(select(Offer).where(Offer.response_token_hash == token_digest(token)))
    if not offer:
        raise NotFoundError("Offer not found")
    return offer


def respond(db: Session, offer: Offer, accept: bool, reason: str | None, p: Principal | None = None) -> Offer:
    from app.ai.orchestrator import Orchestrator

    if offer.status != OfferStatus.SENT:
        raise InvalidTransition(f"Offer cannot be responded to (status {offer.status})")
    if offer.expires_at and offer.expires_at < utcnow():
        offer.status = OfferStatus.EXPIRED
        raise InvalidTransition("This offer has expired")
    offer.status = OfferStatus.ACCEPTED if accept else OfferStatus.DECLINED
    offer.responded_at, offer.decline_reason = utcnow(), None if accept else reason
    app = db.get(Application, offer.application_id)
    assert app
    actor = ActorType.USER if p else ActorType.CANDIDATE
    audit(db, action="offer.accepted" if accept else "offer.declined", entity_type="offer", entity_id=offer.id,
          principal=p, organization_id=offer.organization_id, actor_type=actor,
          actor_id=str(p.user_id) if p else str(app.candidate_id), changes={"reason": reason})
    notify_users(db, offer.organization_id, [offer.created_by_id, app.recruiter_id, app.job.hiring_manager_id],
                 kind="offer_response", title=f"Offer {'accepted' if accept else 'declined'}: "
                                              f"{app.candidate.full_name}", link=f"/offers/{offer.id}")
    if accept:
        app_service.record_hire(db, app, actor=actor, principal=p, reason="Offer accepted")
        _maybe_fill_requisition(db, app)
        Orchestrator(db).handle(app, "offer.accepted", principal=p)
    else:
        Orchestrator(db).handle(app, "offer.declined", principal=p)
    return offer


def _maybe_fill_requisition(db: Session, app: Application) -> None:
    if not app.job.requisition_id:
        return
    req = db.get(HiringRequisition, app.job.requisition_id)
    if not req:
        return
    db.flush()
    hired = db.scalar(select(func.count()).select_from(Application).where(
        Application.job_id == app.job_id, Application.stage == ApplicationStage.HIRED)) or 0
    if hired >= req.headcount:
        req.status, req.filled_at = RequisitionStatus.FILLED, utcnow()


def withdraw(db: Session, offer: Offer, p: Principal, reason: str) -> Offer:
    if offer.status in (OfferStatus.ACCEPTED, OfferStatus.DECLINED, OfferStatus.WITHDRAWN):
        raise InvalidTransition("Offer can no longer be withdrawn")
    offer.status, offer.decline_reason, offer.response_token_hash = OfferStatus.WITHDRAWN, reason, None
    audit(db, action="offer.withdrawn", entity_type="offer", entity_id=offer.id, principal=p,
          changes={"reason": reason})
    return offer


def expire_due(db: Session) -> int:
    n = 0
    for offer in db.scalars(select(Offer).where(Offer.status == OfferStatus.SENT, Offer.expires_at < utcnow())):
        offer.status = OfferStatus.EXPIRED
        n += 1
    return n


def default_expiry(days: int) -> datetime:
    return datetime.combine((utcnow() + timedelta(days=days)).date(), time(23, 59), tzinfo=utcnow().tzinfo)

