from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select

from app.ai.orchestrator import Orchestrator
from app.api.deps import DB, IdempotencyKeyHeader, Paging, require, run_idempotent
from app.core.principal import Principal
from app.domain.enums import ApplicationStage, ApplicationStatus, ReviewStatus
from app.models.candidates import Candidate
from app.models.pipeline import Application, ApplicationStageHistory, ScreeningResult
from app.models.recruitment import Job
from app.models.selection import BackgroundCheck, CandidateEvaluation, CandidateReference
from app.schemas.common import Page
from app.schemas.pipeline import (
    ApplicationDetail,
    ApplicationIn,
    ApplicationOut,
    BackgroundCheckIn,
    BackgroundCheckOut,
    BackgroundCheckUpdate,
    EvaluationDecisionIn,
    EvaluationOut,
    MoveIn,
    ReferenceIn,
    ReferenceOut,
    RejectIn,
    ScreeningOut,
    ScreeningReviewIn,
    SelectionDecisionIn,
    StageHistoryOut,
)
from app.services import applications as svc
from app.services import screening, selection
from app.services.common import get_scoped, paginate

router = APIRouter(tags=["Applications, Screening & Selection"])


def _out(a: Application) -> dict:
    return (
        ApplicationOut.model_validate(a)
        .model_copy(update={"candidate_name": a.candidate.full_name, "job_title": a.job.title})
        .model_dump()
    )


@router.get("/applications", response_model=Page[ApplicationOut])
def list_applications(
    db: DB,
    paging: Paging,
    p: Annotated[Principal, Depends(require("applications:read"))],
    job_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    stage: Annotated[list[ApplicationStage], Query()] = [],  # noqa: B006
    status_: Annotated[ApplicationStatus | None, Query(alias="status")] = None,
    source: str | None = None,
    recruiter_id: uuid.UUID | None = None,
    min_score: float | None = None,
) -> dict:
    stmt = select(Application).where(Application.organization_id == p.organization_id)
    if job_id:
        stmt = stmt.where(Application.job_id == job_id)
    if candidate_id:
        stmt = stmt.where(Application.candidate_id == candidate_id)
    if stage:
        stmt = stmt.where(Application.stage.in_(stage))
    if status_:
        stmt = stmt.where(Application.status == status_)
    if source:
        stmt = stmt.where(Application.source == source)
    if recruiter_id:
        stmt = stmt.where(Application.recruiter_id == recruiter_id)
    if min_score is not None:
        stmt = stmt.where(Application.match_score >= min_score)
    if p.roles == ("interviewer",):
        from app.models.interviews import Interview, Interviewer

        stmt = stmt.where(
            Application.id.in_(
                select(Interview.application_id).join(Interviewer).where(Interviewer.user_id == p.user_id)
            )
        )
    items, total = paginate(
        db,
        stmt,
        model=Application,
        page=paging.page,
        page_size=paging.page_size,
        sort=paging.sort,
        allowed_sorts={"created_at", "applied_at", "match_score", "stage_changed_at"},
        default_sort="-applied_at",
    )
    return {"items": [_out(a) for a in items], "total": total, "page": paging.page, "page_size": paging.page_size}


@router.post(
    "/applications",
    response_model=ApplicationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a candidate to a job (idempotent with Idempotency-Key); starts the agent workflow",
)
def create_application(
    data: ApplicationIn,
    db: DB,
    request: Request,
    key: IdempotencyKeyHeader,
    p: Annotated[Principal, Depends(require("applications:create"))],
) -> dict:
    def _do() -> dict:
        job = get_scoped(db, Job, data.job_id, p)
        cand = get_scoped(db, Candidate, data.candidate_id, p)
        app = svc.create(
            db,
            job=job,
            candidate=cand,
            source=data.source,
            p=p,
            cover_letter=data.cover_letter,
            answers=data.screening_answers,
        )
        Orchestrator(db).start(app, p)
        return _out(app)

    return run_idempotent(db, p, request, key, data.model_dump(mode="json"), _do, 201)


@router.get("/applications/{application_id}", response_model=ApplicationDetail)
def get_application(
    application_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("applications:read"))]
) -> dict:
    a = get_scoped(db, Application, application_id, p, label="Application")
    history = db.scalars(
        select(ApplicationStageHistory)
        .where(ApplicationStageHistory.application_id == a.id)
        .order_by(ApplicationStageHistory.changed_at)
    )
    run = Orchestrator(db).get_run(a)
    return (
        ApplicationDetail.model_validate(a)
        .model_copy(
            update={
                "candidate_name": a.candidate.full_name,
                "job_title": a.job.title,
                "history": [StageHistoryOut.model_validate(h) for h in history],
                "workflow": {
                    "current_node": run.current_node,
                    "status": run.status,
                    "waiting_on": run.waiting_on,
                    "history": run.history,
                }
                if run
                else None,
            }
        )
        .model_dump()
    )


