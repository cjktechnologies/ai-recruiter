"""Data governance: retention enforcement, stale-item expiry, integration secret handling."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.principal import Principal
from app.db.base import utcnow
from app.domain.enums import ApplicationStatus, AssessmentResultStatus
from app.models.assessments import AssessmentResult
from app.models.candidates import Candidate
from app.models.governance import Integration
from app.models.pipeline import Application
from app.schemas.governance import IntegrationIn, IntegrationUpdate
from app.services import candidates as candidate_service
from app.services.audit import audit, diff


def retention_purge(db: Session, *, org_id=None, limit: int = 500) -> int:  # type: ignore[no-untyped-def]
    """Anonymize candidates whose retention period expired and who have no active applications."""
    now = utcnow()
    stmt = select(Candidate).where(Candidate.retention_until < now, Candidate.anonymized_at.is_(None))
    if org_id:
        stmt = stmt.where(Candidate.organization_id == org_id)
    n = 0
    for cand in db.scalars(stmt.limit(limit)):
        active = db.scalar(select(Application.id).where(Application.candidate_id == cand.id,
                                                        Application.status == ApplicationStatus.ACTIVE).limit(1))
        if active:
            continue
        candidate_service.anonymize(db, cand, None, reason="retention_expired")
        n += 1
    return n


def expire_assessments(db: Session) -> int:
    n = 0
    for r in db.scalars(select(AssessmentResult).where(
            AssessmentResult.status.in_([AssessmentResultStatus.INVITED, AssessmentResultStatus.IN_PROGRESS]),
            AssessmentResult.expires_at < utcnow())):
        r.status = AssessmentResultStatus.EXPIRED
        n += 1
    return n


def create_integration(db: Session, data: IntegrationIn, p: Principal) -> Integration:
    integ = Integration(organization_id=p.organization_id, kind=data.kind, name=data.name, config=data.config,
                        secret=json.dumps(data.secret) if data.secret else None, is_enabled=data.is_enabled)
    db.add(integ)
    db.flush()
    audit(db, action="integration.created", entity_type="integration", entity_id=integ.id, principal=p,
          changes={"kind": data.kind, "name": data.name, "has_secret": bool(data.secret)})
    return integ


def update_integration(db: Session, integ: Integration, data: IntegrationUpdate, p: Principal) -> Integration:
    updates = data.model_dump(exclude_unset=True)
    secret = updates.pop("secret", None)
    changes = diff(integ, updates)
    if secret is not None:
        integ.secret = json.dumps(secret)
        changes["secret"] = "rotated"
    audit(db, action="integration.updated", entity_type="integration", entity_id=integ.id, principal=p,
          changes=changes)
    return integ
