"""Shared Redis connection (binary-safe, as required by RQ)."""

from __future__ import annotations

from functools import lru_cache

from redis import Redis

from app.config import get_settings


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(
        get_settings().REDIS_URL,
        socket_connect_timeout=2,
        socket_timeout=5,
        health_check_interval=30,
    )


def redis_ok() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:
        return False
