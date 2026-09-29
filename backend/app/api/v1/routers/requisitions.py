from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select

from app.api.deps import DB, IdempotencyKeyHeader, Paging, require, run_idempotent
from app.core.principal import Principal
from app.domain.enums import RequisitionStatus
from app.models.recruitment import HiringRequisition, Job
from app.schemas.common import DecisionIn, Page
from app.schemas.recruitment import (
    ApprovalWorkflowOut, JobOut, RequisitionDetail, RequisitionIn, RequisitionOut, RequisitionUpdate,
)
from app.services import approvals
from app.services import requisitions as svc
from app.services.common import get_scoped, paginate

router = APIRouter(prefix="/requisitions", tags=["Requisitions"])


def _detail(db, req: HiringRequisition) -> RequisitionDetail:  # type: ignore[no-untyped-def]
    wf = approvals.latest_workflow(db, "requisition", req.id)
    jobs = list(db.scalars(select(Job.id).where(Job.requisition_id == req.id)))
    return RequisitionDetail.model_validate(req).model_copy(update={
        "approval": ApprovalWorkflowOut.model_validate(wf) if wf else None, "job_ids": jobs})


@router.get("", response_model=Page[RequisitionOut])
def list_requisitions(
    db: DB, paging: Paging, p: Annotated[Principal, Depends(require("requisitions:read"))],
    status_: Annotated[RequisitionStatus | None, Query(alias="status")] = None, department_id: uuid.UUID | None = None,
    q: str | None = None, mine: bool = False,
) -> dict:
    stmt = select(HiringRequisition).where(HiringRequisition.organization_id == p.organization_id)
    if status_:
        stmt = stmt.where(HiringRequisition.status == status_)
    if department_id:
        stmt = stmt.where(HiringRequisition.department_id == department_id)
    if q:
        stmt = stmt.where(HiringRequisition.title.ilike(f"%{q}%") | HiringRequisition.reference.ilike(f"%{q}%"))
    if mine:
        stmt = stmt.where((HiringRequisition.requested_by_id == p.user_id) |
                          (HiringRequisition.hiring_manager_id == p.user_id) |
                          (HiringRequisition.recruiter_id == p.user_id))
    items, total = paginate(db, stmt, model=HiringRequisition, page=paging.page, page_size=paging.page_size,
                            sort=paging.sort, allowed_sorts={"created_at", "title", "status", "target_start_date"})
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}


@router.post("", response_model=RequisitionOut, status_code=status.HTTP_201_CREATED)
def create_requisition(data: RequisitionIn, db: DB,
                       p: Annotated[Principal, Depends(require("requisitions:create"))]) -> HiringRequisition:
    req = svc.create(db, data, p)
    db.commit()
    return req


@router.get("/{requisition_id}", response_model=RequisitionDetail)
def get_requisition(requisition_id: uuid.UUID, db: DB,
                    p: Annotated[Principal, Depends(require("requisitions:read"))]) -> RequisitionDetail:
    return _detail(db, get_scoped(db, HiringRequisition, requisition_id, p, label="Requisition"))


@router.patch("/{requisition_id}", response_model=RequisitionOut)
def update_requisition(requisition_id: uuid.UUID, data: RequisitionUpdate, db: DB,
                       p: Annotated[Principal, Depends(require("requisitions:update"))]) -> HiringRequisition:
    req = svc.update(db, get_scoped(db, HiringRequisition, requisition_id, p, label="Requisition"), data, p)
    db.commit()
    return req


@router.post("/{requisition_id}/submit", response_model=RequisitionDetail,
             summary="Validate with the Requisition Agent and start the approval workflow")
def submit_requisition(requisition_id: uuid.UUID, db: DB,
                       p: Annotated[Principal, Depends(require("requisitions:submit"))]) -> RequisitionDetail:
    req = get_scoped(db, HiringRequisition, requisition_id, p, label="Requisition")
    try:
        svc.submit(db, req, p)
    except Exception:
        db.commit()  # persist the AI validation report + execution log even when validation fails
        raise
    db.commit()
    return _detail(db, req)


@router.post("/{requisition_id}/decision", response_model=RequisitionDetail, summary="Approve or reject (current step)")
def decide_requisition(requisition_id: uuid.UUID, data: DecisionIn, db: DB, request: Request,
                       key: IdempotencyKeyHeader,
                       p: Annotated[Principal, Depends(require("requisitions:approve"))]) -> RequisitionDetail:
    req = get_scoped(db, HiringRequisition, requisition_id, p, label="Requisition")
    return run_idempotent(db, p, request, key, data.model_dump(),
                          lambda: _detail(db, svc.decide(db, req, p, data.decision == "approve", data.comment)))


@router.post("/{requisition_id}/jobs", response_model=JobOut, status_code=201,
             summary="Create a draft job; the Job Description Agent writes the JD and advert")
def create_job_from_requisition(requisition_id: uuid.UUID, db: DB,
                                p: Annotated[Principal, Depends(require("jobs:create"))]) -> Job:
    req = get_scoped(db, HiringRequisition, requisition_id, p, label="Requisition")
    job = svc.create_job(db, req, p)
    db.commit()
    return job
