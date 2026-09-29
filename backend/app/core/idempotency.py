"""Idempotency for critical POST operations (``Idempotency-Key`` header).

The first request with a key stores its response; retries with the same key and identical body
receive the stored response; the same key with a different body is rejected (422).
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationFailed
from app.db.base import utcnow
from app.models.governance import IdempotencyKey

TTL = timedelta(hours=24)


def request_fingerprint(body: Any) -> str:
    return hashlib.sha256(json.dumps(jsonable_encoder(body), sort_keys=True, default=str).encode()).hexdigest()


def lookup(db: Session, scope: str, key: str, fingerprint: str) -> IdempotencyKey | None:
    if len(key) > 200 or len(key) < 8:
        raise ValidationFailed("Idempotency-Key must be 8-200 characters")
    db.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < utcnow() - TTL))
    row = db.scalar(select(IdempotencyKey).where(IdempotencyKey.scope == scope, IdempotencyKey.key == key))
    if row is None:
        return None
    if row.request_hash != fingerprint:
        raise ValidationFailed("Idempotency-Key reused with a different request body")
    if row.status_code is None:
        raise ConflictError("A request with this Idempotency-Key is still in progress")
    return row


def store(db: Session, scope: str, key: str, fingerprint: str, status_code: int, body: Any) -> None:
    db.add(
        IdempotencyKey(
            scope=scope,
            key=key,
            request_hash=fingerprint,
            status_code=status_code,
            response_body=jsonable_encoder(body),
        )
    )
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Concurrent request with the same Idempotency-Key") from exc
