"""Fixed-window, per-IP rate limiting backed by Redis.

Redis makes the limit shared across all Gunicorn workers. If Redis is
unreachable we fall back to an in-process counter (per worker) rather than
failing open completely.

The client IP comes from `request.client.host`; behind nginx, Uvicorn/Gunicorn
must be started with `--forwarded-allow-ips` (see deploy/) so this is the real
visitor IP taken from X-Forwarded-For.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from fastapi import HTTPException, Request, status

from app.config import get_settings
from app.redis_client import get_redis

WINDOW_SECONDS = 60


class RateLimiter:
    def __init__(self) -> None:
        self._mem: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int = WINDOW_SECONDS) -> tuple[bool, int]:
        """Record a hit. Returns (allowed, retry_after_seconds)."""
        bucket = int(time.time() // window)
        full_key = f"{key}:{bucket}"
        retry_after = max(1, window - int(time.time() % window))
        if get_settings().QUEUE_MODE == "inline":  # local dev without Redis
            return self._hit_memory(full_key, window) <= limit, retry_after
        try:
            r = get_redis()
            pipe = r.pipeline()
            pipe.incr(full_key)
            pipe.expire(full_key, window + 5)
            count = int(pipe.execute()[0])
        except Exception:
            count = self._hit_memory(full_key, window)
        return count <= limit, retry_after

    def _hit_memory(self, key: str, window: int) -> int:
        now = time.time()
        with self._lock:
            if len(self._mem) > 10_000:  # prune expired buckets
                self._mem = {k: v for k, v in self._mem.items() if v[1] > now}
            count, expires = self._mem.get(key, (0, now + window))
            count += 1
            self._mem[key] = (count, expires)
            return count


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str, limit_setting: str) -> Callable[[Request], None]:
    """FastAPI dependency factory: `Depends(rate_limit("match", "MATCH_RATE_LIMIT_PER_MIN"))`."""

    def dependency(request: Request) -> None:
        s = get_settings()
        if not s.RATE_LIMIT_ENABLED:
            return
        allowed, retry_after = limiter.hit(f"rl:{scope}:{client_ip(request)}", int(getattr(s, limit_setting)))
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "RATE_LIMITED", "message": "Too many requests. Please wait a moment and try again."},
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
