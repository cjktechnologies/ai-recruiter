from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.api.deps import DB, Paging, require
from app.core.principal import Principal
from app.models.assessments import Assessment, AssessmentQuestion, AssessmentResult
from app.models.pipeline import Application
from app.schemas.common import Page
from app.schemas.pipeline import (
    AssessmentIn, AssessmentOut, AssessmentResultOut, GenerateAssessmentIn, InviteAssessmentIn, InviteOut,
    ManualScoreIn, QuestionIn, QuestionOut,
)
from app.services import assessments as svc
from app.services.common import get_scoped, paginate

router = APIRouter(tags=["Assessments"])


@router.get("/question-bank", response_model=list[QuestionOut])
def list_bank(db: DB, p: Annotated[Principal, Depends(require("assessments:read"))], competency: str | None = None,
              tag: str | None = None) -> list[AssessmentQuestion]:
    stmt = select(AssessmentQuestion).where(AssessmentQuestion.organization_id == p.organization_id,
                                            AssessmentQuestion.assessment_id.is_(None))
    if competency:
        stmt = stmt.where(AssessmentQuestion.competency.ilike(competency))
    rows = list(db.scalars(stmt.order_by(AssessmentQuestion.created_at.desc())))
    return [q for q in rows if not tag or tag.lower() in [t.lower() for t in q.tags]]


@router.post("/question-bank", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
def add_bank_question(data: QuestionIn, db: DB,
                      p: Annotated[Principal, Depends(require("assessments:manage"))]) -> AssessmentQuestion:
    q = svc.add_bank_question(db, data, p)
    db.commit()
    return q


@router.get("/assessments", response_model=Page[AssessmentOut])
def list_assessments(db: DB, paging: Paging, p: Annotated[Principal, Depends(require("assessments:read"))],
                     job_id: uuid.UUID | None = None) -> dict:
    stmt = select(Assessment).where(Assessment.organization_id == p.organization_id)
    if job_id:
        stmt = stmt.where(Assessment.job_id == job_id)
    items, total = paginate(db, stmt, model=Assessment, page=paging.page, page_size=paging.page_size,
                            sort=paging.sort, allowed_sorts={"created_at", "title"})
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}


@router.post("/assessments", response_model=AssessmentOut, status_code=201)
def create_assessment(data: AssessmentIn, db: DB,
                      p: Annotated[Principal, Depends(require("assessments:manage"))]) -> Assessment:
    a = svc.create(db, data, p)
    db.commit()
    return a


@router.post("/assessments/generate", response_model=AssessmentOut, status_code=201,
             summary="Assessment Agent: assemble an assessment from the question bank for a job's skills")
def generate_assessment(data: GenerateAssessmentIn, db: DB,
                        p: Annotated[Principal, Depends(require("assessments:manage"))]) -> Assessment:
    a = svc.generate(db, data, p)
    db.commit()
    return a


@router.get("/assessments/{assessment_id}", response_model=AssessmentOut)
def get_assessment(assessment_id: uuid.UUID, db: DB,
                   p: Annotated[Principal, Depends(require("assessments:read"))]) -> Assessment:
    return get_scoped(db, Assessment, assessment_id, p)


@router.post("/applications/{application_id}/assessments", response_model=InviteOut, status_code=201,
             summary="Invite the candidate to an assessment (one-time secure link)")
def invite(application_id: uuid.UUID, data: InviteAssessmentIn, db: DB,
           p: Annotated[Principal, Depends(require("assessments:invite"))]) -> dict:
    app = get_scoped(db, Application, application_id, p, label="Application")
    a = get_scoped(db, Assessment, data.assessment_id, p)
    res, link = svc.invite(db, app, a, p, data.expires_in_days)
    db.commit()
    return {"result": AssessmentResultOut.model_validate(res), "candidate_link": link}


@router.get("/applications/{application_id}/assessment-results", response_model=list[AssessmentResultOut])
def results(application_id: uuid.UUID, db: DB,
            p: Annotated[Principal, Depends(require("assessments:read"))]) -> list[AssessmentResult]:
    app = get_scoped(db, Application, application_id, p, label="Application")
    return list(db.scalars(select(AssessmentResult).where(AssessmentResult.application_id == app.id)))


@router.post("/assessment-results/{result_id}/score", response_model=AssessmentResultOut,
             summary="Human scoring of free-text answers / override of suggested scores")
def manual_score(result_id: uuid.UUID, data: ManualScoreIn, db: DB,
                 p: Annotated[Principal, Depends(require("assessments:score"))]) -> AssessmentResult:
    res = get_scoped(db, AssessmentResult, result_id, p, label="Assessment result")
    svc.manual_score(db, res, data.question_scores, data.candidate_feedback, p)
    db.commit()
    return res
