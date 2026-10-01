"""Fixed-window rate limiter backed by Redis, with an in-process fallback (tests / Redis outage)."""

from __future__ import annotations

import threading
import time
from functools import lru_cache

from app.core.config import get_settings
from app.core.errors import RateLimited
from app.core.logging import get_logger

logger = get_logger(__name__)


class _MemoryWindow:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, tuple[int, int]] = {}

    def hit(self, key: str, window: int) -> int:
        bucket = int(time.time() // window)
        with self._lock:
            b, n = self._counts.get(key, (bucket, 0))
            n = n + 1 if b == bucket else 1
            self._counts[key] = (bucket, n)
            if len(self._counts) > 50_000:
                self._counts = {k: v for k, v in self._counts.items() if v[0] == bucket}
            return n


class RateLimiter:
    def __init__(self) -> None:
        self._memory = _MemoryWindow()
        self._redis = None
        s = get_settings()
        if s.environment != "test":
            try:
                import redis

                self._redis = redis.Redis.from_url(
                    s.redis_url, socket_timeout=0.25, socket_connect_timeout=0.25, **s.redis_ssl_options()
                )
            except Exception:  # pragma: no cover
                self._redis = None

    def check(self, key: str, limit: int, window: int = 60) -> tuple[int, int]:
        """Returns (remaining, reset_seconds). Raises RateLimited when exceeded."""
        count = None
        if self._redis is not None:
            try:
                rkey = f"rl:{key}:{int(time.time() // window)}"
                pipe = self._redis.pipeline()
                pipe.incr(rkey)
                pipe.expire(rkey, window + 1)
                count = int(pipe.execute()[0])
            except Exception:
                count = None
        if count is None:
            count = self._memory.hit(key, window)
        reset = window - int(time.time() % window)
        if count > limit:
            raise RateLimited(f"Rate limit exceeded; retry in {reset}s", extra={"retry_after": reset})
        return limit - count, reset


@lru_cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter()
