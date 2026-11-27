"""Health check."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.config import get_settings
from app.db.session import SessionLocal
from app.face.engine import engine_loaded
from app.redis_client import redis_ok
from app.schemas import HealthOut
from app.workers.queue import queue_size

router = APIRouter(tags=["public"])


@router.get("/health", response_model=HealthOut, summary="Models, database, Redis and queue status")
def health(response: Response) -> HealthOut:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    inline = get_settings().QUEUE_MODE == "inline"  # local dev: no Redis needed
    r_ok = False if inline else redis_ok()
    q: int | None = None
    if r_ok or inline:
        try:
            q = queue_size()
        except Exception:
            q = None

    models = engine_loaded()
    healthy = db_ok and models and (r_ok or inline)
    response.status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthOut(
        status="ok" if healthy else "degraded",
        models_loaded=models,
        db_ok=db_ok,
        redis_ok=r_ok,
        queue_size=q,
    )
