"""Indexing job queue used by the API.

QUEUE_MODE=rq (production): jobs are enqueued in Redis and executed by the
worker processes (`python -m app.workers.run`).

QUEUE_MODE=inline (local development without Redis/Linux): jobs run in a
thread pool inside the API process. Fine for trying things out; use rq for
real workloads (separate processes use all CPU cores and survive API restarts).
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings

QUEUE_NAME = "eventlens-indexing"
JOB_FUNC = "app.workers.tasks.index_photo_job"
ENQUEUE_CHUNK = 500


def _inline() -> bool:
    return get_settings().QUEUE_MODE == "inline"


# ----------------------------------------------------------------------------
# Inline mode (thread pool)
# ----------------------------------------------------------------------------
_executor: ThreadPoolExecutor | None = None
_pending = 0
_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=get_settings().WORKER_CONCURRENCY, thread_name_prefix="eventlens-index"
            )
        return _executor


def _run_inline(photo_id: uuid.UUID) -> None:
    global _pending
    try:
        from app.services.indexing import process_photo

        process_photo(photo_id)
    finally:
        with _lock:
            _pending -= 1


def _enqueue_inline(ids: list[uuid.UUID]) -> int:
    global _pending
    executor = _get_executor()
    with _lock:
        _pending += len(ids)
    for pid in ids:
        executor.submit(_run_inline, pid)
    return len(ids)


# ----------------------------------------------------------------------------
# RQ mode (Redis)
# ----------------------------------------------------------------------------
def get_queue():
    from rq import Queue

    from app.redis_client import get_redis

    return Queue(QUEUE_NAME, connection=get_redis(), default_timeout=get_settings().JOB_TIMEOUT_SECONDS)


def enqueue_photos(photo_ids: Iterable[uuid.UUID]) -> int:
    """Schedule one indexing job per photo. Returns the number scheduled."""
    ids = [pid if isinstance(pid, uuid.UUID) else uuid.UUID(str(pid)) for pid in photo_ids]
    if not ids:
        return 0
    if _inline():
        return _enqueue_inline(ids)

    from rq import Queue

    q = get_queue()
    str_ids = [str(pid) for pid in ids]
    for i in range(0, len(str_ids), ENQUEUE_CHUNK):
        jobs = [
            Queue.prepare_data(
                JOB_FUNC,
                args=(pid,),
                result_ttl=0,  # we don't need RQ results; status lives in Postgres
                failure_ttl=24 * 3600,
                description=f"index photo {pid}",
            )
            for pid in str_ids[i : i + ENQUEUE_CHUNK]
        ]
        q.enqueue_many(jobs)
    return len(str_ids)


def queue_size() -> int:
    """Jobs waiting + currently running."""
    if _inline():
        return _pending
    from rq.registry import StartedJobRegistry

    q = get_queue()
    return int(q.count) + int(StartedJobRegistry(queue=q).count)
