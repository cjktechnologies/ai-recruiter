"""Celery application (Redis broker). Beat schedules periodic governance and reminder jobs."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)

celery = Celery("ai_recruiter", broker=settings.redis_url, backend=settings.redis_url, include=["app.workers.tasks"])
import app.db.events  # noqa: E402,F401  (session hooks in workers too)

celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_default_retry_delay=30,
    task_time_limit=600,
    task_soft_time_limit=540,
    broker_connection_retry_on_startup=True,
    task_routes={"app.workers.tasks.run_ai_*": {"queue": "ai"}},
    beat_schedule={
        "interview-reminders": {"task": "app.workers.tasks.send_interview_reminders", "schedule": crontab(minute="*/15")},
        "expire-offers-assessments": {"task": "app.workers.tasks.expire_stale_items", "schedule": crontab(minute=5)},
        "deliver-queued-messages": {"task": "app.workers.tasks.deliver_communications", "schedule": 60.0},
        "retention-purge": {"task": "app.workers.tasks.retention_purge", "schedule": crontab(hour=2, minute=30)},
    },
)
