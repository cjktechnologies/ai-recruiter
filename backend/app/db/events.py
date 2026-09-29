"""Session hooks: after a successful commit, hand queued candidate messages to the worker."""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.comms import Communication

_KEY = "queued_communications"


@event.listens_for(Session, "before_flush")
def _collect(session: Session, flush_context, instances) -> None:
    for obj in session.new:
        if isinstance(obj, Communication):
            session.info.setdefault(_KEY, []).append(obj)


@event.listens_for(Session, "after_commit")
def _dispatch(session: Session) -> None:
    comms = session.info.pop(_KEY, [])
    ids = [str(c.id) for c in comms if c.id is not None]
    if ids:
        from app.workers.dispatcher import enqueue

        enqueue("deliver_communications", ids=ids)


@event.listens_for(Session, "after_rollback")
def _discard(session: Session) -> None:
    session.info.pop(_KEY, None)
