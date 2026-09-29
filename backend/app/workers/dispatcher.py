"""Job dispatch abstraction: Celery in deployed environments, inline execution when eager.

Services call ``enqueue`` *after* committing so workers always see persisted state.
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger, log_event

logger = get_logger(__name__)


def enqueue(task_name: str, **kwargs: Any) -> None:
    from app.workers import tasks

    fn = getattr(tasks, task_name)
    if get_settings().task_always_eager:
        fn.run(**kwargs) if hasattr(fn, "run") else fn(**kwargs)
        return
    try:
        fn.apply_async(kwargs=kwargs)
    except Exception as exc:  # broker down: degrade to inline so user actions are never lost
        log_event(logger, "enqueue_failed_inline_fallback", task=task_name, error=type(exc).__name__)
        fn.run(**kwargs)
