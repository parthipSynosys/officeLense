"""Admin event management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models import Event, Photo
from app.schemas import AdminEventOut, EventCreate, EventUpdate
from app.services import storage

router = APIRouter(tags=["admin: events"], dependencies=[Depends(get_current_admin)])


def get_event_or_404(db: Session, event_id: uuid.UUID) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "Event not found"})
    return event


def _event_rows(db: Session, event_ids: list[uuid.UUID] | None = None) -> list[AdminEventOut]:
    photo_stats = (
        select(
            Photo.event_id.label("event_id"),
            func.count().label("photo_count"),
            func.sum(case((Photo.status == "done", 1), else_=0)).label("done_count"),
            func.sum(case((Photo.status == "failed", 1), else_=0)).label("failed_count"),
            func.coalesce(func.sum(Photo.face_count), 0).label("face_count"),
        )
        .group_by(Photo.event_id)
        .subquery()
    )
    cover = select(Photo.id, Photo.thumb_path).where(Photo.status == "done").subquery()
    # Fallback thumbnail when no cover is chosen: the event's first processed item.
    first_thumb = (
        select(Photo.thumb_path)
        .where(Photo.event_id == Event.id, Photo.status == "done")
        .order_by(Photo.created_at, Photo.id)
        .limit(1)
        .correlate(Event)
        .scalar_subquery()
    )
    q = (
        select(
            Event,
            func.coalesce(photo_stats.c.photo_count, 0),
            func.coalesce(photo_stats.c.done_count, 0),
            func.coalesce(photo_stats.c.failed_count, 0),
            func.coalesce(photo_stats.c.face_count, 0),
            cover.c.thumb_path,
            first_thumb,
        )
        .outerjoin(photo_stats, photo_stats.c.event_id == Event.id)
        .outerjoin(cover, cover.c.id == Event.cover_photo_id)
        .order_by(Event.event_date.desc(), Event.created_at.desc())
    )
    if event_ids is not None:
        q = q.where(Event.id.in_(event_ids))
    out = []
    for event, photo_count, done, failed, faces, cover_thumb, fallback_thumb in db.execute(q).all():
        item = AdminEventOut.model_validate(event)
        item.photo_count, item.done_count = int(photo_count), int(done)
        item.failed_count, item.face_count = int(failed), int(faces)
        item.cover_thumb_url = storage.public_url(cover_thumb or fallback_thumb)
        out.append(item)
    return out


@router.get("/events", response_model=list[AdminEventOut], summary="All events (incl. unpublished)")
def list_events(db: Session = Depends(get_db)) -> list[AdminEventOut]:
    return _event_rows(db)


@router.post("/events", response_model=AdminEventOut, status_code=status.HTTP_201_CREATED)
def create_event(body: EventCreate, db: Session = Depends(get_db)) -> AdminEventOut:
    event = Event(**body.model_dump())
    db.add(event)
    db.commit()
    return _event_rows(db, [event.id])[0]


@router.get("/events/{event_id}", response_model=AdminEventOut)
def get_event(event_id: uuid.UUID, db: Session = Depends(get_db)) -> AdminEventOut:
    get_event_or_404(db, event_id)
    return _event_rows(db, [event_id])[0]


@router.put("/events/{event_id}", response_model=AdminEventOut, summary="Update (incl. publish / cover)")
def update_event(event_id: uuid.UUID, body: EventUpdate, db: Session = Depends(get_db)) -> AdminEventOut:
    event = get_event_or_404(db, event_id)
    changes = body.model_dump(exclude_unset=True)

    for field in ("name", "type", "event_date", "is_published"):
        if field in changes and changes[field] is None:
            raise HTTPException(422, detail={"code": "INVALID", "message": f"{field} cannot be null"})
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if not changes["name"]:
            raise HTTPException(422, detail={"code": "INVALID", "message": "Name must not be blank"})
    if "description" in changes and changes["description"] is None:
        changes["description"] = ""

    if changes.get("cover_photo_id") is not None:
        photo = db.get(Photo, changes["cover_photo_id"])
        if photo is None or photo.event_id != event.id:
            raise HTTPException(
                422, detail={"code": "INVALID_COVER", "message": "Cover photo must belong to this event"}
            )
        if photo.status != "done":
            raise HTTPException(
                422, detail={"code": "INVALID_COVER", "message": "Cover photo must be fully processed"}
            )

    for field, value in changes.items():
        setattr(event, field, value)
    db.commit()
    return _event_rows(db, [event.id])[0]


@router.delete(
    "/events/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete an event with all its photos, files and faces",
)
def delete_event(event_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    event = get_event_or_404(db, event_id)
    # Staged uploads live outside the event folder; collect them before the rows go.
    staged = db.scalars(select(Photo.source_path).where(Photo.event_id == event_id, Photo.source_path.is_not(None))).all()
    db.delete(event)  # photos + faces removed by ON DELETE CASCADE
    db.commit()
    storage.delete_event_files(event_id)
    storage.delete_photo_files(*staged)
    # Any queued jobs for these photos become no-ops (worker skips missing rows).
    return Response(status_code=status.HTTP_204_NO_CONTENT)
