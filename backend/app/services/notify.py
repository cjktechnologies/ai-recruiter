"""Internal notifications and outbound candidate communications."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents.communication import render_template
from app.db.base import utcnow
from app.domain.enums import Channel, DeliveryStatus, Direction
from app.models.candidates import Candidate
from app.models.comms import Communication, Notification
from app.models.org import Organization, User


def notify_users(
    db: Session, org_id: uuid.UUID, user_ids: Iterable[uuid.UUID | None], *, kind: str, title: str,
    body: str | None = None, link: str | None = None, data: dict | None = None,
) -> None:
    for uid in {u for u in user_ids if u}:
        db.add(Notification(organization_id=org_id, user_id=uid, kind=kind, title=title, body=body, link=link,
                            data=data or {}))


def notify_role(db: Session, org_id: uuid.UUID, role_key: str, **kw: object) -> None:
    users = db.scalars(select(User).where(User.organization_id == org_id, User.is_active.is_(True)))
    notify_users(db, org_id, [u.id for u in users if role_key in u.role_keys], **kw)  # type: ignore[arg-type]


def queue_candidate_message(
    db: Session, *, candidate: Candidate, template_key: str | None = None, variables: dict | None = None,
    subject: str | None = None, body: str | None = None, channel: Channel = Channel.EMAIL,
    application_id: uuid.UUID | None = None, sent_by_id: uuid.UUID | None = None, ai_generated: bool = False,
    force: bool = False,
) -> Communication | None:
    """Persist an outbound message (status=queued). Delivery happens in a worker after commit."""
    if candidate.anonymized_at or (candidate.do_not_contact and not force):
        return None
    if template_key:
        org = db.get(Organization, candidate.organization_id)
        vars_ = {"first_name": candidate.first_name, "company": org.name if org else "", **(variables or {})}
        subject, body = render_template(template_key, vars_)
    if not body:
        raise ValueError("Message body required")
    comm = Communication(
        organization_id=candidate.organization_id, candidate_id=candidate.id, application_id=application_id,
        channel=channel, direction=Direction.OUTBOUND, subject=subject, body=body, template_key=template_key,
        status=DeliveryStatus.QUEUED, sent_by_id=sent_by_id, ai_generated=ai_generated,
    )
    db.add(comm)
    db.flush()
    return comm


def deliver(db: Session, comm: Communication) -> None:
    from app.core.errors import ExternalServiceError
    from app.integrations.messaging import get_email_sender, get_sms_sender

    if comm.status != DeliveryStatus.QUEUED:
        return
    cand = db.get(Candidate, comm.candidate_id)
    if not cand or cand.anonymized_at:
        comm.status, comm.error = DeliveryStatus.FAILED, "candidate unavailable"
        return
    try:
        if comm.channel == Channel.EMAIL:
            res = get_email_sender().send(to=cand.email, subject=comm.subject or "", body=comm.body)
        elif comm.channel in (Channel.SMS, Channel.WHATSAPP):
            if not cand.phone:
                raise ExternalServiceError("Candidate has no phone number")
            res = get_sms_sender().send(to=cand.phone, body=comm.body, whatsapp=comm.channel == Channel.WHATSAPP)
        else:
            comm.status, comm.sent_at = DeliveryStatus.DELIVERED, utcnow()  # portal/chat messages
            return
    except ExternalServiceError as exc:
        comm.status, comm.error = DeliveryStatus.FAILED, exc.detail
        return
    comm.status, comm.external_id, comm.sent_at = DeliveryStatus.SENT, res.external_id, utcnow()
