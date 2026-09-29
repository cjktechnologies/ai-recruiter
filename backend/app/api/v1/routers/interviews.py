from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.api.deps import DB, require
from app.core.errors import PermissionDenied
from app.core.principal import Principal
from app.models.interviews import Interview, Interviewer, InterviewScorecard, InterviewTemplate
from app.models.pipeline import Application
from app.schemas.pipeline import (
    CancelIn,
    InterviewIn,
    InterviewOut,
    InterviewTemplateIn,
    InterviewTemplateOut,
    InterviewUpdate,
    ScorecardIn,
    ScorecardOut,
    SlotOut,
    SlotRequestIn,
    TranscriptIn,
)
from app.services import interviews as svc
from app.services.common import get_scoped

router = APIRouter(tags=["Interviews & Scheduling"])


def _out(iv: Interview, db) -> dict:
    app = db.get(Application, iv.application_id)
    return (
        InterviewOut.model_validate(iv)
        .model_copy(
            update={
                "candidate_name": app.candidate.full_name if app else None,
                "job_title": app.job.title if app else None,
            }
        )
        .model_dump()
    )


def _visible(iv: Interview, p: Principal) -> None:
    if not p.has("interviews:manage") and not any(i.user_id == p.user_id for i in iv.interviewers):
        raise PermissionDenied("You are not on this interview panel")


@router.get("/interview-templates", response_model=list[InterviewTemplateOut])
def list_templates(db: DB, p: Annotated[Principal, Depends(require("interviews:read"))]) -> list[InterviewTemplate]:
    return list(
        db.scalars(
            select(InterviewTemplate)
            .where(InterviewTemplate.organization_id == p.organization_id)
            .order_by(InterviewTemplate.name)
        )
    )


@router.post("/interview-templates", response_model=InterviewTemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    data: InterviewTemplateIn, db: DB, p: Annotated[Principal, Depends(require("interviews:manage"))]
) -> InterviewTemplate:
    t = svc.create_template(db, data, p)
    db.commit()
    return t


@router.post(
    "/applications/{application_id}/interview-slots",
    response_model=list[SlotOut],
    summary="Interview Scheduling Agent: propose slots from panel availability",
)
def suggest_slots(
    application_id: uuid.UUID,
    data: SlotRequestIn,
    db: DB,
    p: Annotated[Principal, Depends(require("interviews:schedule"))],
) -> list[dict]:
    app = get_scoped(db, Application, application_id, p, label="Application")
    slots = svc.suggest_slots(db, app, data, p)
    db.commit()
    return slots


@router.post("/applications/{application_id}/interviews", response_model=InterviewOut, status_code=201)
def schedule(
    application_id: uuid.UUID,
    data: InterviewIn,
    db: DB,
    p: Annotated[Principal, Depends(require("interviews:schedule"))],
) -> dict:
    app = get_scoped(db, Application, application_id, p, label="Application")
    iv = svc.schedule(db, app, data, p)
    db.commit()
    return _out(iv, db)


@router.get("/interviews", response_model=list[InterviewOut], summary="Interview calendar")
def list_interviews(
    db: DB,
    p: Annotated[Principal, Depends(require("interviews:read"))],
    start: datetime | None = None,
    end: datetime | None = None,
    mine: bool = False,
    application_id: uuid.UUID | None = None,
) -> list[dict]:
    stmt = select(Interview).where(Interview.organization_id == p.organization_id)
    if start:
        stmt = stmt.where(Interview.scheduled_end >= start)
    if end:
        stmt = stmt.where(Interview.scheduled_start <= end)
    if application_id:
        stmt = stmt.where(Interview.application_id == application_id)
    if mine or not p.has("interviews:manage"):
        stmt = stmt.where(Interview.id.in_(select(Interviewer.interview_id).where(Interviewer.user_id == p.user_id)))
    return [_out(iv, db) for iv in db.scalars(stmt.order_by(Interview.scheduled_start).limit(1000))]


@router.get("/interviews/{interview_id}", response_model=InterviewOut)
def get_interview(
    interview_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("interviews:read"))]
) -> dict:
    iv = get_scoped(db, Interview, interview_id, p)
    _visible(iv, p)
    return _out(iv, db)


@router.patch("/interviews/{interview_id}", response_model=InterviewOut)
def update_interview(
    interview_id: uuid.UUID,
    data: InterviewUpdate,
    db: DB,
    p: Annotated[Principal, Depends(require("interviews:schedule"))],
) -> dict:
    iv = svc.update(db, get_scoped(db, Interview, interview_id, p), data, p)
    db.commit()
    return _out(iv, db)


@router.post("/interviews/{interview_id}/cancel", response_model=InterviewOut)
def cancel_interview(
    interview_id: uuid.UUID, data: CancelIn, db: DB, p: Annotated[Principal, Depends(require("interviews:schedule"))]
) -> dict:
    iv = svc.cancel(db, get_scoped(db, Interview, interview_id, p), data.reason, p)
    db.commit()
    return _out(iv, db)


@router.post("/interviews/{interview_id}/complete", response_model=InterviewOut)
def complete_interview(
    interview_id: uuid.UUID,
    db: DB,
    p: Annotated[Principal, Depends(require("interviews:feedback"))],
    no_show: bool = False,
) -> dict:
    iv = get_scoped(db, Interview, interview_id, p)
    _visible(iv, p)
    svc.complete(db, iv, p, no_show=no_show)
    db.commit()
    return _out(iv, db)


@router.post(
    "/interviews/{interview_id}/transcript",
    response_model=InterviewOut,
    summary="Interview Assistant Agent: summary + competency evidence from a transcript",
)
def add_transcript(
    interview_id: uuid.UUID,
    data: TranscriptIn,
    db: DB,
    p: Annotated[Principal, Depends(require("interviews:feedback"))],
) -> dict:
    iv = get_scoped(db, Interview, interview_id, p)
    _visible(iv, p)
    svc.add_transcript(db, iv, data.transcript, data.consent_confirmed, p)
    db.commit()
    return _out(iv, db)


@router.get("/interviews/{interview_id}/scorecards", response_model=list[ScorecardOut])
def list_scorecards(
    interview_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("interviews:read"))]
) -> list[InterviewScorecard]:
    iv = get_scoped(db, Interview, interview_id, p)
    _visible(iv, p)
    cards = list(db.scalars(select(InterviewScorecard).where(InterviewScorecard.interview_id == iv.id)))
    if not p.has("evaluations:read"):
        # Independent feedback: panelists only see their own card (prevents anchoring bias).
        cards = [c for c in cards if c.interviewer_id == p.user_id]
    return cards


@router.post("/interviews/{interview_id}/scorecards", response_model=ScorecardOut, status_code=201)
def submit_scorecard(
    interview_id: uuid.UUID, data: ScorecardIn, db: DB, p: Annotated[Principal, Depends(require("interviews:feedback"))]
) -> InterviewScorecard:
    card = svc.submit_scorecard(db, get_scoped(db, Interview, interview_id, p), data, p)
    db.commit()
    return card
