"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.middleware import RequestContextMiddleware
from app.api.v1 import api_router
from app.api.v1.routers import health
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger, log_event, request_id_ctx
from app.db import events  # noqa: F401  (register session hooks)

logger = get_logger(__name__)

API_DESCRIPTION = """
AI-assisted recruitment operations platform: ATS + CRM + agent orchestration.

**Conventions**
* Auth: `Authorization: Bearer <access_token>` (OAuth2/OIDC SSO or password login).
  Super admins select a tenant with `X-Organization-Id`.
* Errors: RFC 7807 `application/problem+json` with a stable `code` and `request_id`.
* Pagination: `page`, `page_size` (≤200), `sort` (e.g. `-created_at,title`); responses are
  `{items,total,page,page_size}`.
* Idempotency: critical POSTs accept `Idempotency-Key` (8-200 chars, 24h retention).
* Rate limiting: per user and per IP for public/auth endpoints; `429` with `Retry-After`.
* Versioning: URI-based (`/api/v1`); breaking changes ship as `/api/v2`.
* AI governance: AI output is advisory. Consequential transitions (advancing after screening,
  selection, offers, hiring) are gated on humans and fully audited.
"""


def _problem(status: int, title: str, code: str, detail: str | None, **extra: object) -> JSONResponse:
    body = {"type": "about:blank", "title": title, "status": status, "detail": detail, "code": code,
            "request_id": request_id_ctx.get(), **extra}
    headers = {"Retry-After": str(extra["retry_after"])} if "retry_after" in extra else None
    return JSONResponse(body, status_code=status, media_type="application/problem+json", headers=headers)


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    app = FastAPI(
        title=f"{s.app_name} API", version="1.0.0", description=API_DESCRIPTION,
        openapi_url=f"{s.api_prefix}/openapi.json", docs_url="/docs", redoc_url="/redoc",
        openapi_tags=[{"name": t} for t in (
            "Authentication", "Organizations & Users", "Requisitions", "Jobs & Sourcing", "Candidates",
            "Applications, Screening & Selection", "Assessments", "Interviews & Scheduling", "Offers", "Onboarding",
            "Analytics", "AI Agents & Governance", "Notifications, Integrations, Audit & Governance",
            "Candidate portal", "Public (careers site & candidate links)", "Health")],
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Organization-Id",
                                      "X-Request-ID"], expose_headers=["X-Request-ID", "Retry-After"])

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            log_event(logger, "app_error", logging.ERROR, code=exc.code)
        return _problem(exc.status_code, exc.title, exc.code, exc.detail, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return _problem(422, "Validation failed", "validation_failed", "Request validation failed", errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _problem(exc.status_code, str(exc.detail), "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error")
        return _problem(500, "Internal server error", "internal_error", "An unexpected error occurred")

    app.include_router(health.router)
    app.include_router(api_router, prefix=s.api_prefix)

    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        from fastapi.openapi.utils import get_openapi

        schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes,
                             tags=app.openapi_tags)
        schema["components"]["schemas"]["Problem"] = {
            "type": "object", "required": ["title", "status", "code"],
            "properties": {k: {"type": t} for k, t in (("type", "string"), ("title", "string"), ("status", "integer"),
                                                         ("detail", "string"), ("code", "string"),
                                                         ("request_id", "string"))}}
        problem = {"application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}}
        for path_item in schema["paths"].values():
            for op in path_item.values():
                for code, desc in (("401", "Unauthenticated"), ("403", "Forbidden"), ("404", "Not found"),
                                   ("409", "Conflict / invalid transition / approval required"),
                                   ("429", "Rate limited")):
                    op.setdefault("responses", {}).setdefault(code, {"description": desc, "content": problem})
        schema["servers"] = [{"url": "/"}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app


app = create_app()
