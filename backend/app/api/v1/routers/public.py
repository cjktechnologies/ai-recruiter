"""Unauthenticated candidate-facing endpoints: careers site, applications, assessments, offers,
reference forms, the recruitment chatbot and portal sign-in links. All are rate limited."""

from __future__ import annotations

import json
from typing import Annotated
from xml.sax.saxutils import escape

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, status
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select

from app.ai.agents import CommunicationAgent
from app.ai.agents.base import AgentContext
from app.ai.agents.communication import DEFAULT_FAQ, ChatInput
from app.ai.orchestrator import Orchestrator
from app.api.deps import DB, IdempotencyKeyHeader, client_ip, run_idempotent
from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationFailed
from app.domain.enums import DocumentKind, JobStatus
from app.integrations.messaging import get_email_sender
from app.models.assessments import Assessment
from app.models.candidates import Candidate
from app.models.org import Organization
from app.models.recruitment import Job
from app.schemas.candidates import CandidateIn, EEOIn
from app.schemas.common import Message
from app.schemas.governance import ChatIn, ChatOut
from app.schemas.pipeline import (
    CandidateQuestionOut, OfferResponseIn, PublicAssessmentOut, PublicOfferOut, ReferenceResponseIn, SubmitAnswersIn,
)
from app.schemas.recruitment import PublicJobOut
from app.services import applications as app_service
from app.services import assessments as assessment_service
from app.services import candidates as candidate_service
from app.services import jobs as job_service
from app.services import offers as offer_service
from app.services import selection
from app.services.auth import create_candidate_magic_token

router = APIRouter(prefix="/public", tags=["Public (careers site & candidate links)"])


def _org(db, slug: str) -> Organization:  # type: ignore[no-untyped-def]
    org = db.scalar(select(Organization).where(Organization.slug == slug, Organization.is_active.is_(True)))
    if not org:
        raise NotFoundError("Organization not found")
    return org


def _public_job(j: Job) -> PublicJobOut:
    kq = [{"id": q["id"], "question": q["question"]} for q in (j.screening_config or {}).get("knockout_questions", [])]
    return PublicJobOut(title=j.title, slug=j.slug, description=j.description, location=j.location,
                        remote_policy=j.remote_policy, employment_type=j.employment_type,
                        salary_min=j.salary_min if j.show_salary else None,
                        salary_max=j.salary_max if j.show_salary else None, currency=j.currency,
                        published_at=j.published_at, closes_at=j.closes_at, knockout_questions=kq)


@router.get("/{org_slug}/jobs", response_model=list[PublicJobOut])
def careers(org_slug: str, db: DB) -> list[PublicJobOut]:
    return [_public_job(j) for j in job_service.public_jobs(db, _org(db, org_slug).id)]


@router.get("/{org_slug}/jobs.xml", response_class=Response, summary="Job-board XML feed of published jobs")
def jobs_feed(org_slug: str, db: DB) -> Response:
    org = _org(db, org_slug)
    base = get_settings().public_base_url
    items = "".join(
        f"<job><title>{escape(j.title)}</title><id>{j.id}</id><url>{base}/careers/{org.slug}/{j.slug}</url>"
        f"<company>{escape(org.name)}</company><location>{escape(j.location or '')}</location>"
        f"<type>{j.employment_type}</type><date>{j.published_at.isoformat() if j.published_at else ''}</date>"
        f"<description><![CDATA[{j.description.replace(']]>', ']]]]><![CDATA[>')}]]></description></job>"
        for j in job_service.public_jobs(db, org.id))
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><source><publisher>{escape(org.name)}</publisher>{items}'
                    "</source>", media_type="application/xml")


@router.get("/{org_slug}/jobs/{job_slug}", response_model=PublicJobOut)
def job_detail(org_slug: str, job_slug: str, db: DB) -> PublicJobOut:
    org = _org(db, org_slug)
    job = db.scalar(select(Job).where(Job.organization_id == org.id, Job.slug == job_slug,
                                      Job.status == JobStatus.PUBLISHED))
    if not job:
        raise NotFoundError("Job not found")
    return _public_job(job)


