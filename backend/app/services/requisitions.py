"""Hiring requisitions: drafting, AI validation, multi-step approval, conversion to jobs."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.agents import JobDescriptionAgent, RequisitionAgent
from app.ai.agents.base import AgentContext
from app.ai.agents.job_description import JDInput
from app.ai.agents.requisition import RequisitionInput
from app.core.errors import ConflictError, InvalidTransition, ValidationFailed
from app.core.principal import Principal
from app.db.base import utcnow
from app.domain.enums import ApprovalStatus, RequirementKind, RequisitionStatus
from app.models.org import Department, Organization, User
from app.models.recruitment import CompensationBand, HiringRequisition, Job
from app.schemas.recruitment import JobIn, RequirementIn, RequisitionIn, RequisitionUpdate, ScreeningConfig
from app.services import approvals
from app.services.audit import audit, diff
from app.services.common import get_scoped
from app.services.notify import notify_role, notify_users


def _next_reference(db: Session, org_id: uuid.UUID) -> str:
    year = date.today().year
    n = (
        db.scalar(
            select(func.count()).select_from(HiringRequisition).where(HiringRequisition.organization_id == org_id)
        )
        or 0
    )
    return f"REQ-{year}-{n + 1:04d}"


def _check_users(db: Session, p: Principal, *ids: uuid.UUID | None) -> None:
    for uid in ids:
        if uid:
            u = db.get(User, uid)
            if not u or u.organization_id != p.organization_id:
                raise ValidationFailed("Referenced user not found in organization")


def create(db: Session, data: RequisitionIn, p: Principal) -> HiringRequisition:
    if data.department_id:
        get_scoped(db, Department, data.department_id, p)
    _check_users(db, p, data.hiring_manager_id, data.recruiter_id)
    req = HiringRequisition(
        organization_id=p.organization_id,
        reference=_next_reference(db, p.organization_id),
        requested_by_id=p.user_id,
        **data.model_dump(),
    )
    if req.hiring_manager_id is None and "hiring_manager" in p.roles:
        req.hiring_manager_id = p.user_id
    db.add(req)
    db.flush()
    audit(
        db,
        action="requisition.created",
        entity_type="requisition",
        entity_id=req.id,
        principal=p,
        changes={"reference": req.reference, "title": req.title},
    )
    return req


def update(db: Session, req: HiringRequisition, data: RequisitionUpdate, p: Principal) -> HiringRequisition:
    updates = data.model_dump(exclude_unset=True)
    new_status = updates.pop("status", None)
    if updates and req.status not in (RequisitionStatus.DRAFT, RequisitionStatus.REJECTED, RequisitionStatus.ON_HOLD):
        raise InvalidTransition("Only draft, rejected or on-hold requisitions can be edited; resubmit afterwards")
    _check_users(db, p, updates.get("hiring_manager_id"), updates.get("recruiter_id"))
    changes = diff(req, updates)
    if new_status:
        allowed = {RequisitionStatus.ON_HOLD, RequisitionStatus.CANCELLED, RequisitionStatus.DRAFT}
        if new_status not in allowed:
            raise InvalidTransition("Status can only be set to draft, on_hold or cancelled directly")
        if req.status == RequisitionStatus.FILLED:
            raise InvalidTransition("Filled requisitions cannot change status")
        changes["status"] = [req.status, new_status]
        req.status = new_status
    if changes and req.status == RequisitionStatus.REJECTED:
        req.status = RequisitionStatus.DRAFT
    audit(db, action="requisition.updated", entity_type="requisition", entity_id=req.id, principal=p, changes=changes)
    return req


def _band_for(db: Session, req: HiringRequisition) -> CompensationBand | None:
    if not req.job_level:
        return None
    stmt = select(CompensationBand).where(
        CompensationBand.organization_id == req.organization_id, CompensationBand.job_level == req.job_level
    )
    bands = list(db.scalars(stmt))
    for b in bands:
        if b.department_id == req.department_id:
            return b
    return bands[0] if bands else None


def submit(db: Session, req: HiringRequisition, p: Principal) -> HiringRequisition:
    if req.status not in (RequisitionStatus.DRAFT, RequisitionStatus.REJECTED, RequisitionStatus.ON_HOLD):
        raise InvalidTransition(f"Cannot submit a requisition in status {req.status}")
    band = _band_for(db, req)
    dept = db.get(Department, req.department_id) if req.department_id else None
    outcome = RequisitionAgent().run(
        AgentContext(db, p.organization_id, p.user_id),
        RequisitionInput(
            title=req.title,
            justification=req.justification,
            headcount=req.headcount,
            employment_type=req.employment_type,
            job_level=req.job_level,
            department=dept.name if dept else None,
            location=req.location,
            required_skills=req.required_skills,
            preferred_skills=req.preferred_skills,
            responsibilities=req.responsibilities,
            min_years_experience=req.min_years_experience,
            budget_min=req.budget_min,
            budget_max=req.budget_max,
            currency=req.currency,
            target_start_date=req.target_start_date,
            band_min=band.min_salary if band else None,
            band_max=band.max_salary if band else None,
        ),
        entity_type="requisition",
        entity_id=req.id,
    )
    req.ai_validation = outcome.output.model_dump(mode="json")
    if not outcome.output.valid:
        db.flush()
        raise ValidationFailed("Requisition failed validation", extra={"issues": req.ai_validation["issues"]})
    assignees = {"hiring_manager": req.hiring_manager_id} if req.hiring_manager_id != p.user_id else {}
    approvals.start_workflow(
        db,
        org_id=p.organization_id,
        entity_type="requisition",
        entity_id=req.id,
        roles=outcome.output.approval_route,
        created_by=p.user_id,
        assignees=assignees,
    )
    req.status = RequisitionStatus.PENDING_APPROVAL
    first_role = outcome.output.approval_route[0]
    if assignees.get(first_role):
        notify_users(
            db,
            p.organization_id,
            [assignees[first_role]],
            kind="approval_requested",
            title=f"Approve requisition {req.reference}",
            link=f"/requisitions/{req.id}",
        )
    else:
        notify_role(
            db,
            p.organization_id,
            first_role,
            kind="approval_requested",
            title=f"Approve requisition {req.reference}",
            link=f"/requisitions/{req.id}",
        )
    audit(
        db,
        action="requisition.submitted",
        entity_type="requisition",
        entity_id=req.id,
        principal=p,
        changes={"approval_route": outcome.output.approval_route},
    )
    return req


def decide(db: Session, req: HiringRequisition, p: Principal, approve: bool, comment: str | None) -> HiringRequisition:
    if req.status != RequisitionStatus.PENDING_APPROVAL:
        raise InvalidTransition("Requisition is not awaiting approval")
    wf = approvals.latest_workflow(db, "requisition", req.id)
    if not wf:
        raise ConflictError("No approval workflow found")
    approvals.decide(db, wf, p, approve, comment)
    if wf.status == ApprovalStatus.APPROVED:
        req.status, req.approved_at = RequisitionStatus.APPROVED, utcnow()
        notify_users(
            db,
            p.organization_id,
            [req.requested_by_id, req.recruiter_id, req.hiring_manager_id],
            kind="requisition_approved",
            title=f"Requisition {req.reference} approved",
            link=f"/requisitions/{req.id}",
        )
    elif wf.status == ApprovalStatus.REJECTED:
        req.status = RequisitionStatus.REJECTED
        notify_users(
            db,
            p.organization_id,
            [req.requested_by_id],
            kind="requisition_rejected",
            title=f"Requisition {req.reference} rejected",
            body=comment,
            link=f"/requisitions/{req.id}",
        )
    else:
        nxt = next(s for s in wf.steps if s.step_order == wf.current_step)
        notify_role(
            db,
            p.organization_id,
            nxt.approver_role,
            kind="approval_requested",
            title=f"Approve requisition {req.reference}",
            link=f"/requisitions/{req.id}",
        )
    audit(
        db,
        action="requisition.approval_decision",
        entity_type="requisition",
        entity_id=req.id,
        principal=p,
        changes={"approve": approve, "comment": comment, "workflow_status": wf.status},
    )
    return req


def create_job(db: Session, req: HiringRequisition, p: Principal) -> Job:
    from app.services import jobs as job_service

    if req.status != RequisitionStatus.APPROVED:
        raise InvalidTransition("Only approved requisitions can be converted to jobs")
    org = db.get(Organization, p.organization_id)
    dept = db.get(Department, req.department_id) if req.department_id else None
    band = _band_for(db, req)
    jd = (
        JobDescriptionAgent()
        .run(
            AgentContext(db, p.organization_id, p.user_id),
            JDInput(
                company_name=org.name if org else "",
                title=req.title,
                department=dept.name if dept else None,
                location=req.location,
                remote_policy=req.remote_policy,
                employment_type=req.employment_type,
                responsibilities=req.responsibilities,
                required_skills=req.required_skills,
                preferred_skills=req.preferred_skills,
                min_years_experience=req.min_years_experience,
                salary_min=float(req.budget_min) if req.budget_min else None,
                salary_max=float(req.budget_max) if req.budget_max else None,
                currency=req.currency,
                benefits=band.benefits if band else [],
            ),
            entity_type="requisition",
            entity_id=req.id,
        )
        .output
    )
    job = job_service.create(
        db,
        JobIn(
            title=req.title,
            requisition_id=req.id,
            department_id=req.department_id,
            description=jd.description,
            advertisement=jd.advertisement,
            location=req.location,
            remote_policy=req.remote_policy,
            employment_type=req.employment_type,
            job_level=req.job_level,
            salary_min=req.budget_min,
            salary_max=req.budget_max,
            currency=req.currency,
            hiring_manager_id=req.hiring_manager_id,
            recruiter_id=req.recruiter_id or p.user_id,
            screening_config=ScreeningConfig(),
            requirements=[
                RequirementIn(
                    kind=RequirementKind(r.kind),
                    name=r.name,
                    is_mandatory=r.is_mandatory,
                    weight=r.weight,
                    min_years=r.min_years,
                )
                for r in jd.requirements
            ],
        ),
        p,
    )
    return job
