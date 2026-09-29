"""Centralized audit logging (append-only)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import redact_obj, request_id_ctx
from app.core.principal import Principal
from app.domain.enums import ActorType
from app.models.governance import AuditLog


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple | set):
        return [_jsonable(x) for x in v]
    if isinstance(v, str | int | float | bool) or v is None:
        return v
    return str(v)


def audit(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str | None,
    principal: Principal | None = None,
    organization_id: uuid.UUID | None = None,
    actor_type: ActorType | None = None,
    actor_id: str | None = None,
    changes: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        organization_id=organization_id or (principal.organization_id if principal else None),
        actor_type=actor_type or (ActorType.CANDIDATE if principal and principal.is_candidate else
                                  ActorType.USER if principal else ActorType.SYSTEM),
        actor_id=actor_id or (str(principal.user_id) if principal else None),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        changes=redact_obj(_jsonable(changes or {})),
        ip_address=principal.ip_address if principal else None,
        user_agent=(principal.user_agent or "")[:400] if principal else None,
        request_id=request_id_ctx.get(),
    )
    db.add(entry)
    return entry


def diff(obj: Any, updates: dict[str, Any]) -> dict[str, Any]:
    """Apply updates to an ORM object and return {field: [old, new]} for changed fields."""
    changes: dict[str, Any] = {}
    for key, value in updates.items():
        old = getattr(obj, key)
        if old != value:
            changes[key] = [_jsonable(old), _jsonable(value)]
            setattr(obj, key, value)
    return changes
