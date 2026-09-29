"""Candidate CRM: profiles, skills, documents (secure upload → scan → parse), duplicates,
consent, notes, erasure and data-subject export."""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from difflib import SequenceMatcher

from sqlalchemy import func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.ai.cv_parser import DocumentParseError, extract_text, parse_cv
from app.ai.embeddings import get_embedder
from app.ai.guardrails import sanitize_untrusted
from app.ai.taxonomy import category_of, normalize_skill
from app.core.config import get_settings
from app.core.errors import ConflictError, UnsafeContent, ValidationFailed
from app.core.principal import Principal
from app.core.security import sha256_hex
from app.db.base import utcnow
from app.domain.enums import ConsentPurpose, DocumentKind, ParseStatus, ScanStatus
from app.models.candidates import (
    Candidate,
    CandidateDocument,
    CandidateNote,
    CandidateSkill,
    ConsentRecord,
    EEOResponse,
    Skill,
)
from app.models.comms import Communication
from app.models.org import Organization
from app.models.pipeline import Application
from app.schemas.candidates import CandidateIn, CandidateUpdate, ConsentIn, EEOIn, NoteIn
from app.services.audit import audit, diff
from app.services.files import scan_bytes, validate_upload
from app.storage import get_storage


def phone_hash(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    return sha256_hex(digits[-9:]) if len(digits) >= 7 else None


def _get_or_create_skill(db: Session, name: str) -> Skill:
    canonical = normalize_skill(name)[:120]
    skill = db.scalar(select(Skill).where(func.lower(Skill.name) == canonical.lower()))
    if not skill:
        skill = Skill(name=canonical, category=category_of(canonical))
        db.add(skill)
        db.flush()
    return skill


def set_skills(
    db: Session,
    cand: Candidate,
    names: list[str],
    *,
    source: str = "manual",
    evidence: dict[str, str] | None = None,
    replace: bool = False,
) -> None:
    existing = {cs.skill.name.lower(): cs for cs in cand.skills}
    if replace:
        keep = {normalize_skill(n).lower() for n in names}
        for key, cs in list(existing.items()):
            if key not in keep and cs.source == "manual":
                cand.skills.remove(cs)
    for name in names:
        if not name.strip():
            continue
        skill = _get_or_create_skill(db, name)
        current = existing.get(skill.name.lower())
        ev = (evidence or {}).get(skill.name)
        if current is None:
            cand.skills.append(CandidateSkill(skill_id=skill.id, skill=skill, source=source, evidence=ev))
        elif ev and not current.evidence:
            current.evidence = ev


def refresh_embedding(cand: Candidate, extra_text: str = "") -> None:
    text = " ".join(filter(None, [cand.headline, cand.current_title, cand.summary, extra_text[:8000]]))
    cand.embedding = get_embedder().embed(text, skills=[cs.skill.name for cs in cand.skills])


def record_consent(
    db: Session, cand: Candidate, purpose: ConsentPurpose, granted: bool, *, source: str, ip: str | None = None
) -> ConsentRecord:
    now = utcnow()
    rec = ConsentRecord(
        organization_id=cand.organization_id,
        candidate_id=cand.id,
        purpose=purpose,
        granted=granted,
        recorded_at=now,
        expires_at=now + timedelta(days=get_settings().consent_validity_days) if granted else None,
        source=source,
        ip_address=ip,
    )
    db.add(rec)
    if purpose == ConsentPurpose.RECRUITMENT_PROCESSING and granted:
        cand.consent_given_at = now
    return rec


def has_consent(db: Session, cand: Candidate, purpose: ConsentPurpose) -> bool:
    rec = db.scalar(
        select(ConsentRecord)
        .where(ConsentRecord.candidate_id == cand.id, ConsentRecord.purpose == purpose)
        .order_by(ConsentRecord.recorded_at.desc())
        .limit(1)
    )
    return bool(rec and rec.granted and (rec.expires_at is None or rec.expires_at > utcnow()))


def create(
    db: Session, data: CandidateIn, p: Principal | None, *, org_id: uuid.UUID | None = None, ip: str | None = None
) -> Candidate:
    org_id = org_id or (p.organization_id if p else None)
    assert org_id
    email = data.email.lower()
    if db.scalar(select(Candidate).where(Candidate.organization_id == org_id, Candidate.email == email)):
        raise ConflictError("A candidate with this e-mail already exists", extra={"field": "email"})
    org = db.get(Organization, org_id)
    payload = data.model_dump(exclude={"skills", "consent_recruitment", "consent_talent_pool", "email"}, mode="json")
    cand = Candidate(
        organization_id=org_id,
        email=email,
        phone_hash=phone_hash(data.phone),
        owner_id=p.user_id if p else None,
        retention_until=utcnow() + timedelta(days=org.data_retention_days if org else 730),
        **payload,
    )
    db.add(cand)
    db.flush()
    set_skills(db, cand, data.skills)
    if data.consent_recruitment:
        record_consent(
            db,
            cand,
            ConsentPurpose.RECRUITMENT_PROCESSING,
            True,
            source="recruiter_recorded" if p else "application_form",
            ip=ip,
        )
        record_consent(
            db,
            cand,
            ConsentPurpose.AI_ASSISTED_SCREENING,
            True,
            source="recruiter_recorded" if p else "application_form",
            ip=ip,
        )
    if data.consent_talent_pool:
        record_consent(db, cand, ConsentPurpose.TALENT_POOL, True, source="application_form", ip=ip)
    refresh_embedding(cand)
    dups = find_duplicates(db, cand)
    if dups and dups[0]["score"] >= 0.9:
        cand.duplicate_of_id = dups[0]["candidate_id"]
    audit(
        db,
        action="candidate.created",
        entity_type="candidate",
        entity_id=cand.id,
        principal=p,
        organization_id=org_id,
        changes={"source": cand.source, "possible_duplicates": len(dups)},
    )
    return cand


def update(db: Session, cand: Candidate, data: CandidateUpdate, p: Principal) -> Candidate:
    if cand.anonymized_at:
        raise ConflictError("Candidate data has been erased")
    updates = data.model_dump(exclude_unset=True)
    skills = updates.pop("skills", None)
    if "phone" in updates:
        updates["phone_hash"] = phone_hash(updates["phone"])
    changes = diff(cand, updates)
    changes.pop("phone", None)
    if skills is not None:
        set_skills(db, cand, skills, replace=True)
        changes["skills"] = skills
    refresh_embedding(cand)
    audit(
        db,
        action="candidate.updated",
        entity_type="candidate",
        entity_id=cand.id,
        principal=p,
        changes={k: v for k, v in changes.items() if k != "phone_hash"},
    )
    return cand


def search(
    db: Session,
    p: Principal,
    *,
    q: str | None,
    skills: list[str],
    tags: list[str],
    source: str | None,
    pool_id: uuid.UUID | None,
):
    from app.models.recruitment import talent_pool_members

    stmt = select(Candidate).where(Candidate.organization_id == p.organization_id, Candidate.anonymized_at.is_(None))
    if q:
        like = f"%{q.lower().strip()}%"
        stmt = stmt.where(
            or_(
                func.lower(Candidate.first_name + " " + Candidate.last_name).like(like),
                func.lower(Candidate.email).like(like),
                func.lower(Candidate.headline).like(like),
                func.lower(Candidate.current_title).like(like),
            )
        )
    for sk in skills:
        stmt = stmt.where(
            Candidate.skills.any(CandidateSkill.skill.has(func.lower(Skill.name) == normalize_skill(sk).lower()))
        )
    if tags:
        stmt = stmt.where(Candidate.tags.contains(tags))
    if source:
        stmt = stmt.where(Candidate.source == source)
    if pool_id:
        stmt = stmt.where(
            Candidate.id.in_(select(talent_pool_members.c.candidate_id).where(talent_pool_members.c.pool_id == pool_id))
        )
    return stmt


def find_duplicates(db: Session, cand: Candidate) -> list[dict]:
    """Heuristic duplicate detection: e-mail local-part, phone hash, fuzzy name + location."""
    others = db.scalars(
        select(Candidate)
        .where(
            Candidate.organization_id == cand.organization_id,
            Candidate.id != cand.id,
            Candidate.anonymized_at.is_(None),
            or_(
                Candidate.phone_hash == cand.phone_hash if cand.phone_hash else False,
                func.lower(Candidate.last_name) == cand.last_name.lower(),
                func.split_part(Candidate.email, "@", 1) == cand.email.split("@")[0],
            ),
        )
        .limit(200)
    )
    out = []
    for o in others:
        reasons, score = [], 0.0
        if cand.phone_hash and o.phone_hash == cand.phone_hash:
            reasons.append("same phone number")
            score += 0.6
        if o.email.split("@")[0] == cand.email.split("@")[0]:
            reasons.append("same e-mail username")
            score += 0.3
        name_sim = SequenceMatcher(None, o.full_name.lower(), cand.full_name.lower()).ratio()
        if name_sim > 0.85:
            reasons.append(f"similar name ({name_sim:.2f})")
            score += 0.35 * name_sim
        if o.location and cand.location and o.location.lower() == cand.location.lower():
            score += 0.05
        if reasons and score >= 0.35:
            out.append(
                {
                    "candidate_id": o.id,
                    "full_name": o.full_name,
                    "email": o.email,
                    "reasons": reasons,
                    "score": round(min(score, 1.0), 2),
                }
            )
    return sorted(out, key=lambda d: d["score"], reverse=True)


def merge(db: Session, primary: Candidate, duplicate: Candidate, p: Principal) -> Candidate:
    if primary.id == duplicate.id:
        raise ValidationFailed("Cannot merge a candidate into itself")
    for app in db.scalars(select(Application).where(Application.candidate_id == duplicate.id)):
        if db.scalar(
            select(Application).where(Application.candidate_id == primary.id, Application.job_id == app.job_id)
        ):
            raise ConflictError("Both candidates applied to the same job; resolve applications first")
        app.candidate_id = primary.id
    for model in (CandidateDocument, CandidateNote, Communication, ConsentRecord):
        db.execute(sa_update(model).where(model.candidate_id == duplicate.id).values(candidate_id=primary.id))
    set_skills(db, primary, [cs.skill.name for cs in duplicate.skills], source="manual")
    primary.tags = sorted(set(primary.tags) | set(duplicate.tags))
    for f in ("phone", "location", "headline", "summary", "linkedin_url", "current_title", "current_company"):
        if not getattr(primary, f) and getattr(duplicate, f):
            setattr(primary, f, getattr(duplicate, f))
    duplicate.duplicate_of_id = primary.id
    db.flush()
    anonymize(db, duplicate, p, reason="merged_duplicate")
    audit(
        db,
        action="candidate.merged",
        entity_type="candidate",
        entity_id=primary.id,
        principal=p,
        changes={"merged_from": str(duplicate.id)},
    )
    return primary


def upload_document(
    db: Session,
    cand: Candidate,
    *,
    data: bytes,
    filename: str,
    content_type: str,
    kind: DocumentKind,
    p: Principal | None,
) -> CandidateDocument:
    real_type, safe_name = validate_upload(data, content_type, filename)
    digest = sha256_hex(data)
    existing = db.scalar(
        select(CandidateDocument).where(CandidateDocument.candidate_id == cand.id, CandidateDocument.sha256 == digest)
    )
    if existing:
        return existing
    key = f"{cand.organization_id}/candidates/{cand.id}/{uuid.uuid4().hex}"
    doc = CandidateDocument(
        organization_id=cand.organization_id,
        candidate_id=cand.id,
        kind=kind,
        filename=safe_name,
        content_type=real_type,
        size_bytes=len(data),
        sha256=digest,
        storage_key=key,
        uploaded_by_id=p.user_id if p else None,
    )
    get_storage().put(key, data, real_type)
    db.add(doc)
    db.flush()
    audit(
        db,
        action="document.uploaded",
        entity_type="document",
        entity_id=doc.id,
        principal=p,
        organization_id=cand.organization_id,
        changes={"filename": safe_name, "size": len(data), "kind": kind},
    )
    return doc


def process_document(db: Session, doc: CandidateDocument) -> CandidateDocument:
    """Scan → extract text → sanitize → parse → enrich candidate profile (only fills empty fields)."""
    data = get_storage().get(doc.storage_key)
    scan = scan_bytes(data)
    doc.scan_status, doc.scan_detail = scan.status, scan.detail
    if scan.status == ScanStatus.INFECTED:
        get_storage().delete(doc.storage_key)
        doc.parse_status = ParseStatus.FAILED
        audit(
            db,
            action="document.quarantined",
            entity_type="document",
            entity_id=doc.id,
            organization_id=doc.organization_id,
            changes={"detail": scan.detail},
        )
        return doc
    if scan.status == ScanStatus.ERROR and get_settings().require_malware_scan:
        doc.parse_status = ParseStatus.PENDING
        return doc
    try:
        raw = extract_text(data, doc.content_type)
    except DocumentParseError as exc:
        doc.parse_status, doc.security_flags = ParseStatus.FAILED, [*doc.security_flags, f"parse_error:{exc}"]
        return doc
    clean = sanitize_untrusted(raw)
    doc.parsed_text = clean.text
    doc.security_flags = clean.flags
    parsed = parse_cv(clean.text)
    doc.parsed_data = parsed.to_dict()
    doc.parse_status = ParseStatus.PARSED
    if doc.kind == DocumentKind.CV:
        cand = db.get(Candidate, doc.candidate_id)
        assert cand
        set_skills(
            db,
            cand,
            [s.name for s in parsed.skills],
            source="extracted",
            evidence={s.name: s.evidence for s in parsed.skills},
        )
        if cand.years_experience is None:
            cand.years_experience = parsed.total_years_experience or parsed.stated_years_experience
        if not cand.experience:
            cand.experience = [e.__dict__ for e in parsed.experience]
        if not cand.education:
            cand.education = [e.__dict__ for e in parsed.education]
        cand.languages = sorted(set(cand.languages) | set(parsed.languages))
        if not cand.headline and parsed.headline:
            cand.headline = parsed.headline[:300]
        if not cand.phone and parsed.phone:
            cand.phone, cand.phone_hash = parsed.phone, phone_hash(parsed.phone)
        if parsed.experience and not cand.current_title:
            cand.current_title = parsed.experience[0].title
            cand.current_company = parsed.experience[0].company
        refresh_embedding(cand, clean.text)
    if clean.is_suspicious:
        audit(
            db,
            action="document.injection_suspected",
            entity_type="document",
            entity_id=doc.id,
            organization_id=doc.organization_id,
            changes={"flags": clean.flags},
        )
    return doc


def add_note(db: Session, cand: Candidate, data: NoteIn, p: Principal) -> CandidateNote:
    note = CandidateNote(
        organization_id=p.organization_id, candidate_id=cand.id, author_id=p.user_id, **data.model_dump()
    )
    db.add(note)
    db.flush()
    audit(db, action="candidate.note_added", entity_type="candidate", entity_id=cand.id, principal=p)
    return note


def add_consent(db: Session, cand: Candidate, data: ConsentIn, p: Principal) -> ConsentRecord:
    rec = record_consent(db, cand, data.purpose, data.granted, source=data.source)
    db.flush()
    audit(
        db,
        action="candidate.consent_recorded",
        entity_type="candidate",
        entity_id=cand.id,
        principal=p,
        changes={"purpose": data.purpose, "granted": data.granted},
    )
    return rec


def save_eeo(db: Session, cand: Candidate, data: EEOIn) -> None:
    row = db.scalar(select(EEOResponse).where(EEOResponse.candidate_id == cand.id))
    if not row:
        row = EEOResponse(organization_id=cand.organization_id, candidate_id=cand.id, recorded_at=utcnow())
        db.add(row)
    for k, v in data.model_dump().items():
        setattr(row, k, v)


def anonymize(db: Session, cand: Candidate, p: Principal | None, *, reason: str) -> Candidate:
    """Right to erasure / retention expiry: irreversibly strip personal data, keep aggregate stats."""
    storage = get_storage()
    for doc in db.scalars(select(CandidateDocument).where(CandidateDocument.candidate_id == cand.id)):
        storage.delete(doc.storage_key)
        db.delete(doc)
    for model in (CandidateNote, EEOResponse):
        for row in db.scalars(select(model).where(model.candidate_id == cand.id)):
            db.delete(row)
    for comm in db.scalars(select(Communication).where(Communication.candidate_id == cand.id)):
        comm.body, comm.subject = "[erased]", None
    token = uuid.uuid4().hex[:12]
    cand.first_name, cand.last_name = "Erased", "Candidate"
    cand.email = f"erased-{token}@erased.invalid"
    for f in (
        "phone",
        "phone_hash",
        "location",
        "headline",
        "summary",
        "linkedin_url",
        "portfolio_url",
        "current_title",
        "current_company",
        "embedding",
        "source_detail",
    ):
        setattr(cand, f, None)
    cand.education, cand.experience, cand.languages, cand.tags = [], [], [], []
    cand.skills.clear()
    cand.anonymized_at, cand.do_not_contact = utcnow(), True
    audit(
        db,
        action="candidate.anonymized",
        entity_type="candidate",
        entity_id=cand.id,
        principal=p,
        organization_id=cand.organization_id,
        changes={"reason": reason},
    )
    return cand


def export_data(db: Session, cand: Candidate) -> dict:
    """Data-subject access request export (everything held about the person, excluding internal notes'
    authorship metadata)."""
    apps = list(db.scalars(select(Application).where(Application.candidate_id == cand.id)))
    return {
        "profile": {
            c: getattr(cand, c)
            for c in (
                "first_name",
                "last_name",
                "email",
                "phone",
                "location",
                "headline",
                "summary",
                "years_experience",
                "source",
                "tags",
            )
        },
        "skills": [{"name": cs.skill.name, "evidence": cs.evidence} for cs in cand.skills],
        "applications": [
            {"job": a.job.title, "stage": a.stage, "status": a.status, "applied_at": a.applied_at} for a in apps
        ],
        "documents": [
            {"filename": d.filename, "uploaded": d.created_at}
            for d in db.scalars(select(CandidateDocument).where(CandidateDocument.candidate_id == cand.id))
        ],
        "communications": [
            {"subject": c.subject, "body": c.body, "sent_at": c.sent_at}
            for c in db.scalars(select(Communication).where(Communication.candidate_id == cand.id))
        ],
        "consents": [
            {"purpose": c.purpose, "granted": c.granted, "at": c.recorded_at}
            for c in db.scalars(select(ConsentRecord).where(ConsentRecord.candidate_id == cand.id))
        ],
        "exported_at": utcnow(),
    }


def ensure_not_erased(cand: Candidate) -> None:
    if cand.anonymized_at:
        raise UnsafeContent("Candidate data has been erased")