@router.post("/{org_slug}/jobs/{job_slug}/apply", response_model=Message, status_code=status.HTTP_201_CREATED,
             summary="Apply with CV upload (consent required; idempotent with Idempotency-Key)")
async def apply(
    org_slug: str, job_slug: str, request: Request, db: DB, key: IdempotencyKeyHeader,
    first_name: Annotated[str, Form(min_length=1, max_length=120)],
    last_name: Annotated[str, Form(min_length=1, max_length=120)],
    email: Annotated[str, Form(max_length=320)],
    consent_recruitment: Annotated[bool, Form()],
    cv: Annotated[UploadFile, File()],
    phone: Annotated[str | None, Form(max_length=40)] = None,
    location: Annotated[str | None, Form(max_length=200)] = None,
    linkedin_url: Annotated[str | None, Form(max_length=400)] = None,
    cover_letter: Annotated[str | None, Form(max_length=20000)] = None,
    answers: Annotated[str | None, Form(max_length=20000, description="JSON object of knockout answers")] = None,
    consent_talent_pool: Annotated[bool, Form()] = False,
    consent_ai_screening: Annotated[bool, Form()] = True,
    eeo: Annotated[str | None, Form(max_length=2000, description="Optional voluntary self-ID JSON")] = None,
    source: Annotated[str, Form(max_length=60)] = "careers_site",
) -> dict:
    if not consent_recruitment:
        raise ValidationFailed("Consent to process your application data is required")
    try:
        email_ok = TypeAdapter(EmailStr).validate_python(email)
        answers_obj = json.loads(answers) if answers else {}
        eeo_obj = EEOIn.model_validate_json(eeo) if eeo else None
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ValidationFailed("Invalid e-mail, answers or EEO data") from exc
    if not isinstance(answers_obj, dict):
        raise ValidationFailed("answers must be a JSON object")
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await cv.read(limit + 1)
    if len(data) > limit:
        raise ValidationFailed("File too large")
    org = _org(db, org_slug)
    job = db.scalar(select(Job).where(Job.organization_id == org.id, Job.slug == job_slug,
                                      Job.status == JobStatus.PUBLISHED))
    if not job:
        raise NotFoundError("Job not found or closed")

    def _do() -> dict:
        cand = db.scalar(select(Candidate).where(Candidate.organization_id == org.id,
                                                 Candidate.email == email_ok.lower()))
        if cand is None:
            cand = candidate_service.create(db, CandidateIn(
                first_name=first_name, last_name=last_name, email=email_ok, phone=phone, location=location,
                linkedin_url=linkedin_url or None, source=source, consent_recruitment=True,
                consent_talent_pool=consent_talent_pool), None, org_id=org.id, ip=client_ip(request))
        else:
            from app.domain.enums import ConsentPurpose

            candidate_service.record_consent(db, cand, ConsentPurpose.RECRUITMENT_PROCESSING, True,
                                             source="application_form", ip=client_ip(request))
        if not consent_ai_screening:
            from app.domain.enums import ConsentPurpose

            candidate_service.record_consent(db, cand, ConsentPurpose.AI_ASSISTED_SCREENING, False,
                                             source="application_form", ip=client_ip(request))
        if eeo_obj:
            candidate_service.save_eeo(db, cand, eeo_obj)
        doc = candidate_service.upload_document(db, cand, data=data, filename=cv.filename or "cv",
                                                content_type=cv.content_type or "", kind=DocumentKind.CV, p=None)
        candidate_service.process_document(db, doc)
        if doc.scan_status == "infected":
            raise ValidationFailed("The uploaded file failed our security checks")
        application = app_service.create(db, job=job, candidate=cand, source=source, p=None,
                                         cover_letter=cover_letter, answers=answers_obj)
        Orchestrator(db).start(application, None)
        return {"message": "Application received. Thank you!"}

    return run_idempotent(db, None, request, key, {"job": job_slug, "email": email_ok.lower()}, _do, 201)


