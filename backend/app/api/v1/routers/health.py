from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.api.deps import DB
from app.core.config import get_settings

router = APIRouter(tags=["Health"])


@router.get("/healthz", summary="Liveness")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness (database + cache)")
def readyz(db: DB, response: Response) -> dict:
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover
        checks["database"] = f"error: {type(exc).__name__}"
    s = get_settings()
    if s.environment != "test":
        try:
            import redis

            redis.Redis.from_url(s.redis_url, socket_timeout=0.5).ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {type(exc).__name__}"
    ok = all(v == "ok" for v in checks.values())
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "degraded", "checks": checks}


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
