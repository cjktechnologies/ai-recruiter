"""FastAPI dependencies: authentication, permissions, pagination, idempotency."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import Depends, Header, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import idempotency
from app.core.config import get_settings
from app.core.errors import AuthenticationError, PermissionDenied
from app.core.logging import org_id_ctx, user_id_ctx
from app.core.principal import Principal
from app.core.ratelimit import get_rate_limiter
from app.db.session import get_db
from app.services.auth import principal_from_token

bearer = HTTPBearer(auto_error=False)
DB = Annotated[Session, Depends(get_db)]
T = TypeVar("T")


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)


def get_principal(
    request: Request,
    db: DB,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    x_organization_id: Annotated[str | None, Header()] = None,
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise AuthenticationError()
    p = principal_from_token(db, creds.credentials, org_override=x_organization_id, ip=client_ip(request),
                             user_agent=request.headers.get("user-agent"))
    org_id_ctx.set(str(p.organization_id))
    user_id_ctx.set(str(p.user_id))
    get_rate_limiter().check(f"user:{p.user_id}", get_settings().rate_limit_per_minute)
    request.state.principal = p
    return p


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require(*permissions: str) -> Callable[[Principal], Principal]:
    def dep(p: CurrentPrincipal) -> Principal:
        if p.is_candidate:
            raise PermissionDenied("Staff access required")
        if p.organization_id == uuid.UUID(int=0):
            raise PermissionDenied("Select an organization (X-Organization-Id) to use tenant APIs")
        p.require(*permissions)
        return p

    return dep


def require_candidate(p: CurrentPrincipal) -> Principal:
    if not p.candidate_id:
        raise PermissionDenied("Candidate portal access only")
    return p


def require_super_admin(p: CurrentPrincipal) -> Principal:
    if not p.is_super_admin:
        raise PermissionDenied("Super admin only")
    return p


class PageParams:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1, le=10_000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 25,
        sort: Annotated[str | None, Query(max_length=100, description="e.g. -created_at,title")] = None,
    ) -> None:
        self.page, self.page_size, self.sort = page, page_size, sort


Paging = Annotated[PageParams, Depends()]
def _idempotency_key(
    key: Annotated[str | None, Header(alias="Idempotency-Key", description="Client-generated key (8-200 chars)")] = None,
) -> str | None:
    return key


IdempotencyKeyHeader = Annotated[str | None, Depends(_idempotency_key)]


def run_idempotent(db: Session, p: Principal | None, request: Request, key: str | None, body: Any,
                   fn: Callable[[], T], status_code: int = 200) -> T | Any:
    """Execute fn once per Idempotency-Key; retries get the stored response."""
    if not key:
        result = fn()
        db.commit()
        return result
    scope = f"{p.organization_id if p else 'public'}:{p.user_id if p else client_ip(request)}:" \
            f"{request.method}:{request.url.path}"[:120]
    fp = idempotency.request_fingerprint(body)
    existing = idempotency.lookup(db, scope, key, fp)
    if existing is not None:
        return existing.response_body
    result = fn()
    idempotency.store(db, scope, key, fp, status_code, jsonable_encoder(result))
    db.commit()
    return result
