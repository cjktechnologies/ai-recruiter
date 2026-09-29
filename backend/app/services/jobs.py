"""Jobs: CRUD, requirements, embeddings, publishing and closing."""

from __future__ import annotations

import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embeddings import get_embedder
from app.core.errors import InvalidTransition, ValidationFailed
from app.core.principal import Principal
from app.db.base import utcnow
from app.domain.enums import JobStatus, RequisitionStatus
from app.models.recruitment import HiringRequisition, Job, JobRequirement
from app.schemas.recruitment import JobIn, JobUpdate, RequirementIn
from app.services.audit import audit, diff
from app.services.common import get_scoped


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:180] or "job"


def refresh_embedding(job: Job) -> None:
    skills = [r.name for r in job.requirements if r.kind == "skill"]
    job.embedding = get_embedder().embed(f"{job.title}\n{job.description}", skills=skills)


def _set_requirements(job: Job, reqs: list[RequirementIn]) -> None:
    job.requirements.clear()
    for i, r in enumerate(reqs):
        job.requirements.append(JobRequirement(position=i, **r.model_dump()))


def create(db: Session, data: JobIn, p: Principal) -> Job:
    if data.salary_min and data.salary_max and data.salary_min > data.salary_max:
        raise ValidationFailed("salary_min must be <= salary_max")
    if data.requisition_id:
        req = get_scoped(db, HiringRequisition, data.requisition_id, p, label="Requisition")
        if req.status != RequisitionStatus.APPROVED:
            raise InvalidTransition("Jobs can only be linked to approved requisitions")
    payload = data.model_dump(exclude={"requirements", "screening_config"})
    job = Job(organization_id=p.organization_id, slug=f"{slugify(data.title)}-{secrets.token_hex(3)}",
              screening_config=data.screening_config.model_dump(mode="json"), **payload)
    _set_requirements(job, data.requirements)
    refresh_embedding(job)
    db.add(job)
    db.flush()
    audit(db, action="job.created", entity_type="job", entity_id=job.id, principal=p, changes={"title": job.title})
    return job


def update(db: Session, job: Job, data: JobUpdate, p: Principal) -> Job:
    if job.status == JobStatus.CLOSED:
        raise InvalidTransition("Closed jobs cannot be edited")
    updates = data.model_dump(exclude_unset=True)
    if "screening_config" in updates and updates["screening_config"] is not None:
        updates["screening_config"] = data.screening_config.model_dump(mode="json")  # type: ignore[union-attr]
    changes = diff(job, updates)
    if {"title", "description"} & changes.keys():
        refresh_embedding(job)
    audit(db, action="job.updated", entity_type="job", entity_id=job.id, principal=p, changes=changes)
    return job


def set_requirements(db: Session, job: Job, reqs: list[RequirementIn], p: Principal) -> Job:
    _set_requirements(job, reqs)
    refresh_embedding(job)
    db.flush()
    audit(db, action="job.requirements_set", entity_type="job", entity_id=job.id, principal=p,
          changes={"requirements": [r.model_dump() for r in reqs]})
    return job


def publish(db: Session, job: Job, p: Principal) -> Job:
    if job.status not in (JobStatus.DRAFT, JobStatus.PAUSED):
        raise InvalidTransition(f"Cannot publish a job in status {job.status}")
    if job.requisition_id:
        req = db.get(HiringRequisition, job.requisition_id)
        if not req or req.status != RequisitionStatus.APPROVED:
            raise InvalidTransition("The linked requisition must be approved before publishing")
    if len(job.description.strip()) < 50:
        raise ValidationFailed("Job description is too short to publish")
    if not job.requirements:
        raise ValidationFailed("Add at least one requirement before publishing")
    job.status, job.published_at = JobStatus.PUBLISHED, job.published_at or utcnow()
    audit(db, action="job.published", entity_type="job", entity_id=job.id, principal=p,
          changes={"channels": job.publish_channels})
    return job


def close(db: Session, job: Job, p: Principal, *, pause: bool = False) -> Job:
    if job.status == JobStatus.CLOSED:
        raise InvalidTransition("Job already closed")
    job.status = JobStatus.PAUSED if pause else JobStatus.CLOSED
    audit(db, action="job.paused" if pause else "job.closed", entity_type="job", entity_id=job.id, principal=p)
    return job


def public_jobs(db: Session, org_id) -> list[Job]:  # type: ignore[no-untyped-def]
    now = utcnow()
    return [j for j in db.scalars(select(Job).where(Job.organization_id == org_id, Job.status == JobStatus.PUBLISHED)
                                  .order_by(Job.published_at.desc()))
            if not j.closes_at or j.closes_at > now]