@router.post("/{org_slug}/chat", response_model=ChatOut, summary="Recruitment FAQ chatbot (grounded, no decisions)")
def chat(org_slug: str, data: ChatIn, db: DB) -> ChatOut:
    org = _org(db, org_slug)
    faq = (org.settings or {}).get("faq") or DEFAULT_FAQ
    out = CommunicationAgent().run(AgentContext(db, org.id), ChatInput(question=data.message, company=org.name,
                                                                       faq=faq),
                                   entity_type="organization", entity_id=org.id).output
    db.commit()
    return ChatOut(answer=out.answer, needs_human=out.needs_human, ai_generated=out.ai_generated)


@router.post("/{org_slug}/portal/link", response_model=Message,
             summary="E-mail a candidate portal sign-in link (always returns 200 to avoid enumeration)")
def portal_link(org_slug: str, email: Annotated[EmailStr, Form()], db: DB) -> Message:
    org = _org(db, org_slug)
    token = create_candidate_magic_token(db, org, email)
    if token:
        link = f"{get_settings().public_base_url}/portal/verify?token={token}"
        get_email_sender().send(to=email, subject=f"Your {org.name} candidate portal link",
                                body=f"Sign in to track your applications: {link}\nThis link expires in 20 minutes.")
    return Message(message="If we have your application on file, you'll receive an e-mail shortly.")


# --- Tokenised candidate links -------------------------------------------------------------
@router.get("/assessments/{token}", response_model=PublicAssessmentOut)
def get_assessment(token: str, db: DB) -> PublicAssessmentOut:
    res = assessment_service.by_token(db, token)
    a = db.get(Assessment, res.assessment_id)
    assert a
    assessment_service.start(db, res)
    db.commit()
    return PublicAssessmentOut(
        title=a.title, instructions=a.instructions, duration_minutes=a.duration_minutes, expires_at=res.expires_at,
        status=res.status, questions=[CandidateQuestionOut(id=q.id, kind=q.kind, prompt=q.prompt, options=q.options,
                                                           points=q.points) for q in a.questions])


@router.post("/assessments/{token}/submit", response_model=Message)
def submit_assessment(token: str, data: SubmitAnswersIn, db: DB) -> Message:
    res = assessment_service.by_token(db, token)
    assessment_service.submit(db, res, data.answers)
    db.commit()
    return Message(message="Thank you — your answers have been submitted.")


@router.get("/offers/{token}", response_model=PublicOfferOut)
def get_offer(token: str, db: DB) -> PublicOfferOut:
    offer = offer_service.by_token(db, token)
    org = db.get(Organization, offer.organization_id)
    return PublicOfferOut(company=org.name if org else "", job_title=offer.job_title, base_salary=offer.base_salary,
                          currency=offer.currency, bonus_pct=offer.bonus_pct, benefits=offer.benefits,
                          start_date=offer.start_date, expires_at=offer.expires_at, letter_body=offer.letter_body,
                          status=offer.status)


@router.post("/offers/{token}/respond", response_model=Message)
def respond_offer(token: str, data: OfferResponseIn, db: DB) -> Message:
    offer = offer_service.by_token(db, token)
    offer_service.respond(db, offer, data.accept, data.reason)
    db.commit()
    return Message(message="Thank you — we've recorded your response." if data.accept else
                   "Thank you for letting us know.")


@router.get("/references/{token}", response_model=dict)
def get_reference(token: str, db: DB) -> dict:
    ref = selection.reference_by_token(db, token)
    return {"referee_name": ref.referee_name, "questions": ref.questionnaire, "status": ref.status}


@router.post("/references/{token}", response_model=Message)
def submit_reference(token: str, data: ReferenceResponseIn, db: DB) -> Message:
    ref = selection.reference_by_token(db, token)
    selection.submit_reference(db, ref, data.responses, data.decline)
    db.commit()
    return Message(message="Thank you for your reference.")
