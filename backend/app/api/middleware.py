"""Request context, security headers, public rate limiting and Prometheus metrics."""

from __future__ import annotations

import time
import uuid

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.errors import RateLimited
from app.core.logging import get_logger, log_event, org_id_ctx, request_id_ctx, user_id_ctx
from app.core.ratelimit import get_rate_limiter

logger = get_logger("http")
REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP latency",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
SENSITIVE_PUBLIC = ("/auth/login", "/auth/refresh", "/public/", "/auth/candidate")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id")
        if not rid or len(rid) > 64 or not rid.replace("-", "").isalnum():
            rid = uuid.uuid4().hex
        request_id_ctx.set(rid)
        org_id_ctx.set(None)
        user_id_ctx.set(None)
        start = time.perf_counter()
        path = request.url.path
        s = get_settings()
        if any(seg in path for seg in SENSITIVE_PUBLIC):
            ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
                request.client.host if request.client else "unknown"
            )
            try:
                get_rate_limiter().check(
                    f"ip:{ip}:{path.split('/')[3] if path.count('/') > 3 else path}",
                    s.auth_rate_limit_per_minute if "/auth/" in path else s.rate_limit_per_minute,
                )
            except RateLimited as exc:
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(exc.extra.get("retry_after", 60)), "X-Request-ID": rid},
                    content={
                        "type": "about:blank",
                        "title": exc.title,
                        "status": 429,
                        "detail": exc.detail,
                        "code": exc.code,
                        "request_id": rid,
                    },
                )
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        REQUESTS.labels(request.method, route_path, str(response.status_code)).inc()
        LATENCY.labels(request.method, route_path).observe(elapsed)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        if s.environment in ("staging", "production"):
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if not path.startswith(("/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if path not in ("/healthz", "/readyz", "/metrics"):
            log_event(
                logger,
                "request",
                method=request.method,
                path=route_path,
                status=response.status_code,
                duration_ms=round(elapsed * 1000, 1),
            )
        return response
