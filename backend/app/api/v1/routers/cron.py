"""Scheduled jobs over HTTP for platforms without a long-running scheduler (Vercel Cron).

Vercel Cron sends ``GET <path>`` with ``Authorization: Bearer $CRON_SECRET``. Each job is the same
idempotent function Celery beat runs on Kubernetes, executed inline.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from app.core.config import get_settings
from app.core.logging import get_logger, log_event
from app.workers import tasks

logger = get_logger(__name__)
router = APIRouter(prefix="/internal/cron", include_in_schema=False)

JOBS: dict[str, Callable[[], Any]] = {
    "deliver-communications": lambda: tasks.deliver_communications.run(),
    "interview-reminders": lambda: tasks.send_interview_reminders.run(),
    "expire-stale-items": lambda: tasks.expire_stale_items.run(),
    "retention-purge": lambda: tasks.retention_purge.run(),
}


@router.get("/{job}")
def run_job(job: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    secret = get_settings().cron_secret
    expected = f"Bearer {secret.get_secret_value()}" if secret else None
    # Disabled entirely unless CRON_SECRET is configured.
    if expected is None or not hmac.compare_digest((authorization or "").encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")
    fn = JOBS.get(job)
    if fn is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    result = fn()
    log_event(logger, "cron_job_completed", job=job)
    return {"job": job, "result": result}
