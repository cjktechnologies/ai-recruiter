from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy import select

from app.api.deps import DB, Paging, require
from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationFailed
from app.core.principal import Principal
from app.domain.enums import DocumentKind
from app.models.candidates import Candidate, CandidateDocument, CandidateNote, ConsentRecord
from app.models.comms import Communication
from app.models.pipeline import Application
from app.schemas.candidates import (
    CandidateDetail, CandidateIn, CandidateOut, CandidateSkillOut, CandidateUpdate, ConsentIn, ConsentOut,
    DocumentOut, DuplicateOut, MergeIn, NoteIn, NoteOut,
)
from app.schemas.common import Page
from app.schemas.governance import CommunicationOut, MessageIn
from app.services import candidates as svc
from app.services.audit import audit
from app.services.common import get_scoped, paginate
from app.services.notify import deliver, queue_candidate_message
from app.storage import get_storage

router = APIRouter(prefix="/candidates", tags=["Candidates"])


def _detail(db, c: Candidate, p: Principal) -> CandidateDetail:  # type: ignore[no-untyped-def]
    apps = list(db.scalars(select(Application.id).where(Application.candidate_id == c.id)))
    base = {k: getattr(c, k) for k in CandidateDetail.model_fields if k not in ("skills", "application_ids", "phone")}
    return CandidateDetail.model_validate({
        **base,
        "skills": [CandidateSkillOut(name=s.skill.name, category=s.skill.category, years=s.years, source=s.source,
                                     evidence=s.evidence) for s in c.skills],
        "application_ids": apps,
        "phone": c.phone if p.has("candidates:read_pii") else None,
    })


@router.get("", response_model=Page[CandidateOut])
def search_candidates(
    db: DB, paging: Paging, p: Annotated[Principal, Depends(require("candidates:read"))],
    q: Annotated[str | None, Query(max_length=200)] = None,
    skills: Annotated[list[str], Query()] = [],  # noqa: B006
    tags: Annotated[list[str], Query()] = [],  # noqa: B006
    source: str | None = None, pool_id: uuid.UUID | None = None,
) -> dict:
    stmt = svc.search(db, p, q=q, skills=skills, tags=tags, source=source, pool_id=pool_id)
    items, total = paginate(db, stmt, model=Candidate, page=paging.page, page_size=paging.page_size, sort=paging.sort,
                            allowed_sorts={"created_at", "last_name", "years_experience", "updated_at"})
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}


@router.post("", response_model=CandidateDetail, status_code=status.HTTP_201_CREATED)
def create_candidate(data: CandidateIn, db: DB,
                     p: Annotated[Principal, Depends(require("candidates:create"))]) -> CandidateDetail:
    c = svc.create(db, data, p)
    db.commit()
    return _detail(db, c, p)


@router.get("/{candidate_id}", response_model=CandidateDetail)
def get_candidate(candidate_id: uuid.UUID, db: DB,
                  p: Annotated[Principal, Depends(require("candidates:read"))]) -> CandidateDetail:
    c = get_scoped(db, Candidate, candidate_id, p)
    if p.has("candidates:read_pii"):
        audit(db, action="candidate.pii_viewed", entity_type="candidate", entity_id=c.id, principal=p)
        db.commit()
    return _detail(db, c, p)


@router.patch("/{candidate_id}", response_model=CandidateDetail)
def update_candidate(candidate_id: uuid.UUID, data: CandidateUpdate, db: DB,
                     p: Annotated[Principal, Depends(require("candidates:update"))]) -> CandidateDetail:
    c = svc.update(db, get_scoped(db, Candidate, candidate_id, p), data, p)
    db.commit()
    return _detail(db, c, p)


@router.delete("/{candidate_id}", response_model=CandidateOut,
               summary="Erase personal data (right to erasure). Irreversible; keeps anonymized statistics.")
def erase_candidate(candidate_id: uuid.UUID, db: DB,
                    p: Annotated[Principal, Depends(require("candidates:delete"))]) -> Candidate:
    c = svc.anonymize(db, get_scoped(db, Candidate, candidate_id, p), p, reason="erasure_request")
    db.commit()
    return c


@router.get("/{candidate_id}/export", response_model=dict, summary="Data-subject access export")
def export_candidate(candidate_id: uuid.UUID, db: DB,
                     p: Annotated[Principal, Depends(require("candidates:export"))]) -> dict:
    c = get_scoped(db, Candidate, candidate_id, p)
    audit(db, action="candidate.exported", entity_type="candidate", entity_id=c.id, principal=p)
    db.commit()
    return svc.export_data(db, c)


@router.post("/{candidate_id}/documents", response_model=DocumentOut, status_code=201,
             summary="Upload a CV/document: validated, malware-scanned, parsed, profile enriched")
async def upload_document(
    candidate_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("documents:upload"))],
    file: Annotated[UploadFile, File()], kind: Annotated[DocumentKind, Form()] = DocumentKind.CV,
) -> CandidateDocument:
    c = get_scoped(db, Candidate, candidate_id, p)
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ValidationFailed("File too large")
    doc = svc.upload_document(db, c, data=data, filename=file.filename or "document",
                              content_type=file.content_type or "", kind=kind, p=p)
    svc.process_document(db, doc)
    db.commit()
    return doc


