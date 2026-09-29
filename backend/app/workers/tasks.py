"""Background jobs. Each task opens its own unit of work (session_scope) and is idempotent."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.logging import get_logger, log_event
from app.db.base import utcnow
from app.db.session import session_scope
from app.domain.enums import DeliveryStatus, InterviewStatus
from app.models.candidates import CandidateDocument
from app.models.comms import Communication
from app.models.pipeline import Application
from app.services import candidates as candidate_service
from app.services import governance
from app.services import interviews as interview_service
from app.services import offers as offer_service
from app.services.notify import deliver, notify_users, queue_candidate_message
from app.workers.celery_app import celery

logger = get_logger(__name__)


@celery.task(name="app.workers.tasks.deliver_communications", bind=True, max_retries=5, default_retry_delay=60)
def deliver_communications(self, ids: list[str] | None = None) -> int:
    with session_scope() as db:
        stmt = select(Communication).where(Communication.status == DeliveryStatus.QUEUED)
        if ids:
            stmt = stmt.where(Communication.id.in_([uuid.UUID(i) for i in ids]))
        n = 0
        for comm in db.scalars(stmt.limit(500).with_for_update(skip_locked=True)):
            deliver(db, comm)
            n += 1
        return n


@celery.task(name="app.workers.tasks.process_document")
def process_document(document_id: str) -> str:
    with session_scope() as db:
        doc = db.get(CandidateDocument, uuid.UUID(document_id))
        if not doc:
            return "missing"
        candidate_service.process_document(db, doc)
        return str(doc.parse_status)


@celery.task(name="app.workers.tasks.send_interview_reminders")
def send_interview_reminders() -> int:
    with session_scope() as db:
        n = 0
        for iv in interview_service.due_reminders(db):
            app = db.get(Application, iv.application_id)
            if not app or iv.status != InterviewStatus.SCHEDULED:
                continue
            queue_candidate_message(
                db,
                candidate=app.candidate,
                template_key="interview_reminder",
                application_id=app.id,
                variables={
                    "job_title": app.job.title,
                    "when": iv.scheduled_start.strftime("%A %d %B %Y, %H:%M UTC"),
                    "timezone": iv.timezone,
                    "location": iv.location or (iv.meeting_url or ""),
                },
            )
            notify_users(
                db,
                iv.organization_id,
                [i.user_id for i in iv.interviewers],
                kind="interview_reminder",
                title=f"Upcoming interview: {app.candidate.full_name}",
                link=f"/interviews/{iv.id}",
            )
            iv.reminder_sent_at = utcnow()
            n += 1
        return n


@celery.task(name="app.workers.tasks.expire_stale_items")
def expire_stale_items() -> dict:
    with session_scope() as db:
        return {"offers": offer_service.expire_due(db), "assessments": governance.expire_assessments(db)}


@celery.task(name="app.workers.tasks.retention_purge")
def retention_purge() -> int:
    with session_scope() as db:
        n = governance.retention_purge(db)
    log_event(logger, "retention_purge", anonymized=n)
    return n
