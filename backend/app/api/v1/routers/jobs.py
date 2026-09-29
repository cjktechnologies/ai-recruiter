from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select

from app.ai.agents import JobDescriptionAgent, SourcingAgent
from app.ai.agents.base import AgentContext
from app.ai.agents.job_description import JDInput
from app.ai.agents.matching import CandidateSkillIn
from app.ai.agents.matching import RequirementIn as MatchReq
from app.ai.agents.sourcing import PoolCandidate, SourcingInput
from app.api.deps import DB, Paging, require
from app.core.principal import Principal
from app.domain.enums import ConsentPurpose, JobStatus
from app.models.candidates import Candidate, ConsentRecord
from app.models.org import Department, Organization
from app.models.pipeline import Application
from app.models.recruitment import Job, TalentPool, talent_pool_members
from app.schemas.common import Page
from app.schemas.recruitment import JobIn, JobOut, JobUpdate, RequirementIn, TalentPoolIn, TalentPoolOut
from app.services import applications as app_service
from app.services import jobs as svc
from app.services.audit import audit
from app.services.common import get_scoped, paginate

router = APIRouter(tags=["Jobs & Sourcing"])


@router.get("/jobs", response_model=Page[JobOut])
def list_jobs(
    db: DB,
    paging: Paging,
    p: Annotated[Principal, Depends(require("jobs:read"))],
    status_: Annotated[JobStatus | None, Query(alias="status")] = None,
    department_id: uuid.UUID | None = None,
    q: str | None = None,
    recruiter_id: uuid.UUID | None = None,
    hiring_manager_id: uuid.UUID | None = None,
) -> dict:
    stmt = select(Job).where(Job.organization_id == p.organization_id)
    if status_:
        stmt = stmt.where(Job.status == status_)
    if department_id:
        stmt = stmt.where(Job.department_id == department_id)
    if recruiter_id:
        stmt = stmt.where(Job.recruiter_id == recruiter_id)
    if hiring_manager_id:
        stmt = stmt.where(Job.hiring_manager_id == hiring_manager_id)
    if q:
        stmt = stmt.where(Job.title.ilike(f"%{q}%"))
    items, total = paginate(
        db,
        stmt,
        model=Job,
        page=paging.page,
        page_size=paging.page_size,
        sort=paging.sort,
        allowed_sorts={"created_at", "title", "status", "published_at"},
    )
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(data: JobIn, db: DB, p: Annotated[Principal, Depends(require("jobs:create"))]) -> Job:
    job = svc.create(db, data, p)
    db.commit()
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("jobs:read"))]) -> Job:
    return get_scoped(db, Job, job_id, p)


@router.patch("/jobs/{job_id}", response_model=JobOut)
def update_job(
    job_id: uuid.UUID, data: JobUpdate, db: DB, p: Annotated[Principal, Depends(require("jobs:update"))]
) -> Job:
    job = svc.update(db, get_scoped(db, Job, job_id, p), data, p)
    db.commit()
    return job


@router.put("/jobs/{job_id}/requirements", response_model=JobOut)
def set_requirements(
    job_id: uuid.UUID, data: list[RequirementIn], db: DB, p: Annotated[Principal, Depends(require("jobs:update"))]
) -> Job:
    job = svc.set_requirements(db, get_scoped(db, Job, job_id, p), data, p)
    db.commit()
    return job


@router.post(
    "/jobs/{job_id}/generate-description",
    response_model=dict,
    summary="Job Description Agent: draft/optimize JD + advert (not saved until you PATCH)",
)
def generate_description(job_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("jobs:update"))]) -> dict:
    job = get_scoped(db, Job, job_id, p)
    org = db.get(Organization, p.organization_id)
    dept = db.get(Department, job.department_id) if job.department_id else None
    out = JobDescriptionAgent().run(
        AgentContext(db, p.organization_id, p.user_id),
        JDInput(
            company_name=org.name if org else "",
            title=job.title,
            department=dept.name if dept else None,
            location=job.location,
            remote_policy=job.remote_policy,
            employment_type=job.employment_type,
            required_skills=[r.name for r in job.requirements if r.kind == "skill" and r.is_mandatory],
            preferred_skills=[r.name for r in job.requirements if r.kind == "skill" and not r.is_mandatory],
            min_years_experience=next(
                (int(r.min_years) for r in job.requirements if r.kind == "experience" and r.min_years), None
            ),
            salary_min=float(job.salary_min) if job.salary_min else None,
            salary_max=float(job.salary_max) if job.salary_max else None,
            currency=job.currency,
            show_salary=job.show_salary,
            existing_description=job.description,
        ),
        entity_type="job",
        entity_id=job.id,
    )
    db.commit()
    return out.output.model_dump(mode="json") | {"execution_id": str(out.execution.id)}


@router.post("/jobs/{job_id}/publish", response_model=JobOut)
def publish_job(job_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("jobs:publish"))]) -> Job:
    job = svc.publish(db, get_scoped(db, Job, job_id, p), p)
    db.commit()
    return job


@router.post("/jobs/{job_id}/close", response_model=JobOut)
def close_job(
    job_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("jobs:publish"))], pause: bool = False
) -> Job:
    job = svc.close(db, get_scoped(db, Job, job_id, p), p, pause=pause)
    db.commit()
    return job


