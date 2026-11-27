"""Start N indexing worker PROCESSES (face detection is CPU-bound).

    python -m app.workers.run                 # WORKER_CONCURRENCY processes
    python -m app.workers.run --concurrency 4

Each child process loads the face models once and runs an RQ `SimpleWorker`
(no fork-per-job), so models stay in memory between jobs. OpenCV is limited to
one thread per process to avoid CPU oversubscription. SIGTERM/SIGINT trigger a
warm shutdown: running jobs finish, then the processes exit.
"""

from __future__ import annotations

import argparse
import logging
import multiprocessing as mp
import os
import signal
import socket
import sys
import time


def _child(index: int) -> None:
    import cv2

    cv2.setNumThreads(1)

    from rq import SimpleWorker

    from app.config import get_settings
    from app.face.engine import load_engine
    from app.logging_config import configure_logging
    from app.redis_client import get_redis
    from app.workers.queue import QUEUE_NAME

    configure_logging(get_settings().LOG_LEVEL)
    load_engine()
    worker = SimpleWorker(
        [QUEUE_NAME],
        connection=get_redis(),
        name=f"eventlens-{socket.gethostname()}-{os.getpid()}-{index}",
    )
    worker.work(with_scheduler=False, logging_level=get_settings().LOG_LEVEL)


def main() -> int:
    from app.config import get_settings
    from app.logging_config import configure_logging

    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    log = logging.getLogger("eventlens.workers")

    ap = argparse.ArgumentParser(description="Run EventLens indexing workers")
    ap.add_argument("--concurrency", type=int, default=settings.WORKER_CONCURRENCY)
    args = ap.parse_args()
    n = max(1, args.concurrency)

    ctx = mp.get_context("spawn")
    procs: dict[int, mp.Process] = {}
    stopping = False

    def start(i: int) -> None:
        p = ctx.Process(target=_child, args=(i,), name=f"eventlens-worker-{i}")
        p.start()
        procs[i] = p
        log.info("Started worker %d (pid %s)", i, p.pid)

    def shutdown(signum, _frame) -> None:
        nonlocal stopping
        stopping = True
        log.info("Received signal %s, stopping workers...", signum)
        for p in procs.values():
            if p.is_alive() and p.pid:
                os.kill(p.pid, signal.SIGTERM)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    for i in range(n):
        start(i)

    # Supervise: restart crashed children until asked to stop.
    while not stopping:
        time.sleep(2)
        for i, p in list(procs.items()):
            if not p.is_alive() and not stopping:
                log.warning("Worker %d exited with code %s; restarting", i, p.exitcode)
                start(i)

    for p in procs.values():
        p.join(timeout=get_settings().JOB_TIMEOUT_SECONDS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