@router.get("/{candidate_id}/documents", response_model=list[DocumentOut])
def list_documents(candidate_id: uuid.UUID, db: DB,
                   p: Annotated[Principal, Depends(require("documents:read"))]) -> list[CandidateDocument]:
    c = get_scoped(db, Candidate, candidate_id, p)
    return list(db.scalars(select(CandidateDocument).where(CandidateDocument.candidate_id == c.id)
                           .order_by(CandidateDocument.created_at.desc())))


@router.get("/{candidate_id}/documents/{document_id}/download", response_class=Response)
def download_document(candidate_id: uuid.UUID, document_id: uuid.UUID, db: DB,
                      p: Annotated[Principal, Depends(require("documents:read"))]) -> Response:
    doc = get_scoped(db, CandidateDocument, document_id, p, label="Document")
    if doc.candidate_id != candidate_id or doc.scan_status in ("infected", "pending"):
        raise NotFoundError("Document not available")
    audit(db, action="document.downloaded", entity_type="document", entity_id=doc.id, principal=p)
    db.commit()
    return Response(get_storage().get(doc.storage_key), media_type=doc.content_type, headers={
        "Content-Disposition": f'attachment; filename="{doc.filename}"', "X-Content-Type-Options": "nosniff"})


@router.get("/{candidate_id}/notes", response_model=list[NoteOut])
def list_notes(candidate_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("candidates:read"))]) -> list:
    c = get_scoped(db, Candidate, candidate_id, p)
    return list(db.scalars(select(CandidateNote).where(
        CandidateNote.candidate_id == c.id,
        (CandidateNote.visibility == "team") | (CandidateNote.author_id == p.user_id))
        .order_by(CandidateNote.created_at.desc())))


@router.post("/{candidate_id}/notes", response_model=NoteOut, status_code=201)
def add_note(candidate_id: uuid.UUID, data: NoteIn, db: DB,
             p: Annotated[Principal, Depends(require("candidates:read"))]) -> CandidateNote:
    note = svc.add_note(db, get_scoped(db, Candidate, candidate_id, p), data, p)
    db.commit()
    return note


@router.get("/{candidate_id}/consents", response_model=list[ConsentOut])
def list_consents(candidate_id: uuid.UUID, db: DB,
                  p: Annotated[Principal, Depends(require("candidates:read"))]) -> list[ConsentRecord]:
    c = get_scoped(db, Candidate, candidate_id, p)
    return list(db.scalars(select(ConsentRecord).where(ConsentRecord.candidate_id == c.id)
                           .order_by(ConsentRecord.recorded_at.desc())))


@router.post("/{candidate_id}/consents", response_model=ConsentOut, status_code=201)
def add_consent(candidate_id: uuid.UUID, data: ConsentIn, db: DB,
                p: Annotated[Principal, Depends(require("candidates:update"))]) -> ConsentRecord:
    rec = svc.add_consent(db, get_scoped(db, Candidate, candidate_id, p), data, p)
    db.commit()
    return rec


@router.get("/{candidate_id}/duplicates", response_model=list[DuplicateOut])
def duplicates(candidate_id: uuid.UUID, db: DB, p: Annotated[Principal, Depends(require("candidates:read"))]) -> list:
    return svc.find_duplicates(db, get_scoped(db, Candidate, candidate_id, p))


@router.post("/{candidate_id}/merge", response_model=CandidateDetail, summary="Merge a duplicate into this candidate")
def merge(candidate_id: uuid.UUID, data: MergeIn, db: DB,
          p: Annotated[Principal, Depends(require("candidates:update"))]) -> CandidateDetail:
    p.require("candidates:delete")
    primary = get_scoped(db, Candidate, candidate_id, p)
    dup = get_scoped(db, Candidate, data.duplicate_id, p)
    svc.merge(db, primary, dup, p)
    db.commit()
    return _detail(db, primary, p)


@router.get("/{candidate_id}/communications", response_model=list[CommunicationOut])
def communications(candidate_id: uuid.UUID, db: DB,
                   p: Annotated[Principal, Depends(require("communications:read"))]) -> list[Communication]:
    c = get_scoped(db, Candidate, candidate_id, p)
    return list(db.scalars(select(Communication).where(Communication.candidate_id == c.id)
                           .order_by(Communication.created_at.desc())))


@router.post("/{candidate_id}/messages", response_model=CommunicationOut, status_code=201)
def send_message(candidate_id: uuid.UUID, data: MessageIn, db: DB,
                 p: Annotated[Principal, Depends(require("communications:send"))]) -> Communication:
    c = get_scoped(db, Candidate, candidate_id, p)
    if not data.template_key and not data.body:
        raise ValidationFailed("Provide a template_key or a body")
    comm = queue_candidate_message(db, candidate=c, template_key=data.template_key, variables=data.variables,
                                   subject=data.subject, body=data.body, channel=data.channel,
                                   application_id=data.application_id, sent_by_id=p.user_id)
    if comm is None:
        raise ValidationFailed("Candidate cannot be contacted (do-not-contact or erased)")
    deliver(db, comm)
    audit(db, action="communication.sent", entity_type="candidate", entity_id=c.id, principal=p,
          changes={"channel": data.channel, "template": data.template_key})
    db.commit()
    return comm

