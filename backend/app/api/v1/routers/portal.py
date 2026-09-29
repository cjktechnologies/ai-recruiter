"""Candidate self-service portal (candidate-role JWT from a magic link)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.ai.agents import CommunicationAgent
from app.ai.agents.base import AgentContext
from app.ai.agents.communication import DEFAULT_FAQ, ChatInput
from app.api.deps import DB, require_candidate
from app.core.errors import NotFoundError
from app.core.principal import Principal
from app.models.candidates import Candidate
from app.models.org import Organization
from app.models.pipeline import Application
from app.schemas.common import Message
from app.schemas.governance import ChatIn, ChatOut
from app.services import applications as app_service
from app.services import candidates as candidate_service
from app.services.audit import audit
from app.services.notify import notify_role

router = APIRouter(prefix="/portal", tags=["Candidate portal"])
CandidateP = Annotated[Principal, Depends(require_candidate)]
PUBLIC_STAGE = {"applied": "Received", "screening": "Under review", "screened": "Under review",
                "assessment": "Assessment", "interview": "Interviewing", "evaluation": "Interviewing",
                "selection": "Final review", "verification": "Final review", "offer": "Offer",
                "hired": "Hired", "rejected": "Closed", "withdrawn": "Withdrawn"}


@router.get("/applications", response_model=list[dict])
def my_applications(db: DB, p: CandidateP) -> list[dict]:
    apps = db.scalars(select(Application).where(Application.candidate_id == p.candidate_id))
    return [{"id": str(a.id), "job_title": a.job.title, "status": PUBLIC_STAGE.get(str(a.stage), "In progress"),
             "applied_at": a.applied_at.isoformat()} for a in apps]


@router.post("/applications/{application_id}/withdraw", response_model=Message)
def withdraw(application_id: uuid.UUID, db: DB, p: CandidateP) -> Message:
    a = db.get(Application, application_id)
    if not a or a.candidate_id != p.candidate_id:
        raise NotFoundError("Application not found")
    app_service.withdraw(db, a, p, "Withdrawn by candidate")
    db.commit()
    return Message(message="Your application has been withdrawn.")


@router.get("/me/export", response_model=dict, summary="Download all data held about me")
def export(db: DB, p: CandidateP) -> dict:
    cand = db.get(Candidate, p.candidate_id)
    assert cand
    audit(db, action="candidate.self_export", entity_type="candidate", entity_id=cand.id, principal=p)
    db.commit()
    return candidate_service.export_data(db, cand)


@router.post("/me/erasure-request", response_model=Message)
def erasure_request(db: DB, p: CandidateP) -> Message:
    cand = db.get(Candidate, p.candidate_id)
    assert cand
    audit(db, action="candidate.erasure_requested", entity_type="candidate", entity_id=cand.id, principal=p)
    notify_role(db, cand.organization_id, "hr_manager", kind="erasure_request",
                title="Candidate data erasure request", link=f"/candidates/{cand.id}")
    db.commit()
    return Message(message="Your request has been received; we'll confirm by e-mail once completed.")


@router.post("/chat", response_model=ChatOut)
def chat(data: ChatIn, db: DB, p: CandidateP) -> ChatOut:
    cand = db.get(Candidate, p.candidate_id)
    assert cand
    org = db.get(Organization, cand.organization_id)
    latest = db.scalar(select(Application).where(Application.candidate_id == cand.id)
                       .order_by(Application.applied_at.desc()).limit(1))
    status = {"job_title": latest.job.title, "stage": PUBLIC_STAGE.get(str(latest.stage), "in progress")} \
        if latest else None
    out = CommunicationAgent().run(AgentContext(db, cand.organization_id), ChatInput(
        question=data.message, company=org.name if org else "", candidate_first_name=cand.first_name,
        application_status=status, faq=((org.settings or {}).get("faq") if org else None) or DEFAULT_FAQ),
        entity_type="candidate", entity_id=cand.id).output
    db.commit()
    return ChatOut(answer=out.answer, needs_human=out.needs_human, ai_generated=out.ai_generated)