@router.get("/jobs/{job_id}/pipeline", response_model=dict, summary="Stage counts and cards for the kanban board")
def job_pipeline(job_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("applications:read"))]) -> dict:
    job = get_scoped(db, Job, job_id, p)
    apps = db.scalars(
        select(Application).where(Application.job_id == job.id).order_by(Application.match_score.desc().nulls_last())
    )
    cards = [
        {
            "id": str(a.id),
            "candidate_id": str(a.candidate_id),
            "candidate_name": a.candidate.full_name,
            "stage": a.stage,
            "status": a.status,
            "match_score": a.match_score,
            "source": a.source,
            "applied_at": a.applied_at.isoformat(),
            "stage_changed_at": a.stage_changed_at.isoformat(),
        }
        for a in apps
    ]
    return {
        "job_id": str(job.id),
        "counts": app_service.pipeline_counts(db, p.organization_id, job.id),
        "applications": cards,
    }


@router.post(
    "/jobs/{job_id}/sourcing",
    response_model=dict,
    summary="Talent Sourcing Agent: rank consented talent-pool candidates for this job",
)
def source_candidates(
    job_id: uuid.UUID,
    db: DB,
    p: Annotated[Principal, Depends(require("candidates:read"))],
    pool_id: uuid.UUID | None = None,
    limit: int = 20,
) -> dict:
    job = get_scoped(db, Job, job_id, p)
    consented = select(ConsentRecord.candidate_id).where(
        ConsentRecord.purpose == ConsentPurpose.TALENT_POOL,
        ConsentRecord.granted.is_(True),
        ConsentRecord.organization_id == p.organization_id,
    )
    applied = select(Application.candidate_id).where(Application.job_id == job.id)
    stmt = select(Candidate).where(
        Candidate.organization_id == p.organization_id,
        Candidate.anonymized_at.is_(None),
        Candidate.do_not_contact.is_(False),
        Candidate.id.in_(consented),
        Candidate.id.not_in(applied),
    )
    if pool_id:
        get_scoped(db, TalentPool, pool_id, p)
        stmt = stmt.where(
            Candidate.id.in_(select(talent_pool_members.c.candidate_id).where(talent_pool_members.c.pool_id == pool_id))
        )
    pool = list(db.scalars(stmt.limit(2000)))
    out = (
        SourcingAgent()
        .run(
            AgentContext(db, p.organization_id, p.user_id),
            SourcingInput(
                requirements=[
                    MatchReq(
                        kind=r.kind, name=r.name, min_years=r.min_years, is_mandatory=r.is_mandatory, weight=r.weight
                    )
                    for r in job.requirements
                ],
                job_embedding=job.embedding,
                approved_channels=job.publish_channels,
                limit=min(limit, 100),
                pool=[
                    PoolCandidate(
                        candidate_id=c.id,
                        skills=[CandidateSkillIn(name=s.skill.name) for s in c.skills],
                        years=c.years_experience,
                        embedding=c.embedding,
                        location=c.location,
                    )
                    for c in pool
                ],
            ),
            entity_type="job",
            entity_id=job.id,
        )
        .output
    )
    names = {c.id: c for c in pool}
    db.commit()
    return {
        "recommended_channels": out.recommended_channels,
        "candidates": [
            {
                **r.model_dump(mode="json"),
                "full_name": names[r.candidate_id].full_name,
                "headline": names[r.candidate_id].headline,
            }
            for r in out.candidates
        ],
    }


@router.get("/talent-pools", response_model=list[TalentPoolOut])
def list_pools(db: DB, p: Annotated[Principal, Depends(require("candidates:read"))]) -> list[dict]:
    pools = db.scalars(
        select(TalentPool).where(TalentPool.organization_id == p.organization_id).order_by(TalentPool.name)
    )
    counts: dict[uuid.UUID, int] = dict(
        db.execute(select(talent_pool_members.c.pool_id, func.count()).group_by(talent_pool_members.c.pool_id)).all()
    )
    return [
        TalentPoolOut.model_validate(tp).model_copy(update={"member_count": counts.get(tp.id, 0)}).model_dump()
        for tp in pools
    ]


@router.post("/talent-pools", response_model=TalentPoolOut, status_code=201)
def create_pool(
    data: TalentPoolIn, db: DB, p: Annotated[Principal, Depends(require("candidates:update"))]
) -> TalentPool:
    pool = TalentPool(organization_id=p.organization_id, owner_id=p.user_id, **data.model_dump())
    db.add(pool)
    db.flush()
    audit(db, action="talent_pool.created", entity_type="talent_pool", entity_id=pool.id, principal=p)
    db.commit()
    return pool


@router.post("/talent-pools/{pool_id}/members", response_model=dict)
def add_pool_members(
    pool_id: uuid.UUID,
    candidate_ids: list[uuid.UUID],
    db: DB,
    p: Annotated[Principal, Depends(require("candidates:update"))],
) -> dict:
    pool = get_scoped(db, TalentPool, pool_id, p)
    existing: set[uuid.UUID] = set(
        db.scalars(select(talent_pool_members.c.candidate_id).where(talent_pool_members.c.pool_id == pool.id))
    )
    added = 0
    for cid in candidate_ids:
        get_scoped(db, Candidate, cid, p)
        if cid not in existing:
            db.execute(talent_pool_members.insert().values(pool_id=pool.id, candidate_id=cid))
            added += 1
    audit(
        db,
        action="talent_pool.members_added",
        entity_type="talent_pool",
        entity_id=pool.id,
        principal=p,
        changes={"added": added},
    )
    db.commit()
    return {"added": added}
