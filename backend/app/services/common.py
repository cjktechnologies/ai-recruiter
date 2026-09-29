"""Shared query helpers: tenant-scoped lookup, pagination, filtering and sorting."""

from __future__ import annotations

import uuid
from typing import Any, TypeVar

from sqlalchemy import Select, asc, desc, func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationFailed
from app.core.principal import Principal

M = TypeVar("M")


def get_scoped(db: Session, model: type[M], obj_id: uuid.UUID, principal: Principal, *, label: str | None = None) -> M:
    """Fetch a tenant-owned row; rows of other tenants are indistinguishable from missing ones."""
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "organization_id", None) != principal.organization_id:
        raise NotFoundError(f"{label or model.__name__} not found")
    return obj


def paginate(
    db: Session,
    stmt: Select[Any],
    *,
    model: Any,
    page: int,
    page_size: int,
    sort: str | None,
    allowed_sorts: set[str],
    default_sort: str = "-created_at",
) -> tuple[list[Any], int]:
    if page < 1 or page_size < 1 or page_size > 200:
        raise ValidationFailed("page must be >= 1 and page_size between 1 and 200")
    sort = sort or default_sort
    orders = []
    for part in sort.split(","):
        part = part.strip()
        field = part.lstrip("-+")
        if field not in allowed_sorts:
            raise ValidationFailed(f"Unsupported sort field '{field}'. Allowed: {sorted(allowed_sorts)}")
        col = getattr(model, field)
        orders.append(desc(col) if part.startswith("-") else asc(col))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.order_by(*orders, model.id).offset((page - 1) * page_size).limit(page_size)).unique().all()
    return list(rows), int(total)
