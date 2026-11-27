"""Public event listing."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.db.session import get_db
from app.models import EVENT_TYPES, Event, Photo
from app.schemas import EventTypeList, PublicEventOut
from app.services import storage

router = APIRouter(tags=["public"])


@router.get("/events", response_model=list[PublicEventOut], summary="Published events")
def list_events(db: Session = Depends(get_db)) -> list[PublicEventOut]:
    counts = (
        select(Photo.event_id, func.count().label("n"))
        .where(Photo.status == "done")
        .group_by(Photo.event_id)
        .subquery()
    )
    # Fallback cover: the first processed photo of the event.
    first_photo = (
        select(Photo.thumb_path)
        .where(Photo.event_id == Event.id, Photo.status == "done")
        .order_by(Photo.created_at, Photo.id)
        .limit(1)
        .correlate(Event)
        .scalar_subquery()
    )
    cover = aliased(Photo)
    q = (
        select(Event, func.coalesce(counts.c.n, 0), cover.thumb_path, first_photo)
        .outerjoin(counts, counts.c.event_id == Event.id)
        .outerjoin(cover, (cover.id == Event.cover_photo_id) & (cover.status == "done"))
        .where(Event.is_published.is_(True))
        .order_by(Event.event_date.desc(), Event.name)
    )
    return [
        PublicEventOut(
            id=e.id,
            name=e.name,
            type=e.type,
            date=e.event_date,
            cover_thumb_url=storage.public_url(cover_thumb or fallback_thumb),
            photo_count=int(n),
        )
        for e, n, cover_thumb, fallback_thumb in db.execute(q).all()
    ]


@router.get("/event-types", response_model=EventTypeList, summary="Event types that have published events")
def event_types(db: Session = Depends(get_db)) -> EventTypeList:
    present = set(db.scalars(select(Event.type).where(Event.is_published.is_(True)).distinct()).all())
    # Keep the canonical display order.
    return EventTypeList(types=[t for t in EVENT_TYPES if t in present])