@router.post(
    "/applications/{application_id}/move",
    response_model=ApplicationOut,
    summary="Move stage (human gates enforced; see pipeline rules)",
)
def move_application(
    application_id: uuid.UUID, data: MoveIn, db: DB, p: Annotated[Principal, Depends(require("applications:move"))]
) -> dict:
    a = get_scoped(db, Application, application_id, p, label="Application")
    svc.move_stage(db, a, data.to_stage, principal=p, reason=data.reason)
    Orchestrator(db).handle(a, f"stage.{data.to_stage}", principal=p)
    db.commit()
    return _out(a)


@router.post("/applications/{application_id}/reject", response_model=ApplicationOut)
def reject_application(
    application_id: uuid.UUID, data: RejectIn, db: DB, p: Annotated[Principal, Depends(require("applications:reject"))]
) -> dict:
    a = get_scoped(db, Application, application_id, p, label="Application")
    svc.reject(db, a, p, data.reason, data.notify_candidate)
    db.commit()
    return _out(a)


# --- Screening -------------------------------------------------------------------------
@router.post(
    "/applications/{application_id}/screening",
    response_model=ScreeningOut,
    summary="Run (or re-run) the Candidate Screening Agent",
)
def run_screening(
    application_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("screening:run"))]
) -> ScreeningResult:
    a = get_scoped(db, Application, application_id, p, label="Application")
    prev = screening.latest(db, a)
    if prev and prev.review_status == ReviewStatus.PENDING_REVIEW:
        prev.review_status = ReviewStatus.REJECTED  # superseded by the new run
    result = screening.run(db, a, triggered_by=p)
    Orchestrator(db).handle(a, "screening.completed", principal=p)
    db.commit()
    return result


@router.get("/applications/{application_id}/screening", response_model=list[ScreeningOut])
def list_screening(
    application_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("screening:read"))]
) -> list[ScreeningResult]:
    a = get_scoped(db, Application, application_id, p, label="Application")
    return list(
        db.scalars(
            select(ScreeningResult)
            .where(ScreeningResult.application_id == a.id)
            .order_by(ScreeningResult.created_at.desc())
        )
    )


@router.get("/screening/queue", response_model=list[dict], summary="Screening results awaiting human review")
def screening_queue(
    db: DB,
    p: Annotated[Principal, Depends(require("screening:review"))],
    job_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[dict]:
    stmt = (
        select(ScreeningResult, Application)
        .join(Application, Application.id == ScreeningResult.application_id)
        .where(
            ScreeningResult.organization_id == p.organization_id,
            ScreeningResult.review_status == ReviewStatus.PENDING_REVIEW,
            Application.stage == ApplicationStage.SCREENED,
        )
    )
    if job_id:
        stmt = stmt.where(Application.job_id == job_id)
    rows = db.execute(stmt.order_by(ScreeningResult.score.desc()).limit(min(limit, 500))).all()
    return [
        {"screening": ScreeningOut.model_validate(r).model_dump(mode="json"), "application": _out(a)} for r, a in rows
    ]


@router.post(
    "/screening/{result_id}/review",
    response_model=ScreeningOut,
    summary="Recruiter decision on AI screening (override requires a reason)",
)
def review_screening(
    result_id: uuid.UUID, data: ScreeningReviewIn, db: DB, p: Annotated[Principal, Depends(require("screening:review"))]
) -> ScreeningResult:
    r = get_scoped(db, ScreeningResult, result_id, p, label="Screening result")
    a = get_scoped(db, Application, r.application_id, p, label="Application")
    screening.review(
        db,
        r,
        a,
        p,
        decision=data.decision,
        next_stage=data.next_stage,
        override_reason=data.override_reason,
        rejection_reason=data.rejection_reason,
    )
    db.commit()
    return r


# --- Evaluation & selection -------------------------------------------------------------
@router.post(
    "/applications/{application_id}/evaluations",
    response_model=EvaluationOut,
    summary="Run the Candidate Evaluation Agent on all collected evidence",
)
def run_evaluation(
    application_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("evaluations:run"))]
) -> CandidateEvaluation:
    a = get_scoped(db, Application, application_id, p, label="Application")
    ev = selection.run_evaluation(db, a, p)
    Orchestrator(db).handle(a, "interviews.feedback_complete", principal=p)
    db.commit()
    return ev


