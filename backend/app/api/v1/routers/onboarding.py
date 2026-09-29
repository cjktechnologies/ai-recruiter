from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.api.deps import DB, IdempotencyKeyHeader, require, run_idempotent
from app.core.principal import Principal
from app.models.onboarding import OnboardingHandoff, OnboardingTask
from app.models.pipeline import Application
from app.schemas.pipeline import HandoffOut, OnboardingTaskOut, OnboardingTaskUpdate
from app.services import onboarding as svc
from app.services.common import get_scoped

router = APIRouter(tags=["Onboarding"])


@router.post("/applications/{application_id}/onboarding", response_model=HandoffOut,
             summary="Onboarding Handoff Agent: HRIS handoff + preboarding checklist (idempotent)")
def handoff(application_id: uuid.UUID, db: DB, request: Request, key: IdempotencyKeyHeader,
            p: Annotated[Principal, Depends(require("onboarding:handoff"))]) -> dict:
    app = get_scoped(db, Application, application_id, p, label="Application")
    return run_idempotent(db, p, request, key, {"application_id": str(application_id)},
                          lambda: HandoffOut.model_validate(svc.handoff(db, app, p)).model_dump(mode="json"))


@router.get("/applications/{application_id}/onboarding", response_model=dict)
def get_onboarding(application_id: uuid.UUID, db: DB,
                   p: Annotated[Principal, Depends(require("onboarding:read"))]) -> dict:
    app = get_scoped(db, Application, application_id, p, label="Application")
    h = db.scalar(select(OnboardingHandoff).where(OnboardingHandoff.application_id == app.id))
    tasks = db.scalars(select(OnboardingTask).where(OnboardingTask.application_id == app.id)
                       .order_by(OnboardingTask.due_date))
    return {"handoff": HandoffOut.model_validate(h).model_dump(mode="json") if h else None,
            "tasks": [OnboardingTaskOut.model_validate(t).model_dump(mode="json") for t in tasks]}


@router.get("/onboarding/tasks", response_model=list[OnboardingTaskOut])
def list_tasks(db: DB, p: Annotated[Principal, Depends(require("onboarding:read"))], mine: bool = False,
               status: str | None = None) -> list[OnboardingTask]:
    stmt = select(OnboardingTask).where(OnboardingTask.organization_id == p.organization_id)
    if mine:
        stmt = stmt.where(OnboardingTask.assignee_id == p.user_id)
    if status:
        stmt = stmt.where(OnboardingTask.status == status)
    return list(db.scalars(stmt.order_by(OnboardingTask.due_date).limit(500)))


@router.patch("/onboarding/tasks/{task_id}", response_model=OnboardingTaskOut)
def update_task(task_id: uuid.UUID, data: OnboardingTaskUpdate, db: DB,
                p: Annotated[Principal, Depends(require("onboarding:manage"))]) -> OnboardingTask:
    task = svc.update_task(db, get_scoped(db, OnboardingTask, task_id, p, label="Task"), data, p)
    db.commit()
    return task
