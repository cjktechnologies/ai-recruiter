"""Onboarding handoff: HRIS payload, preboarding checklist, IT provisioning triggers."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents import OnboardingAgent
from app.ai.agents.base import AgentContext
from app.ai.agents.onboarding import OnboardingInput, is_tech_title
from app.core.errors import ExternalServiceError, InvalidTransition
from app.core.principal import Principal
from app.db.base import utcnow
from app.domain.enums import ApplicationStage, IntegrationKind, OfferStatus, OnboardingCategory, OnboardingTaskStatus
from app.integrations.hris import post_signed_webhook
from app.models.governance import Integration
from app.models.onboarding import OnboardingHandoff, OnboardingTask
from app.models.org import Department, User
from app.models.pipeline import Application
from app.models.selection import Offer
from app.schemas.pipeline import OnboardingTaskUpdate
from app.services.audit import audit, diff
from app.services.notify import notify_role, queue_candidate_message


def handoff(db: Session, app: Application, p: Principal) -> OnboardingHandoff:
    """Idempotent: repeated calls return the existing handoff (and retry a failed HRIS delivery)."""
    from app.ai.orchestrator import Orchestrator

    if app.stage != ApplicationStage.HIRED:
        raise InvalidTransition("Only hired candidates can be handed off to onboarding")
    existing = db.scalar(select(OnboardingHandoff).where(OnboardingHandoff.application_id == app.id))
    if existing and existing.status in ("sent", "done"):
        return existing
    offer = db.scalar(
        select(Offer)
        .where(Offer.application_id == app.id, Offer.status == OfferStatus.ACCEPTED)
        .order_by(Offer.version.desc())
        .limit(1)
    )
    if not offer or not offer.start_date:
        raise InvalidTransition("An accepted offer with a start date is required")
    cand, job = app.candidate, app.job
    manager = db.get(User, job.hiring_manager_id) if job.hiring_manager_id else None
    dept = db.get(Department, job.department_id) if job.department_id else None
    out = (
        OnboardingAgent()
        .run(
            AgentContext(db, p.organization_id, p.user_id),
            OnboardingInput(
                first_name=cand.first_name,
                last_name=cand.last_name,
                email=cand.email,
                job_title=offer.job_title,
                department=dept.name if dept else None,
                manager_email=manager.email if manager else None,
                location=job.location,
                employment_type=job.employment_type,
                start_date=offer.start_date,
                base_salary=str(offer.base_salary),
                currency=offer.currency,
                remote_policy=job.remote_policy,
                tech_role=is_tech_title(job.title),
            ),
            entity_type="application",
            entity_id=app.id,
        )
        .output
    )
    h = existing or OnboardingHandoff(
        organization_id=p.organization_id, application_id=app.id, offer_id=offer.id, initiated_by_id=p.user_id
    )
    h.payload = out.hris_payload | {"it_provisioning": out.it_provisioning}
    if not existing:
        db.add(h)
        for t in out.tasks:
            db.add(
                OnboardingTask(
                    organization_id=p.organization_id,
                    application_id=app.id,
                    title=t.title,
                    category=t.category,
                    due_date=t.due_date,
                    description=t.description,
                    assignee_id=manager.id if manager and t.category == OnboardingCategory.TEAM else None,
                )
            )
    integ = db.scalar(
        select(Integration).where(
            Integration.organization_id == p.organization_id,
            Integration.kind == IntegrationKind.HRIS_WEBHOOK,
            Integration.is_enabled.is_(True),
        )
    )
    if integ and integ.config.get("url") and integ.secret:
        try:
            res = post_signed_webhook(
                integ.config["url"], json.loads(integ.secret)["signing_secret"], "employee.hired", h.payload
            )
            h.status, h.sent_at, h.hris_employee_id, h.last_error = "sent", utcnow(), res.external_id, None
            integ.last_sync_at, integ.last_error = utcnow(), None
        except ExternalServiceError as exc:
            h.status, h.last_error = "failed", exc.detail
            integ.last_error = exc.detail
    else:
        h.status, h.sent_at = "done", utcnow()  # no HRIS configured: internal checklist is the system of record
    notify_role(
        db,
        p.organization_id,
        "hr_manager",
        kind="onboarding_started",
        title=f"Onboarding started: {cand.full_name}",
        link=f"/onboarding?application={app.id}",
    )
    if not existing:
        queue_candidate_message(
            db,
            candidate=cand,
            template_key="welcome",
            application_id=app.id,
            force=True,
            variables={"start_date": offer.start_date.isoformat()},
        )
    db.flush()
    audit(
        db,
        action="onboarding.handoff",
        entity_type="application",
        entity_id=app.id,
        principal=p,
        changes={"status": h.status, "tasks": len(out.tasks)},
    )
    if h.status in ("sent", "done"):
        Orchestrator(db).handle(app, "onboarding.handed_off", principal=p)
    return h


def update_task(db: Session, task: OnboardingTask, data: OnboardingTaskUpdate, p: Principal) -> OnboardingTask:
    updates = data.model_dump(exclude_unset=True)
    changes = diff(task, updates)
    if task.status == OnboardingTaskStatus.DONE and not task.completed_at:
        task.completed_at = utcnow()
    audit(
        db,
        action="onboarding_task.updated",
        entity_type="onboarding_task",
        entity_id=task.id,
        principal=p,
        changes=changes,
    )
    return task