@router.get("/applications/{application_id}/evaluations", response_model=list[EvaluationOut])
def list_evaluations(
    application_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("evaluations:read"))]
) -> list[CandidateEvaluation]:
    a = get_scoped(db, Application, application_id, p, label="Application")
    return list(
        db.scalars(
            select(CandidateEvaluation)
            .where(CandidateEvaluation.application_id == a.id)
            .order_by(CandidateEvaluation.created_at.desc())
        )
    )


@router.post("/evaluations/{evaluation_id}/decision", response_model=EvaluationOut)
def decide_evaluation(
    evaluation_id: uuid.UUID,
    data: EvaluationDecisionIn,
    db: DB,
    p: Annotated[Principal, Depends(require("evaluations:decide"))],
) -> CandidateEvaluation:
    ev = get_scoped(db, CandidateEvaluation, evaluation_id, p, label="Evaluation")
    a = get_scoped(db, Application, ev.application_id, p, label="Application")
    selection.decide_evaluation(db, ev, a, p, data.decision, data.rationale)
    db.commit()
    return ev


@router.post(
    "/applications/{application_id}/selection",
    response_model=ApplicationOut,
    summary="Selection approval gate (segregation of duties enforced)",
)
def selection_decision(
    application_id: uuid.UUID,
    data: SelectionDecisionIn,
    db: DB,
    request: Request,
    key: IdempotencyKeyHeader,
    p: Annotated[Principal, Depends(require("selection:approve"))],
) -> dict:
    a = get_scoped(db, Application, application_id, p, label="Application")
    return run_idempotent(
        db,
        p,
        request,
        key,
        data.model_dump(),
        lambda: _out(
            selection.approve_selection(db, a, p, data.decision == "approve", data.comment, data.skip_verification)
        ),
    )


@router.get("/comparison", response_model=list[dict], summary="Candidate comparison workspace")
def compare(
    db: DB,
    p: Annotated[Principal, Depends(require("evaluations:read"))],
    application_ids: Annotated[list[uuid.UUID], Query(min_length=2, max_length=10)],
) -> list[dict]:
    return selection.comparison(db, application_ids, p)


# --- Verification ------------------------------------------------------------------------
@router.get("/applications/{application_id}/references", response_model=list[ReferenceOut])
def list_references(
    application_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("verification:read"))]
) -> list:
    a = get_scoped(db, Application, application_id, p, label="Application")
    return list(db.scalars(select(CandidateReference).where(CandidateReference.application_id == a.id)))


@router.post("/applications/{application_id}/references", response_model=dict, status_code=201)
def add_reference(
    application_id: uuid.UUID,
    data: ReferenceIn,
    db: DB,
    p: Annotated[Principal, Depends(require("verification:manage"))],
) -> dict:
    a = get_scoped(db, Application, application_id, p, label="Application")
    ref, link = selection.add_reference(db, a, data, p)
    db.commit()
    return {"reference": ReferenceOut.model_validate(ref).model_dump(mode="json"), "referee_link": link}


@router.get("/applications/{application_id}/background-checks", response_model=list[BackgroundCheckOut])
def list_checks(
    application_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("verification:read"))]
) -> list:
    a = get_scoped(db, Application, application_id, p, label="Application")
    return list(db.scalars(select(BackgroundCheck).where(BackgroundCheck.application_id == a.id)))


@router.post("/applications/{application_id}/background-checks", response_model=BackgroundCheckOut, status_code=201)
def request_check(
    application_id: uuid.UUID,
    data: BackgroundCheckIn,
    db: DB,
    p: Annotated[Principal, Depends(require("verification:manage"))],
) -> BackgroundCheck:
    a = get_scoped(db, Application, application_id, p, label="Application")
    bc = selection.request_background_check(db, a, data, p)
    db.commit()
    return bc


@router.patch("/background-checks/{check_id}", response_model=BackgroundCheckOut)
def update_check(
    check_id: uuid.UUID,
    data: BackgroundCheckUpdate,
    db: DB,
    p: Annotated[Principal, Depends(require("verification:manage"))],
) -> BackgroundCheck:
    bc = get_scoped(db, BackgroundCheck, check_id, p, label="Background check")
    selection.update_background_check(db, bc, data, p)
    db.commit()
    return bc
