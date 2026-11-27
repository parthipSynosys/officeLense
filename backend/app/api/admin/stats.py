"""Admin dashboard statistics."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models import Event, Face, Photo
from app.schemas import StatsOut
from app.workers.queue import queue_size

router = APIRouter(tags=["admin: stats"], dependencies=[Depends(get_current_admin)])


@router.get("/stats", response_model=StatsOut, summary="Totals for the dashboard")
def stats(db: Session = Depends(get_db)) -> StatsOut:
    events = db.scalar(select(func.count()).select_from(Event)) or 0
    published = db.scalar(select(func.count()).select_from(Event).where(Event.is_published.is_(True))) or 0
    photos = db.scalar(select(func.count()).select_from(Photo).where(Photo.media_type == "photo")) or 0
    videos = db.scalar(select(func.count()).select_from(Photo).where(Photo.media_type == "video")) or 0
    failed = db.scalar(select(func.count()).select_from(Photo).where(Photo.status == "failed")) or 0
    processing = db.scalar(select(func.count()).select_from(Photo).where(Photo.status == "processing")) or 0
    faces = db.scalar(select(func.count()).select_from(Face)) or 0
    try:
        queue: int | None = queue_size()
    except Exception:
        queue = None
    return StatsOut(
        events=events,
        published_events=published,
        photos=photos,
        videos=videos,
        faces=faces,
        failed=failed,
        processing=processing,
        queue=queue,
    )
