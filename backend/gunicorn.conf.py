"""Gunicorn settings for production (Uvicorn workers)."""

import multiprocessing
import os

bind = os.getenv("BIND", "127.0.0.1:8000")
worker_class = "uvicorn.workers.UvicornWorker"
# Each worker loads the face models (~40 MB). 2–4 workers suit a 2–4 vCPU box;
# the indexing workers run as separate processes.
workers = int(os.getenv("WEB_CONCURRENCY", max(2, min(4, multiprocessing.cpu_count()))))
timeout = 120
graceful_timeout = 30
keepalive = 5
# Trust X-Forwarded-For from nginx on the same host / Docker network so that
# rate limiting sees the real client IP.
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
# Uvicorn's access log records only method, path and status — never bodies.
accesslog = "-"
errorlog = "-"
